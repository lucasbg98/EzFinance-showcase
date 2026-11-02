"""Casos de uso de lançamentos e relatórios contra o SQLCipher real (dados fictícios)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from appfin.application.read_models import TransactionFilter
from appfin.application.reports import month_range
from appfin.application.transactions import TransactionDraft
from appfin.domain.entities import Account, Category, Contact
from appfin.domain.enums import (
    AccountKind,
    CategoryKind,
    DreGroup,
    IntervalUnit,
    PaymentMethod,
    ReportBasis,
    TaxRegime,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import (
    BusinessRuleError,
    ConcurrencyConflictError,
    ValidationError,
)
from appfin.domain.money import Money
from tests.integration.conftest import TODAY, App


def _category(app: App, name: str) -> Category:
    return next(c for c in app.catalog.list_categories() if c.name == name)


def _account(app: App, name: str = "Caixa do consultório") -> Account:
    return next(a for a in app.catalog.list_accounts() if a.name == name)


def _income(app: App, **changes: object) -> TransactionDraft:
    draft = TransactionDraft(
        kind=TransactionKind.INCOME,
        description="Tratamento ortodôntico",
        total=Money(120_000),
        first_due=date(2026, 3, 10),
        account_id=_account(app).id,
        category_id=_category(app, "Tratamentos particulares").id,
        payment_method=PaymentMethod.PIX,
    )
    return replace(draft, **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- cadastros
def test_defaults_are_seeded_once(app: App) -> None:
    before = len(app.catalog.list_categories())
    app.catalog.initialize_defaults(TaxRegime.SIMPLES)

    assert before == len(app.catalog.list_categories()) > 30
    assert [a.name for a in app.catalog.list_accounts()] == ["Caixa do consultório"]
    groups = [c for c in app.catalog.list_categories() if c.is_group]
    assert {g.dre_group for g in groups} == set(DreGroup)


def test_subcategory_needs_a_group_parent(app: App) -> None:
    leaf = _category(app, "Aluguel")

    with pytest.raises(ValidationError):
        app.catalog.save_category(
            Category("", "Sub de sub", CategoryKind.EXPENSE, parent_id=leaf.id)
        )


def test_contact_with_transactions_cannot_be_deleted(app: App) -> None:
    contact = app.catalog.save_contact(Contact("", "Paciente Fictício"))
    app.transactions.create(_income(app, contact_id=contact.id))

    with pytest.raises(BusinessRuleError):
        app.catalog.delete_contact(contact.id)


def test_last_active_account_cannot_be_archived(app: App) -> None:
    with pytest.raises(BusinessRuleError):
        app.catalog.set_account_archived(_account(app).id, archived=True)


def test_optimistic_concurrency_on_contacts(app: App) -> None:
    contact = app.catalog.save_contact(Contact("", "Fornecedor X"))
    app.catalog.save_contact(replace(contact, phone="11987654321"))

    with pytest.raises(ConcurrencyConflictError):
        app.catalog.save_contact(replace(contact, phone="11912345678"))  # versão antiga


# ---------------------------------------------------------------------- parcelamento
def test_installments_share_accrual_and_split_exactly(app: App) -> None:
    created = app.transactions.create(
        _income(app, total=Money(100_000), installments=3, accrual_date=date(2026, 3, 1))
    )

    assert [t.amount.cents for t in created] == [33_334, 33_333, 33_333]
    assert [t.due_date for t in created] == [
        date(2026, 3, 10),
        date(2026, 4, 10),
        date(2026, 5, 10),
    ]
    assert {t.accrual_date for t in created} == {date(2026, 3, 1)}
    assert created[1].description == "Tratamento ortodôntico — parcela 2/3"
    assert len({t.installment_group_id for t in created}) == 1


def test_pay_now_settles_only_first_installment(app: App) -> None:
    created = app.transactions.create(_income(app, installments=2, pay_now=True))

    assert created[0].status is TransactionStatus.PAID and created[0].paid_date == TODAY
    assert created[1].status is TransactionStatus.PENDING


def test_daily_interval(app: App) -> None:
    created = app.transactions.create(
        _income(app, installments=2, interval_unit=IntervalUnit.DAY, interval_value=30)
    )

    assert created[1].due_date == date(2026, 4, 9)


def test_category_kind_must_match(app: App) -> None:
    with pytest.raises(ValidationError):
        app.transactions.create(_income(app, category_id=_category(app, "Aluguel").id))


def test_creation_is_atomic(app: App) -> None:
    """Uma referência inválida não deixa parcelas pela metade."""
    with pytest.raises(ValidationError):
        app.transactions.create(_income(app, installments=5, contact_id="inexistente"))

    month = TransactionFilter(*month_range(2026, 3), limit=1000)
    assert app.reports.transactions(month) == []


# ---------------------------------------------------------------------- baixa / exclusão
def test_batch_mark_paid_and_overdue(app: App) -> None:
    created = app.transactions.create(_income(app, installments=3))
    rows = app.reports.transactions(TransactionFilter(date(2026, 1, 1), date(2026, 12, 31)))
    assert [r.is_overdue for r in rows] == [True, False, False]  # venceu 10/03, hoje 15/03

    changed = app.transactions.mark_paid([t.id for t in created[:2]], TODAY)

    assert changed == 2
    rows = app.reports.transactions(TransactionFilter(date(2026, 1, 1), date(2026, 12, 31)))
    assert [r.status for r in rows] == [
        TransactionStatus.PAID,
        TransactionStatus.PAID,
        TransactionStatus.PENDING,
    ]
    assert app.transactions.mark_paid([created[0].id], TODAY) == 0  # idempotente


def test_delete_is_soft_and_hidden_from_lists(app: App) -> None:
    created = app.transactions.create(_income(app))

    assert app.transactions.delete([created[0].id, created[0].id]) == 1
    assert app.reports.transactions(TransactionFilter(*month_range(2026, 3))) == []
    row = app.db.execute(
        "SELECT deleted_at IS NOT NULL FROM financial_transaction WHERE id = ?", (created[0].id,)
    ).fetchone()
    assert row[0] == 1


def test_search_by_text_contact_and_overdue(app: App) -> None:
    patient = app.catalog.save_contact(Contact("", "Paciente Busca"))
    app.transactions.create(_income(app, contact_id=patient.id, description="Clareamento"))
    app.transactions.create(_income(app, description="Limpeza", first_due=date(2026, 3, 20)))
    month = month_range(2026, 3)

    assert [
        r.description for r in app.reports.transactions(TransactionFilter(*month, text="busca"))
    ] == ["Clareamento"]
    assert [
        r.description for r in app.reports.transactions(TransactionFilter(*month, text="100%"))
    ] == []
    overdue = app.reports.transactions(TransactionFilter(*month, overdue_only=True))
    assert [r.description for r in overdue] == ["Clareamento"]


# ---------------------------------------------------------------------- transferências e saldos
def test_transfer_two_legs_affect_balances_not_results(app: App) -> None:
    bank = app.catalog.save_account(Account("", "Banco", AccountKind.CHECKING))
    cash = _account(app)
    paid = app.transactions.create(_income(app, pay_now=True, paid_date=date(2026, 3, 5)))
    assert paid[0].status is TransactionStatus.PAID

    out_leg, in_leg = app.transactions.transfer(cash.id, bank.id, Money(50_000), date(2026, 3, 6))

    assert out_leg.transfer_id == in_leg.transfer_id
    balances = {b.name: b.balance_cents for b in app.reports.dashboard(2026, 3).balances}
    assert balances == {"Banco": 50_000, "Caixa do consultório": 70_000}
    summary = app.reports.dashboard(2026, 3).summary
    assert summary.received_cents == 120_000 and summary.paid_cents == 0

    # Excluir uma perna exclui as duas.
    assert app.transactions.delete([in_leg.id]) == 2
    balances = {b.name: b.balance_cents for b in app.reports.dashboard(2026, 3).balances}
    assert balances == {"Banco": 0, "Caixa do consultório": 120_000}


# ---------------------------------------------------------------------- DRE
def test_income_statement_cash_vs_accrual(app: App) -> None:
    # Venda de tratamento em março (competência), 3 parcelas; só a 1ª paga em março.
    created = app.transactions.create(
        _income(app, total=Money(90_000), installments=3, accrual_date=date(2026, 3, 1))
    )
    app.transactions.mark_paid([created[0].id], date(2026, 3, 10))
    app.transactions.create(
        TransactionDraft(
            kind=TransactionKind.EXPENSE,
            description="Laboratório",
            total=Money(20_000),
            first_due=date(2026, 3, 12),
            account_id=_account(app).id,
            category_id=_category(app, "Laboratório de prótese").id,
            pay_now=True,
            paid_date=date(2026, 3, 12),
        )
    )
    start, end = month_range(2026, 3)

    cash = {
        line.label: line.amount.cents
        for line in app.reports.income_statement(start, end, ReportBasis.CASH)
    }
    accrual = {
        line.label: line.amount.cents
        for line in app.reports.income_statement(start, end, ReportBasis.ACCRUAL)
    }

    assert cash["(+) Receita bruta"] == 30_000
    assert accrual["(+) Receita bruta"] == 90_000
    assert cash["(-) Custos diretos"] == accrual["(-) Custos diretos"] == -20_000
    assert cash["(=) Resultado do período"] == 10_000
    assert accrual["(=) Resultado do período"] == 70_000


def test_uncategorized_goes_to_unclassified(app: App) -> None:
    app.transactions.create(
        _income(app, category_id=None, pay_now=True, paid_date=date(2026, 3, 2))
    )
    lines = app.reports.income_statement(*month_range(2026, 3), ReportBasis.CASH)

    labels = {line.label: line.amount.cents for line in lines}
    assert labels["(±) Não classificados"] == 120_000
    assert labels["(=) Resultado do período"] == 120_000


def test_monthly_flow_and_category_totals(app: App) -> None:
    app.transactions.create(_income(app, pay_now=True, paid_date=date(2026, 2, 3)))
    app.transactions.create(_income(app, pay_now=True, paid_date=date(2026, 3, 3)))

    flow = app.reports.dashboard(2026, 3).monthly_flow
    assert len(flow) == 12
    assert [f.received_cents for f in flow[:3]] == [0, 120_000, 120_000]

    totals = app.reports.category_totals(date(2026, 1, 1), date(2026, 12, 31), ReportBasis.CASH)
    assert [(t.category_name, t.total_cents, t.count) for t in totals] == [
        ("Tratamentos particulares", 240_000, 2)
    ]


def test_outbox_records_every_change(app: App) -> None:
    before = app.db.execute("SELECT count(*) FROM outbox").fetchone()[0]
    created = app.transactions.create(_income(app, installments=2))
    app.transactions.mark_paid([created[0].id], TODAY)

    after = app.db.execute("SELECT count(*) FROM outbox").fetchone()[0]
    assert after - before == 4  # grupo + 2 parcelas + 1 baixa


@pytest.mark.parametrize(
    "hostile",
    [
        "'; DROP TABLE financial_transaction; --",
        '" OR 1=1 --',
        "%' OR '1'='1",
        "\\",
        "_",
    ],
)
def test_hostile_text_is_stored_and_searched_literally(app: App, hostile: str) -> None:
    contact = app.catalog.save_contact(Contact("", f"Contato {hostile}"))
    app.transactions.create(_income(app, description=f"Desc {hostile}", contact_id=contact.id))

    found = app.reports.transactions(TransactionFilter(*month_range(2026, 3), text=hostile))

    assert [r.description for r in found] == [f"Desc {hostile}"]
    assert app.db.execute("SELECT count(*) FROM financial_transaction").fetchone()[0] == 1
