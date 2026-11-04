"""Assistente de importação e histórico (pytest-qt, banco real, planilha sintética)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel
from pytestqt.qtbot import QtBot

from appfin.application.spreadsheet_import import (
    ImportRequest,
    LineChoice,
    LineSource,
    NewCategory,
)
from appfin.domain.enums import CategoryKind, DreGroup
from appfin.domain.spreadsheet_import.monthly_matrix import MonthStatus
from appfin.domain.spreadsheet_import.reconcile import ReconcileAction
from appfin.presentation.features.spreadsheet_import import history as history_module
from appfin.presentation.features.spreadsheet_import import view as import_view
from appfin.presentation.features.spreadsheet_import.line_dialog import NEW, LineDialog
from appfin.presentation.features.spreadsheet_import.view import (
    SpreadsheetImportPage,
    Step,
)
from appfin.presentation.features.spreadsheet_import.view_model import LoadedFile
from appfin.presentation.shared.formatting import HIDDEN_AMOUNT
from appfin.presentation.shell import AppShell
from appfin.presentation.workspace import Workspace
from tests.spreadsheet_fixtures import (
    UNKNOWN_LABEL,
    cash_flow_fixture,
    with_unknown_line,
    write_xlsx,
)


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
def messages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captura mensagens e aceita as confirmações, sem abrir caixas de diálogo."""
    shown: list[str] = []
    for module in (import_view, history_module):
        monkeypatch.setattr(module, "show_error", lambda _p, e, _ev: shown.append(f"ERRO: {e}"))
        monkeypatch.setattr(module, "confirm", lambda _p, text, **_k: shown.append(text) or True)
    monkeypatch.setattr(history_module, "show_info", lambda _p, text: shown.append(text))
    return shown


@pytest.fixture
def page(qtbot: QtBot, ws: Workspace, messages: list[str]) -> SpreadsheetImportPage:
    widget = SpreadsheetImportPage(ws, runner=sync_runner)
    qtbot.addWidget(widget)
    return widget


