"""Janela principal: alterna entre configuração, chave de recuperação, desbloqueio e o app.

Ao bloquear, a página com dados é **destruída** (não só escondida) para limpar o estado das telas.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget

from appfin import __version__
from appfin.application.session import AppSession, SessionState
from appfin.presentation.auto_lock import InactivityLock, WindowsSessionWatcher
from appfin.presentation.features.lock.view_model import LockViewModel
from appfin.presentation.features.lock.views import RecoveryKeyView, SetupView, UnlockView

APP_TITLE = "AppFinanceiro"


class HomePlaceholder(QWidget):
    """Página inicial provisória da fase 0 (as telas do consultório chegam na fase 1)."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Cofre aberto")
        title.setObjectName("title")
        text = QLabel(
            "A base segura do app está funcionando: dados cifrados, bloqueio automático e "
            "chave de recuperação. As telas do consultório chegam na fase 1."
        )
        for label in (title, text):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, session: AppSession, auto_lock_minutes: float) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self.resize(1100, 720)
        self._session = session
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

    def _show_home(self) -> None:
        self._destroy_home()
        self._home = HomePlaceholder()
        self._stack.addWidget(self._home)
        self._stack.setCurrentWidget(self._home)
        self._toolbar.setVisible(True)
        self._inactivity.start()

    def _destroy_home(self) -> None:
        if self._home is not None:
            self._stack.removeWidget(self._home)
            self._home.deleteLater()
            self._home = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API Qt
        self.lock("app_closed")
        super().closeEvent(event)
