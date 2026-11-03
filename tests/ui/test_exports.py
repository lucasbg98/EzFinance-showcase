"""Recibo e exportação a partir das telas (diálogos substituídos; dados fictícios)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pytestqt.qtbot import QtBot

from appfin.domain.enums import TransactionKind
from appfin.presentation.features.reports.view import ReportsPage
from appfin.presentation.features.transactions.dialog import TransactionDialog
from appfin.presentation.features.transactions.view import TransactionsPage
from appfin.presentation.shared.ui import export_flow
from appfin.presentation.workspace import Workspace


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Responde aos diálogos: confirma o aviso e salva em ``tmp_path/exports``."""
    folder = tmp_path / "exports"
    folder.mkdir()
    state: dict[str, object] = {"confirm": True, "name": "saida.xlsx", "warnings": [], "opened": []}

    def confirmation(_parent: object, text: str) -> bool:
        state["warnings"].append(text)  # type: ignore[attr-defined]
        return bool(state["confirm"])

    monkeypatch.setattr(export_flow, "ask_confirmation", confirmation)
    monkeypatch.setattr(export_flow, "ask_path", lambda *_a: str(folder / str(state["name"])))
    monkeypatch.setattr(export_flow, "open_file", lambda p: state["opened"].append(p))  # type: ignore[attr-defined]
    state["dir"] = folder
    return state


def _page_with_paid_income(qtbot: QtBot, ws: Workspace) -> TransactionsPage:
    page = TransactionsPage(ws, TransactionKind.INCOME)
    qtbot.addWidget(page)
    dialog = TransactionDialog(ws, TransactionKind.INCOME, None, page)
    dialog.description.setText("=CMD|' /C calc'!A0")  # texto malicioso fictício
    dialog.amount.set_cents(25_050)
    dialog.due_date.set_date(date(2026, 3, 10))
    dialog.paid.setChecked(True)
    dialog._on_save()
    assert dialog.error.text() == "", dialog.error.text()
    page.vm.reload()
    return page


def test_receipt_is_saved_and_opened(qtbot: QtBot, ws: Workspace, saved: dict[str, object]) -> None:
    page = _page_with_paid_income(qtbot, ws)
    page.table.selectRow(0)
    saved["name"] = "recibo"

    page.issue_receipt()

    pdf = Path(str(saved["dir"])) / "recibo.pdf"
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert saved["opened"] == [pdf]
    assert "SEM a proteção do app" in saved["warnings"][0]  # type: ignore[index]


def test_declining_the_warning_saves_nothing(
    qtbot: QtBot, ws: Workspace, saved: dict[str, object]
) -> None:
    page = _page_with_paid_income(qtbot, ws)
    saved["confirm"] = False

    page.export()

    assert list(Path(str(saved["dir"])).iterdir()) == []


def test_month_export_neutralizes_formulas_and_uses_real_values(
    qtbot: QtBot, ws: Workspace, saved: dict[str, object]
) -> None:
    page = _page_with_paid_income(qtbot, ws)
    ws.visibility.set_hidden(True)  # exportar não depende de "Ocultar valores"

    page.export()

    sheet = load_workbook(io.BytesIO((Path(str(saved["dir"])) / "saida.xlsx").read_bytes())).active
    assert sheet is not None
    assert sheet["B2"].value == "=CMD|' /C calc'!A0" and sheet["B2"].data_type == "s"
    assert float(sheet["H2"].value) == 250.5
    assert sheet["B3"].value == "TOTAL"

    saved["name"] = "saida.csv"
    page.export()
    text = (Path(str(saved["dir"])) / "saida.csv").read_text(encoding="utf-8-sig")
    assert ";'=CMD|' /C calc'!A0;" in text and ";250,50;" in text


def test_reports_tabs_export(qtbot: QtBot, ws: Workspace, saved: dict[str, object]) -> None:
    _page_with_paid_income(qtbot, ws)
    reports = ReportsPage(ws)
    qtbot.addWidget(reports)
    folder = Path(str(saved["dir"]))

    for index, name in enumerate(("dre.xlsx", "cat.xlsx", "venc.xlsx")):
        saved["name"] = name
        reports.tabs.widget(index).export()  # type: ignore[attr-defined]
        assert (folder / name).stat().st_size > 0

    sheet = load_workbook(folder / "dre.xlsx").active
    assert sheet is not None
    assert sheet["A1"].value == "Linha" and sheet["A2"].value
