"""View model das telas "Contas a receber" e "Contas a pagar".

Guarda o estado da tela (mês, filtros, busca), carrega as linhas pelo caso de uso e calcula o
resumo do mês. Não conhece widgets: é testável sem abrir janela (skill ``frontend-architecture``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from appfin.application.read_models import TransactionFilter, TransactionRow
from appfin.application.reports import month_range
from appfin.domain.enums import TransactionKind, TransactionStatus
from appfin.presentation.workspace import Workspace


class StatusFilter(StrEnum):
    ALL = "all"
    PENDING = "pending"
    OVERDUE = "overdue"
    PAID = "paid"


@dataclass(frozen=True, slots=True)
class MonthSummary:
    total_cents: int = 0
    paid_cents: int = 0
    pending_cents: int = 0
    overdue_cents: int = 0
    count: int = 0


class TransactionsViewModel(QObject):
    changed = Signal()  # linhas e resumo atualizados

    def __init__(self, ws: Workspace, kind: TransactionKind) -> None:
        super().__init__()
        if kind not in (TransactionKind.INCOME, TransactionKind.EXPENSE):
            raise ValueError("Tela de lançamentos só para receitas ou despesas.")
        self._ws = ws
        self.kind = kind
        today = ws.today()
        self.year, self.month = today.year, today.month
        self.account_id: str | None = None
        self.status_filter = StatusFilter.ALL
        self.search = ""
        self.rows: list[TransactionRow] = []
        self.summary = MonthSummary()

    # ------------------------------------------------------------------ filtros
    def set_month(self, year: int, month: int) -> None:
        self.year, self.month = year, month
        self.reload()

    def set_account(self, account_id: str | None) -> None:
        self.account_id = account_id
        self.reload()

    def set_status(self, status: StatusFilter) -> None:
        self.status_filter = status
        self.reload()

    def set_search(self, text: str) -> None:
        self.search = text.strip()
        self.reload()

    # ------------------------------------------------------------------ carga
    def reload(self) -> None:
        start, end = month_range(self.year, self.month)
        statuses = frozenset({TransactionStatus.PENDING, TransactionStatus.PAID})
        if self.status_filter is StatusFilter.PAID:
            statuses = frozenset({TransactionStatus.PAID})
        elif self.status_filter in (StatusFilter.PENDING, StatusFilter.OVERDUE):
            statuses = frozenset({TransactionStatus.PENDING})
        criteria = TransactionFilter(
            start=start,
            end=end,
            kinds=frozenset({self.kind}),
            statuses=statuses,
            account_id=self.account_id,
            text=self.search,
            overdue_only=self.status_filter is StatusFilter.OVERDUE,
            limit=1000,
        )
        self.rows = self._ws.reports.transactions(criteria)
        self.summary = _summarize(self.rows)
        self.changed.emit()

    # ------------------------------------------------------------------ ações
    def settle(self, ids: list[str], paid_date: date, account_id: str | None) -> int:
        changed = self._ws.transactions.mark_paid(ids, paid_date, account_id)
        self.reload()
        return changed

    def reopen(self, ids: list[str]) -> int:
        changed = self._ws.transactions.mark_pending(ids)
        self.reload()
        return changed

    def delete(self, ids: list[str]) -> int:
        deleted = self._ws.transactions.delete(ids)
        self.reload()
        return deleted


def _summarize(rows: list[TransactionRow]) -> MonthSummary:
    total = paid = pending = overdue = 0
    for row in rows:
        total += row.amount_cents
        if row.status is TransactionStatus.PAID:
            paid += row.amount_cents
        elif row.status is TransactionStatus.PENDING:
            pending += row.amount_cents
            if row.is_overdue:
                overdue += row.amount_cents
    return MonthSummary(total, paid, pending, overdue, len(rows))
