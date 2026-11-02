from dataclasses import replace
from datetime import date

import pytest

from appfin.domain.entities import Account, Category, Company, Contact, Transaction
from appfin.domain.enums import (
    CategoryKind,
    ContactRole,
    LegalType,
    PersonType,
    TransactionKind,
    TransactionStatus,
)
from appfin.domain.errors import ValidationError
from appfin.domain.money import Money
from appfin.domain.validation import clean_document, clean_text, is_valid_cnpj, is_valid_cpf

VALID_CPF = "52998224725"
VALID_CNPJ = "11222333000181"


def _tx(**changes: object) -> Transaction:
    base = Transaction(
        id="t1",
        kind=TransactionKind.INCOME,
        description="Tratamento — parcela 1/3",
        amount=Money(15_000),
        accrual_date=date(2026, 3, 1),
        due_date=date(2026, 3, 10),
        account_id="a1",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- documentos
def test_cpf_and_cnpj_check_digits() -> None:
    assert is_valid_cpf(VALID_CPF)
    assert is_valid_cnpj(VALID_CNPJ)
    assert not is_valid_cpf("52998224724")
    assert not is_valid_cpf("11111111111")
    assert not is_valid_cnpj("11222333000180")


def test_document_accepts_masks() -> None:
    assert clean_document("529.982.247-25") == VALID_CPF
    assert clean_document("11.222.333/0001-81") == VALID_CNPJ
    assert clean_document("") == ""
    with pytest.raises(ValidationError):
        clean_document("123")


# ---------------------------------------------------------------------- textos
def test_text_cleaning_removes_control_and_invisible_chars() -> None:
    zero_width, nul, right_to_left = chr(0x200B), chr(0), chr(0x202E)
    hostile = f"  Ma{zero_width}ria{nul} {right_to_left}Silva "

    assert clean_text(hostile, "name", max_length=50) == "Maria Silva"


def test_text_limits_and_required() -> None:
    with pytest.raises(ValidationError):
        clean_text("   ", "name", max_length=10, required=True)
    with pytest.raises(ValidationError):
        clean_text("x" * 11, "name", max_length=10)


# ---------------------------------------------------------------------- empresa / contato
def test_company_document_must_match_legal_type() -> None:
    assert Company(name="Clínica Sorriso", document="11.222.333/0001-81").document == VALID_CNPJ
    with pytest.raises(ValidationError):
        Company(name="Clínica", legal_type=LegalType.PJ, document=VALID_CPF)


def test_contact_minimal_patient_needs_only_name() -> None:
    contact = Contact(id="c1", name="  Paciente Fictício ")

    assert contact.name == "Paciente Fictício"
    assert contact.roles == frozenset({ContactRole.PATIENT})


@pytest.mark.parametrize(
    "changes",
    [
        {"roles": frozenset()},
        {"person_type": PersonType.PF, "document": VALID_CNPJ},
        {"state": "XX"},
        {"zip_code": "123"},
        {"phone": "123"},
        {"email": "não-é-email"},
    ],
)
def test_contact_invalid_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Contact(id="c1", name="Fulano", **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- categoria / conta
def test_category_accepts_matching_kind() -> None:
    income = Category(id="k1", name="Tratamentos", kind=CategoryKind.INCOME, parent_id="g1")
    both = Category(id="k2", name="Outros", kind=CategoryKind.BOTH, parent_id="g1")

    assert income.accepts(TransactionKind.INCOME)
    assert not income.accepts(TransactionKind.EXPENSE)
    assert both.accepts(TransactionKind.EXPENSE)
    assert not both.accepts(TransactionKind.TRANSFER_IN)


def test_category_cannot_be_its_own_group() -> None:
    with pytest.raises(ValidationError):
        Category(id="k1", name="X", kind=CategoryKind.INCOME, parent_id="k1")


def test_account_name_required() -> None:
    with pytest.raises(ValidationError):
        Account(id="a1", name=" ")


# ---------------------------------------------------------------------- lançamento
def test_transaction_lifecycle() -> None:
    pending = _tx()
    assert pending.is_overdue(date(2026, 3, 11))
    assert not pending.is_overdue(date(2026, 3, 10))

    paid = pending.mark_paid(date(2026, 3, 9), account_id="a2")

    assert paid.status is TransactionStatus.PAID
    assert paid.paid_date == date(2026, 3, 9) and paid.account_id == "a2"
    assert not paid.is_overdue(date(2027, 1, 1))
    assert paid.mark_pending().paid_date is None


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": Money(0)},
        {"description": ""},
        {"status": TransactionStatus.PAID},
        {"paid_date": date(2026, 1, 1)},
        {"kind": TransactionKind.TRANSFER_OUT},
        {"transfer_id": "x"},
        {"installment_group_id": "g1"},
        {"installment_group_id": "g1", "installment_number": 0},
    ],
)
def test_transaction_invariants(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _tx(**changes)


def test_transfer_leg_rules() -> None:
    leg = _tx(kind=TransactionKind.TRANSFER_OUT, transfer_id="tr1")
    assert leg.kind.is_transfer
    with pytest.raises(ValidationError):
        _tx(kind=TransactionKind.TRANSFER_IN, transfer_id="tr1", category_id="k1")


def test_cancelled_cannot_be_paid() -> None:
    with pytest.raises(ValidationError):
        _tx(status=TransactionStatus.CANCELLED).mark_paid(date(2026, 3, 9))
