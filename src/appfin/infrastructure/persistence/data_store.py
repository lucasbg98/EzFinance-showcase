"""Implementação do ``DataStore``: banco SQLCipher local com migrações."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
            migrate(connection)
        except DatabaseError as exc:
            raise StorageUnavailableError("Não foi possível abrir o banco de dados.") from exc
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
