"""Backup e restauração ponta a ponta com SQLCipher real (dados sempre fictícios).

Cenários do docs/PROJETO.md §7.9: criar → restaurar → dados idênticos; criar → corromper → falha
detectada; restauração em outro computador; restauração interrompida; backup antes de migrar.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from appfin.application.ports import BackupFileError, InvalidCredentialError
from appfin.application.session import AppSession, SessionLockedError, SessionState
from appfin.bootstrap import AppConfig, AppContainer, build_app
from appfin.domain.entities import Company, Contact
from appfin.domain.enums import TaxRegime
from appfin.infrastructure.backup.engine import complete_pending_restore
from appfin.infrastructure.backup.retention import list_backups
from appfin.infrastructure.crypto.secret import SecretBytes
from appfin.infrastructure.paths import AppPaths
from appfin.infrastructure.persistence.data_store import SqlCipherDataStore
from appfin.infrastructure.persistence.database import open_encrypted
from appfin.infrastructure.persistence.migrator import available_migrations, migrate
from appfin.presentation.shared.formatting import ValuesVisibility
from tests.support import FAST_MINIMUM, FAST_PARAMS

PASSWORD = "girassol trator piano nuvem"
OTHER_PASSWORD = "janela cometa abacaxi violino"
TODAY = date(2026, 3, 15)


def _container(root: Path) -> AppContainer:
    config = AppConfig(paths=AppPaths(root), kdf_params=FAST_PARAMS, kdf_minimum=FAST_MINIMUM)
    return build_app(config, today=lambda: TODAY)


def _populated(root: Path, password: str = PASSWORD) -> tuple[AppContainer, str]:
    container = _container(root)
    recovery_key = container.session.create(password)
    ws = container.workspace_factory(ValuesVisibility(), None)
    ws.catalog.save_company(Company(name="Clínica Fictícia"))
    ws.catalog.initialize_defaults(TaxRegime.SIMPLES)
    ws.catalog.save_contact(Contact("", "Paciente Fictício"))
    return container, recovery_key


def _contacts(container: AppContainer) -> list[str]:
    ws = container.workspace_factory(ValuesVisibility(), None)
    return sorted(c.name for c in ws.catalog.search_contacts())


def _backup(container: AppContainer, *folders: Path) -> Path:
    report = container.session.create_backup(list(folders), reason="test")
    return report.saved_to[0]


# ---------------------------------------------------------------------- criação
def test_backup_is_written_verified_and_copied(tmp_path: Path) -> None:
    container, _ = _populated(tmp_path / "pc1")
    local, extra = tmp_path / "pc1" / "backups", tmp_path / "pendrive"

    report = container.session.create_backup([local, extra], reason="test")

    assert [p.parent for p in report.saved_to] == [local, extra] and report.failed == []
    assert report.manifest.counts["contact"] == 1
    assert report.manifest.counts["account"] >= 1
    assert (local / report.file_name).read_bytes() == (extra / report.file_name).read_bytes()
    assert b"Paciente" not in (local / report.file_name).read_bytes()
    assert not (tmp_path / "pc1" / "backup-work").exists(), "sem sobras temporárias"


def test_unreachable_extra_folder_is_reported_not_fatal(tmp_path: Path) -> None:
    container, _ = _populated(tmp_path / "pc1")
    blocked = tmp_path / "arquivo-no-lugar-da-pasta"
    blocked.write_text("x")

    report = container.session.create_backup([tmp_path / "local", blocked], reason="test")

    assert report.failed == [blocked] and len(report.saved_to) == 1


def test_backup_requires_unlocked_session(tmp_path: Path) -> None:
    container, _ = _populated(tmp_path / "pc1")
    container.session.lock()

    with pytest.raises(SessionLockedError):
        container.session.create_backup([tmp_path / "b"], reason="test")


# ---------------------------------------------------------------------- restauração
def test_restore_on_another_computer_with_password(tmp_path: Path) -> None:
    pc1, _ = _populated(tmp_path / "pc1")
    file = _backup(pc1, tmp_path / "pendrive")
    pc2 = _container(tmp_path / "pc2")
    assert pc2.session.state is SessionState.NEEDS_SETUP

    manifest = pc2.session.prepare_restore(file, password=PASSWORD)
    assert manifest.counts["contact"] == 1
    assert pc2.session.state is SessionState.NEEDS_SETUP, "preparar não muda nada"
    pc2.session.apply_restore()

    assert pc2.session.state is SessionState.LOCKED
    pc2.session.unlock(PASSWORD)
    assert _contacts(pc2) == ["Paciente Fictício"]


def test_restore_with_recovery_key(tmp_path: Path) -> None:
    pc1, recovery_key = _populated(tmp_path / "pc1")
    file = _backup(pc1, tmp_path / "pendrive")
    pc2 = _container(tmp_path / "pc2")

    pc2.session.prepare_restore(file, recovery_key=recovery_key.lower())
    pc2.session.apply_restore()
    pc2.session.unlock_with_recovery_key(recovery_key)

    assert _contacts(pc2) == ["Paciente Fictício"]


def test_wrong_credentials_change_nothing(tmp_path: Path) -> None:
    pc1, _ = _populated(tmp_path / "pc1")
    file = _backup(pc1, tmp_path / "pendrive")
    pc2 = _container(tmp_path / "pc2")

    with pytest.raises(InvalidCredentialError):
        pc2.session.prepare_restore(file, password=OTHER_PASSWORD)

    assert not (tmp_path / "pc2" / "restore-staging").exists()
    assert pc2.session.state is SessionState.NEEDS_SETUP


@pytest.mark.parametrize("damage", ["flip", "truncate", "not_backup"])
def test_damaged_backup_is_refused_and_current_data_kept(tmp_path: Path, damage: str) -> None:
    container, _ = _populated(tmp_path / "pc1")
    file = _backup(container, tmp_path / "pendrive")
    data = file.read_bytes()
    if damage == "flip":
        middle = len(data) // 2
        data = data[:middle] + bytes([data[middle] ^ 0x40]) + data[middle + 1 :]
    elif damage == "truncate":
        data = data[: len(data) - 100]
    else:
        data = b"isto nao e um backup"
    file.write_bytes(data)

    with pytest.raises(BackupFileError):
        container.session.prepare_restore(file, password=PASSWORD)

    assert container.session.state is SessionState.UNLOCKED
    assert _contacts(container) == ["Paciente Fictício"]


def test_restore_while_unlocked_backs_up_current_state_first(tmp_path: Path) -> None:
    pc1, _ = _populated(tmp_path / "pc1")
    old_backup = _backup(pc1, tmp_path / "pendrive")
    ws = pc1.workspace_factory(ValuesVisibility(), None)
    ws.catalog.save_contact(Contact("", "Contato Novo Fictício"))
    local = tmp_path / "pc1" / "backups"
    before = len(list_backups(local))

    pc1.session.prepare_restore(old_backup, password=PASSWORD)
    pc1.session.apply_restore()

    assert pc1.session.state is SessionState.LOCKED
    assert len(list_backups(local)) == before + 1, "backup automático antes de restaurar"
    assert (tmp_path / "pc1" / "restore-previous" / "appfin.db").exists()
    pc1.session.unlock(PASSWORD)
    assert _contacts(pc1) == ["Paciente Fictício"]
    # O backup automático guardou o contato novo: dá para voltar.
    newest = list_backups(local)[0][1]
    pc3 = _container(tmp_path / "pc3")
    pc3.session.prepare_restore(newest, password=PASSWORD)
    pc3.session.apply_restore()
    pc3.session.unlock(PASSWORD)
    assert _contacts(pc3) == ["Contato Novo Fictício", "Paciente Fictício"]


def test_discarded_preparation_leaves_no_traces(tmp_path: Path) -> None:
    pc1, _ = _populated(tmp_path / "pc1")
    file = _backup(pc1, tmp_path / "pendrive")

    pc1.session.prepare_restore(file, password=PASSWORD)
    pc1.session.discard_restore()

    assert not (tmp_path / "pc1" / "restore-staging").exists()
    assert pc1.session.state is SessionState.UNLOCKED


def test_interrupted_restore_is_completed_on_next_start(tmp_path: Path) -> None:
    pc1, _ = _populated(tmp_path / "pc1")
    file = _backup(pc1, tmp_path / "pendrive")
    pc2_root = tmp_path / "pc2"
    pc2, _ = _populated(pc2_root, OTHER_PASSWORD)
    pc2.session.prepare_restore(file, password=PASSWORD)
    pc2.session.lock()
    paths = AppPaths(pc2_root)
    staging = pc2_root / "restore-staging"
    (staging / "ready").touch()
    # Simula queda de energia no meio: o banco antigo já foi movido, o novo ainda não entrou.
    previous = pc2_root / "restore-previous"
    previous.mkdir()
    paths.database_file.replace(previous / "appfin.db")
    (staging / "old-moved").touch()

    restarted = _container(pc2_root)  # o bootstrap termina a troca

    assert not staging.exists()
    assert complete_pending_restore(paths) is False, "idempotente"
    restarted.session.unlock(PASSWORD)
    assert _contacts(restarted) == ["Paciente Fictício"]


def test_restore_refuses_backup_from_newer_app(tmp_path: Path) -> None:
    pc1, _ = _populated(tmp_path / "pc1")
    connection = pc1.session._store.connection  # type: ignore[attr-defined]
    connection.execute("PRAGMA user_version = 999")
    file = _backup(pc1, tmp_path / "pendrive")

    with pytest.raises(BackupFileError, match="mais nova"):
        _container(tmp_path / "pc2").session.prepare_restore(file, password=PASSWORD)


# ---------------------------------------------------------------------- backup antes de migrar
def test_backup_runs_before_migrating_a_database_with_data(tmp_path: Path) -> None:
    key = SecretBytes(bytes(range(32)))
    path = tmp_path / "appfin.db"
    connection = open_encrypted(path, key)
    migrate(connection, available_migrations()[:1])
    connection.close()
    calls: list[int] = []
    store = SqlCipherDataStore(path)
    store.before_migration = lambda conn, _key: calls.append(
        conn.execute("PRAGMA user_version").fetchone()[0]
    )

    store.open(key)

    assert calls == [1], "backup feito ainda na versão antiga"
    store.close()
    store.open(key)
    assert calls == [1], "sem migração pendente, sem backup"
    store.close()


def test_failed_pre_migration_backup_aborts_migration(tmp_path: Path) -> None:
    key = SecretBytes(bytes(range(32)))
    path = tmp_path / "appfin.db"
    connection = open_encrypted(path, key)
    migrate(connection, available_migrations()[:1])
    connection.close()
    store = SqlCipherDataStore(path)

    def broken(_connection: object, _key: object) -> None:
        raise OSError("disco cheio")

    store.before_migration = broken

    with pytest.raises(OSError):
        store.open(key)
    check = open_encrypted(path, key)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 1, "não migrou sem backup"
    check.close()


# ---------------------------------------------------------------------- chave de recuperação
def test_new_recovery_key_only_counts_after_confirmation(tmp_path: Path) -> None:
    container, old_key = _populated(tmp_path / "pc1")
    session: AppSession = container.session

    with pytest.raises(InvalidCredentialError):
        session.prepare_recovery_key(OTHER_PASSWORD)
    new_key = session.prepare_recovery_key(PASSWORD)
    session.lock()  # bloqueou antes de confirmar: nada muda
    session.unlock_with_recovery_key(old_key)

    new_key = session.prepare_recovery_key(PASSWORD)
    session.confirm_recovery_key()
    session.lock()

    with pytest.raises(InvalidCredentialError):
        session.unlock_with_recovery_key(old_key)
    session.unlock_with_recovery_key(new_key)
    assert session.state is SessionState.UNLOCKED
