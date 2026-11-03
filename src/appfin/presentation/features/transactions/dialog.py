"""Modais de lançamento: novo/editar e registrar recebimento/pagamento em lote."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QWidget,
)

from appfin.application.transactions import TransactionDraft
from appfin.domain.entities import MAX_INSTALLMENTS, Category, Transaction
from appfin.domain.enums import IntervalUnit, TransactionKind, TransactionStatus
from appfin.domain.errors import DomainError, ValidationError
from appfin.domain.installments import plan_installments
from appfin.domain.money import Money
from appfin.presentation.features.contacts.view import ContactDialog
from appfin.presentation.features.transactions.labels import PAYMENT_LABELS, TEXTS
from appfin.presentation.shared.formatting import format_cents, format_date
from appfin.presentation.shared.ui.forms import (
    Field,
    FormDialog,
    SearchCombo,
    combo,
    notes_field,
    plain_label,
    text_field,
)
from appfin.presentation.shared.ui.inputs import DateEdit, MoneyEdit
from appfin.presentation.workspace import Workspace

NO_CONTACT = "(sem contato)"
NO_CATEGORY = "(sem categoria)"
_PREVIEW_LIMIT = 4


def category_options(categories: list[Category], kind: TransactionKind) -> list[tuple[str, str]]:
    """Categorias que aceitam o tipo, como "Grupo / Categoria" (grupos vazios aparecem sozinhos)."""
    active = [c for c in categories if not c.archived]
    groups = {c.id: c for c in active if c.is_group}
    options: list[tuple[str, str]] = []
    for group in sorted(groups.values(), key=lambda g: g.name.lower()):
        children = sorted(
            (c for c in active if c.parent_id == group.id and c.accepts(kind)),
            key=lambda c: c.name.lower(),
        )
        if children:
            options.extend((f"{group.name} / {child.name}", child.id) for child in children)
        elif group.accepts(kind):
            options.append((group.name, group.id))
    return options


class TransactionDialog(FormDialog):
    def __init__(
        self,
        ws: Workspace,
        kind: TransactionKind,
        transaction: Transaction | None,
        parent: QWidget,
        *,
        installment_label: str = "",
    ) -> None:
        texts = TEXTS[kind]
        editing = transaction is not None
        subtitle = (
            f"Parcela {installment_label}. Alterações valem só para esta parcela."
            if installment_label
            else ("" if editing else "Use o parcelamento para tratamentos pagos em várias vezes.")
        )
        super().__init__(
            texts.edit_title if editing else texts.new_title,
            parent,
            subtitle=subtitle,
            save_text="Salvar",
            width=760,
        )
        self._ws = ws
        self._kind = kind
        self._transaction = transaction
        today = ws.today()

        self.description = text_field(200, "Descrição", "Ex.: Tratamento ortodôntico")
        self.amount = MoneyEdit()
        self.amount.setAccessibleName("Valor")
        self.installments = QSpinBox()
        self.installments.setRange(1, MAX_INSTALLMENTS)
        self.installments.setAccessibleName("Número de parcelas")
        self.installments.setSuffix("x")
        self.interval_value = QSpinBox()
        self.interval_value.setRange(1, 366)
        self.interval_value.setAccessibleName("Intervalo entre parcelas")
        # As setas ficam ocultas pelo tema (largura 0); ↑/↓ no teclado continuam funcionando.
        self.interval_unit = combo(
            [("mês(es)", IntervalUnit.MONTH), ("dia(s)", IntervalUnit.DAY)], "Unidade do intervalo"
        )
        interval = QWidget()
        interval_layout = QHBoxLayout(interval)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(plain_label("a cada", "muted", wrap=False))
        interval_layout.addWidget(self.interval_value)
        interval_layout.addWidget(self.interval_unit, 1)
        self.preview = plain_label("", "muted")

        self.due_date = DateEdit(today)
        self.due_date.setAccessibleName("Vencimento")
        self.accrual_date = DateEdit(today)
        self.accrual_date.setAccessibleName("Competência")
        self.paid = QCheckBox(texts.pay_now)
        self.paid_date = DateEdit(today)
        self.paid_date.setAccessibleName("Data do pagamento")
        paid_box = QWidget()
        paid_layout = QHBoxLayout(paid_box)
        paid_layout.setContentsMargins(0, 0, 0, 0)
        paid_layout.addWidget(self.paid)
        paid_layout.addWidget(plain_label("em", "muted", wrap=False))
        paid_layout.addWidget(self.paid_date, 1)

        self.contact = SearchCombo(
            [(NO_CONTACT, None)],
            texts.contact_label,
            field_name="contact_id",
            not_found_message="Contato não encontrado. Escolha da lista ou use “+ Novo”.",
        )
        self.new_contact = QPushButton("+ Novo")
        self.new_contact.setToolTip("Cadastrar um contato sem sair deste lançamento")
        contact_box = QWidget()
        contact_layout = QHBoxLayout(contact_box)
        contact_layout.setContentsMargins(0, 0, 0, 0)
        contact_layout.addWidget(self.contact, 1)
        contact_layout.addWidget(self.new_contact)
        self.category = SearchCombo(
            [(NO_CATEGORY, None)],
            "Categoria",
            field_name="category_id",
            not_found_message="Categoria não encontrada. Escolha da lista.",
        )
        self.account = combo([], "Conta")
        self.payment_method = combo(
            [("(não informada)", None), *((label, m) for m, label in PAYMENT_LABELS.items())],
            "Forma de pagamento",
        )
        self.document_number = text_field(40, "Número do documento", "Nota, boleto, recibo…")
        self.notes = notes_field(1000, "Observações")
        self.notes.setPlaceholderText("Informações administrativas (nunca clínicas).")

        self.add_section("LANÇAMENTO")
        self.add_row(Field("Descrição", self.description, "description", required=True))
        if editing:
            self.add_row(Field("Valor (R$)", self.amount, "amount", required=True, stretch=1))
        else:
            self.add_row(
                Field("Valor total (R$)", self.amount, "amount", required=True, stretch=2),
                Field("Parcelas", self.installments, "count", stretch=1),
                Field("Intervalo", interval, "interval_value", stretch=3),
            )
            self.add_widget(self.preview)
        self.add_section("DATAS")
        self.add_row(
            Field("Vencimento" if editing else "1º vencimento", self.due_date, "due_date"),
            Field("Competência", self.accrual_date, "accrual_date"),
            Field(texts.paid_word, paid_box, "paid_date"),
        )
        self.add_widget(
            plain_label(
                "Competência: data do atendimento/compra (usada no DRE por competência). "
                "No parcelamento, todas as parcelas ficam com a mesma competência.",
                "muted",
            )
        )
        self.add_section("CLASSIFICAÇÃO")
        self.add_row(
            Field(texts.contact_label, contact_box, "contact_id", stretch=1),
            Field("Categoria", self.category, "category_id", stretch=1),
        )
        self.add_row(
            Field("Conta", self.account, "account_id", required=True, stretch=1),
            Field("Forma de pagamento", self.payment_method, "payment_method", stretch=1),
            Field("Nº do documento", self.document_number, "document_number", stretch=1),
        )
        self.add_section("OBSERVAÇÕES")
        self.add_row(Field("Observações", self.notes, "notes"))

        # Campos compostos: o destaque de erro vai para o controle de entrada, não o contêiner.
        self._fields["contact_id"] = self.contact
        self._fields["paid_date"] = self.paid_date
        if not editing:
            self._fields["interval_value"] = self.interval_value
        self._load_choices()
        for signal in (
            self.amount.cents_changed,
            self.installments.valueChanged,
            self.interval_value.valueChanged,
            self.interval_unit.currentIndexChanged,
            self.due_date.dateChanged,
        ):
            signal.connect(self._update_preview)
        self.paid.toggled.connect(self.paid_date.setEnabled)
        self.new_contact.clicked.connect(self._create_contact)
        if transaction is not None:
            self._load(transaction)
        self.paid_date.setEnabled(self.paid.isChecked())
        self._update_preview()
        self.on_save(self._save)

    # ------------------------------------------------------------------ opções
    def _load_choices(self, select_contact: str | None = None) -> None:
        self.contact.set_options(
            [(NO_CONTACT, None)]
            + [(c.name, c.id) for c in self._ws.catalog.search_contacts(limit=1000)],
        )
        categories = category_options(self._ws.catalog.list_categories(), self._kind)
        self.category.set_options([(NO_CATEGORY, None), *categories])
        keep = {self._transaction.account_id} if self._transaction else set()
        accounts = [
            a
            for a in self._ws.catalog.list_accounts(include_archived=True)
            if not a.archived or a.id in keep
        ]
        self.account.set_options([(a.name, a.id) for a in accounts])
        if select_contact:
            self.contact.select(select_contact)

    def _create_contact(self) -> None:
        dialog = ContactDialog(self._ws, None, self)
        if dialog.exec() and dialog.result_value is not None:
            self._load_choices(select_contact=dialog.result_value.id)

    # ------------------------------------------------------------------ prévia
    def _update_preview(self) -> None:
        if self._transaction is not None:
            return
        count = self.installments.value()
        enabled = count > 1
        self.interval_value.setEnabled(enabled)
        self.interval_unit.setEnabled(enabled)
        if self.amount.cents() <= 0:
            self.preview.setText("Informe o valor para ver as parcelas.")
            return
        try:
            plan = plan_installments(
                Money(self.amount.cents()),
                count,
                self.due_date.value(),
                self.interval_unit.value(),
                self.interval_value.value(),
            )
        except DomainError as error:
            self.preview.setText(str(error))
            return
        if count == 1:
            self.preview.setText(
                f"Pagamento único com vencimento em {format_date(plan[0].due_date)}."
            )
            return
        first, last = plan[0], plan[-1]
        dates = ", ".join(format_date(p.due_date) for p in plan[:_PREVIEW_LIMIT])
        more = f" … até {format_date(last.due_date)}" if count > _PREVIEW_LIMIT else ""
        if first.amount == last.amount:
            values = f"{count}x de {format_cents(first.amount.cents)}"
        else:
            values = (
                f"1x de {format_cents(first.amount.cents)} + "
                f"{count - 1}x de {format_cents(last.amount.cents)}"
            )
        self.preview.setText(f"{values}. Vencimentos: {dates}{more}.")

    # ------------------------------------------------------------------ carregar / salvar
    def _load(self, t: Transaction) -> None:
        self.description.setText(t.description)
        self.amount.set_cents(t.amount.cents)
        self.due_date.set_date(t.due_date)
        self.accrual_date.set_date(t.accrual_date)
        self.paid.setChecked(t.status is TransactionStatus.PAID)
        if t.paid_date:
            self.paid_date.set_date(t.paid_date)
        self.contact.select(t.contact_id)
        self.category.select(t.category_id)
        self.account.select(t.account_id)
        self.payment_method.select(t.payment_method)
        self.document_number.setText(t.document_number)
        self.notes.setPlainText(t.notes)

    def _save(self) -> object:
        if self.amount.cents() <= 0:
            raise ValidationError("amount", "Informe um valor maior que zero.")
        contact_id = self.contact.checked_value()
        category_id = self.category.checked_value()
        account_id = self.account.value()
        if account_id is None:
            raise ValidationError("account_id", "Cadastre uma conta antes de lançar.")
        if self._transaction is None:
            draft = TransactionDraft(
                kind=self._kind,
                description=self.description.text(),
                total=Money(self.amount.cents()),
                first_due=self.due_date.value(),
                accrual_date=self.accrual_date.value(),
                account_id=account_id,
                category_id=category_id,
                contact_id=contact_id,
                payment_method=self.payment_method.value(),
                document_number=self.document_number.text(),
                notes=self.notes.toPlainText(),
                installments=self.installments.value(),
                interval_unit=self.interval_unit.value(),
                interval_value=self.interval_value.value(),
                pay_now=self.paid.isChecked(),
                paid_date=self.paid_date.value(),
            )
            return self._ws.transactions.create(draft)
        paid = self.paid.isChecked()
        updated = replace(
            self._transaction,
            description=self.description.text(),
            amount=Money(self.amount.cents()),
            due_date=self.due_date.value(),
            accrual_date=self.accrual_date.value(),
            status=TransactionStatus.PAID if paid else TransactionStatus.PENDING,
            paid_date=self.paid_date.value() if paid else None,
            contact_id=contact_id,
            category_id=category_id,
            account_id=account_id,
            payment_method=self.payment_method.value(),
            document_number=self.document_number.text(),
            notes=self.notes.toPlainText(),
        )
        return self._ws.transactions.update(updated)


class SettleDialog(FormDialog):
    """Registrar recebimento/pagamento de vários lançamentos de uma vez."""

    KEEP_ACCOUNT = "__keep__"

    def __init__(
        self, ws: Workspace, kind: TransactionKind, count: int, total_cents: int, parent: QWidget
    ) -> None:
        texts = TEXTS[kind]
        plural = "lançamento" if count == 1 else "lançamentos"
        super().__init__(
            texts.settle_title,
            parent,
            subtitle=f"{count} {plural} selecionado(s) — total {format_cents(total_cents)}.",
            save_text=texts.settle_button.replace(" selecionados", ""),
            width=520,
        )
        self.paid_date = DateEdit(ws.today())
        self.paid_date.setAccessibleName("Data")
        self.account = combo(
            [("Manter a conta de cada lançamento", self.KEEP_ACCOUNT)]
            + [(a.name, a.id) for a in ws.catalog.list_accounts()],
            "Conta",
        )
        self.add_row(
            Field(f"Data ({texts.paid_word.lower()} em)", self.paid_date, "paid_date", stretch=1),
            Field("Conta", self.account, "account_id", stretch=2),
        )
        self.on_save(self._values)

    def _values(self) -> tuple[date, str | None]:
        account = self.account.value()
        return self.paid_date.value(), None if account == self.KEEP_ACCOUNT else account
