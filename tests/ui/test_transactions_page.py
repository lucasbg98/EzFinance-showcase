"""Contas a receber/pagar: view model, formulário, baixa em lote e filtros (dados fictícios)."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from appfin.domain.entities import Contact
from appfin.domain.enums import CategoryKind, IntervalUnit, TransactionKind
from appfin.domain.enums import TransactionStatus as Status
from appfin.presentation.features.transactions.dialog import TransactionDialog
from appfin.presentation.features.transactions.view import TransactionsPage
from appfin.presentation.features.transactions.view_model import StatusFilter
from appfin.presentation.shared.formatting import HIDDEN_AMOUNT
from appfin.presentation.workspace import Workspace

TODAY = date(2026, 3, 15)


def _page(qtbot: QtBot, ws: Workspace, kind: TransactionKind) -> TransactionsPage:
    page = TransactionsPage(ws, kind)
    qtbot.addWidget(page)
    return page


def _new(page: TransactionsPage, **fields: object) -> TransactionDialog:
    dialog = TransactionDialog(page._ws, page.vm.kind, None, page)
    dialog.description.setText(str(fields.get("description", "Tratamento ortodôntico")))
    dialog.amount.set_cents(int(fields.get("cents", 90_000)))  # type: ignore[call-overload]
    dialog.installments.setValue(int(fields.get("installments", 1)))  # type: ignore[call-overload]
    if "due" in fields:
        dialog.due_date.set_date(fields["due"])  # type: ignore[arg-type]
    if fields.get("paid"):
        dialog.paid.setChecked(True)
    if "contact_text" in fields:
        dialog.contact.setEditText(str(fields["contact_text"]))
    return dialog


def test_installments_spread_over_months_and_summary(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.INCOME)
    dialog = _new(page, cents=100_000, installments=3, due=date(2026, 3, 10))

    assert dialog.preview.text().startswith("1x de R$ 333,34 + 2x de R$ 333,33")
    dialog._on_save()
    assert dialog.error.text() == "", dialog.error.text()
    page.vm.reload()

    assert [r.description for r in page.vm.rows] == ["Tratamento ortodôntico — parcela 1/3"]
    assert page.vm.summary.total_cents == 33_334
    assert page.vm.summary.overdue_cents == 33_334  # venceu 10/03; hoje é 15/03
    page.month.shift(1)
    assert [r.amount_cents for r in page.vm.rows] == [33_333]
    assert page.model.data(page.model.index(0, 5)) == "2/3"


def test_daily_interval_option(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.INCOME)
    dialog = _new(page, installments=2, due=date(2026, 3, 1))
    dialog.interval_unit.select(IntervalUnit.DAY)
    dialog.interval_value.setValue(15)

    assert "01/03/2026, 16/03/2026" in dialog.preview.text()
    dialog._on_save()
    page.vm.reload()
    assert len(page.vm.rows) == 2


def test_unknown_contact_text_is_refused(qtbot: QtBot, ws: Workspace) -> None:
    ws.catalog.save_contact(Contact("", "Ana Paciente Fictícia"))
    page = _page(qtbot, ws, TransactionKind.INCOME)

    dialog = _new(page, contact_text="Fulano que não existe")
    dialog._on_save()
    assert "Contato não encontrado" in dialog.error.text()
    assert dialog.contact.property("invalid") is True

    dialog.contact.setEditText("Ana Paciente Fictícia")
    dialog._on_save()
    assert dialog.error.text() == ""
    page.vm.reload()
    assert page.vm.rows[0].contact_name == "Ana Paciente Fictícia"


def test_expense_page_offers_only_expense_categories(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.EXPENSE)
    dialog = TransactionDialog(ws, TransactionKind.EXPENSE, None, page)
    labels = [dialog.category.itemText(i) for i in range(dialog.category.count())]

    assert "Custos diretos / Laboratório de prótese" in labels
    assert not any("Tratamentos particulares" in label for label in labels)
    kinds = {c.id: c.kind for c in ws.catalog.list_categories()}
    assert all(
        kinds[dialog.category._values[i]] in (CategoryKind.EXPENSE, CategoryKind.BOTH)
        for i in range(1, dialog.category.count())
    )


def test_settle_reopen_and_status_filters(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.EXPENSE)
    _new(page, description="Aluguel", due=date(2026, 3, 5))._on_save()
    _new(page, description="Laboratório", due=date(2026, 3, 25))._on_save()
    page.vm.reload()
    ids = {r.description: r.id for r in page.vm.rows}

    page.vm.set_status(StatusFilter.OVERDUE)
    assert [r.description for r in page.vm.rows] == ["Aluguel"]

    page.vm.set_status(StatusFilter.ALL)
    assert page.vm.settle([ids["Aluguel"]], TODAY, None) == 1
    statuses = {r.description: r.status for r in page.vm.rows}
    assert statuses == {"Aluguel": Status.PAID, "Laboratório": Status.PENDING}
    assert page.vm.summary.paid_cents == 90_000 and page.vm.summary.overdue_cents == 0
    assert page.model.data(page.model.index(0, 8)) == "Pago"

    page.vm.set_status(StatusFilter.PAID)
    assert [r.description for r in page.vm.rows] == ["Aluguel"]

    assert page.vm.reopen([ids["Aluguel"]]) == 1
    assert page.vm.rows == []


def test_edit_single_installment_and_delete(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.INCOME)
    _new(page, cents=60_000, installments=2, due=date(2026, 3, 20))._on_save()
    page.vm.reload()
    row = page.vm.rows[0]
    transaction = ws.transactions.get(row.id)

    edit = TransactionDialog(ws, TransactionKind.INCOME, transaction, page, installment_label="1/2")
    edit.amount.set_cents(25_000)
    edit.paid.setChecked(True)
    edit._on_save()
    assert edit.error.text() == ""
    page.vm.reload()
    assert page.vm.rows[0].amount_cents == 25_000
    assert page.vm.rows[0].status is Status.PAID

    assert page.vm.delete([row.id]) == 1
    assert page.vm.rows == []


def test_search_and_hidden_values(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.INCOME)
    _new(page, description="Clareamento", due=date(2026, 3, 20))._on_save()
    _new(page, description="Limpeza", due=date(2026, 3, 21))._on_save()

    page.vm.set_search("clare")
    assert [r.description for r in page.vm.rows] == ["Clareamento"]

    ws.visibility.set_hidden(True)
    assert page.card_total.value.text() == HIDDEN_AMOUNT
    assert page.model.data(page.model.index(0, 7)) == HIDDEN_AMOUNT


def test_pay_now_marks_first_installment(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.INCOME)
    dialog = _new(page, installments=2, due=date(2026, 3, 20), paid=True)
    dialog._on_save()
    page.vm.reload()

    assert page.vm.rows[0].status is Status.PAID
    assert page.vm.rows[0].paid_date == TODAY


def test_page_widget_is_a_qwidget(qtbot: QtBot, ws: Workspace) -> None:
    page = _page(qtbot, ws, TransactionKind.EXPENSE)
    assert isinstance(page, QWidget)
    assert page.texts.settle_button == "Pagar selecionados"


def test_spin_boxes_keep_a_visible_editor(qtbot: QtBot, ws: Workspace) -> None:
    """Regressão: NoButtons + regra do tema deixava o editor com 1 px (número invisível)."""
    from appfin.presentation.theme.style import build_stylesheet

    page = _page(qtbot, ws, TransactionKind.INCOME)
    page.setStyleSheet(build_stylesheet())
    dialog = TransactionDialog(ws, TransactionKind.INCOME, None, page)
    dialog.show()
    qtbot.waitExposed(dialog)

    for spin in (dialog.installments, dialog.interval_value):
        editor = spin.lineEdit()
        assert editor is not None
        assert editor.width() > 20, f"editor com {editor.width()} px"
