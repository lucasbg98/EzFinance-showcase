"""Modelos de leitura (consultas para telas e relatórios) e o contrato das consultas."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from appfin.domain.enums import (
    DreGroup,
    PaymentMethod,
    ReportBasis,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.income_statement import GroupTotals

MAX_PAGE = 1000


@dataclass(frozen=True, slots=True)
class TransactionFilter:
    start: date
    end: date
    kinds: frozenset[TransactionKind] = frozenset({TransactionKind.INCOME, TransactionKind.EXPENSE})
    statuses: frozenset[TransactionStatus] = frozenset(
        {TransactionStatus.PENDING, TransactionStatus.PAID}
    )
    account_id: str | None = None
    contact_id: str | None = None
    category_id: str | None = None
    text: str = ""
    overdue_only: bool = False
    limit: int = 500
    offset: int = 0

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("Período inválido.")
        object.__setattr__(self, "limit", min(max(self.limit, 1), MAX_PAGE))
        object.__setattr__(self, "offset", max(self.offset, 0))
        object.__setattr__(self, "text", self.text.strip()[:100])


@dataclass(frozen=True, slots=True)
class TransactionRow:
    id: str
    kind: TransactionKind
    description: str
    amount_cents: int
    accrual_date: date
    due_date: date
    paid_date: date | None
    status: TransactionStatus
    is_overdue: bool
    account_id: str
    account_name: str
    category_name: str | None
    contact_name: str | None
    payment_method: PaymentMethod | None
    document_number: str
    installment_number: int | None
    installment_count: int | None
    version: int


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    """Cards do dashboard: recebido/pago no período (por data de pagamento) e pendentes."""

    received_cents: int
    paid_cents: int
    pending_receive_cents: int
    pending_pay_cents: int

    @property
    def balance_cents(self) -> int:
        return self.received_cents - self.paid_cents


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account_id: str
    name: str
    balance_cents: int
    archived: bool


@dataclass(frozen=True, slots=True)
class MonthlyFlow:
    month: int
    received_cents: int
    paid_cents: int


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    group_name: str | None
    category_name: str | None
    kind: TransactionKind
    total_cents: int
    count: int


@dataclass(frozen=True, slots=True)
class IncomeStatementTotals:
    totals: Mapping[DreGroup | str, GroupTotals] = field(default_factory=dict)


class ReportQueries(Protocol):
    def list_transactions(
        self, criteria: TransactionFilter, today: date
    ) -> list[TransactionRow]: ...
    def period_summary(self, start: date, end: date) -> PeriodSummary: ...
    def account_balances(self, until: date) -> list[AccountBalance]: ...
    def monthly_flow(self, year: int) -> list[MonthlyFlow]: ...
    def cumulative_balance(self, until: date) -> int: ...
    def income_statement_totals(
        self, start: date, end: date, basis: ReportBasis
    ) -> Mapping[DreGroup | str, GroupTotals]: ...
    def category_totals(
        self, start: date, end: date, basis: ReportBasis
    ) -> list[CategoryTotal]: ...
