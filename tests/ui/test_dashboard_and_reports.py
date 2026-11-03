"""Início (dashboard), DRE, relatório por categoria e vencidas (dados fictícios)."""

from __future__ import annotations

from datetime import date

from pytestqt.qtbot import QtBot

from appfin.application.read_models import CategoryTotal
from appfin.application.transactions import TransactionDraft
from appfin.domain.enums import ReportBasis, TransactionKind
from appfin.domain.money import Money
from appfin.presentation.features.dashboard.view import DashboardPage
from appfin.presentation.features.reports.view import (
    CategoryTab,
    IncomeStatementTab,
    OverdueTab,
    ReportsPage,
    build_category_lines,
    percent_text,
)
from appfin.presentation.shared.formatting import HIDDEN_AMOUNT
from appfin.presentation.shared.ui.charts import BarChart, Series, _short_money, nice_ceiling
from appfin.presentation.shared.ui.period import PeriodMode
from appfin.presentation.workspace import Workspace


def _category(ws: Workspace, name: str) -> str:
    return next(c.id for c in ws.catalog.list_categories() if c.name == name)


def _seed(ws: Workspace) -> None:
    """Março/2026 (hoje = 15/03): tratamento vendido em 3x, só a 1ª recebida; laboratório pago;
    uma conta a pagar vencida."""
    account = ws.catalog.list_accounts()[0].id
    created = ws.transactions.create(
        TransactionDraft(
            TransactionKind.INCOME,
            "Tratamento",
            Money(90_000),
            date(2026, 3, 5),
            account,
            accrual_date=date(2026, 3, 1),
            category_id=_category(ws, "Tratamentos particulares"),
            installments=3,
        )
    )
    ws.transactions.mark_paid([created[0].id], date(2026, 3, 6))
    ws.transactions.create(
        TransactionDraft(
            TransactionKind.EXPENSE,
            "Laboratório",
            Money(20_000),
            date(2026, 3, 10),
            account,
            category_id=_category(ws, "Laboratório de prótese"),
            pay_now=True,
            paid_date=date(2026, 3, 10),
        )
    )
    ws.transactions.create(
        TransactionDraft(
            TransactionKind.EXPENSE,
            "Energia",
            Money(15_000),
            date(2026, 3, 12),
            account,
            category_id=_category(ws, "Energia"),
        )
    )


# ---------------------------------------------------------------------- unidades puras
def test_percent_and_axis_helpers() -> None:
    assert percent_text(1234, 10_000) == "12,3%"
    assert percent_text(-500, 10_000) == "-5,0%"
    assert percent_text(1, 3_000) == "0,0%"
    assert percent_text(-1, 3_000) == "0,0%", "zero não leva sinal"
    assert percent_text(2, 3) == "66,7%"
    assert percent_text(5, 0) == ""
    assert nice_ceiling(3_740_000) == 5_000_000
    assert nice_ceiling(1_900_000) == 2_000_000
    assert nice_ceiling(0) == 100
    assert _short_money(4_000_000) == "R$ 40 mil"
    assert _short_money(120_000_000) == "R$ 1,2 mi"
    assert _short_money(250_000) == "R$ 2,5 mil"
    assert _short_money(50_000) == "R$ 500"


def test_category_lines_totals_and_shares() -> None:
    totals = [
        CategoryTotal("Receitas", "Tratamentos", TransactionKind.INCOME, 75_000, 3),
        CategoryTotal("Receitas", "Convênios", TransactionKind.INCOME, 25_000, 1),
        CategoryTotal(None, None, TransactionKind.EXPENSE, 40_000, 2),
    ]
    names = {TransactionKind.INCOME: "Receitas", TransactionKind.EXPENSE: "Despesas"}

    lines = build_category_lines(totals, names)

    by_label = {line.label: line for line in lines}
    assert by_label["Receitas / Tratamentos"].share_tenths == 750
    assert by_label["(sem categoria)"].share_tenths == 1000
    assert by_label["Total de receitas"].cents == 100_000
    assert by_label["Resultado (receitas - despesas)"].cents == 60_000


