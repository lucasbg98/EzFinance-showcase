"""Criação, verificação e restauração de backups cifrados (docs/PROJETO.md §7.9).

Criação:
1. Cópia consistente do banco com a API de backup do SQLite para um arquivo **SQLCipher** temporário
   (mesma chave): nenhum dado em claro no disco.
2. Cifra com ``secretstream`` (``stream.py``) num ``.tmp`` no 1º destino.
3. **Verifica** antes de aceitar: decifra, roda ``PRAGMA integrity_check`` e confere as contagens.
4. Copia para os outros destinos (conferindo o SHA-256 da cópia) e aplica a retenção.

Restauração (em duas fases, para nada mudar até tudo estar conferido):
1. ``prepare_restore``: abre o envelope do backup com a senha/chave de recuperação **da época**,
   decifra o banco para ``restore-staging/`` e verifica (integridade, contagens, versão).
2. ``apply_restore``: marca a área como pronta e troca os arquivos. A troca é **retomável**: se o
   computador desligar no meio, ``complete_pending_restore`` termina o serviço na próxima abertura.
   Os arquivos substituídos ficam em ``restore-previous/`` (cifrados) como desfazer de emergência.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from appfin import __version__
from appfin.application.ports import (
    BackupFileError,
    BackupManifest,
    BackupReport,
    DataKey,
    InvalidCredentialError,
    StorageUnavailableError,
)
from appfin.infrastructure.backup import stream
from appfin.infrastructure.backup.retention import backup_name, list_backups, to_delete
from appfin.infrastructure.crypto import errors as crypto_errors
from appfin.infrastructure.crypto import vault
from appfin.infrastructure.crypto.kdf import MINIMUM_SECURE_PARAMS, KdfParams
from appfin.infrastructure.crypto.secret import SecretBytes
from appfin.infrastructure.paths import AppPaths
from appfin.infrastructure.persistence.database import Connection, DatabaseError, open_encrypted
from appfin.infrastructure.persistence.migrator import available_migrations, current_version

COUNTED_TABLES = ("account", "category", "contact", "financial_transaction", "receipt")
MAX_BACKUP_FILE_BYTES = stream.MAX_DATABASE_BYTES + 16 * 1024 * 1024
_SIDE_FILES = ("-wal", "-shm", "-journal")
_STAGING = "restore-staging"
_PREVIOUS = "restore-previous"
_WORK = "backup-work"
_READY = "ready"
_OLD_MOVED = "old-moved"


class FileBackupEngine:
    def __init__(
        self,
        paths: AppPaths,
        connection: Callable[[], Connection],
        now: Callable[[], datetime],
        minimum: KdfParams = MINIMUM_SECURE_PARAMS,
    ) -> None:
        self._paths = paths
        self._connection = connection
        self._now = now
        self._minimum = minimum

    # ------------------------------------------------------------------ criação
    def create(self, key: DataKey, destinations: Sequence[Path]) -> BackupReport:
        return self.create_from(self._connection(), _secret(key), destinations)

    def create_from(
        self, connection: Connection, key: SecretBytes, destinations: Sequence[Path]
    ) -> BackupReport:
        if not destinations:
            raise ValueError("Nenhum destino de backup.")
        work = self._paths.root / _WORK
        _reset_dir(work)
        try:
            snapshot = work / "snapshot.db"
            target = open_encrypted(snapshot, key)
            try:
                connection.backup(target)
                manifest = BackupManifest(
                    created_at=self._now().astimezone(),
                    app_version=__version__,
                    schema_version=current_version(target),
                    counts=_counts(target),
                )
            finally:
                target.close()
            header = stream.encode_header(vault.envelope_document(self._envelope()))
            primary, *others = destinations
            name = _unique_name(destinations, manifest.created_at)
            first = primary / name
            self._write_verified(first, header, manifest, snapshot, key, work)
            saved, failed = [first], []
            digest = _sha256(first)
            for folder in others:
                try:
                    saved.append(_copy_verified(first, folder / name, digest))
                except OSError:
                    failed.append(folder)
            for folder in (primary, *(p.parent for p in saved[1:])):
                _prune(folder)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return BackupReport(name, manifest, saved, failed)

    def _write_verified(
        self,
        final: Path,
        header: bytes,
        manifest: BackupManifest,
        snapshot: Path,
        key: SecretBytes,
        work: Path,
    ) -> None:
        final.parent.mkdir(parents=True, exist_ok=True)
        partial = final.with_name(final.name + ".tmp")
        try:
            with partial.open("wb") as target:
                stream.write_backup(target, header, _manifest_document(manifest), snapshot, key)
            check = work / "verify.db"
            with partial.open("rb") as source, check.open("wb") as out:
                stream.read_backup(source, stream.read_header(source), key, out)
            _verify_database(check, key, manifest.counts)
            partial.replace(final)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

    def _envelope(self) -> vault.VaultEnvelope:
        try:
            return vault.load_envelope(self._paths.vault_file)
        except crypto_errors.VaultFormatError as exc:
            raise StorageUnavailableError("Cofre ausente ou corrompido.") from exc

    # ------------------------------------------------------------------ restauração
    def prepare_restore(
        self, file: Path, *, password: str | None = None, recovery_key: str | None = None
    ) -> BackupManifest:
        if (password is None) == (recovery_key is None):
            raise ValueError("Informe a senha mestra OU a chave de recuperação.")
        staging = self._paths.root / _STAGING
        _reset_dir(staging)
        try:
            return self._prepare(file, staging, password, recovery_key)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _prepare(
        self, file: Path, staging: Path, password: str | None, recovery_key: str | None
    ) -> BackupManifest:
        try:
            if file.stat().st_size > MAX_BACKUP_FILE_BYTES:
                raise BackupFileError("Arquivo grande demais para ser um backup do app.")
            with file.open("rb") as source:
                header = stream.read_header(source)
                envelope = vault.parse_envelope_document(header.vault)
                dek = self._unlock(envelope, password, recovery_key)
                with dek, (staging / "appfin.db").open("wb") as out:
                    document = stream.read_backup(source, header, dek, out)
                    out.close()
                    manifest = _parse_manifest(document)
                    _verify_database(staging / "appfin.db", dek, manifest.counts)
        except stream.BackupFormatError as exc:
            raise BackupFileError(str(exc)) from exc
        except crypto_errors.VaultFormatError as exc:
            raise BackupFileError("Cofre do backup corrompido ou inseguro.") from exc
        except OSError as exc:
            raise BackupFileError("Não foi possível ler o arquivo de backup.") from exc
        latest = available_migrations()[-1].version
        if manifest.schema_version > latest:
            raise BackupFileError("Este backup é de uma versão mais nova do app: atualize o app.")
        vault.save_envelope(envelope, staging / "vault.json")
        return manifest

    def _unlock(
        self, envelope: vault.VaultEnvelope, password: str | None, recovery_key: str | None
    ) -> SecretBytes:
        try:
            if password is not None:
                return vault.unlock_with_password(envelope, password, self._minimum)
            return vault.unlock_with_recovery_key(envelope, recovery_key or "", self._minimum)
        except crypto_errors.InvalidCredentialError as exc:
            raise InvalidCredentialError(str(exc)) from exc

    def discard_restore(self) -> None:
        staging = self._paths.root / _STAGING
        if not (staging / _READY).exists():
            shutil.rmtree(staging, ignore_errors=True)

    def apply_restore(self) -> None:
        staging = self._paths.root / _STAGING
        if not ((staging / "appfin.db").is_file() and (staging / "vault.json").is_file()):
            raise BackupFileError("Nenhuma restauração preparada.")
        (staging / _READY).touch()
        complete_pending_restore(self._paths)


# ---------------------------------------------------------------------- troca retomável
def complete_pending_restore(paths: AppPaths) -> bool:
    """Termina uma restauração interrompida (ou descarta uma preparada e não confirmada).

    Idempotente: cada passo confere o que já foi feito. Retorna ``True`` se concluiu uma troca.
    """
    root = paths.root
    staging = root / _STAGING
    if not staging.exists():
        return False
    if not (staging / _READY).exists():
        shutil.rmtree(staging, ignore_errors=True)
        return False
    previous = root / _PREVIOUS
    database = paths.database_file
    if not (staging / _OLD_MOVED).exists():
        _reset_dir(previous)
        for current in (database, *(_side(database, s) for s in _SIDE_FILES), paths.vault_file):
            if current.exists():
                current.replace(previous / current.name)
        (staging / _OLD_MOVED).touch()
    for side in _SIDE_FILES:  # WAL antigo nunca pode ser aplicado sobre o banco restaurado
        _side(database, side).unlink(missing_ok=True)
    if (staging / "appfin.db").exists():
        (staging / "appfin.db").replace(database)
    if (staging / "vault.json").exists():
        (staging / "vault.json").replace(paths.vault_file)
    shutil.rmtree(staging, ignore_errors=True)
    return True


# ---------------------------------------------------------------------- auxiliares
def _verify_database(path: Path, key: SecretBytes, expected: dict[str, int]) -> None:
    try:
        connection = open_encrypted(path, key)
    except DatabaseError as exc:
        raise BackupFileError("O banco dentro do backup não abre.") from exc
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise BackupFileError("O banco dentro do backup está corrompido.")
        if _counts(connection) != expected:
            raise BackupFileError("O conteúdo do backup não confere com o manifesto.")
    finally:
        connection.close()
    for side in _SIDE_FILES:
        _side(path, side).unlink(missing_ok=True)


def _counts(connection: Connection) -> dict[str, int]:
    existing = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    counts = {}
    for table in COUNTED_TABLES:
        if table in existing:
            # Nome vem da tupla fixa acima (nunca de entrada externa).
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608  # nosec B608
            counts[table] = int(row[0])
    return counts


def _manifest_document(manifest: BackupManifest) -> dict[str, Any]:
    return {
        "created_at": manifest.created_at.isoformat(),
        "app_version": manifest.app_version,
        "schema_version": manifest.schema_version,
        "counts": manifest.counts,
    }


def _parse_manifest(document: dict[str, Any]) -> BackupManifest:
    try:
        created = datetime.fromisoformat(str(document["created_at"]))
        app_version = str(document["app_version"])[:32]
        schema = document["schema_version"]
        counts = document["counts"]
        if not isinstance(schema, int) or isinstance(schema, bool) or not isinstance(counts, dict):
            raise TypeError
        clean = {
            str(name): int(value)
            for name, value in counts.items()
            if name in COUNTED_TABLES and isinstance(value, int) and not isinstance(value, bool)
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupFileError("Manifesto do backup corrompido.") from exc
    return BackupManifest(created, app_version, schema, clean)


def _unique_name(destinations: Sequence[Path], moment: datetime) -> str:
    sequence = 0
    while any((folder / backup_name(moment, sequence)).exists() for folder in destinations):
        sequence += 1
    return backup_name(moment, sequence)


def _copy_verified(source: Path, target: Path, digest: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".tmp")
    try:
        shutil.copyfile(source, partial)
        if _sha256(partial) != digest:
            raise OSError("Cópia do backup não confere.")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def _prune(folder: Path) -> None:
    for path in to_delete(list_backups(folder)):
        path.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _side(database: Path, suffix: str) -> Path:
    return database.with_name(database.name + suffix)


def _reset_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)


def _secret(key: DataKey) -> SecretBytes:
    if not isinstance(key, SecretBytes):
        raise TypeError("Chave de dados de tipo inesperado.")
    return key
