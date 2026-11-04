"""Janela principal: alterna entre configuração, chave de recuperação, desbloqueio e o app.

Depois do desbloqueio: no primeiro uso, os dados do consultório (que criam categorias e conta
padrão); depois, o app com menu lateral. Ao bloquear, a página com dados é **destruída** (não só
escondida) para limpar o estado das telas.

Também é o AppControl das telas: restauração de backup (que troca de tela), pausa do bloqueio
automático e nova chave de recuperação. Backups automáticos: a cada 24 h de uso e ao fechar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QDialog, QMainWindow, QStackedWidget, QToolBar, QWidget

from appfin import PRODUCT_NAME, __version__
from appfin.application.session import AppSession, SessionState
from appfin.infrastructure.app_logging import log_exception
from appfin.infrastructure.updater import Updater
from appfin.presentation.auto_lock import InactivityLock, WindowsSessionWatcher
from appfin.presentation.features.backup.view import RestoreDialog
from appfin.presentation.features.company.view import CompanyForm
from appfin.presentation.features.lock.view_model import LockViewModel
from appfin.presentation.features.lock.views import RecoveryKeyView, SetupView, UnlockView
from appfin.presentation.features.updates.update_controller import UpdateController
from appfin.presentation.shared.formatting import ValuesVisibility
from appfin.presentation.shared.ui.feedback import show_error, show_info
from appfin.presentation.shell import AppShell
from appfin.presentation.workspace import WorkspaceFactory

APP_TITLE = PRODUCT_NAME
AUTO_BACKUP_CHECK_MS = 30 * 60 * 1000  # confere a cada 30 min se já passaram 24 h do último


class MainWindow(QMainWindow):
    def __init__(
        self,
        session: AppSession,
        auto_lock_minutes: float,
        workspace_factory: WorkspaceFactory,
        updater: Updater | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self.resize(1100, 720)
        self._session = session
        self._workspace_factory = workspace_factory
        self.visibility = ValuesVisibility()
        self._vm = LockViewModel(session)
        self._inactivity = InactivityLock(auto_lock_minutes, self)
        self._session_watcher = WindowsSessionWatcher(self)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        self.setup_view = SetupView(self._vm)
        self.recovery_view = RecoveryKeyView()
        self.unlock_view = UnlockView(self._vm)
        for page in (self.setup_view, self.recovery_view, self.unlock_view):
            self._stack.addWidget(page)
        self._home: QWidget | None = None

        self._lock_action = QAction("Bloquear", self)
        self._lock_action.setShortcut(QKeySequence("Ctrl+L"))
        self._lock_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._lock_action.triggered.connect(lambda: self.lock("manual"))
        self._toolbar = QToolBar("Ações")
        self._toolbar.setMovable(False)
        self._toolbar.addAction(self._lock_action)
        self._hide_action = QAction("Ocultar valores", self)
        self._hide_action.setCheckable(True)
        self._hide_action.setShortcut(QKeySequence("Ctrl+H"))
        self._hide_action.setToolTip("Mostra R$ ••••• no lugar dos valores (Ctrl+H)")
        self._hide_action.toggled.connect(self.visibility.set_hidden)
        self._toolbar.addAction(self._hide_action)
        self._updates = UpdateController(updater, self, self.lock)
        self._checked_updates = False
        self._update_action = QAction("Verificar atualizações", self)
        self._update_action.triggered.connect(lambda: self._updates.check(silent=False))
        self._toolbar.addAction(self._update_action)
        self.addToolBar(self._toolbar)

        self._backup_timer = QTimer(self)
        self._backup_timer.setInterval(AUTO_BACKUP_CHECK_MS)
        self._backup_timer.timeout.connect(lambda: self.auto_backup("periodic"))
        self._auto_lock_paused = False
        self.setup_view.restore_requested.connect(self._restore_from_setup)

        self._vm.created.connect(self._on_created)
        self._vm.unlocked.connect(self._show_home)
        self.recovery_view.confirmed.connect(self._show_home)
        self._inactivity.lock_requested.connect(self.lock)
        self._session_watcher.lock_requested.connect(self.lock)

        self._show_for_state()

    # ------------------------------------------------------------------ API
    def register_native_events(self) -> None:
        """Chamar depois de ``show()``: precisa do identificador nativo da janela."""
        self._session_watcher.register(int(self.winId()))

    def lock(self, reason: str = "manual") -> None:
        if self._session.state is not SessionState.UNLOCKED:
            return
        self._inactivity.stop()
        self._backup_timer.stop()
        self._destroy_home()
        self.recovery_view.clear()
        self._session.lock(reason)
        self._show_for_state()

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ navegação
    def _show_for_state(self) -> None:
        state = self._session.state
        self._toolbar.setVisible(state is SessionState.UNLOCKED)
        if state is SessionState.NEEDS_SETUP:
            self.setup_view.clear()
            self._stack.setCurrentWidget(self.setup_view)
        elif state is SessionState.LOCKED:
            self.unlock_view.reset()
            self._stack.setCurrentWidget(self.unlock_view)

    def _on_created(self, recovery_key: str) -> None:
        self.setup_view.clear()
        self.recovery_view.show_key(recovery_key)
        self._stack.setCurrentWidget(self.recovery_view)
        # A contagem de inatividade só começa após a confirmação: um bloqueio aqui faria a chave
        # sumir antes de ser anotada. (Bloquear o Windows ainda bloqueia; para esse caso e o de
        # chave perdida existe "Gerar nova chave de recuperação" em Backup e segurança.)

    @property
    def data_page(self) -> QWidget | None:
        """Página com dados (onboarding ou app), ou ``None`` se bloqueado."""
        return self._home

    def _show_home(self) -> None:
        self._destroy_home()
        workspace = self._workspace_factory(self.visibility, self)
        if workspace.catalog.get_company() is None:
            onboarding = CompanyForm(workspace, onboarding=True)
            onboarding.saved.connect(lambda _company: self._show_shell(initial="accounts"))
            self._set_home(onboarding)
        else:
            self._set_home(AppShell(workspace))
        self._toolbar.setVisible(True)
        self._start_inactivity()
        self._backup_timer.start()
        QTimer.singleShot(0, lambda: self.auto_backup("periodic"))
        if not self._checked_updates and self._updates.is_enabled:
            # Uma verificação automática por execução, depois do desbloqueio (sem incomodar se não
            # houver novidade).
            self._checked_updates = True
            self._updates.check(silent=True)

    def _show_shell(self, initial: str) -> None:
        self._destroy_home()
        self._set_home(AppShell(self._workspace_factory(self.visibility, self), initial=initial))

    def _set_home(self, page: QWidget) -> None:
        self._home = page
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def _destroy_home(self) -> None:
        if self._home is not None:
            self._stack.removeWidget(self._home)
            self._home.deleteLater()
            self._home = None

    # ------------------------------------------------------------------ backup automático
    def auto_backup(self, reason: str) -> None:
        """Backup se já passaram 24 h do último (ou sempre, ao fechar). Falha não interrompe."""
        if self._session.state is not SessionState.UNLOCKED:
            return
        try:
            backups = self._workspace_factory(self.visibility, self).backups
            if reason == "close" or backups.is_due():
                report = backups.backup_now(reason)
                if report.failed:
                    self._warn_backup()
        except Exception as error:  # noqa: BLE001 - nunca derrubar o app por causa do backup
            log_exception("backup.auto", error, error_code="E-BACKUP")
            self._warn_backup()

    def _warn_backup(self) -> None:
        self.statusBar().showMessage(
            "Atenção: o backup automático não foi gravado em todas as pastas. "
            "Veja em Backup e segurança."
        )

    # ------------------------------------------------------------------ AppControl
    def apply_restore(self) -> None:
        """Troca os dados pelos do backup preparado e volta para a tela de desbloqueio."""
        self._inactivity.stop()
        self._backup_timer.stop()
        self._destroy_home()
        self.recovery_view.clear()
        try:
            self._session.apply_restore()
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            self._session.discard_restore()
            show_error(self, error, "backup.restore")
            if self._session.state is SessionState.UNLOCKED:
                self._show_home()
            else:
                self._show_for_state()
            return
        self._show_for_state()
        show_info(
            self,
            "Backup restaurado. Entre com a senha mestra da época do backup "
            "(ou com a chave de recuperação daquela época).",
        )

    def discard_restore(self) -> None:
        self._session.discard_restore()

    def set_auto_lock_paused(self, paused: bool) -> None:
        self._auto_lock_paused = paused
        if paused:
            self._inactivity.stop()
        elif self._session.state is SessionState.UNLOCKED:
            self._inactivity.start()

    def prepare_recovery_key(self, password: str) -> str:
        return self._session.prepare_recovery_key(password)

    def confirm_recovery_key(self) -> None:
        self._session.confirm_recovery_key()

    def cancel_recovery_key(self) -> None:
        self._session.cancel_recovery_key()

    def _start_inactivity(self) -> None:
        if not self._auto_lock_paused:
            self._inactivity.start()

    def _restore_from_setup(self) -> None:
        dialog = RestoreDialog(
            lambda path, password, recovery_key: self._session.prepare_restore(
                path, password=password, recovery_key=recovery_key
            ),
            self._session.discard_restore,
            self,
            replaces_data=False,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_restore()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API Qt
        self.auto_backup("close")
        self.lock("app_closed")
        super().closeEvent(event)
