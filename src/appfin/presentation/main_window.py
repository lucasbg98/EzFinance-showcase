"""Janela principal: alterna entre configuração, chave de recuperação, desbloqueio e o app.

Depois do desbloqueio: no primeiro uso, os dados do consultório (que criam categorias e conta
padrão); depois, o app com menu lateral. Ao bloquear, a página com dados é **destruída** (não só
escondida) para limpar o estado das telas.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QToolBar, QWidget

from appfin import __version__
from appfin.application.session import AppSession, SessionState
from appfin.infrastructure.updater import Updater
from appfin.presentation.auto_lock import InactivityLock, WindowsSessionWatcher
from appfin.presentation.features.company.view import CompanyForm
from appfin.presentation.features.lock.view_model import LockViewModel
from appfin.presentation.features.lock.views import RecoveryKeyView, SetupView, UnlockView
from appfin.presentation.features.updates.update_controller import UpdateController
from appfin.presentation.shared.formatting import ValuesVisibility
from appfin.presentation.shell import AppShell
from appfin.presentation.workspace import WorkspaceFactory

APP_TITLE = "AppFinanceiro"


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
        # sumir antes de ser anotada. (Bloquear o Windows ainda bloqueia; "gerar nova chave de
        # recuperação" entra na fase 1 para cobrir esse caso e o de chave perdida.)

    @property
    def data_page(self) -> QWidget | None:
        """Página com dados (onboarding ou app), ou ``None`` se bloqueado."""
        return self._home

    def _show_home(self) -> None:
        self._destroy_home()
        workspace = self._workspace_factory(self.visibility)
        if workspace.catalog.get_company() is None:
            onboarding = CompanyForm(workspace, onboarding=True)
            onboarding.saved.connect(lambda _company: self._show_shell(initial="accounts"))
            self._set_home(onboarding)
        else:
            self._set_home(AppShell(workspace))
        self._toolbar.setVisible(True)
        self._inactivity.start()
        if not self._checked_updates and self._updates.is_enabled:
            # Uma verificação automática por execução, depois do desbloqueio (sem incomodar se não
            # houver novidade).
            self._checked_updates = True
            self._updates.check(silent=True)

    def _show_shell(self, initial: str) -> None:
        self._destroy_home()
        self._set_home(AppShell(self._workspace_factory(self.visibility), initial=initial))

    def _set_home(self, page: QWidget) -> None:
        self._home = page
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def _destroy_home(self) -> None:
        if self._home is not None:
            self._stack.removeWidget(self._home)
            self._home.deleteLater()
            self._home = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API Qt
        self.lock("app_closed")
        super().closeEvent(event)
