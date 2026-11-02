"""Fluxos críticos da interface: configuração, chave de recuperação, bloqueio e desbloqueio."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from appfin.application.session import SessionState
from appfin.bootstrap import AppConfig, build_app
from appfin.infrastructure.paths import AppPaths
from appfin.presentation.main_window import MainWindow
from tests.support import FAST_MINIMUM, FAST_PARAMS

STRONG = "girassol trator piano nuvem"
TIMEOUT = 5000


def _window(qtbot: QtBot, root: Path, auto_lock_minutes: float = 3) -> MainWindow:
    config = AppConfig(
        paths=AppPaths(root),
        kdf_params=FAST_PARAMS,
        kdf_minimum=FAST_MINIMUM,
        auto_lock_minutes=auto_lock_minutes,
    )
    container = build_app(config)
    window = MainWindow(container.session, config.auto_lock_minutes, container.workspace_factory)
    qtbot.addWidget(window)
    window.show()
    return window


def _complete_setup(qtbot: QtBot, window: MainWindow) -> str:
    window.setup_view.password.setText(STRONG)
    window.setup_view.confirmation.setText(STRONG)
    qtbot.mouseClick(window.setup_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window.centralWidget().currentWidget() is window.recovery_view, timeout=TIMEOUT
    )
    shown_key = window.recovery_view.key_label.text()
    window.recovery_view.saved.setChecked(True)
    window.recovery_view.last_group.setText(shown_key.split()[-1].lower())
    qtbot.mouseClick(window.recovery_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: _on_data_page(window), timeout=TIMEOUT)
    return shown_key


def _on_data_page(window: MainWindow) -> bool:
    return (
        window.data_page is not None and window.centralWidget().currentWidget() is window.data_page
    )


def _current(window: MainWindow) -> object:
    return window.centralWidget().currentWidget()


def test_first_use_lock_and_unlock(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    assert _current(window) is window.setup_view

    shown_key = _complete_setup(qtbot, window)

    assert len(shown_key.split()) == 13
    assert window.recovery_view.key_label.text() == "", "a chave some da tela após confirmar"

    window.lock()
    assert _current(window) is window.unlock_view

    window.unlock_view.secret.setText("senha errada qualquer")
    qtbot.mouseClick(window.unlock_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: window.unlock_view.message.text() == "Senha incorreta.", timeout=TIMEOUT
    )
    assert not window.unlock_view.submit.isEnabled(), "atraso progressivo após erro"
    assert window.unlock_view.secret.text() == "", "campo de senha é limpo após a tentativa"

    qtbot.waitUntil(window.unlock_view.submit.isEnabled, timeout=TIMEOUT)
    window.unlock_view.secret.setText(STRONG)
    qtbot.mouseClick(window.unlock_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: _on_data_page(window), timeout=TIMEOUT)


def test_unlock_with_recovery_key(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    shown_key = _complete_setup(qtbot, window)
    window.lock()

    qtbot.mouseClick(window.unlock_view.toggle_mode, Qt.MouseButton.LeftButton)
    window.unlock_view.secret.setText(shown_key)
    qtbot.mouseClick(window.unlock_view.submit, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: _on_data_page(window), timeout=TIMEOUT)


def test_recovery_key_confirmation_must_match(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    window.setup_view.password.setText(STRONG)
    window.setup_view.confirmation.setText(STRONG)
    qtbot.mouseClick(window.setup_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: _current(window) is window.recovery_view, timeout=TIMEOUT)

    window.recovery_view.saved.setChecked(True)
    window.recovery_view.last_group.setText("XXXX")
    qtbot.mouseClick(window.recovery_view.submit, Qt.MouseButton.LeftButton)

    assert _current(window) is window.recovery_view
    assert "não confere" in window.recovery_view.message.text()


def test_weak_password_is_refused_in_the_ui(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    window.setup_view.password.setText("123456")
    window.setup_view.confirmation.setText("123456")

    qtbot.mouseClick(window.setup_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.setup_view.message.text() != "", timeout=TIMEOUT)

    assert _current(window) is window.setup_view
    assert not AppPaths(data_dir).vault_file.exists()


def test_inactivity_locks_and_destroys_the_data_page(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir, auto_lock_minutes=0.002)  # ~120 ms
    _complete_setup(qtbot, window)

    qtbot.waitUntil(lambda: _current(window) is window.unlock_view, timeout=TIMEOUT)

    assert window.data_page is None


@pytest.mark.parametrize("attribute", ["setup_view", "recovery_view", "unlock_view"])
def test_all_labels_render_plain_text(qtbot: QtBot, data_dir: Path, attribute: str) -> None:
    window = _window(qtbot, data_dir)
    view = getattr(window, attribute)

    labels = view.findChildren(QLabel)

    assert labels
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)


def test_session_is_locked_when_window_closes(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    _complete_setup(qtbot, window)
    session = window._session

    window.close()

    assert session.state is SessionState.LOCKED


def test_update_confirmation_defaults_to_decline(qtbot: QtBot) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

    from appfin.presentation.features.updates.update_controller import UpdateController

    parent = QWidget()
    qtbot.addWidget(parent)
    controller = UpdateController(None, parent, lambda _reason: None)
    seen: dict[str, str] = {}

    def respond(action: str) -> None:
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        seen["default"] = box.defaultButton().text()
        seen["buttons"] = ",".join(b.text() for b in box.buttons())
        if action == "escape":
            box.reject()
        else:
            next(b for b in box.buttons() if b.text() == action).click()

    QTimer.singleShot(200, lambda: respond("escape"))
    assert controller._ask("teste") is False
    QTimer.singleShot(200, lambda: respond("Agora não"))
    assert controller._ask("teste") is False
    QTimer.singleShot(200, lambda: respond("Atualizar agora"))
    assert controller._ask("teste") is True

    assert seen["default"] == "Agora não"
    assert "&" not in seen["buttons"], "sem atalhos de letra que confirmem por engano"
