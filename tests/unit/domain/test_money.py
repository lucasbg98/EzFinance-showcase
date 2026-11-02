from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from appfin.domain.errors import CurrencyMismatchError, InvalidAmountError
from appfin.domain.money import MAX_ABS_CENTS, Money


def test_split_gives_remainder_to_first_installments() -> None:
    parts = Money(10_000).split(3)

    assert [p.cents for p in parts] == [3334, 3333, 3333]


def test_single_installment_keeps_full_amount() -> None:
    assert Money(12_345).split(1) == [Money(12_345)]


@given(
    cents=st.integers(min_value=0, max_value=MAX_ABS_CENTS),
    parts=st.integers(min_value=1, max_value=360),
)
def test_installments_sum_equals_total_and_differ_by_at_most_one_cent(
    cents: int, parts: int
) -> None:
    result = Money(cents).split(parts)

    assert len(result) == parts
    assert sum(p.cents for p in result) == cents
    assert max(p.cents for p in result) - min(p.cents for p in result) <= 1
    assert [p.cents for p in result] == sorted((p.cents for p in result), reverse=True)


@pytest.mark.parametrize("parts", [0, -1, True])
def test_split_rejects_invalid_parts(parts: int) -> None:
    with pytest.raises(InvalidAmountError):
        Money(100).split(parts)


def test_split_rejects_negative_amount() -> None:
    with pytest.raises(InvalidAmountError):
        Money(-100).split(2)


@pytest.mark.parametrize("value", [1.5, "100", True, None])
def test_rejects_non_integer_cents(value: object) -> None:
    with pytest.raises(InvalidAmountError):
        Money(value)  # type: ignore[arg-type]


def test_rejects_amount_above_limit() -> None:
    with pytest.raises(InvalidAmountError):
        Money(MAX_ABS_CENTS + 1)


@pytest.mark.parametrize("currency", ["brl", "R$", "BRLX", ""])
def test_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(InvalidAmountError):
        Money(1, currency)


def test_addition_and_subtraction() -> None:
    assert Money(150) + Money(250) == Money(400)
    assert Money(150) - Money(250) == Money(-100)
    assert -Money(5) == Money(-5)


def test_operations_between_currencies_fail() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money(1, "BRL") + Money(1, "USD")


@pytest.mark.parametrize(
    ("amount", "cents"),
    [("1234.56", 123456), ("0.1", 10), ("10", 1000), ("-2.50", -250), ("0.00", 0)],
)
def test_from_decimal_is_exact(amount: str, cents: int) -> None:
    assert Money.from_decimal(Decimal(amount)).cents == cents


@pytest.mark.parametrize("amount", ["1.005", "NaN", "Infinity"])
def test_from_decimal_rejects_inexact_or_non_finite(amount: str) -> None:
    with pytest.raises(InvalidAmountError):
        Money.from_decimal(Decimal(amount))
