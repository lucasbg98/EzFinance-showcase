"""Tela de backup, restauração pela interface e backup automático (dados fictícios)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from appfin.application.session import SessionState
from appfin.bootstrap import AppConfig, build_app
from appfin.domain.entities import Company, Contact
from appfin.domain.enums import TaxRegime
from appfin.infrastructure.backup.retention import list_backups
from appfin.infrastructure.paths import AppPaths
from appfin.presentation.features.backup import view as backup_view
from appfin.presentation.features.backup.view import (
    BackupPage,
    NewRecoveryKeyDialog,
    OpenWith,
    RestoreDialog,
)
from appfin.presentation.main_window import MainWindow
from appfin.presentation.shared.formatting import ValuesVisibility
from appfin.presentation.workspace import Workspace
from tests.support import FAST_MINIMUM, FAST_PARAMS

PASSWORD = "girassol trator piano nuvem"


def sync_runner(
    work: Callable[[], Any], ok: Callable[[Any], None], fail: Callable[[Exception], None]
) -> None:
    try:
        result = work()
    except Exception as error:  # noqa: BLE001 - repassa como o runner real
        fail(error)
        return
    ok(result)


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captura as mensagens em vez de abrir caixas de diálogo."""
    shown: list[str] = []
    monkeypatch.setattr(backup_view, "show_info", lambda _p, text: shown.append(text))
    monkeypatch.setattr(
        backup_view, "show_error", lambda _p, error, _e: shown.append(f"ERRO: {error}")
    )
    return shown


def _window(qtbot: QtBot, root: Path) -> MainWindow:
    config = AppConfig(paths=AppPaths(root), kdf_params=FAST_PARAMS, kdf_minimum=FAST_MINIMUM)
    container = build_app(config)
    window = MainWindow(container.session, 3, container.workspace_factory)
    qtbot.addWidget(window)
    return window


def _setup_with_data(window: MainWindow) -> Workspace:
    window._session.create(PASSWORD)
    ws = window._workspace_factory(window.visibility, window)
    ws.catalog.save_company(Company(name="Clínica Fictícia"))
    ws.catalog.initialize_defaults(TaxRegime.SIMPLES)
    ws.catalog.save_contact(Contact("", "Paciente Fictício"))
    return ws


# ---------------------------------------------------------------------- página
def test_backup_now_and_extra_folder(
    qtbot: QtBot, ws: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quiet: list[str]
) -> None:
    page = BackupPage(ws)
    qtbot.addWidget(page)
    assert page.status_text.text() == "Nenhum backup feito ainda."
    assert "Pasta extra: nenhuma" in page.folder_text.text()

    pendrive = tmp_path / "pendrive"
    monkeypatch.setattr(backup_view, "ask_folder", lambda _p: str(pendrive))
    page.choose_folder()
    page.backup_now()

    assert quiet == ["Backup feito e conferido (2 cópia(s))."]
    assert page.status_text.text().startswith("Último backup:")
    assert len(list_backups(pendrive)) == 1
    assert not page.alert.isVisibleTo(page)


def test_missing_pendrive_is_flagged(
    qtbot: QtBot, ws: Workspace, tmp_path: Path, quiet: list[str]
) -> None:
    blocked = tmp_path / "nao-e-pasta"
    blocked.write_text("x")
    ws.backups.set_folder(blocked)
    page = BackupPage(ws)
    qtbot.addWidget(page)

    page.backup_now()

    assert "NÃO foi possível gravar na pasta extra" in quiet[0]
    assert page.alert.isVisibleTo(page)


def test_relative_folder_is_refused(ws: Workspace) -> None:
    with pytest.raises(ValueError, match="pasta completa"):
        ws.backups.set_folder(Path("relativa"))


