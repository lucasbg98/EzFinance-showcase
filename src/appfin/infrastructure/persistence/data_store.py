"""Implementação do ``DataStore``: banco SQLCipher local com migrações."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from appfin.application.ports import DataKey, StorageUnavailableError
from appfin.infrastructure.crypto.secret import SecretBytes
from appfin.infrastructure.persistence.database import (
    Connection,
    DatabaseError,
    open_encrypted,
)
from appfin.infrastructure.persistence.migrator import migrate


class SqlCipherDataStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._connection: Connection | None = None
        # Chamado antes de migrar um banco com dados: (conexão, chave) -> backup.
        self.before_migration: Callable[[Connection, SecretBytes], Any] | None = None

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise StorageUnavailableError("Banco fechado.")
        return self._connection

    def exists(self) -> bool:
        return self._path.exists()

    def open(self, key: DataKey) -> None:
        if not isinstance(key, SecretBytes):
            raise TypeError("Chave de dados de tipo inesperado.")
        try:
            connection = open_encrypted(self._path, key)
        except DatabaseError as exc:
            raise StorageUnavailableError("Não foi possível abrir o banco de dados.") from exc
        hook = self.before_migration

        def backup_first(_old: int, _new: int) -> None:
            if hook is not None:
                hook(connection, key)

        try:
            migrate(connection, before_migrate=backup_first)
        except DatabaseError as exc:
            connection.close()
            raise StorageUnavailableError("Não foi possível abrir o banco de dados.") from exc
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def record_audit(self, event: str, outcome: str, occurred_at: datetime) -> None:
        self.connection.execute(
            "INSERT INTO audit_event (occurred_at, event, outcome) VALUES (?, ?, ?)",
            (occurred_at.isoformat(), event, outcome),
        )
