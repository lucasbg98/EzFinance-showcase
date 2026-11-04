"""Lançamentos que formam o valor de uma categoria no DRE (duplo clique na categoria)."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from appfin.application.read_models import StatementTransactionsFilter, TransactionRow
from appfin.domain.enums import ReportBasis, TransactionKind
from appfin.presentation.features.reports.style import NEGATIVE, POSITIVE
from appfin.presentation.features.transactions.dialog import TransactionDialog
from appfin.presentation.features.transactions.labels import (
    PAYMENT_LABELS,
    TEXTS,
    installment_text,
    status_text,
)
from appfin.presentation.shared.formatting import format_date, format_money
from appfin.presentation.shared.ui.feedback import show_error
from appfin.presentation.shared.ui.forms import plain_label
from appfin.presentation.shared.ui.table import Column, RowsTableModel, TablePanel, make_table
from appfin.presentation.workspace import Workspace


def signed_cents(row: TransactionRow) -> int:
    """Como no DRE: receita soma, despesa subtrai."""
    return row.amount_cents if row.kind is TransactionKind.INCOME else -row.amount_cents


class StatementTransactionsDialog(QDialog):
    def __init__(
        self,
        ws: Workspace,
        criteria: StatementTransactionsFilter,
        title: str,
        expected_count: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._ws = ws
        self._criteria = criteria
        self._expected_count = expected_count
        self.changed = False
        self.rows: list[TransactionRow] = []
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(860, 480)

        date_header = "Pagamento" if criteria.basis is ReportBasis.CASH else "Competência"
        columns = [
            Column(date_header, self._date_text),
            Column("Descrição", lambda r: r.description, stretch=True),
            Column("Contato", lambda r: r.contact_name or ""),
            Column("Conta", lambda r: r.account_name),
            Column("Forma", lambda r: PAYMENT_LABELS[r.payment_method] if r.payment_method else ""),
            Column("Situação", lambda r: status_text(r, TEXTS[r.kind])),
            Column(
                "Valor",
                lambda r: format_money(signed_cents(r), ws.visibility),
                align_right=True,
                color=lambda r: POSITIVE if r.kind is TransactionKind.INCOME else NEGATIVE,
            ),
        ]
        self.model = RowsTableModel(columns, self)
        self.table = make_table(self.model, columns)
        self.panel = TablePanel(self.table, self.model, "Nenhum lançamento neste período.")
        self.summary = plain_label("", "muted")
        close = QPushButton("Fechar")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addWidget(self.summary, 1)
        footer.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(title, "dialogTitle"))
        layout.addWidget(
            plain_label("Dê duplo clique (ou Enter) num lançamento para editar.", "muted")
        )
        layout.addWidget(self.panel, 1)
        layout.addLayout(footer)

        self.table.activated.connect(self._on_activated)
        ws.visibility.changed.connect(lambda _h: self._render_summary())
        self.reload()

    def reload(self) -> None:
        self.rows = self._ws.reports.statement_transactions(self._criteria)
        self.model.set_rows(self.rows)
        self._render_summary()

    def edit_row(self, row: TransactionRow) -> None:
        try:
            transaction = self._ws.transactions.get(row.id)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "statement.open_transaction")
            return
        dialog = TransactionDialog(
            self._ws, row.kind, transaction, self, installment_label=installment_text(row)
        )
        if dialog.exec():
            self.changed = True
            self.reload()

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.edit_row(self.model.row_at(index.row()))

    def _date_text(self, row: TransactionRow) -> str:
        if self._criteria.basis is ReportBasis.CASH and row.paid_date is not None:
            return format_date(row.paid_date)
        return format_date(row.accrual_date)

    def _render_summary(self) -> None:
        self.model.refresh()
        total = sum(signed_cents(r) for r in self.rows)
        text = f"{len(self.rows)} lançamento(s) — total {format_money(total, self._ws.visibility)}"
        if self._expected_count > len(self.rows):
            text += f" · mostrando os primeiros {len(self.rows)} de {self._expected_count}"
        self.summary.setText(text)