# ---------------------------------------------------------------------- diálogo de restauração
def test_restore_dialog_verifies_before_restoring(
    qtbot: QtBot, ws: Workspace, tmp_path: Path
) -> None:
    file = ws.backups.backup_now().saved_to[0]
    discarded: list[bool] = []

    def prepare(path: Path, password: str | None, recovery_key: str | None) -> Any:
        return ws.backups.prepare_restore(path, password=password, recovery_key=recovery_key)

    dialog = RestoreDialog(
        prepare, lambda: discarded.append(True), None, replaces_data=True, runner=sync_runner
    )
    qtbot.addWidget(dialog)

    dialog._on_save()
    assert dialog.error.text() == "Escolha o arquivo de backup."
    dialog.set_file(str(file))
    dialog.secret.setText("senha errada qualquer")
    dialog._on_save()
    assert "Senha incorreta para este backup" in dialog.error.text()

    dialog.secret.setText("girassol trator piano nuvem")
    dialog._on_save()
    assert dialog.save_button.text() == "Restaurar agora"
    assert "Contém:" in dialog.preview.text() and "lançamento(s)" in dialog.preview.text()
    assert dialog.warning.isVisibleTo(dialog)

    dialog.secret.setText("mudou")  # editar depois de verificar descarta a preparação
    assert discarded == [True] and dialog.save_button.text() == "Verificar backup"

    dialog.mode.select(OpenWith.RECOVERY_KEY)
    assert dialog.secret.echoMode() == dialog.secret.EchoMode.Normal
    dialog.reject()


# ---------------------------------------------------------------------- janela principal
def test_restore_from_first_run_screen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quiet: list[str]
) -> None:
    pc1 = _window(qtbot, tmp_path / "pc1")
    ws = _setup_with_data(pc1)
    file = ws.backups.backup_now().saved_to[0]

    pc2 = _window(qtbot, tmp_path / "pc2")
    assert pc2._session.state is SessionState.NEEDS_SETUP

    def fake_exec(dialog: RestoreDialog) -> int:
        dialog._runner = sync_runner
        dialog.set_file(str(file))
        dialog.secret.setText(PASSWORD)
        dialog._on_save()  # verificar
        dialog._on_save()  # restaurar
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(RestoreDialog, "exec", fake_exec)
    monkeypatch.setattr("appfin.presentation.main_window.show_info", lambda *_a: None)
    pc2.setup_view.restore.click()

    assert pc2._session.state is SessionState.LOCKED
    pc2._session.unlock(PASSWORD)
    ws2 = pc2._workspace_factory(pc2.visibility, pc2)
    assert [c.name for c in ws2.catalog.search_contacts()] == ["Paciente Fictício"]


def test_close_makes_a_backup(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path / "pc1")
    _setup_with_data(window)
    window._show_home()
    qtbot.waitUntil(lambda: len(list_backups(tmp_path / "pc1" / "backups")) == 1)

    window.close()

    assert window._session.state is SessionState.LOCKED
    assert len(list_backups(tmp_path / "pc1" / "backups")) == 2


def test_new_recovery_key_dialog(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path / "pc1")
    ws = _setup_with_data(window)
    dialog = NewRecoveryKeyDialog(ws, None, runner=sync_runner)
    qtbot.addWidget(dialog)
    assert window._auto_lock_paused, "o bloqueio automático pausa enquanto a chave é anotada"

    dialog.password.setText("senha errada")
    dialog._generate()
    assert dialog.message.text() == "Senha incorreta."
    dialog.password.setText(PASSWORD)
    dialog._generate()
    key = dialog.key_view.key_label.text().replace(" ", "-")
    dialog.key_view.saved.setChecked(True)
    dialog.key_view.last_group.setText(key.split("-")[-1])
    dialog.key_view._on_submit()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not window._auto_lock_paused
    window._session.lock()
    window._session.unlock_with_recovery_key(key)
    assert window._session.state is SessionState.UNLOCKED


def test_workspace_without_window_cannot_restore(ws: Workspace) -> None:
    with pytest.raises(RuntimeError):
        ws.app.apply_restore()
    assert isinstance(ws.visibility, ValuesVisibility)
