from datetime import date

import pytest

from appfin.domain.errors import ValidationError
from appfin.presentation.shared.formatting import (
    HIDDEN_AMOUNT,
    ValuesVisibility,
    format_cents,
    format_date,
    format_document,
    format_money,
    format_phone,
    month_label,
    parse_money,
)


@pytest.mark.parametrize(
    ("cents", "text"),
    [(0, "R$ 0,00"), (5, "R$ 0,05"), (123_456, "R$ 1.234,56"), (-100_000_000, "-R$ 1.000.000,00")],
)
def test_format_cents(cents: int, text: str) -> None:
    assert format_cents(cents) == text


@pytest.mark.parametrize(
    ("text", "cents"),
    [("1.234,56", 123_456), ("R$ 10", 1000), ("10,5", 1050), ("0,01", 1), ("1234", 123_400)],
)
def test_parse_money(text: str, cents: int) -> None:
    assert parse_money(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "1,234", "1e5", "--5", "1,2,3"])
def test_parse_money_rejects_invalid(text: str) -> None:
    with pytest.raises(ValidationError):
        parse_money(text)


def test_negative_only_when_allowed() -> None:
    with pytest.raises(ValidationError):
        parse_money("-5,00")
    assert parse_money("-5,00", allow_negative=True) == -500


def test_hidden_values() -> None:
    visibility = ValuesVisibility()
    assert format_money(990, visibility) == "R$ 9,90"
    visibility.set_hidden(True)
    assert format_money(990, visibility) == HIDDEN_AMOUNT


def test_dates_documents_phones() -> None:
    assert format_date(date(2026, 3, 5)) == "05/03/2026"
    assert month_label(2026, 3) == "Março de 2026"
    assert format_document("52998224725") == "529.982.247-25"
    assert format_document("11222333000181") == "11.222.333/0001-81"
    assert format_phone("11987654321") == "(11) 98765-4321"
    assert format_phone("1133334444") == "(11) 3333-4444"
