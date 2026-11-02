"""Conjuntos fechados do domínio (glossário: skill ``clean-code``)."""

from __future__ import annotations

from enum import StrEnum


class LegalType(StrEnum):
    PF = "pf"
    PJ = "pj"


class TaxRegime(StrEnum):
    SIMPLES = "simples"
    PRESUMIDO = "presumido"
    CARNE_LEAO = "carne_leao"
    OTHER = "other"


class AccountKind(StrEnum):
    CASH = "cash"
    CHECKING = "checking"
    SAVINGS = "savings"
    CARD_ACQUIRER = "card_acquirer"
    OTHER = "other"


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    BOTH = "both"


class DreGroup(StrEnum):
    """Grupos do DRE do consultório (skill ``dominio-consultorio``)."""

    GROSS_REVENUE = "gross_revenue"
    DEDUCTIONS = "deductions"
    TAXES = "taxes"
    DIRECT_COSTS = "direct_costs"
    OPERATING_EXPENSES = "operating_expenses"
    SELLING_EXPENSES = "selling_expenses"
    OTHER_RESULTS = "other_results"


class PersonType(StrEnum):
    PF = "pf"
    PJ = "pj"


class ContactRole(StrEnum):
    PATIENT = "patient"
    SUPPLIER = "supplier"
    INSURER = "insurer"
    OTHER = "other"


class TransactionKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"

    @property
    def is_transfer(self) -> bool:
        return self in (TransactionKind.TRANSFER_OUT, TransactionKind.TRANSFER_IN)

    @property
    def is_inflow(self) -> bool:
        return self in (TransactionKind.INCOME, TransactionKind.TRANSFER_IN)


class TransactionStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class PaymentMethod(StrEnum):
    CASH = "cash"
    PIX = "pix"
    DEBIT = "debit"
    CREDIT = "credit"
    BOLETO = "boleto"
    TRANSFER = "transfer"
    CHECK = "check"
    OTHER = "other"


class IntervalUnit(StrEnum):
    DAY = "day"
    MONTH = "month"


class ReportBasis(StrEnum):
    """Regime do DRE/relatórios: caixa (pagos, por pagamento) ou competência."""

    CASH = "cash"
    ACCRUAL = "accrual"
