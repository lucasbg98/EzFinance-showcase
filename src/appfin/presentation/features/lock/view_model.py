"""View model das telas de configuração inicial e desbloqueio.

Operações com Argon2id (~1 s) rodam em segundo plano; o resultado volta por signal.
Mensagens para a usuária são amigáveis e nunca trazem detalhe técnico nem dado sensível.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from appfin.application.password_policy import PasswordAssessment, assess_master_password
from appfin.application.ports import InvalidCredentialError, StorageUnavailableError
from appfin.application.session import AppSession, SessionState, WeakPasswordError
from appfin.infrastructure.app_logging import log_exception
from appfin.presentation.shared.worker import run_in_background

Runner = Callable[[Callable[[], Any], Callable[[Any], None], Callable[[Exception], None]], None]


class LockViewModel(QObject):
    busy_changed = Signal(bool)
    error = Signal(str)
    created = Signal(str)  # chave de recuperação, exibida uma única vez
    unlocked = Signal()
    delay_started = Signal(int)

    def __init__(self, session: AppSession, runner: Runner | None = None) -> None:
        super().__init__()
        self._session = session
        self._runner: Runner = runner or self._qt_runner
        self._busy = False

    @property
    def state(self) -> SessionState:
        return self._session.state

    @property
    def is_busy(self) -> bool:
        return self._busy

    def assess(self, password: str) -> PasswordAssessment:
        return assess_master_password(password)

    # ------------------------------------------------------------------ comandos
    def create(self, password: str, confirmation: str) -> None:
        if password != confirmation:
            self.error.emit("As senhas digitadas não são iguais.")
            return
        self._run(lambda: self._session.create(password), self._on_created, "setup.create")

    def unlock(self, password: str) -> None:
        if not password:
            self.error.emit("Digite a senha mestra.")
            return
        self._run(lambda: self._session.unlock(password), self._on_unlocked, "session.unlock")

    def unlock_with_recovery_key(self, recovery_key: str) -> None:
        if not recovery_key.strip():
            self.error.emit("Digite a chave de recuperação.")
            return
        self._run(
            lambda: self._session.unlock_with_recovery_key(recovery_key),
            self._on_unlocked,
            "session.unlock_recovery",
        )

    # ------------------------------------------------------------------ interno
    def _run(self, work: Callable[[], Any], on_ok: Callable[[Any], None], event: str) -> None:
        if self._busy:
            return
        self._set_busy(True)

        def succeeded(result: Any) -> None:
            self._set_busy(False)
            on_ok(result)

        def failed(error: Exception) -> None:
            self._set_busy(False)
            self._handle_error(error, event)

        self._runner(work, succeeded, failed)

    def _on_created(self, recovery_key: Any) -> None:
        self.created.emit(str(recovery_key))

    def _on_unlocked(self, _: Any) -> None:
        self.unlocked.emit()

    def _handle_error(self, error: Exception, event: str) -> None:
        if isinstance(error, WeakPasswordError):
            self.error.emit(" ".join(error.problems))
        elif isinstance(error, InvalidCredentialError):
            self.error.emit(
                "Chave de recuperação incorreta." if "recovery" in event else "Senha incorreta."
            )
            delay = self._session.unlock_delay_seconds()
            if delay:
                self.delay_started.emit(delay)
        elif isinstance(error, StorageUnavailableError):
            log_exception(event, error, error_code="E-STORAGE")
            self.error.emit("Não foi possível abrir os dados do app. (código E-STORAGE)")
        else:
            log_exception(event, error, error_code="E-UNEXPECTED")
            self.error.emit("Ocorreu um erro inesperado. (código E-UNEXPECTED)")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    def _qt_runner(
        self,
        work: Callable[[], Any],
        on_ok: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        run_in_background(work, on_ok, on_error, parent=self)
