"""Cadastro de contas (caixa, banco, maquininha…) com saldo atual."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from appfin.application.read_models import AccountBalance
from appfin.domain.entities import NEW_ID, Account
from appfin.domain.enums import AccountKind
from appfin.domain.money import Money
from appfin.presentation.shared.formatting import format_money
from appfin.presentation.shared.ui.feedback import show_error
from appfin.presentation.shared.ui.forms import (
    FormDialog,
    combo,
    plain_label,
    select_data,
    text_field,
)
from appfin.presentation.shared.ui.inputs import DateEdit, MoneyEdit
from appfin.presentation.shared.ui.table import Column, RowsTableModel, make_table, selected_rows
from appfin.presentation.workspace import Workspace

KIND_LABELS = {
    AccountKind.CASH: "Caixa (dinheiro)",
    AccountKind.CHECKING: "Conta corrente",
    AccountKind.SAVINGS: "Poupança / aplicação",
    AccountKind.CARD_ACQUIRER: "Maquininha / adquirente",
    AccountKind.OTHER: "Outra",
}


class AccountDialog(FormDialog):
    def __init__(self, ws: Workspace, account: Account | None, parent: QWidget) -> None:
        super().__init__("Editar conta" if account else "Nova conta", parent)
        self._ws = ws
        self._account = account
        self.name = text_field(60, "Nome da conta", "Ex.: Banco do consultório")
        self.kind = combo([(label, kind) for kind, label in KIND_LABELS.items()], "Tipo de conta")
        self.opening = MoneyEdit(allow_negative=True)
        self.opening.setAccessibleName("Saldo inicial")
        self.opening_date = DateEdit(ws.today())
        self.opening_date.setAccessibleName("Data do saldo inicial")
        self.form.addRow("Nome:*", self.name)
        self.form.addRow("Tipo:", self.kind)
        self.form.addRow("Saldo inicial (R$):", self.opening)
        self.form.addRow("Data do saldo inicial:", self.opening_date)
        self.form.addRow(
            "",
            plain_label(
                "O saldo inicial é o valor que havia na conta antes de começar a usar o app. "
                "Use '-' para saldo negativo.",
                "muted",
            ),
        )
        if account:
            self.name.setText(account.name)
            select_data(self.kind, account.kind)
            self.opening.set_cents(account.opening_balance.cents)
            if account.opening_date:
                self.opening_date.set_date(account.opening_date)
        self.on_save(self._save)

    def _save(self) -> Account:
        base = self._account or Account(NEW_ID, self.name.text() or "?")
        account = replace(
            base,
            name=self.name.text(),
            kind=self.kind.value(),
            opening_balance=Money(self.opening.cents()),
            opening_date=self.opening_date.value(),
        )
        return self._ws.catalog.save_account(account)


class AccountsPage(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        columns = [
            Column("Nome", lambda r: r.name, stretch=True),
            Column("Tipo", lambda r: KIND_LABELS[self._accounts[r.account_id].kind]),
            Column(
                "Saldo atual",
                lambda r: format_money(r.balance_cents, ws.visibility),
                align_right=True,
                color=lambda r: "#B42318" if r.balance_cents < 0 else None,
            ),
            Column("Situação", lambda r: "Arquivada" if r.archived else "Ativa"),
        ]
        self._accounts: dict[str, Account] = {}
        self.model = RowsTableModel(columns, self)
        self.table = make_table(self.model, columns)
        self.new_button = QPushButton("+ Nova conta")
        self.new_button.setObjectName("primary")
        self.edit_button = QPushButton("Editar")
        self.archive_button = QPushButton("Arquivar / reativar")
        bar = QHBoxLayout()
        for button in (self.new_button, self.edit_button, self.archive_button):
            bar.addWidget(button)
        bar.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Contas", "title"))
        layout.addWidget(
            plain_label(
                "Onde o dinheiro do consultório fica: caixa, bancos e maquininhas. "
                "Contas com lançamentos não são excluídas: arquive.",
                "muted",
            )
        )
        layout.addLayout(bar)
        layout.addWidget(self.table)
        self.new_button.clicked.connect(lambda: self._open(None))
        self.edit_button.clicked.connect(self._edit_selected)
        self.table.doubleClicked.connect(self._edit_selected)
        self.archive_button.clicked.connect(self._toggle_archive)
        ws.visibility.changed.connect(lambda _: self.model.refresh())
        self.reload()

    def reload(self) -> None:
        self._accounts = {a.id: a for a in self._ws.catalog.list_accounts(include_archived=True)}
        balances: list[AccountBalance] = self._ws.reports.account_balances()
        self.model.set_rows(balances)

    def _selected(self) -> Account | None:
        rows = selected_rows(self.table)
        if not rows:
            return None
        return self._accounts.get(self.model.row_at(rows[0]).account_id)

    def _open(self, account: Account | None) -> None:
        if AccountDialog(self._ws, account, self).exec():
            self.reload()

    def _edit_selected(self) -> None:
        account = self._selected()
        if account:
            self._open(account)

    def _toggle_archive(self) -> None:
        account = self._selected()
        if account is None:
            return
        try:
            self._ws.catalog.set_account_archived(account.id, not account.archived)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "account.archive")
        self.reload()
