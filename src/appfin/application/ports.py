"""Interfaces (portas) que a aplicação usa e a infraestrutura implementa."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol


class InvalidCredentialError(Exception):
    """Senha mestra ou chave de recuperação incorreta."""


class StorageUnavailableError(Exception):
    """Cofre ou banco ausente, corrompido ou de versão incompatível."""


class OrphanedDataError(Exception):
    """Existe um banco de dados, mas não o cofre que guarda a chave dele."""


class BackupFileError(Exception):
    """Arquivo de backup inválido, corrompido, adulterado, incompleto ou de versão incompatível."""


class DataKey(Protocol):
    """Chave de dados (DEK) opaca para a aplicação."""

    def wipe(self) -> None: ...

    @property
    def is_wiped(self) -> bool: ...


class KeyVault(Protocol):
    def exists(self) -> bool: ...

    def create(self, password: str) -> tuple[str, DataKey]:
        """Cria o cofre. Retorna (chave de recuperação para exibir uma vez, DEK)."""
        ...

    def unlock_with_password(self, password: str) -> DataKey: ...

    def unlock_with_recovery_key(self, recovery_key: str) -> DataKey: ...

    def verify_password(self, password: str) -> None:
        """Levanta ``InvalidCredentialError`` se a senha não abrir o cofre."""
        ...

    def prepare_recovery_key(self, key: DataKey) -> tuple[str, object]:
        """Gera uma nova chave de recuperação SEM gravar. Retorna (texto, pendência opaca)."""
        ...

    def commit_recovery_key(self, pending: object) -> None:
        """Grava a chave preparada (só depois que a usuária confirmou que anotou)."""
        ...


class DataStore(Protocol):
    def exists(self) -> bool:
        """Há um banco de dados no disco (de qualquer instalação)."""
        ...

    def open(self, key: DataKey) -> None:
        """Abre o banco cifrado e aplica migrações pendentes."""
        ...

    def close(self) -> None: ...

    def record_audit(self, event: str, outcome: str, occurred_at: datetime) -> None: ...


class EventLog(Protocol):
    def record(self, event: str, **fields: object) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime:
        """Agora, com fuso (UTC)."""
        ...


# ---------------------------------------------------------------------- backup
@dataclass(frozen=True, slots=True)
class BackupManifest:
    created_at: datetime
    app_version: str
    schema_version: int
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BackupReport:
    file_name: str
    manifest: BackupManifest
    saved_to: list[Path]
    failed: list[Path]  # destinos que não puderam ser gravados (ex.: pen drive ausente)


class BackupEngine(Protocol):
    def create(self, key: DataKey, destinations: Sequence[Path]) -> BackupReport:
        """Gera, verifica e grava o backup cifrado em cada destino (o 1º é obrigatório)."""
        ...

    def prepare_restore(
        self, file: Path, *, password: str | None = None, recovery_key: str | None = None
    ) -> BackupManifest:
        """Decifra e verifica o backup numa área temporária. Nada dos dados atuais muda."""
        ...

    def discard_restore(self) -> None: ...

    def apply_restore(self) -> None:
        """Troca os dados atuais pelos preparados (o banco precisa estar fechado)."""
        ...
