"""Ciclo de vida da sessão: configurar, desbloquear e bloquear o app.

Estados: ``NEEDS_SETUP`` (sem cofre) → ``UNLOCKED`` ↔ ``LOCKED``.
Ao bloquear, o banco é fechado e a chave de dados é sobrescrita.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from appfin.application.password_policy import assess_master_password
from appfin.application.ports import (
    Clock,
    DataKey,
    DataStore,
    EventLog,
    InvalidCredentialError,
    KeyVault,
)

MAX_UNLOCK_DELAY_SECONDS = 60


class SessionState(StrEnum):
    NEEDS_SETUP = "needs_setup"
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class WeakPasswordError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("Senha mestra não atende à política.")
        self.problems = problems


class SessionLockedError(RuntimeError):
    """Operação que exige o app desbloqueado."""


class AppSession:
    def __init__(self, vault: KeyVault, store: DataStore, clock: Clock, events: EventLog) -> None:
        self._vault = vault
        self._store = store
        self._clock = clock
        self._events = events
        self._key: DataKey | None = None
        self._failed_attempts = 0

    # ------------------------------------------------------------------ estado
    @property
    def state(self) -> SessionState:
        if self._key is not None:
            return SessionState.UNLOCKED
        return SessionState.LOCKED if self._vault.exists() else SessionState.NEEDS_SETUP

    @property
    def failed_attempts(self) -> int:
        return self._failed_attempts

    def unlock_delay_seconds(self) -> int:
        """Atraso progressivo após falhas (1, 2, 4… até 60 s).

        Só dificulta tentativas pela interface; a defesa real contra ataque offline é o custo do
        Argon2id (docs/PROJETO.md, T12).
        """
        if self._failed_attempts == 0:
            return 0
        return int(min(2 ** (self._failed_attempts - 1), MAX_UNLOCK_DELAY_SECONDS))

    # ------------------------------------------------------------------ transições
    def create(self, password: str, user_inputs: tuple[str, ...] = ()) -> str:
        """Cria o cofre e o banco. Retorna a chave de recuperação (mostrar uma única vez)."""
        if self.state is not SessionState.NEEDS_SETUP:
            raise RuntimeError("O cofre já existe.")
        assessment = assess_master_password(password, user_inputs)
        if not assessment.is_acceptable:
            raise WeakPasswordError(assessment.problems)
        recovery_key, key = self._vault.create(password)
        self._open(key, "vault.created")
        return recovery_key

    def unlock(self, password: str) -> None:
        self._unlock(lambda: self._vault.unlock_with_password(password), "session.unlock")

    def unlock_with_recovery_key(self, recovery_key: str) -> None:
        self._unlock(
            lambda: self._vault.unlock_with_recovery_key(recovery_key),
            "session.unlock_recovery",
        )

    def lock(self, reason: str = "manual") -> None:
        if self._key is None:
            return
        try:
            self._store.record_audit("session.lock", "ok", self._clock.now())
        finally:
            self._store.close()
            self._key.wipe()
            self._key = None
            self._events.record("session.lock", outcome="ok", reason=reason)

    # ------------------------------------------------------------------ interno
    def _unlock(self, obtain_key: Callable[[], DataKey], event: str) -> None:
        if self.state is not SessionState.LOCKED:
            raise RuntimeError("Estado inválido para desbloqueio.")
        try:
            key = obtain_key()
        except InvalidCredentialError:
            self._failed_attempts += 1
            self._events.record(event, outcome="failed", attempt=self._failed_attempts)
            raise
        self._failed_attempts = 0
        self._open(key, event)

    def _open(self, key: DataKey, event: str) -> None:
        try:
            self._store.open(key)
        except BaseException:
            key.wipe()
            raise
        self._key = key
        self._store.record_audit(event, "ok", self._clock.now())
        self._events.record(event, outcome="ok")
