"""Migrações de esquema numeradas (``NNNN_descricao.sql``) controladas por ``PRAGMA user_version``.

Cada migração roda numa transação: ou aplica inteira (e incrementa a versão) ou nada muda.
Antes de migrar um banco que já tem dados, o chamador **deve** fazer backup
(``before_migrate``); o app usa o backup cifrado (``SqlCipherDataStore.before_migration``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

from appfin.infrastructure.persistence.database import Connection, DatabaseError

_MIGRATIONS_PACKAGE = "appfin.infrastructure.persistence.migrations"
_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(DatabaseError):
    """Falha ao aplicar migração (o banco permanece na versão anterior)."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def available_migrations() -> list[Migration]:
    found: list[Migration] = []
    for entry in resources.files(_MIGRATIONS_PACKAGE).iterdir():
        match = _FILENAME.match(entry.name)
        if match:
            found.append(Migration(int(match.group(1)), entry.name, entry.read_text("utf-8")))
    found.sort(key=lambda migration: migration.version)
    expected = list(range(1, len(found) + 1))
    if [migration.version for migration in found] != expected:
        raise MigrationError("Sequência de migrações com lacunas ou duplicatas.")
    return found


def current_version(connection: Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(
    connection: Connection,
    migrations: list[Migration] | None = None,
    before_migrate: Callable[[int, int], None] | None = None,
) -> int:
    """Aplica as migrações pendentes. Retorna a versão final do esquema."""
    pending_source = available_migrations() if migrations is None else migrations
    version = current_version(connection)
    latest = pending_source[-1].version if pending_source else 0
    if version > latest:
        raise MigrationError("O banco é de uma versão mais nova do app.")
    pending = [migration for migration in pending_source if migration.version > version]
    if not pending:
        return version
    if before_migrate is not None and version > 0:
        before_migrate(version, latest)
    for migration in pending:
        _apply(connection, migration)
    return current_version(connection)


def _apply(connection: Connection, migration: Migration) -> None:
    # executescript não aceita parâmetros; o conteúdo vem de arquivos do próprio pacote.
    script = (
        f"BEGIN IMMEDIATE;\n{migration.sql}\nPRAGMA user_version = {migration.version:d};\nCOMMIT;"
    )
    try:
        connection.executescript(script)
    except Exception as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise MigrationError(f"Falha na migração {migration.version:04d}.") from exc
