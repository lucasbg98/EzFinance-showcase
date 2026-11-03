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
# Primeira linha de uma migração que reconstrói tabela referenciada por chave estrangeira.
_FOREIGN_KEYS_OFF_MARKER = "-- appfin:foreign-keys-off"


class MigrationError(DatabaseError):
    """Falha ao aplicar migração (o banco permanece na versão anterior)."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def disables_foreign_keys(self) -> bool:
        """Reconstrução de tabela: FKs desligadas só durante o script (ver ``_apply``)."""
        return self.sql.lstrip().startswith(_FOREIGN_KEYS_OFF_MARKER)


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
    if migration.disables_foreign_keys:
        _apply_with_foreign_keys_off(connection, migration)
        return
    # executescript não aceita parâmetros; o conteúdo vem de arquivos do próprio pacote.
    script = (
        f"BEGIN IMMEDIATE;\n{migration.sql}\nPRAGMA user_version = {migration.version:d};\nCOMMIT;"
    )
    try:
        connection.executescript(script)
    except Exception as exc:
        _rollback(connection)
        raise MigrationError(f"Falha na migração {migration.version:04d}.") from exc


def _apply_with_foreign_keys_off(connection: Connection, migration: Migration) -> None:
    """Procedimento oficial do SQLite para reconstruir tabelas referenciadas por FK.

    ``PRAGMA foreign_keys`` só muda fora de transação. A integridade não é relaxada: antes do
    commit, ``PRAGMA foreign_key_check`` precisa voltar vazio; senão, tudo é desfeito.
    """
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{migration.sql}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise MigrationError("Chaves estrangeiras inválidas após a migração.")
        connection.execute(f"PRAGMA user_version = {migration.version:d}")
        connection.execute("COMMIT")
    except Exception as exc:
        _rollback(connection)
        raise MigrationError(f"Falha na migração {migration.version:04d}.") from exc
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _rollback(connection: Connection) -> None:
    if connection.in_transaction:
        connection.execute("ROLLBACK")
