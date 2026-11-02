"""Fluxo de atualização na interface.

Verificar → confirmar com a usuária → baixar → bloquear → instalar.

Rede e verificação rodam em segundo plano. Nada é instalado sem confirmação.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from appfin.infrastructure.app_logging import log_event, log_exception
from appfin.infrastructure.updater import AvailableUpdate, PreparedUpdate, Updater
from appfin.presentation.shared.worker import run_in_background


class UpdateController(QObject):
    def __init__(
        self, updater: Updater | None, window: QWidget, lock_session: Callable[[str], None]
    ) -> None:
        super().__init__(window)
        self._updater = updater
        self._window = window
        self._lock_session = lock_session
        self._busy = False

    @property
    def is_enabled(self) -> bool:
        return self._updater is not None

    def check(self, *, silent: bool) -> None:
        """``silent``: verificação automática — só incomoda se houver atualização."""
        updater = self._updater
        if updater is None:
            if not silent:
                self._inform(
                    "Atualizações automáticas ainda não estão configuradas nesta instalação."
                )
            return
        if self._busy:
            return
        self._busy = True

        def found(result: object) -> None:
            self._busy = False
            if isinstance(result, AvailableUpdate):
                self._offer(result)
            elif not silent:
                self._inform("Você já está usando a versão mais recente.")

        def failed(error: Exception) -> None:
            self._busy = False
            log_exception("update.check", error, error_code="E-UPDATE-CHECK")
            if not silent:
                self._inform(
                    "Não foi possível verificar atualizações agora. (código E-UPDATE-CHECK)"
                )

        run_in_background(updater.check, found, failed, parent=self)

    def _offer(self, update: AvailableUpdate) -> None:
        answer = self._ask(
            f"A versão {update.version} está disponível.\n\n"
            "O app será bloqueado, atualizado e aberto de novo. Seus dados não são alterados.\n\n"
            "Atualizar agora?"
        )
        if answer:
            self._download()

    def _download(self) -> None:
        updater = self._updater
        if updater is None or self._busy:
            return
        self._busy = True

        def ready(result: object) -> None:
            self._busy = False
            if isinstance(result, PreparedUpdate):
                self._install(result)

        def failed(error: Exception) -> None:
            self._busy = False
            log_exception("update.download", error, error_code="E-UPDATE-VERIFY")
            self._inform(
                "A atualização não foi instalada porque não passou na verificação de segurança "
                "ou o download falhou. (código E-UPDATE-VERIFY)"
            )

        run_in_background(updater.download, ready, failed, parent=self)

    def _install(self, prepared: PreparedUpdate) -> None:
        log_event("update.install", outcome="ok", app_version=prepared.version)
        self._lock_session("update")
        try:
            Updater.install_and_exit(prepared)
        except SystemExit:
            # O tufup encerra com sys.exit() após iniciar o script de troca dos arquivos; dentro do
            # loop do Qt, encerramos de forma ordenada.
            QCoreApplication.quit()

    def _inform(self, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, "Atualizações", text, parent=self._window)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.exec()

    def _ask(self, text: str) -> bool:
        """Confirmação explícita: botões em português, sem atalho de letra; o padrão é recusar."""
        box = QMessageBox(
            QMessageBox.Icon.Question, "Atualização disponível", text, parent=self._window
        )
        box.setTextFormat(Qt.TextFormat.PlainText)
        accept = box.addButton("Atualizar agora", QMessageBox.ButtonRole.AcceptRole)
        decline = box.addButton("Agora não", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(decline)
        box.setEscapeButton(decline)
        box.exec()
        return box.clickedButton() is accept
