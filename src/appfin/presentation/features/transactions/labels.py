"""Textos das telas de lançamentos (receber e pagar) num só lugar."""

from __future__ import annotations

from dataclasses import dataclass

from appfin.application.read_models import TransactionRow
from appfin.domain.enums import PaymentMethod, TransactionKind, TransactionStatus

PAYMENT_LABELS = {
    PaymentMethod.PIX: "Pix",
    PaymentMethod.CASH: "Dinheiro",
    PaymentMethod.CREDIT: "Cartão de crédito",
    PaymentMethod.DEBIT: "Cartão de débito",
    PaymentMethod.BOLETO: "Boleto",
    PaymentMethod.TRANSFER: "Transferência",
    PaymentMethod.CHECK: "Cheque",
    PaymentMethod.OTHER: "Outra",
}

OVERDUE_COLOR = "#B42318"
PENDING_COLOR = "#B54708"
PAID_COLOR = "#027A48"


@dataclass(frozen=True, slots=True)
class KindTexts:
    kind: TransactionKind
    title: str
    subtitle: str
    new_button: str
    new_title: str
    edit_title: str
    contact_label: str
    settle_button: str
    settle_title: str
    paid_word: str  # "Recebido" / "Pago"
    pay_now: str
    empty: str


TEXTS = {
    TransactionKind.INCOME: KindTexts(
        kind=TransactionKind.INCOME,
        title="Contas a receber",
        subtitle="Tratamentos, convênios e outras entradas do consultório.",
        new_button="+ Nova conta a receber",
        new_title="Nova conta a receber",
        edit_title="Editar conta a receber",
        contact_label="Paciente / pagador",
        settle_button="Receber selecionados",
        settle_title="Registrar recebimento",
        paid_word="Recebido",
        pay_now="Já recebido",
        empty="Nenhuma conta a receber neste mês.",
    ),
    TransactionKind.EXPENSE: KindTexts(
        kind=TransactionKind.EXPENSE,
        title="Contas a pagar",
        subtitle="Fornecedores, laboratório, aluguel, impostos e outras saídas.",
        new_button="+ Nova conta a pagar",
        new_title="Nova conta a pagar",
        edit_title="Editar conta a pagar",
        contact_label="Fornecedor / favorecido",
        settle_button="Pagar selecionados",
        settle_title="Registrar pagamento",
        paid_word="Pago",
        pay_now="Já pago",
        empty="Nenhuma conta a pagar neste mês.",
    ),
}


def status_text(row: TransactionRow, texts: KindTexts) -> str:
    if row.status is TransactionStatus.PAID:
        return texts.paid_word
    if row.status is TransactionStatus.CANCELLED:
        return "Cancelado"
    return "Vencida" if row.is_overdue else "Pendente"


def status_color(row: TransactionRow) -> str | None:
    if row.status is TransactionStatus.PAID:
        return PAID_COLOR
    if row.is_overdue:
        return OVERDUE_COLOR
    return PENDING_COLOR if row.status is TransactionStatus.PENDING else None


def installment_text(row: TransactionRow) -> str:
    if row.installment_number and row.installment_count:
        return f"{row.installment_number}/{row.installment_count}"
    return ""
