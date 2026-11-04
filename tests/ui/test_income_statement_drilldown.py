"""DRE detalhável: grupos expandem em categorias; categoria abre os lançamentos.

Dados fictícios.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from appfin.application.read_models import (
    StatementCategoryTotal,
    StatementTransactionsFilter,
)
from appfin.application.transactions import TransactionDraft
from appfin.domain.enums import DreGroup, ReportBasis, TransactionKind
from appfin.domain.income_statement import UNCLASSIFIED, GroupTotals, build_income_statement
from appfin.domain.money import Money
from appfin.presentation.features.reports import statement_details, view
from appfin.presentation.features.reports.statement_details import StatementTransactionsDialog
from appfin.presentation.features.reports.statement_rows import (
    NO_CATEGORY,
    RowStyle,
    build_statement_rows,
)
from appfin.presentation.features.reports.view import IncomeStatementTab, statement_label
from appfin.presentation.shared.formatting import HIDDEN_AMOUNT
from appfin.presentation.workspace import Workspace

MARCH = (date(2026, 3, 1), date(2026, 3, 31))


def _category(ws: Workspace, name: str) -> str:
    return next(c.id for c in ws.catalog.list_categories() if c.name == name)


def _seed(ws: Workspace) -> None:
    account = ws.catalog.list_accounts()[0].id
    for category, kind, cents in (
        ("Tratamentos particulares", TransactionKind.INCOME, 50_000),
        ("Contador", TransactionKind.EXPENSE, 20_000),
        ("Tarifas bancárias", TransactionKind.EXPENSE, 1_500),
        ("Cursos e capacitação", TransactionKind.EXPENSE, 10_000),
    ):
        ws.transactions.create(
            TransactionDraft(
                kind,
                f"Fictício {category}",
                Money(cents),
                date(2026, 3, 10),
                account,
                category_id=_category(ws, category),
                pay_now=True,
                paid_date=date(2026, 3, 10),
            )
        )


def _detail(
    group: DreGroup | str, name: str | None, net: int, **extra: Any
) -> StatementCategoryTotal:
    values: dict[str, Any] = {
        "group": group,
        "category_id": f"id-{name}",
        "group_name": "Grupo",
        "category_name": name,
        "inflow_cents": max(net, 0),
        "outflow_cents": max(-net, 0),
        "count": 1,
    }
    values.update(extra)
    return StatementCategoryTotal(**values)


# ---------------------------------------------------------------------- linhas (sem Qt)
def test_rows_show_categories_only_under_expanded_groups() -> None:
    lines = build_income_statement({})
    details = [
        _detail(DreGroup.TAXES, "Contador", -200),
        _detail(DreGroup.TAXES, "Tarifas bancárias", -15),
        _detail(DreGroup.INVESTMENTS, "Cursos", -100),
    ]

    collapsed = build_statement_rows(lines, details, set())
    opened = build_statement_rows(lines, details, {DreGroup.TAXES})

    assert all(row.style is not RowStyle.CATEGORY for row in collapsed)
    taxes = next(row for row in collapsed if row.group is DreGroup.TAXES)
    assert taxes.expandable and not taxes.expanded
    labels = [row.label for row in opened]
    position = labels.index("(-) Impostos")
    assert labels[position + 1 : position + 3] == [
        "Contador",
        "Tarifas bancárias",
    ]  # maior primeiro
    assert "Cursos" not in labels


def test_groups_without_details_do_not_expand() -> None:
    rows = build_statement_rows(build_income_statement({}), [], {DreGroup.TAXES})

    assert not any(row.expandable or row.expanded for row in rows)


def test_repeated_category_names_show_their_group_and_missing_name_is_explicit() -> None:
    details = [
        _detail(UNCLASSIFIED, "Outros", 10, group_name="A"),
        _detail(UNCLASSIFIED, "Outros", 20, group_name="B"),
        _detail(UNCLASSIFIED, None, 5, category_id=None),
    ]
    totals = GroupTotals(
        sum(d.inflow_cents for d in details), sum(d.outflow_cents for d in details)
    )
    lines = build_income_statement({UNCLASSIFIED: totals})

    rows = build_statement_rows(lines, details, {UNCLASSIFIED})

    names = {row.label for row in rows if row.style is RowStyle.CATEGORY}
    assert names == {"Outros (A)", "Outros (B)", NO_CATEGORY}


# ---------------------------------------------------------------------- tela do DRE
def test_tab_expands_groups_and_keeps_values_consistent(qtbot: QtBot, ws: Workspace) -> None:
    _seed(ws)
    tab = IncomeStatementTab(ws)
    qtbot.addWidget(tab)

    taxes_line = next(r for r in tab.model.rows() if r.group is DreGroup.TAXES)
    assert statement_label(taxes_line).startswith("▸ ")
    tab.toggle(DreGroup.TAXES)

    rows = tab.model.rows()
    taxes_line = next(r for r in rows if r.group is DreGroup.TAXES and r.style is RowStyle.GROUP)
    children = [r for r in rows if r.style is RowStyle.CATEGORY]
    assert statement_label(taxes_line).startswith("▾ ")
    assert [c.label for c in children] == ["Contador", "Tarifas bancárias"]
    assert sum(c.amount.cents for c in children) == taxes_line.amount.cents == -21_500

    tab.expand_all()
    expanded = {r.group for r in tab.model.rows() if r.style is RowStyle.CATEGORY}
    assert expanded == {DreGroup.GROSS_REVENUE, DreGroup.TAXES, DreGroup.INVESTMENTS}
    tab.collapse_all()
    assert not any(r.style is RowStyle.CATEGORY for r in tab.model.rows())


def test_expansion_survives_period_and_basis_changes(qtbot: QtBot, ws: Workspace) -> None:
    _seed(ws)
    tab = IncomeStatementTab(ws)
    qtbot.addWidget(tab)
    tab.toggle(DreGroup.TAXES)

    tab.basis.select(ReportBasis.ACCRUAL)
    assert any(r.label == "Contador" for r in tab.model.rows())
    tab.period.shift(1)  # abril: sem lançamentos, nada para expandir
    assert not any(r.style is RowStyle.CATEGORY for r in tab.model.rows())
    tab.period.shift(-1)
    assert any(r.label == "Contador" for r in tab.model.rows())


def test_activating_rows_toggles_groups_and_opens_categories(
    qtbot: QtBot, ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(ws)
    tab = IncomeStatementTab(ws)
    qtbot.addWidget(tab)
    opened: list[tuple[StatementTransactionsFilter, str, int]] = []

    class FakeDialog:
        changed = False

        def __init__(self, _ws: Workspace, criteria: Any, title: str, count: int, _p: Any) -> None:
            opened.append((criteria, title, count))

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(view, "StatementTransactionsDialog", FakeDialog)

    def activate(predicate: Any) -> None:
        position = next(i for i, r in enumerate(tab.model.rows()) if predicate(r))
        tab._on_activated(tab.model.index(position, 0))

    activate(lambda r: r.group is DreGroup.TAXES)
    activate(lambda r: r.label == "Contador")

    criteria, title, count = opened[0]
    assert criteria.category_id == _category(ws, "Contador")
    assert criteria.basis is ReportBasis.CASH
    assert (criteria.start, criteria.end) == MARCH
    assert title.startswith("Contador — ") and "caixa" in title
    assert count == 1


def test_export_includes_expanded_categories(
    qtbot: QtBot, ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(ws)
    tab = IncomeStatementTab(ws)
    qtbot.addWidget(tab)
    tab.toggle(DreGroup.INVESTMENTS)
    exported: list[Any] = []
    monkeypatch.setattr(view, "export_table", lambda _p, table, _name: exported.append(table))

    tab.export()

    labels = [row[0] for row in exported[0].rows]
    position = labels.index("(-) Investimentos")
    assert labels[position + 1].strip() == "Cursos e capacitação"
    assert labels[position + 1].startswith(" ")


# ---------------------------------------------------------------------- lista de lançamentos
def test_dialog_lists_transactions_with_signed_total_and_hides_values(
    qtbot: QtBot, ws: Workspace
) -> None:
    _seed(ws)
    criteria = StatementTransactionsFilter(*MARCH, ReportBasis.CASH, _category(ws, "Contador"))
    dialog = StatementTransactionsDialog(ws, criteria, "Contador", 1, None)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    assert [r.description for r in dialog.rows] == ["Fictício Contador"]
    assert dialog.model.data(dialog.model.index(0, 6)) == "-R$ 200,00"
    assert "1 lançamento(s)" in dialog.summary.text()
    assert "-R$ 200,00" in dialog.summary.text()

    ws.visibility.set_hidden(True)
    assert HIDDEN_AMOUNT in dialog.summary.text()
    assert dialog.model.data(dialog.model.index(0, 6)) == HIDDEN_AMOUNT


def test_dialog_warns_when_list_is_truncated(qtbot: QtBot, ws: Workspace) -> None:
    _seed(ws)
    criteria = StatementTransactionsFilter(
        *MARCH, ReportBasis.CASH, _category(ws, "Contador"), limit=1
    )
    dialog = StatementTransactionsDialog(ws, criteria, "Contador", 5, None)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)

    assert "mostrando os primeiros 1 de 5" in dialog.summary.text()


def test_editing_from_dialog_marks_change_and_reloads(
    qtbot: QtBot, ws: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(ws)
    criteria = StatementTransactionsFilter(*MARCH, ReportBasis.CASH, _category(ws, "Contador"))
    dialog = StatementTransactionsDialog(ws, criteria, "Contador", 1, None)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    monkeypatch.setattr(statement_details.TransactionDialog, "exec", lambda _self: 1)

    dialog._on_activated(dialog.model.index(0, 0))

    assert dialog.changed
    assert len(dialog.rows) == 1
