from pathlib import Path

import pytest

from appfin.infrastructure.crypto.secret import SecretBytes
from appfin.infrastructure.persistence.database import (
    Connection,
    WrongDatabaseKeyError,
    open_encrypted,
)
from appfin.infrastructure.persistence.migrator import (
    Migration,
    MigrationError,
    available_migrations,
    current_version,
    migrate,
)

DEK = bytes(range(32))
CANARY = "PACIENTE-FICTICIO-CANARIO-123"


def _dek() -> SecretBytes:
    return SecretBytes(DEK)


def test_file_on_disk_is_encrypted(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    connection = open_encrypted(path, _dek())
    migrate(connection)
    connection.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?)",
        ("teste", CANARY, "2026-01-01T00:00:00Z"),
    )
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    raw = path.read_bytes()

    assert not raw.startswith(b"SQLite format 3")
    assert CANARY.encode() not in raw


def test_wrong_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    open_encrypted(path, _dek()).close()

    with pytest.raises(WrongDatabaseKeyError):
        open_encrypted(path, SecretBytes(bytes(32)))


def test_reopen_with_same_key_reads_data(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    first = open_encrypted(path, _dek())
    migrate(first)
    first.execute(
        "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, ?)",
        ("tema", "claro", "2026-01-01T00:00:00Z"),
    )
    first.close()

    second = open_encrypted(path, _dek())

    assert second.execute("SELECT value FROM setting WHERE key = ?", ("tema",)).fetchone()[0] == (
        "claro"
    )
    second.close()


def test_security_pragmas_are_active(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())

    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA cipher_memory_security").fetchone()[0] == "1"
    connection.close()


def test_sqlite_is_built_serialized_so_connection_handoff_is_safe(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    options = {row[0] for row in connection.execute("PRAGMA compile_options")}

    assert "THREADSAFE=1" in options
    connection.close()


def test_migrations_are_sequential_and_idempotent(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    latest = available_migrations()[-1].version

    assert migrate(connection) == latest
    assert migrate(connection) == latest
    assert current_version(connection) == latest
    connection.close()


def test_failed_migration_rolls_back_completely(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    broken = [
        Migration(1, "0001_ok.sql", "CREATE TABLE a (x INTEGER) STRICT;"),
        Migration(2, "0002_broken.sql", "CREATE TABLE b (x INTEGER) STRICT; SELECT * FROM nada;"),
    ]

    with pytest.raises(MigrationError):
        migrate(connection, broken)

    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "a" in tables
    assert "b" not in tables
    assert current_version(connection) == 1
    connection.close()


def test_backup_hook_runs_only_when_upgrading_existing_database(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    calls: list[tuple[int, int]] = []
    v1 = [Migration(1, "0001_a.sql", "CREATE TABLE a (x INTEGER) STRICT;")]
    v2 = [*v1, Migration(2, "0002_b.sql", "CREATE TABLE b (x INTEGER) STRICT;")]

    migrate(connection, v1, before_migrate=lambda old, new: calls.append((old, new)))
    migrate(connection, v2, before_migrate=lambda old, new: calls.append((old, new)))

    assert calls == [(1, 2)]
    connection.close()


def test_database_from_newer_app_is_refused(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    connection.execute("PRAGMA user_version = 99")

    with pytest.raises(MigrationError):
        migrate(connection)
    connection.close()


def test_audit_table_rejects_free_text_outcome(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    migrate(connection)

    with pytest.raises(Exception, match="CHECK"):
        connection.execute(
            "INSERT INTO audit_event (occurred_at, event, outcome) VALUES (?, ?, ?)",
            ("2026-01-01T00:00:00Z", "unlock", "senha era X"),
        )
    connection.close()


_NOW = "2026-01-01T00:00:00Z"


def _seed_version_3(connection: Connection) -> None:
    """Banco na versão anterior à 0004, com grupo, categoria e lançamento que a referencia."""
    migrate(connection, available_migrations()[:3])
    connection.execute(
        "INSERT INTO account (id, name, kind, version, created_at, updated_at) "
        "VALUES ('acc', 'Caixa', 'cash', 1, ?, ?)",
        (_NOW, _NOW),
    )
    connection.executemany(
        "INSERT INTO category (id, parent_id, name, kind, dre_group, version, created_at, "
        "updated_at) VALUES (?, ?, ?, 'expense', 'operating_expenses', 1, ?, ?)",
        [("grp", None, "Despesas", _NOW, _NOW), ("cat", "grp", "Aluguel", _NOW, _NOW)],
    )
    connection.execute(
        "INSERT INTO financial_transaction (id, kind, description, amount_cents, accrual_date, "
        "due_date, status, account_id, category_id, version, created_at, updated_at) "
        "VALUES ('tx', 'expense', 'Aluguel', 1000, '2026-01-31', '2026-01-31', 'pending', "
        "'acc', 'cat', 1, ?, ?)",
        (_NOW, _NOW),
    )


def test_migration_0004_keeps_categories_and_references(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    _seed_version_3(connection)
    before = connection.execute("SELECT * FROM category ORDER BY id").fetchall()

    migrate(connection)

    assert connection.execute("SELECT * FROM category ORDER BY id").fetchall() == before
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    indexes = {row[1] for row in connection.execute("PRAGMA index_list(category)")}
    assert "idx_category_parent" in indexes
    connection.close()


def test_migration_0004_accepts_investments_and_still_enforces_rules(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    _seed_version_3(connection)
    migrate(connection)
    insert = (
        "INSERT INTO category (id, name, kind, dre_group, version, created_at, updated_at) "
        "VALUES (?, 'Cursos', 'expense', ?, 1, ?, ?)"
    )

    connection.execute(insert, ("inv", "investments", _NOW, _NOW))

    with pytest.raises(Exception, match="CHECK"):
        connection.execute(insert, ("bad", "lucro_magico", _NOW, _NOW))
    with pytest.raises(Exception, match="FOREIGN KEY"):
        connection.execute("DELETE FROM category WHERE id = 'cat'")
    connection.close()


def test_foreign_keys_off_migration_with_broken_reference_rolls_back(tmp_path: Path) -> None:
    connection = open_encrypted(tmp_path / "app.db", _dek())
    base = [
        Migration(1, "0001_a.sql", "CREATE TABLE p (id TEXT PRIMARY KEY) STRICT;"),
    ]
    broken = [
        *base,
        Migration(
            2,
            "0002_b.sql",
            "-- appfin:foreign-keys-off\n"
            "CREATE TABLE c (p_id TEXT REFERENCES p (id)) STRICT;\n"
            "INSERT INTO c VALUES ('inexistente');",
        ),
    ]
    migrate(connection, base)

    with pytest.raises(MigrationError):
        migrate(connection, broken)

    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "c" not in tables
    assert current_version(connection) == 1
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    connection.close()
