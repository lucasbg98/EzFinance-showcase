"""Interfaces (portas) que a aplicação usa e a infraestrutura implementa."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class InvalidCredentialError(Exception):
    """Senha mestra ou chave de recuperação incorreta."""


class StorageUnavailableError(Exception):
    """Cofre ou banco ausente, corrompido ou de versão incompatível."""


class OrphanedDataError(Exception):
    """Existe um banco de dados, mas não o cofre que guarda a chave dele."""


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
