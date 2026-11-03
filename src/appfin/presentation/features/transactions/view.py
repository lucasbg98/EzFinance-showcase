"""Telas "Contas a receber" e "Contas a pagar" (mesma página, parametrizada pelo tipo)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from appfin.application.export_table import Cell, ColumnKind, ExportColumn, ExportTable
from appfin.application.read_models import TransactionRow
from appfin.domain.enums import TransactionKind, TransactionStatus
from appfin.infrastructure.exporters.receipt_pdf import receipt_number, render_receipt
from appfin.presentation.features.transactions.dialog import SettleDialog, TransactionDialog
from appfin.presentation.features.transactions.labels import (
    PAYMENT_LABELS,
    TEXTS,
    KindTexts,
    installment_text,
    status_color,
    status_text,
)
from appfin.presentation.features.transactions.view_model import (
    StatusFilter,
    TransactionsViewModel,
)
from appfin.presentation.shared.formatting import format_date, format_money
from appfin.presentation.shared.ui.cards import StatCard
from appfin.presentation.shared.ui.export_flow import export_table, save_pdf
from appfin.presentation.shared.ui.feedback import confirm, show_error, show_info
from appfin.presentation.shared.ui.forms import combo, plain_label, search_field
from appfin.presentation.shared.ui.inputs import MonthNavigator
from appfin.presentation.shared.ui.table import (
    Column,
    RowsTableModel,
    TablePanel,
    make_table,
    selected_rows,
)
from appfin.presentation.workspace import Workspace

ALL_ACCOUNTS = "__all__"


class TransactionsPage(QWidget):
    def __init__(self, ws: Workspace, kind: TransactionKind) -> None:
        super().__init__()
        self._ws = ws
        self.texts = TEXTS[kind]
        self.vm = TransactionsViewModel(ws, kind)
        texts = self.texts

        columns = [
            Column("Vencimento", lambda r: format_date(r.due_date)),
            Column("Descrição", lambda r: r.description, stretch=True),
            Column(texts.contact_label, lambda r: r.contact_name or ""),
            Column("Categoria", lambda r: r.category_name or ""),
            Column("Conta", lambda r: r.account_name),
            Column("Parcela", installment_text),
            Column(
                "Forma",
                lambda r: PAYMENT_LABELS.get(r.payment_method, "") if r.payment_method else "",
            ),
            Column(
                "Valor", lambda r: format_money(r.amount_cents, ws.visibility), align_right=True
            ),
            Column("Situação", lambda r: status_text(r, texts), color=status_color),
        ]
        self.model = RowsTableModel(columns, self)
        self.table = make_table(self.model, columns, multi=True)
        self.panel = TablePanel(self.table, self.model, texts.empty)

        # ---------------------------------------------------------------- ações
        self.new_button = QPushButton(texts.new_button)
        self.new_button.setObjectName("primary")
        self.edit_button = QPushButton("Editar")
        self.delete_button = QPushButton("Excluir")
        self.settle_button = QPushButton(texts.settle_button)
        self.reopen_button = QPushButton("Desfazer baixa")
        self.reopen_button.setToolTip("Volta os selecionados para pendente")
        self.receipt_button = QPushButton("Emitir recibo")
        self.receipt_button.setToolTip("Recibo em PDF do lançamento selecionado (já pago)")
        self.export_button = QPushButton("Exportar")
        self.export_button.setToolTip("Salvar a lista do mês em Excel ou CSV")
        self.search = search_field("Buscar descrição, documento ou contato", "Buscar")
        self.search.setMinimumWidth(360)
        actions = QHBoxLayout()
        for button in (
            self.new_button,
            self.edit_button,
            self.delete_button,
            self.settle_button,
            self.reopen_button,
            self.receipt_button,
            self.export_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.search)

        # ---------------------------------------------------------------- filtros
        self.month = MonthNavigator(ws.today())
        self.account = combo([("Todas as contas", ALL_ACCOUNTS)], "Filtrar por conta")
        self.status = combo(
            [
                ("Todas as situações", StatusFilter.ALL),
                ("Pendentes", StatusFilter.PENDING),
                ("Vencidas", StatusFilter.OVERDUE),
                (texts.paid_word + "s", StatusFilter.PAID),
            ],
            "Filtrar por situação",
        )
        filters = QHBoxLayout()
        filters.addWidget(self.month)
        filters.addStretch(1)
        filters.addWidget(plain_label("Conta:", "muted", wrap=False))
        filters.addWidget(self.account)
        filters.addWidget(plain_label("Situação:", "muted", wrap=False))
        filters.addWidget(self.status)

        # ---------------------------------------------------------------- resumo
        self.card_total = StatCard("Total do mês", ws.visibility)
        self.card_paid = StatCard(texts.paid_word, ws.visibility, tone="success")
        self.card_pending = StatCard("Pendente", ws.visibility, tone="warning")
        self.card_overdue = StatCard("Vencido", ws.visibility, tone="danger")
        cards = QHBoxLayout()
        cards.setSpacing(12)
        for card in (self.card_total, self.card_paid, self.card_pending, self.card_overdue):
            cards.addWidget(card)
        self.selection_info = plain_label("", "muted")

        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(texts.title, "title"))
        layout.addWidget(plain_label(texts.subtitle, "muted"))
        layout.addLayout(actions)
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        layout.addLayout(filters)
        layout.addLayout(cards)
        layout.addWidget(self.panel, 1)
        layout.addWidget(self.selection_info)

        # ---------------------------------------------------------------- sinais
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self.new_button.clicked.connect(self.new_transaction)
        self.edit_button.clicked.connect(self.edit_selected)
        self.table.doubleClicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.settle_button.clicked.connect(self.settle_selected)
        self.reopen_button.clicked.connect(self.reopen_selected)
        self.receipt_button.clicked.connect(self.issue_receipt)
        self.export_button.clicked.connect(self.export)
        self.month.changed.connect(self.vm.set_month)
        self.account.currentIndexChanged.connect(self._on_account)
        self.status.currentIndexChanged.connect(lambda _i: self.vm.set_status(self.status.value()))
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        self._debounce.timeout.connect(lambda: self.vm.set_search(self.search.text()))
        self.vm.changed.connect(self._render)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_selection())
        ws.visibility.changed.connect(self._on_visibility)
        for sequence, handler in (
            (QKeySequence.StandardKey.New, self.new_transaction),
            (QKeySequence.StandardKey.Delete, self.delete_selected),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
        enter = QShortcut(QKeySequence(Qt.Key.Key_Return), self.table)
        enter.setContext(Qt.ShortcutContext.WidgetShortcut)
        enter.activated.connect(self.edit_selected)

        self.reload()

    # ------------------------------------------------------------------ carga
    def reload(self) -> None:
        self.account.set_options(
            [("Todas as contas", ALL_ACCOUNTS)]
            + [(a.name, a.id) for a in self._ws.catalog.list_accounts(include_archived=True)]
        )
        self.vm.reload()

    def _on_account(self, _index: int) -> None:
        value = self.account.value()
        self.vm.set_account(None if value in (None, ALL_ACCOUNTS) else value)

    def _render(self) -> None:
        self.model.set_rows(self.vm.rows)
        summary = self.vm.summary
        self.card_total.set_cents(summary.total_cents)
        self.card_paid.set_cents(summary.paid_cents)
        self.card_pending.set_cents(summary.pending_cents)
        self.card_overdue.set_cents(summary.overdue_cents)
        filtered = self.vm.search or self.vm.status_filter is not StatusFilter.ALL
        self.panel.set_empty_text(
            "Nenhum lançamento encontrado com esses filtros." if filtered else self.texts.empty
        )
        self._update_selection()

    def _on_visibility(self, _hidden: bool) -> None:
        self.model.refresh()
        self._update_selection()

    def _selected(self) -> list[TransactionRow]:
        return [self.model.row_at(row) for row in selected_rows(self.table)]

    def _update_selection(self) -> None:
        rows = self._selected()
        if not rows:
            self.selection_info.setText(f"{len(self.vm.rows)} lançamento(s) no mês.")
            return
        total = sum(r.amount_cents for r in rows)
        self.selection_info.setText(
            f"{len(rows)} selecionado(s) — total {format_money(total, self._ws.visibility)}"
        )

    # ------------------------------------------------------------------ ações
    def new_transaction(self) -> None:
        dialog = TransactionDialog(self._ws, self.vm.kind, None, self)
        if dialog.exec():
            self.vm.reload()

    def edit_selected(self) -> None:
        rows = self._selected()
        if len(rows) != 1:
            if len(rows) > 1:
                show_info(self, "Selecione um único lançamento para editar.")
            return
        row = rows[0]
        try:
            transaction = self._ws.transactions.get(row.id)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "transaction.open")
            return
        dialog = TransactionDialog(
            self._ws, self.vm.kind, transaction, self, installment_label=installment_text(row)
        )
        if dialog.exec():
            self.vm.reload()

    def delete_selected(self) -> None:
        rows = self._selected()
        if not rows:
            return
        if not confirm(
            self,
            f"Excluir {len(rows)} lançamento(s)? Esta ação pode ser desfeita só por backup.",
            accept="Excluir",
        ):
            return
        self._run(lambda: self.vm.delete([r.id for r in rows]), "transaction.delete")

    def settle_selected(self) -> None:
        rows = [r for r in self._selected() if r.status is TransactionStatus.PENDING]
        if not rows:
            show_info(self, "Selecione lançamentos pendentes.")
            return
        total = sum(r.amount_cents for r in rows)
        dialog = SettleDialog(self._ws, self.vm.kind, len(rows), total, self)
        if dialog.exec():
            paid_date, account_id = dialog.result_value
            self._run(
                lambda: self.vm.settle([r.id for r in rows], paid_date, account_id),
                "transaction.settle",
            )

    def reopen_selected(self) -> None:
        rows = [r for r in self._selected() if r.status is TransactionStatus.PAID]
        if not rows:
            show_info(self, f"Selecione lançamentos com situação “{self.texts.paid_word}”.")
            return
        if confirm(self, f"Voltar {len(rows)} lançamento(s) para pendente?", accept="Desfazer"):
            self._run(lambda: self.vm.reopen([r.id for r in rows]), "transaction.reopen")

    def issue_receipt(self) -> None:
        rows = self._selected()
        if len(rows) != 1:
            show_info(self, "Selecione um único lançamento para emitir o recibo.")
            return
        try:
            data = self._ws.receipts.issue(rows[0].id)
            pdf = render_receipt(data)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "receipt.issue")
            return
        save_pdf(self, pdf, f"Recibo-{receipt_number(data.receipt.number)}.pdf", open_after=True)

    def export(self) -> None:
        name = f"{self.texts.title} {self.vm.year}-{self.vm.month:02d}"
        export_table(self, transactions_table(self.vm.rows, self.texts), name)

    def _run(self, action: Callable[[], object], event: str) -> None:
        try:
            action()
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, event)
            self.vm.reload()


def transactions_table(rows: list[TransactionRow], texts: KindTexts) -> ExportTable:
    """Lista do mês para Excel/CSV, com os valores reais (independe de "Ocultar valores")."""
    columns = [
        ExportColumn("Vencimento", ColumnKind.DATE),
        ExportColumn("Descrição"),
        ExportColumn(texts.contact_label),
        ExportColumn("Categoria"),
        ExportColumn("Conta"),
        ExportColumn("Parcela"),
        ExportColumn("Forma de pagamento"),
        ExportColumn("Valor", ColumnKind.MONEY),
        ExportColumn("Situação"),
        ExportColumn("Data do pagamento", ColumnKind.DATE),
        ExportColumn("Competência", ColumnKind.DATE),
        ExportColumn("Documento"),
    ]
    data: list[list[Cell]] = [
        [
            r.due_date,
            r.description,
            r.contact_name or "",
            r.category_name or "",
            r.account_name,
            installment_text(r),
            PAYMENT_LABELS.get(r.payment_method, "") if r.payment_method else "",
            r.amount_cents,
            status_text(r, texts),
            r.paid_date,
            r.accrual_date,
            r.document_number,
        ]
        for r in rows
    ]
    total: list[Cell] = [
        "",
        "TOTAL",
        "",
        "",
        "",
        "",
        "",
        sum(r.amount_cents for r in rows),
        "",
        None,
        None,
        "",
    ]
    return ExportTable(texts.title, columns, [*data, total] if rows else data)


def receivables_page(ws: Workspace) -> TransactionsPage:
    return TransactionsPage(ws, TransactionKind.INCOME)


def payables_page(ws: Workspace) -> TransactionsPage:
    return TransactionsPage(ws, TransactionKind.EXPENSE)
