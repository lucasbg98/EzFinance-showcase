"""Ciclo de vida da sessão: configurar, desbloquear e bloquear o app.

Estados: ``NEEDS_SETUP`` (sem cofre) → ``UNLOCKED`` ↔ ``LOCKED``.
Ao bloquear, o banco é fechado e a chave de dados é sobrescrita.

Backup e restauração também passam por aqui, porque dependem da chave de dados (que só a sessão
guarda) e do estado (restaurar exige fechar o banco).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path

from appfin.application.password_policy import assess_master_password
from appfin.application.ports import (
    BackupEngine,
    BackupManifest,
    BackupReport,
    Clock,
    DataKey,
    DataStore,
    EventLog,
    InvalidCredentialError,
    KeyVault,
    OrphanedDataError,
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
    def __init__(
        self,
        vault: KeyVault,
        store: DataStore,
        clock: Clock,
        events: EventLog,
        backups: BackupEngine | None = None,
        local_backup_dir: Path | None = None,
    ) -> None:
        self._vault = vault
        self._store = store
        self._clock = clock
        self._events = events
        self._backups = backups
        self._local_backup_dir = local_backup_dir
        self._key: DataKey | None = None
        self._failed_attempts = 0
        self._pending_recovery: object | None = None

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
        if self._store.exists():
            # Criar um cofre novo aqui geraria uma chave que nunca abriria o banco existente.
            raise OrphanedDataError("Banco existente sem o cofre correspondente.")
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
            self._pending_recovery = None
            self._store.close()
            self._key.wipe()
            self._key = None
            self._events.record("session.lock", outcome="ok", reason=reason)

    # ------------------------------------------------------------------ chave de recuperação
    def prepare_recovery_key(self, password: str) -> str:
        """Exige a senha mestra de novo e gera uma nova chave, **ainda sem gravar**.

        A chave antiga continua valendo até ``confirm_recovery_key``: se o app bloquear antes da
        confirmação, nada se perde.
        """
        key = self._require_key()
        try:
            self._vault.verify_password(password)
        except InvalidCredentialError:
            self._events.record("vault.recovery_key_replaced", outcome="failed")
            raise
        text, self._pending_recovery = self._vault.prepare_recovery_key(key)
        return text

    def confirm_recovery_key(self) -> None:
        self._require_key()
        if self._pending_recovery is None:
            raise RuntimeError("Nenhuma chave de recuperação pendente.")
        pending, self._pending_recovery = self._pending_recovery, None
        self._vault.commit_recovery_key(pending)
        self._store.record_audit("vault.recovery_key_replaced", "ok", self._clock.now())
        self._events.record("vault.recovery_key_replaced", outcome="ok")

    def cancel_recovery_key(self) -> None:
        self._pending_recovery = None

    # ------------------------------------------------------------------ backup
    def create_backup(self, destinations: Sequence[Path], reason: str) -> BackupReport:
        key = self._require_key()
        try:
            report = self._engine().create(key, destinations)
        except Exception:
            self._events.record("backup.create", outcome="failed", reason=reason)
            raise
        self._store.record_audit("backup.create", "ok", self._clock.now())
        self._events.record(
            "backup.create", outcome="ok", reason=reason, count=len(report.saved_to)
        )
        return report

    def prepare_restore(
        self, file: Path, *, password: str | None = None, recovery_key: str | None = None
    ) -> BackupManifest:
        """Pode ser chamado em qualquer estado (inclusive no primeiro uso, em outro computador)."""
        try:
            manifest = self._engine().prepare_restore(
                file, password=password, recovery_key=recovery_key
            )
        except Exception:
            self._events.record("backup.restore_prepare", outcome="failed")
            raise
        self._events.record(
            "backup.restore_prepare", outcome="ok", schema_version=manifest.schema_version
        )
        return manifest

    def discard_restore(self) -> None:
        self._engine().discard_restore()

    def apply_restore(self) -> None:
        """Troca os dados atuais pelos do backup preparado.

        Se o app estiver desbloqueado: primeiro faz um backup do estado atual (na pasta local) e
        bloqueia. Depois da troca, o app fica bloqueado e abre com a senha **da época do backup**.
        """
        if self._key is not None:
            if self._local_backup_dir is None:
                raise RuntimeError("Pasta de backup local não configurada.")
            self.create_backup([self._local_backup_dir], reason="before_restore")
            self.lock("restore")
        self._engine().apply_restore()
        self._failed_attempts = 0
        self._events.record("backup.restore", outcome="ok")

    # ------------------------------------------------------------------ interno
    def _require_key(self) -> DataKey:
        if self._key is None:
            raise SessionLockedError("O app está bloqueado.")
        return self._key

    def _engine(self) -> BackupEngine:
        if self._backups is None:
            raise RuntimeError("Backup não configurado.")
        return self._backups

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