def _choose(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(import_view, "ask_spreadsheet_file", lambda _parent: str(path))


def _import_fixture(
    page: SpreadsheetImportPage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _choose(monkeypatch, write_xlsx(tmp_path / "fluxo.xlsx", cash_flow_fixture()))
    wizard = page.wizard
    wizard.choose_file()
    while wizard.current_step() is not Step.PREVIEW:
        wizard.go_next()
    wizard.go_next()  # confirmar


# ---------------------------------------------------------------------- caminho feliz
def test_first_import_end_to_end(
    page: SpreadsheetImportPage,
    ws: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    messages: list[str],
) -> None:
    fixture = cash_flow_fixture()
    _choose(monkeypatch, write_xlsx(tmp_path / "fluxo.xlsx", fixture))
    wizard = page.wizard

    wizard.choose_file()

    assert wizard.current_step() is Step.PERIOD
    assert wizard.year.value() == 2026  # sugerido pela aba "JAN26"
    assert wizard.month_boxes[0].value() is MonthStatus.REALIZED
    assert wizard.month_boxes[11].value() is MonthStatus.PROJECTION
    assert not wizard.sheet.isVisible()  # uma aba só

    wizard.go_next()
    assert wizard.current_step() is Step.CATEGORIES  # 1ª vez: sugestões e categorias novas
    first = wizard.lines_model.row_at(0)
    assert first.source in (LineSource.BLOCK, LineSource.RULE)

    wizard.go_next()
    assert wizard.current_step() is Step.PREVIEW
    cells = sum(1 for d in fixture.details for c in d.cents if c)
    assert wizard.items_model.rowCount() == cells
    assert wizard.next_button.isEnabled()
    assert "Tudo certo" in wizard.verdict.text()

    wizard.go_next()

    assert wizard.current_step() is Step.DONE
    assert f"{cells} lançamento(s) novo(s)" in wizard.done_text.text()
    assert any("backup automático" in text for text in messages)  # pergunta antes de gravar
    assert page.history.model.rowCount() == 1
    assert len(ws.imports.history()) == 1


def test_reimport_skips_the_categories_step_and_has_nothing_to_write(
    page: SpreadsheetImportPage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _import_fixture(page, monkeypatch, tmp_path)
    wizard = page.wizard
    wizard.restart()

    wizard.choose_file()
    wizard.go_next()

    assert wizard.current_step() is Step.PREVIEW  # perfil salvo: nada a decidir
    assert wizard.items_model.rowCount() == 0  # "só o que muda"
    assert not wizard.next_button.isEnabled()
    assert "já está importada" in wizard.verdict.text()


def test_replacement_can_be_unchecked_with_double_click(
    page: SpreadsheetImportPage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _import_fixture(page, monkeypatch, tmp_path)
    fixture = cash_flow_fixture()
    fixture.detail("fixed", "INTERNET").cents[8] += 1_000
    _choose(monkeypatch, write_xlsx(tmp_path / "fluxo2.xlsx", fixture))
    wizard = page.wizard
    wizard.restart()
    wizard.choose_file()
    wizard.go_next()
    assert wizard.items_model.rowCount() == 1

    wizard.items_table.selectRow(0)
    wizard.toggle_selected_item()

    item = wizard.items_model.row_at(0)
    assert item.action is ReconcileAction.REPLACE and not item.selected
    assert "desmarcado" in wizard.items_model.index(0, 3).data()
    assert wizard.model.preview is not None and wizard.model.preview.counts.kept == 1


# ---------------------------------------------------------------------- linha desconhecida
def test_unknown_line_blocks_until_chosen_in_the_line_dialog(
    page: SpreadsheetImportPage, monkeypatch: pytest.MonkeyPatch
) -> None:
    wizard = page.wizard
    wizard._on_loaded(LoadedFile(with_unknown_line(cash_flow_fixture()), "fluxo.xlsx"))
    wizard.go_next()
    assert wizard.current_step() is Step.CATEGORIES
    unknown = wizard.lines_model.row_at(0)  # sem categoria vem primeiro
    assert unknown.label == UNKNOWN_LABEL and unknown.source is LineSource.MISSING
    assert "1 linha(s) sem categoria" in wizard.lines_summary.text()

    wizard.go_next()
    assert not wizard.next_button.isEnabled()  # prévia bloqueada
    wizard.go_back()
    assert wizard.current_step() is Step.CATEGORIES

    class ChosenDialog:
        def __init__(self, *_args: object) -> None:
            new = NewCategory(
                "Despesas fictícias", CategoryKind.EXPENSE, DreGroup.OPERATING_EXPENSES
            )
            self.result_value = (LineChoice(new_category=new), None)

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(import_view, "LineDialog", ChosenDialog)
    wizard.lines_table.selectRow(0)
    wizard.edit_selected_line()

    assert "Todas as linhas têm categoria" in wizard.lines_summary.text()
    wizard.go_next()
    assert wizard.next_button.isEnabled()


def test_line_dialog_creates_a_new_category(qtbot: QtBot, ws: Workspace) -> None:
    file = with_unknown_line(cash_flow_fixture(), label="<b>ITEM FICTÍCIO</b>")
    preview = ws.imports.preview(file, ImportRequest(2026, ws.catalog.list_accounts()[0].id))
    line = next(line for line in preview.lines if line.source is LineSource.MISSING)
    dialog = LineDialog(line, ws.catalog.list_categories())
    qtbot.addWidget(dialog)

    labels = [label for label in dialog.findChildren(QLabel) if "ITEM" in label.text()]
    assert labels and all(lb.textFormat() is Qt.TextFormat.PlainText for lb in labels)
    dialog.category.select(NEW)
    assert not dialog.new_row.isHidden()
    dialog.new_name.setText("Despesas fictícias")
    dialog.new_group.select(DreGroup.OPERATING_EXPENSES)
    dialog.description.setText("Item fictício")
    dialog._on_save()

    choice, description = dialog.result_value
    assert choice.new_category == NewCategory(
        "Despesas fictícias", CategoryKind.EXPENSE, DreGroup.OPERATING_EXPENSES
    )
    assert description == "Item fictício"


# ---------------------------------------------------------------------- erros e dados sensíveis
def test_refused_file_stays_on_the_first_step(
    page: SpreadsheetImportPage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = tmp_path / "antiga.xls"
    old.write_bytes(b"conteudo")
    _choose(monkeypatch, old)

    page.wizard.choose_file()

    assert page.wizard.current_step() is Step.FILE
    assert ".xls" in page.wizard.file_status.text()
    assert "antiga" not in page.wizard.file_status.text()


def test_hide_values_applies_to_the_preview(
    page: SpreadsheetImportPage, ws: Workspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _choose(monkeypatch, write_xlsx(tmp_path / "fluxo.xlsx", cash_flow_fixture()))
    wizard = page.wizard
    wizard.choose_file()
    wizard.go_next()
    wizard.go_next()

    ws.visibility.set_hidden(True)

    assert wizard.items_model.index(0, 4).data() == HIDDEN_AMOUNT
    assert wizard.checks_model.index(0, 3).data() == HIDDEN_AMOUNT
    ws.visibility.set_hidden(False)


def test_excluding_a_month_in_the_period_step(
    page: SpreadsheetImportPage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _choose(monkeypatch, write_xlsx(tmp_path / "fluxo.xlsx", cash_flow_fixture()))
    wizard = page.wizard
    wizard.choose_file()
    wizard.month_boxes[11].select(MonthStatus.EMPTY)

    wizard.go_next()
    wizard.go_next()

    assert wizard.model.preview is not None
    assert not [item for item in wizard.model.preview.items if item.month == 12]


# ---------------------------------------------------------------------- histórico
def test_undo_from_the_history(
    page: SpreadsheetImportPage,
    ws: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    messages: list[str],
) -> None:
    _import_fixture(page, monkeypatch, tmp_path)
    history = page.history
    history.select_row(0)
    assert history.undo_button.isEnabled()

    history.undo_selected()

    assert ws.imports.history()[0].is_undone
    assert "Desfeita" in history.model.index(0, 8).data()
    assert not history.undo_button.isEnabled()
    assert "Importação desfeita." in messages


def test_undo_blocked_lists_the_changed_transactions(
    page: SpreadsheetImportPage,
    ws: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    messages: list[str],
) -> None:
    _import_fixture(page, monkeypatch, tmp_path)
    preview = page.wizard.model.refresh()  # mesma planilha: tudo "já importado", com o id atual
    rent = next(
        item
        for item in preview.items
        if item.description == "ALUGUEL" and item.month == 9 and item.current_transaction_id
    )
    ws.transactions.mark_paid([str(rent.current_transaction_id)], date(2026, 9, 30))
    history = page.history
    history.refresh()
    history.select_row(0)

    history.undo_selected()

    assert not ws.imports.history()[0].is_undone
    blocked = messages[-1]
    assert "não pode ser desfeita" in blocked and "ALUGUEL" in blocked


def test_import_page_is_in_the_side_menu(qtbot: QtBot, ws: Workspace) -> None:
    shell = AppShell(ws, initial="import")
    qtbot.addWidget(shell)

    assert isinstance(shell.page("import"), SpreadsheetImportPage)
    assert shell.menu.currentItem().text() == "Importar planilha"


# ---------------------------------------------------------------------- bloqueio
def test_lock_during_the_wizard_discards_everything(qtbot: QtBot, tmp_path: Path) -> None:
    from appfin.bootstrap import AppConfig, build_app
    from appfin.domain.entities import Company
    from appfin.domain.enums import TaxRegime
    from appfin.infrastructure.paths import AppPaths
    from appfin.presentation.main_window import MainWindow
    from tests.support import FAST_MINIMUM, FAST_PARAMS

    password = "girassol trator piano nuvem"
    config = AppConfig(
        paths=AppPaths(tmp_path / "dados"), kdf_params=FAST_PARAMS, kdf_minimum=FAST_MINIMUM
    )
    container = build_app(config)
    window = MainWindow(container.session, 3, container.workspace_factory)
    qtbot.addWidget(window)
    container.session.create(password)
    ws = container.workspace_factory(window.visibility, window)
    ws.catalog.save_company(Company(name="Clínica Fictícia"))
    ws.catalog.initialize_defaults(TaxRegime.SIMPLES)
    window._show_home()
    shell = window.data_page
    assert isinstance(shell, AppShell)
    shell.open("import")
    page = shell.page("import")
    assert isinstance(page, SpreadsheetImportPage)
    page.wizard._on_loaded(LoadedFile(with_unknown_line(cash_flow_fixture()), "fluxo.xlsx"))
    assert page.wizard.model.preview is not None

    window.lock("manual")

    assert window.data_page is None
    container.session.unlock(password)
    assert container.workspace_factory(window.visibility, window).imports.history() == []
    container.session.lock()
