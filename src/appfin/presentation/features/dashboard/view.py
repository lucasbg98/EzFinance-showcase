"""Início (dashboard): resumo do mês, saldos das contas, gráfico do ano e contas vencidas."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from appfin.application.read_models import AccountBalance, TransactionFilter, TransactionRow
from appfin.domain.enums import TransactionKind, TransactionStatus
from appfin.presentation.shared.formatting import format_date, format_money
from appfin.presentation.shared.ui.cards import StatCard
from appfin.presentation.shared.ui.charts import BarChart, Series
from appfin.presentation.shared.ui.forms import plain_label
from appfin.presentation.shared.ui.inputs import MonthNavigator
from appfin.presentation.shared.ui.table import Column, RowsTableModel, TablePanel, make_table
from appfin.presentation.workspace import Workspace

INCOME_COLOR = "#0F766E"
EXPENSE_COLOR = "#E07A5F"
SHORT_MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
OVERDUE_START = date(2000, 1, 1)
OVERDUE_LIMIT = 8


def _right(button: QPushButton) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch(1)
    row.addWidget(button)
    return holder


def _panel(title: str, *widgets: QWidget) -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 12)
    layout.setSpacing(8)
    layout.addWidget(plain_label(title, "panelTitle"))
    for widget in widgets:
        layout.addWidget(widget)
    return frame


class DashboardPage(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self._open_section: Callable[[str], None] | None = None
        visibility = ws.visibility

        self.month = MonthNavigator(ws.today())
        self.card_received = StatCard("Recebido no mês", visibility, tone="success")
        self.card_paid = StatCard("Pago no mês", visibility, tone="danger")
        self.card_balance = StatCard("Saldo do mês", visibility)
        self.card_to_receive = StatCard("A receber (pendente)", visibility, tone="warning")
        self.card_to_pay = StatCard("A pagar (pendente)", visibility, tone="warning")
        cards = QHBoxLayout()
        cards.setSpacing(12)
        for card in (
            self.card_received,
            self.card_paid,
            self.card_balance,
            self.card_to_receive,
            self.card_to_pay,
        ):
            cards.addWidget(card)

        self.chart = BarChart(visibility)
        self.chart.setMinimumHeight(300)

        balance_columns = [
            Column("Conta", lambda b: b.name, stretch=True),
            Column(
                "Saldo",
                lambda b: format_money(b.balance_cents, visibility),
                align_right=True,
                color=lambda b: "#B42318" if b.balance_cents < 0 else None,
                bold=lambda b: b.account_id == "",
            ),
        ]
        self.balances = RowsTableModel(balance_columns, self)
        balances_view = make_table(self.balances, balance_columns)

        overdue_columns = [
            Column("Vencimento", lambda r: format_date(r.due_date)),
            Column("Descrição", lambda r: r.description, stretch=True),
            Column("Valor", lambda r: format_money(r.amount_cents, visibility), align_right=True),
        ]
        self.overdue_receive = RowsTableModel(overdue_columns, self)
        self.overdue_pay = RowsTableModel(overdue_columns, self)
        self.receive_panel = TablePanel(
            make_table(self.overdue_receive, overdue_columns),
            self.overdue_receive,
            "Nenhuma conta a receber vencida.",
        )
        self.pay_panel = TablePanel(
            make_table(self.overdue_pay, overdue_columns),
            self.overdue_pay,
            "Nenhuma conta a pagar vencida.",
        )
        self.receive_total = plain_label("", "muted")
        self.pay_total = plain_label("", "muted")
        self.go_receivables = QPushButton("Ver contas a receber →")
        self.go_payables = QPushButton("Ver contas a pagar →")

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(_panel("Recebido e pago no ano", self.chart), 0, 0, 1, 2)
        grid.addWidget(_panel("Saldo das contas (até hoje)", balances_view), 0, 2)
        grid.addWidget(
            _panel(
                "Vencidas a receber",
                self.receive_panel,
                self.receive_total,
                _right(self.go_receivables),
            ),
            1,
            0,
            1,
            2,
        )
        grid.addWidget(
            _panel("Vencidas a pagar", self.pay_panel, self.pay_total, _right(self.go_payables)),
            1,
            2,
        )
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        header = QHBoxLayout()
        header.addWidget(plain_label("Início", "title"))
        header.addStretch(1)
        header.addWidget(self.month)

        content = QWidget()
        content.setObjectName("pageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.addLayout(header)
        layout.addWidget(plain_label("Visão geral do consultório no mês escolhido.", "muted"))
        layout.addLayout(cards)
        layout.addLayout(grid, 1)
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.month.changed.connect(lambda _y, _m: self.reload())
        visibility.changed.connect(lambda _hidden: self._refresh_texts())
        self.go_receivables.clicked.connect(lambda: self._go("receivables"))
        self.go_payables.clicked.connect(lambda: self._go("payables"))
        self.reload()

    def reload(self) -> None:
        data = self._ws.reports.dashboard(self.month.year, self.month.month)
        summary = data.summary
        self.card_received.set_cents(summary.received_cents)
        self.card_paid.set_cents(summary.paid_cents)
        self.card_balance.set_cents(summary.balance_cents, signed_tone=True)
        self.card_to_receive.set_cents(summary.pending_receive_cents)
        self.card_to_pay.set_cents(summary.pending_pay_cents)
        self.chart.set_data(
            SHORT_MONTHS,
            [
                Series("Recebido", INCOME_COLOR, [m.received_cents for m in data.monthly_flow]),
                Series("Pago", EXPENSE_COLOR, [m.paid_cents for m in data.monthly_flow]),
            ],
            title=str(self.month.year),
        )
        balances = [b for b in self._ws.reports.account_balances() if not b.archived]
        total = AccountBalance("", "Total", sum(b.balance_cents for b in balances), False)
        self.balances.set_rows([*balances, total])
        self._overdue_receive = self._overdue(TransactionKind.INCOME)
        self._overdue_pay = self._overdue(TransactionKind.EXPENSE)
        self.overdue_receive.set_rows(self._overdue_receive[:OVERDUE_LIMIT])
        self.overdue_pay.set_rows(self._overdue_pay[:OVERDUE_LIMIT])
        self._refresh_texts()

    def _overdue(self, kind: TransactionKind) -> list[TransactionRow]:
        today = self._ws.today()
        criteria = TransactionFilter(
            start=OVERDUE_START,
            end=today,
            kinds=frozenset({kind}),
            statuses=frozenset({TransactionStatus.PENDING}),
            overdue_only=True,
            limit=1000,
        )
        return self._ws.reports.transactions(criteria)

    def _refresh_texts(self) -> None:
        for model in (self.balances, self.overdue_receive, self.overdue_pay):
            model.refresh()
        for rows, label in (
            (self._overdue_receive, self.receive_total),
            (self._overdue_pay, self.pay_total),
        ):
            total = sum(r.amount_cents for r in rows)
            more = f" (mostrando {OVERDUE_LIMIT})" if len(rows) > OVERDUE_LIMIT else ""
            label.setText(
                f"{len(rows)} vencida(s) — total {format_money(total, self._ws.visibility)}{more}"
                if rows
                else ""
            )

    def set_navigator(self, open_section: Callable[[str], None]) -> None:
        """Permite que os botões "Ver contas…" abram outra seção do menu."""
        self._open_section = open_section

    def _go(self, section: str) -> None:
        if self._open_section is not None:
            self._open_section(section)
