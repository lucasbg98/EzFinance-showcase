"""Casos de uso de leitura: listagens, dashboard, DRE e relatório por categoria."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from appfin.application.read_models import (
    AccountBalance,
    CategoryTotal,
    MonthlyFlow,
    PeriodSummary,
    ReportQueries,
    TransactionFilter,
    TransactionRow,
)
from appfin.domain.enums import ReportBasis
from appfin.domain.income_statement import StatementLine, build_income_statement


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


@dataclass(frozen=True, slots=True)
class Dashboard:
    summary: PeriodSummary
    balances: list[AccountBalance]
    total_balance_cents: int
    monthly_flow: list[MonthlyFlow]


class ReportService:
    def __init__(self, queries: Callable[[], ReportQueries], today: Callable[[], date]) -> None:
        self._queries = queries
        self._today = today

    def transactions(self, criteria: TransactionFilter) -> list[TransactionRow]:
        return self._queries().list_transactions(criteria, self._today())

    def dashboard(self, year: int, month: int) -> Dashboard:
        start, end = month_range(year, month)
        queries = self._queries()
        balances = queries.account_balances(end)
        return Dashboard(
            summary=queries.period_summary(start, end),
            balances=balances,
            total_balance_cents=sum(b.balance_cents for b in balances),
            monthly_flow=queries.monthly_flow(year),
        )

    def income_statement(self, start: date, end: date, basis: ReportBasis) -> list[StatementLine]:
        return build_income_statement(self._queries().income_statement_totals(start, end, basis))

    def category_totals(self, start: date, end: date, basis: ReportBasis) -> list[CategoryTotal]:
        return self._queries().category_totals(start, end, basis)
