"""Detalhamento do DRE: categorias de cada grupo e lançamentos de cada categoria.

Dados fictícios.
"""

from __future__ import annotations

from datetime import date

import pytest

from appfin.application.read_models import StatementTransactionsFilter
from appfin.application.reports import month_range
from appfin.application.transactions import TransactionDraft
from appfin.domain.entities import Account
from appfin.domain.enums import DreGroup, ReportBasis, TransactionKind
from appfin.domain.income_statement import UNCLASSIFIED, LineType
from appfin.domain.money import Money
from tests.integration.conftest import App

MARCH = month_range(2026, 3)


def _category_id(app: App, name: str) -> str:
    return next(c.id for c in app.catalog.list_categories() if c.name == name)


def _cash_account(app: App) -> str:
    return next(a.id for a in app.catalog.list_accounts() if a.name == "Caixa do consultório")


def _draft(
    app: App, kind: TransactionKind, category: str | None, **changes: object
) -> TransactionDraft:
    values: dict[str, object] = {
        "kind": kind,
        "description": f"Lançamento fictício {category or 'sem categoria'}",
        "total": Money(10_000),
        "first_due": date(2026, 3, 10),
        "account_id": _cash_account(app),
        "category_id": _category_id(app, category) if category else None,
    }
    values.update(changes)
    return TransactionDraft(**values)  # type: ignore[arg-type]


def _seed(app: App) -> None:
    """Março/2026: tratamento 3x (só a 1ª paga), contador pago, curso pendente, receita sem
    categoria paga e uma transferência (que nunca entra no DRE)."""
    sale = app.transactions.create(
        _draft(
            app,
            TransactionKind.INCOME,
            "Tratamentos particulares",
            total=Money(90_000),
            installments=3,
            accrual_date=date(2026, 3, 1),
        )
    )
    app.transactions.mark_paid([sale[0].id], date(2026, 3, 5))
    app.transactions.create(
        _draft(
            app,
            TransactionKind.EXPENSE,
            "Contador",
            total=Money(20_000),
            pay_now=True,
            paid_date=date(2026, 3, 8),
        )
    )
    app.transactions.create(
        _draft(app, TransactionKind.EXPENSE, "Cursos e capacitação", total=Money(15_000))
    )
    app.transactions.create(
        _draft(
            app,
            TransactionKind.INCOME,
            None,
            total=Money(5_000),
            pay_now=True,
            paid_date=date(2026, 3, 9),
        )
    )
    cash = _cash_account(app)
    bank = app.catalog.save_account(Account("", "Banco fictício"))
    app.transactions.transfer(cash, bank.id, Money(1_000), date(2026, 3, 11))


@pytest.mark.parametrize("basis", list(ReportBasis))
def test_details_of_each_group_add_up_to_the_statement_line(app: App, basis: ReportBasis) -> None:
    _seed(app)

    lines = app.reports.income_statement(*MARCH, basis)
    details = app.reports.income_statement_details(*MARCH, basis)

    for line in lines:
        if line.line_type is not LineType.GROUP:
            continue
        in_group = [d for d in details if d.group == line.group]
        assert sum(d.net_cents for d in in_group) == line.amount.cents, line.label


def test_details_follow_the_basis_and_keep_the_category_group(app: App) -> None:
    _seed(app)

    cash = app.reports.income_statement_details(*MARCH, ReportBasis.CASH)
    accrual = app.reports.income_statement_details(*MARCH, ReportBasis.ACCRUAL)

    by_name_cash = {d.category_name: d for d in cash}
    by_name_accrual = {d.category_name: d for d in accrual}
    assert by_name_cash["Tratamentos particulares"].inflow_cents == 30_000
    assert by_name_accrual["Tratamentos particulares"].inflow_cents == 90_000
    assert by_name_accrual["Tratamentos particulares"].count == 3
    assert by_name_cash["Contador"].group is DreGroup.TAXES
    assert by_name_cash["Contador"].group_name == "Impostos"
    assert "Cursos e capacitação" not in by_name_cash  # pendente: fora do regime de caixa
    assert by_name_accrual["Cursos e capacitação"].group is DreGroup.INVESTMENTS
    assert by_name_cash[None].group == UNCLASSIFIED
    assert by_name_cash[None].category_id is None


def test_transactions_of_a_category_match_its_total_in_each_basis(app: App) -> None:
    _seed(app)
    category = _category_id(app, "Tratamentos particulares")

    def rows(basis: ReportBasis) -> list[int]:
        found = app.reports.statement_transactions(
            StatementTransactionsFilter(*MARCH, basis, category)
        )
        return [r.amount_cents for r in found]

    assert rows(ReportBasis.CASH) == [30_000]
    assert rows(ReportBasis.ACCRUAL) == [30_000, 30_000, 30_000]


def test_transactions_without_category_and_never_transfers(app: App) -> None:
    _seed(app)

    found = app.reports.statement_transactions(
        StatementTransactionsFilter(*MARCH, ReportBasis.CASH, None)
    )

    assert [(r.kind, r.amount_cents) for r in found] == [(TransactionKind.INCOME, 5_000)]


def test_transactions_list_respects_the_limit(app: App) -> None:
    _seed(app)
    category = _category_id(app, "Tratamentos particulares")

    found = app.reports.statement_transactions(
        StatementTransactionsFilter(*MARCH, ReportBasis.ACCRUAL, category, limit=2)
    )

    assert len(found) == 2


def test_filter_rejects_inverted_period() -> None:
    with pytest.raises(ValueError, match="Período"):
        StatementTransactionsFilter(date(2026, 3, 31), date(2026, 3, 1), ReportBasis.CASH, None)