def test_bar_chart_rejects_mismatched_series(qtbot: QtBot, ws: Workspace) -> None:
    chart = BarChart(ws.visibility)
    qtbot.addWidget(chart)
    chart.set_data(["Jan", "Fev"], [Series("A", "#000", [1, 2])])
    assert chart.maximum == 2

    try:
        chart.set_data(["Jan"], [Series("A", "#000", [1, 2])])
    except ValueError:
        pass
    else:
        raise AssertionError("deveria recusar séries de tamanho diferente")


# ---------------------------------------------------------------------- telas
def test_dashboard_cards_balances_overdue_and_hidden(qtbot: QtBot, ws: Workspace) -> None:
    _seed(ws)
    page = DashboardPage(ws)
    qtbot.addWidget(page)
    opened: list[str] = []
    page.set_navigator(opened.append)

    assert page.card_received.value.text() == "R$ 300,00"
    assert page.card_paid.value.text() == "R$ 200,00"
    assert page.card_balance.value.text() == "R$ 100,00"
    assert page.card_to_pay.value.text() == "R$ 150,00"
    total_row = page.balances.rows()[-1]
    assert total_row.name == "Total" and total_row.balance_cents == 10_000
    assert [r.description for r in page.overdue_pay.rows()] == ["Energia"]
    assert page.overdue_receive.rows() == []
    assert page.chart._series[0].values[2] == 30_000  # março

    page.go_payables.click()
    assert opened == ["payables"]

    ws.visibility.set_hidden(True)
    assert page.card_received.value.text() == HIDDEN_AMOUNT
    assert HIDDEN_AMOUNT in page.pay_total.text()


def test_income_statement_tab_switches_basis_and_period(qtbot: QtBot, ws: Workspace) -> None:
    _seed(ws)
    tab = IncomeStatementTab(ws)
    qtbot.addWidget(tab)

    def amounts() -> dict[str, int]:
        return {line.label: line.amount.cents for line in tab.model.rows()}

    assert amounts()["(+) Receita bruta"] == 30_000  # caixa: só a parcela recebida
    assert "caixa" in tab.help.text().lower()
    tab.basis.select(ReportBasis.ACCRUAL)
    assert amounts()["(+) Receita bruta"] == 90_000  # competência: a venda inteira em março
    assert amounts()["(=) Resultado do período"] == 90_000 - 20_000 - 15_000
    assert tab.model.data(tab.model.index(0, 2)) == "100,0%"

    tab.period.shift(1)  # abril
    assert amounts()["(+) Receita bruta"] == 0
    tab.period.set_mode(PeriodMode.YEAR)
    assert tab.period.range() == (date(2026, 1, 1), date(2026, 12, 31))
    assert amounts()["(+) Receita bruta"] == 90_000


def test_category_and_overdue_tabs(qtbot: QtBot, ws: Workspace) -> None:
    _seed(ws)
    categories = CategoryTab(ws)
    overdue = OverdueTab(ws)
    qtbot.addWidget(categories)
    qtbot.addWidget(overdue)

    labels = {r.label: r.cents for r in categories.model.rows()}
    assert labels["Receitas de atendimento / Tratamentos particulares"] == 30_000
    assert labels["Resultado (receitas - despesas)"] == 30_000 - 20_000

    assert [r.description for r in overdue.rows] == ["Energia"]
    assert overdue.model.data(overdue.model.index(0, 2)) == "3"  # 12/03 → 15/03
    overdue.kind.select(TransactionKind.INCOME)
    assert overdue.rows == []


def test_reports_page_has_three_tabs(qtbot: QtBot, ws: Workspace) -> None:
    page = ReportsPage(ws)
    qtbot.addWidget(page)

    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "DRE",
        "Por categoria",
        "Vencidas",
    ]
    page.reload()


def test_axis_ticks_are_round_numbers() -> None:
    for maximum, ticks in ((5_000_000, 5), (2_000_000, 4), (250_000, 5), (1_000_000, 4)):
        assert BarChart.tick_count(maximum) == ticks
        assert maximum % (ticks * 100) == 0, "cada divisão cai em reais inteiros"
