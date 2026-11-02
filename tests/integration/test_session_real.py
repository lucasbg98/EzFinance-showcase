"""Sessão com cofre em arquivo e banco SQLCipher reais (parâmetros de Argon2id rápidos)."""

from pathlib import Path

import pytest

from appfin.application.ports import InvalidCredentialError, StorageUnavailableError
from appfin.application.session import AppSession, SessionState
from appfin.infrastructure.key_vault import FileKeyVault
from appfin.infrastructure.paths import AppPaths
from appfin.infrastructure.persistence.data_store import SqlCipherDataStore
from appfin.infrastructure.system import LoggingEventLog, SystemClock
from tests.support import FAST_MINIMUM, FAST_PARAMS

STRONG = "girassol trator piano nuvem"


def _build(root: Path) -> tuple[AppSession, SqlCipherDataStore, AppPaths]:
    paths = AppPaths(root)
    store = SqlCipherDataStore(paths.database_file)
    vault = FileKeyVault(paths.vault_file, FAST_PARAMS, FAST_MINIMUM)
    return AppSession(vault, store, SystemClock(), LoggingEventLog()), store, paths


def test_full_cycle_with_real_crypto_and_database(data_dir: Path) -> None:
    session, _store, paths = _build(data_dir)

    recovery = session.create(STRONG)
    session.lock()

    assert paths.vault_file.exists() and paths.database_file.exists()

    # Reabrindo "o app" do zero (novos objetos), como após reiniciar.
    session2, store2, _ = _build(data_dir)
    assert session2.state is SessionState.LOCKED
    with pytest.raises(InvalidCredentialError):
        session2.unlock("senha totalmente errada")
    session2.unlock(STRONG)
    events = [row[0] for row in store2.connection.execute("SELECT event FROM audit_event")]
    assert events == ["vault.created", "session.lock", "session.unlock"]
    session2.lock()

    session2.unlock_with_recovery_key(recovery)
    assert session2.state is SessionState.UNLOCKED
    session2.lock()


def test_corrupted_vault_is_reported_without_crashing(data_dir: Path) -> None:
    session, _, paths = _build(data_dir)
    session.create(STRONG)
    session.lock()
    paths.vault_file.write_text("corrompido", encoding="utf-8")

    session2, _, _ = _build(data_dir)
    with pytest.raises(StorageUnavailableError):
        session2.unlock(STRONG)
