from datetime import date
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from appfin.domain.enums import IntervalUnit
from appfin.domain.errors import ValidationError
from appfin.domain.installments import add_months, plan_installments
from appfin.domain.money import Money


def test_monthly_plan_keeps_day_and_sums_to_total() -> None:
    plan = plan_installments(Money(100_000), 3, date(2026, 1, 10))

    assert [p.due_date for p in plan] == [date(2026, 1, 10), date(2026, 2, 10), date(2026, 3, 10)]
    assert [p.amount.cents for p in plan] == [33_334, 33_333, 33_333]
    assert [p.number for p in plan] == [1, 2, 3]


def test_month_end_is_clamped_without_drifting() -> None:
    plan = plan_installments(Money(400), 4, date(2026, 1, 31))

    assert [p.due_date for p in plan] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_leap_year_february() -> None:
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_daily_interval_like_the_reference_app() -> None:
    plan = plan_installments(Money(300), 3, date(2026, 12, 15), IntervalUnit.DAY, 30)

    assert [p.due_date for p in plan] == [date(2026, 12, 15), date(2027, 1, 14), date(2027, 2, 13)]


def test_every_two_months_crosses_year() -> None:
    plan = plan_installments(Money(300), 3, date(2026, 11, 5), IntervalUnit.MONTH, 2)

    assert [p.due_date for p in plan] == [date(2026, 11, 5), date(2027, 1, 5), date(2027, 3, 5)]


def test_single_installment() -> None:
    (only,) = plan_installments(Money(12_345), 1, date(2026, 5, 1))

    assert only.amount == Money(12_345) and only.due_date == date(2026, 5, 1)


@pytest.mark.parametrize(("cents", "count"), [(0, 1), (100, 0), (100, 361), (2, 3), (-500, 2)])
def test_invalid_plans_are_rejected(cents: int, count: int) -> None:
    with pytest.raises(ValidationError):
        plan_installments(Money(cents), count, date(2026, 1, 1))


@given(
    cents=st.integers(min_value=360, max_value=10**10),
    count=st.integers(min_value=1, max_value=360),
    first=st.dates(min_value=date(2000, 1, 1), max_value=date(2080, 12, 31)),
)
def test_plan_properties(cents: int, count: int, first: date) -> None:
    plan = plan_installments(Money(cents), count, first)

    assert sum(p.amount.cents for p in plan) == cents
    assert all(a.due_date < b.due_date for a, b in pairwise(plan))
    assert all(p.due_date.day <= first.day for p in plan)
