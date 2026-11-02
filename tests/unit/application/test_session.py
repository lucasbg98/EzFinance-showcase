"""Testes da sessão com fakes em memória (sem cripto nem banco)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from appfin.application.ports import InvalidCredentialError
from appfin.application.session import AppSession, SessionState, WeakPasswordError

STRONG = "girassol trator piano nuvem"


class FakeKey:
    def __init__(self) -> None:
        self.is_wiped = False

    def wipe(self) -> None:
        self.is_wiped = True


class FakeVault:
    def __init__(self) -> None:
        self.password: str | None = None
        self.issued: list[FakeKey] = []

    def exists(self) -> bool:
        return self.password is not None

    def create(self, password: str) -> tuple[str, FakeKey]:
        self.password = password
        return "RECOVERY-KEY", self._issue()

    def unlock_with_password(self, password: str) -> FakeKey:
        if password != self.password:
            raise InvalidCredentialError
        return self._issue()

    def unlock_with_recovery_key(self, recovery_key: str) -> FakeKey:
        if recovery_key != "RECOVERY-KEY":
            raise InvalidCredentialError
        return self._issue()

    def _issue(self) -> FakeKey:
        key = FakeKey()
        self.issued.append(key)
        return key


class FakeStore:
    def __init__(self) -> None:
        self.is_open = False
        self.audit: list[tuple[str, str]] = []
        self.fail_open = False

    def open(self, key: FakeKey) -> None:
        if self.fail_open:
            raise RuntimeError("falha simulada")
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def record_audit(self, event: str, outcome: str, occurred_at: datetime) -> None:
        self.audit.append((event, outcome))


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def record(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def parts() -> tuple[FakeVault, FakeStore, FakeEvents]:
    return FakeVault(), FakeStore(), FakeEvents()


def _session(parts: tuple[FakeVault, FakeStore, FakeEvents]) -> AppSession:
    vault, store, events = parts
    return AppSession(vault, store, FixedClock(), events)  # type: ignore[arg-type]


def test_lifecycle_setup_lock_unlock(parts: tuple[FakeVault, FakeStore, FakeEvents]) -> None:
    session = _session(parts)
    _, store, _ = parts
    assert session.state is SessionState.NEEDS_SETUP

    recovery = session.create(STRONG)

    assert recovery == "RECOVERY-KEY"
    assert session.state is SessionState.UNLOCKED and store.is_open

    session.lock()

    assert session.state is SessionState.LOCKED and not store.is_open

    session.unlock(STRONG)

    assert session.state is SessionState.UNLOCKED


def test_lock_wipes_the_key(parts: tuple[FakeVault, FakeStore, FakeEvents]) -> None:
    session = _session(parts)
    vault, _, _ = parts
    session.create(STRONG)

    session.lock()

    assert all(key.is_wiped for key in vault.issued)


def test_weak_password_is_refused_before_creating_vault(
    parts: tuple[FakeVault, FakeStore, FakeEvents],
) -> None:
    session = _session(parts)
    vault, _, _ = parts

    with pytest.raises(WeakPasswordError) as error:
        session.create("123456")

    assert error.value.problems
    assert not vault.exists()


def test_failed_unlocks_increase_delay_and_reset_on_success(
    parts: tuple[FakeVault, FakeStore, FakeEvents],
) -> None:
    session = _session(parts)
    session.create(STRONG)
    session.lock()

    delays = []
    for _ in range(8):
        with pytest.raises(InvalidCredentialError):
            session.unlock("errada")
        delays.append(session.unlock_delay_seconds())

    assert delays == [1, 2, 4, 8, 16, 32, 60, 60]

    session.unlock(STRONG)

    assert session.unlock_delay_seconds() == 0


def test_recovery_key_unlocks(parts: tuple[FakeVault, FakeStore, FakeEvents]) -> None:
    session = _session(parts)
    session.create(STRONG)
    session.lock()

    session.unlock_with_recovery_key("RECOVERY-KEY")

    assert session.state is SessionState.UNLOCKED


def test_key_is_wiped_if_database_fails_to_open(
    parts: tuple[FakeVault, FakeStore, FakeEvents],
) -> None:
    session = _session(parts)
    vault, store, _ = parts
    session.create(STRONG)
    session.lock()
    store.fail_open = True

    with pytest.raises(RuntimeError):
        session.unlock(STRONG)

    assert vault.issued[-1].is_wiped
    assert session.state is SessionState.LOCKED


def test_events_and_audit_never_carry_secrets(
    parts: tuple[FakeVault, FakeStore, FakeEvents],
) -> None:
    session = _session(parts)
    _, store, events = parts
    session.create(STRONG)
    session.lock()
    with pytest.raises(InvalidCredentialError):
        session.unlock("tentativa-errada-xyz")

    dump = repr(events.events) + repr(store.audit)

    assert STRONG not in dump
    assert "tentativa-errada-xyz" not in dump
    assert "RECOVERY-KEY" not in dump
