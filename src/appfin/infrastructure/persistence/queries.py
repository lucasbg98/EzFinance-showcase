"""Consultas de leitura (listagens e relatórios), agregadas no banco.

Regras de negócio refletidas aqui (skill ``dominio-consultorio``):
- "Vencida" = pendente com vencimento anterior a hoje (calculado, nunca gravado).
- Regime de caixa: só pagos, pela data de pagamento. Competência: não cancelados, pela competência.
- Transferências nunca entram em receita/despesa/DRE; entram nos saldos das contas.
- Grupo do DRE: o da categoria; se vazio, o do grupo (categoria-pai).

Segurança: o SQL é montado só com fragmentos fixos deste módulo (colunas, condições e o
número de ``?``); todo valor vindo de fora vai como parâmetro. Por isso os ``noqa: S608``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from appfin.application.read_models import (
    AccountBalance,
    CategoryTotal,
    MonthlyFlow,
    PeriodSummary,
    TransactionFilter,
    TransactionRow,
)
from appfin.domain.enums import (
    DreGroup,
    PaymentMethod,
    ReportBasis,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.income_statement import UNCLASSIFIED, GroupTotals
from appfin.infrastructure.persistence.database import Connection

_LIVE = "t.deleted_at IS NULL"
_NOT_TRANSFER = "t.kind IN ('income', 'expense')"


def _escape_like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _basis_clause(basis: ReportBasis) -> tuple[str, str]:
    """(condição de status, coluna de data) do regime escolhido. Valores fixos, não externos."""
    if basis is ReportBasis.CASH:
        return "t.status = 'paid'", "t.paid_date"
    return "t.status <> 'cancelled'", "t.accrual_date"


class SqlReportQueries:
    def __init__(self, connection: Connection) -> None:
        self._db = connection

    # ------------------------------------------------------------------ listagem
    def list_transactions(self, criteria: TransactionFilter, today: date) -> list[TransactionRow]:
        conditions = [_LIVE, "t.due_date BETWEEN ? AND ?"]
        params: list[Any] = [criteria.start.isoformat(), criteria.end.isoformat()]
        conditions.append(f"t.kind IN ({', '.join('?' * len(criteria.kinds))})")
        params.extend(sorted(kind.value for kind in criteria.kinds))
        conditions.append(f"t.status IN ({', '.join('?' * len(criteria.statuses))})")
        params.extend(sorted(status.value for status in criteria.statuses))
        for column, value in (
            ("t.account_id", criteria.account_id),
            ("t.contact_id", criteria.contact_id),
            ("t.category_id", criteria.category_id),
        ):
            if value is not None:
                conditions.append(f"{column} = ?")
                params.append(value)
        if criteria.text:
            conditions.append(
                "(t.description LIKE ? ESCAPE '\\' OR t.document_number LIKE ? ESCAPE '\\' "
                "OR co.name LIKE ? ESCAPE '\\')"
            )
            params.extend([_escape_like(criteria.text)] * 3)
        if criteria.overdue_only:
            conditions.append("t.status = 'pending' AND t.due_date < ?")
            params.append(today.isoformat())
        sql = (
            "SELECT t.id, t.kind, t.description, t.amount_cents, t.accrual_date, t.due_date, "  # noqa: S608  # nosec B608
            "t.paid_date, t.status, t.account_id, a.name, c.name, co.name, t.payment_method, "
            "t.document_number, t.installment_number, g.count, t.version "
            "FROM financial_transaction t "
            "JOIN account a ON a.id = t.account_id "
            "LEFT JOIN category c ON c.id = t.category_id "
            "LEFT JOIN contact co ON co.id = t.contact_id "
            "LEFT JOIN installment_group g ON g.id = t.installment_group_id "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY t.due_date, t.description COLLATE NOCASE, t.id LIMIT ? OFFSET ?"
        )
        params.extend([criteria.limit, criteria.offset])
        rows = self._db.execute(sql, params).fetchall()
        return [self._row(row, today) for row in rows]

    @staticmethod
    def _row(row: tuple[Any, ...], today: date) -> TransactionRow:
        status = TransactionStatus(row[7])
        due = date.fromisoformat(row[5])
        return TransactionRow(
            id=row[0],
            kind=TransactionKind(row[1]),
            description=row[2],
            amount_cents=row[3],
            accrual_date=date.fromisoformat(row[4]),
            due_date=due,
            paid_date=date.fromisoformat(row[6]) if row[6] else None,
            status=status,
            is_overdue=status is TransactionStatus.PENDING and due < today,
            account_id=row[8],
            account_name=row[9],
            category_name=row[10],
            contact_name=row[11],
            payment_method=PaymentMethod(row[12]) if row[12] else None,
            document_number=row[13],
            installment_number=row[14],
            installment_count=row[15],
            version=row[16],
        )

    # ------------------------------------------------------------------ dashboard
    def period_summary(self, start: date, end: date) -> PeriodSummary:
        s, e = start.isoformat(), end.isoformat()
        row = self._db.execute(
            "SELECT "  # noqa: S608  # nosec B608
            "COALESCE(SUM(CASE WHEN t.kind = 'income' AND t.status = 'paid' "
            "  AND t.paid_date BETWEEN ? AND ? THEN t.amount_cents END), 0), "
            "COALESCE(SUM(CASE WHEN t.kind = 'expense' AND t.status = 'paid' "
            "  AND t.paid_date BETWEEN ? AND ? THEN t.amount_cents END), 0), "
            "COALESCE(SUM(CASE WHEN t.kind = 'income' AND t.status = 'pending' "
            "  AND t.due_date BETWEEN ? AND ? THEN t.amount_cents END), 0), "
            "COALESCE(SUM(CASE WHEN t.kind = 'expense' AND t.status = 'pending' "
            "  AND t.due_date BETWEEN ? AND ? THEN t.amount_cents END), 0) "
            f"FROM financial_transaction t WHERE {_LIVE} AND {_NOT_TRANSFER}",
            (s, e, s, e, s, e, s, e),
        ).fetchone()
        return PeriodSummary(row[0], row[1], row[2], row[3])

    def account_balances(self, until: date) -> list[AccountBalance]:
        rows = self._db.execute(
            "SELECT a.id, a.name, a.opening_balance_cents + COALESCE(SUM(CASE "  # noqa: S608  # nosec B608
            "  WHEN t.kind IN ('income', 'transfer_in') THEN t.amount_cents "
            "  ELSE -t.amount_cents END), 0), a.archived "
            "FROM account a LEFT JOIN financial_transaction t ON t.account_id = a.id "
            f"  AND {_LIVE} AND t.status = 'paid' AND t.paid_date <= ? "
            "WHERE a.deleted_at IS NULL GROUP BY a.id ORDER BY a.archived, a.name COLLATE NOCASE",
            (until.isoformat(),),
        ).fetchall()
        return [AccountBalance(r[0], r[1], r[2], bool(r[3])) for r in rows]

    def cumulative_balance(self, until: date) -> int:
        return sum(b.balance_cents for b in self.account_balances(until))

    def monthly_flow(self, year: int) -> list[MonthlyFlow]:
        rows = self._db.execute(
            "SELECT CAST(substr(t.paid_date, 6, 2) AS INTEGER) AS m, "  # noqa: S608  # nosec B608
            "COALESCE(SUM(CASE WHEN t.kind = 'income' THEN t.amount_cents END), 0), "
            "COALESCE(SUM(CASE WHEN t.kind = 'expense' THEN t.amount_cents END), 0) "
            f"FROM financial_transaction t WHERE {_LIVE} AND {_NOT_TRANSFER} "
            "AND t.status = 'paid' AND t.paid_date BETWEEN ? AND ? GROUP BY m",
            (f"{year:04d}-01-01", f"{year:04d}-12-31"),
        ).fetchall()
        by_month = {int(r[0]): (int(r[1]), int(r[2])) for r in rows}
        return [MonthlyFlow(m, *by_month.get(m, (0, 0))) for m in range(1, 13)]

    # ------------------------------------------------------------------ DRE / categorias
    def income_statement_totals(
        self, start: date, end: date, basis: ReportBasis
    ) -> Mapping[DreGroup | str, GroupTotals]:
        status_clause, date_column = _basis_clause(basis)
        rows = self._db.execute(
            "SELECT COALESCE(c.dre_group, p.dre_group), "  # noqa: S608  # nosec B608
            "COALESCE(SUM(CASE WHEN t.kind = 'income' THEN t.amount_cents END), 0), "
            "COALESCE(SUM(CASE WHEN t.kind = 'expense' THEN t.amount_cents END), 0) "
            "FROM financial_transaction t "
            "LEFT JOIN category c ON c.id = t.category_id "
            "LEFT JOIN category p ON p.id = c.parent_id "
            f"WHERE {_LIVE} AND {_NOT_TRANSFER} AND {status_clause} "
            f"AND {date_column} BETWEEN ? AND ? "
            "GROUP BY COALESCE(c.dre_group, p.dre_group)",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        totals: dict[DreGroup | str, GroupTotals] = {}
        for group, inflow, outflow in rows:
            key: DreGroup | str = DreGroup(group) if group else UNCLASSIFIED
            totals[key] = GroupTotals(int(inflow), int(outflow))
        return totals

    def category_totals(self, start: date, end: date, basis: ReportBasis) -> list[CategoryTotal]:
        status_clause, date_column = _basis_clause(basis)
        rows = self._db.execute(
            "SELECT p.name, c.name, t.kind, SUM(t.amount_cents), count(*) "  # noqa: S608  # nosec B608
            "FROM financial_transaction t "
            "LEFT JOIN category c ON c.id = t.category_id "
            "LEFT JOIN category p ON p.id = c.parent_id "
            f"WHERE {_LIVE} AND {_NOT_TRANSFER} AND {status_clause} "
            f"AND {date_column} BETWEEN ? AND ? "
            "GROUP BY t.kind, c.id ORDER BY t.kind DESC, SUM(t.amount_cents) DESC",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            CategoryTotal(r[0], r[1], TransactionKind(r[2]), int(r[3]), int(r[4])) for r in rows
        ]
