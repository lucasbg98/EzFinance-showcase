"""Conversões puras da importação (valores pt-BR, rótulos, meses, comentários, chaves)."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from appfin.domain.spreadsheet_import.grid import CellComment, CellError
from appfin.domain.spreadsheet_import.parse import (
    MAX_COMMENT_LENGTH,
    AmountError,
    cell_key,
    clean_comment,
    detail_cents,
    display_label,
    is_separator,
    month_number,
    normalize_label,
    parse_amount,
    total_cents,
)
from tests.spreadsheet_fixtures import pt_br


# ---------------------------------------------------------------------- valores
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R$ 1.234,56", Decimal("1234.56")),
        (" R$ 1.234,56 ", Decimal("1234.56")),
        ("R$" + chr(0xA0) + "1.234,56", Decimal("1234.56")),
        ("R$ -", Decimal(0)),
        ("-R$ 1,00", Decimal("-1.00")),
        ("R$ -1,00", Decimal("-1.00")),
        ("1000", Decimal(1000)),
        ("1.000", Decimal(1000)),
        ("0,5", Decimal("0.5")),
        ("1234,567", Decimal("1234.567")),
        ("r$ 10,00", Decimal("10.00")),
    ],
)
def test_parses_pt_br_amounts(text: str, expected: Decimal) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_cell_is_none(value: str | None) -> None:
    assert parse_amount(value) is None


@pytest.mark.parametrize(
    "text", ["abc", "1.23,4", "1,234.56", "R$ 12a", "=1+1", "1.2345,00", "--1"]
)
def test_rejects_text_that_is_not_an_amount(text: str) -> None:
    with pytest.raises(AmountError):
        parse_amount(text)


def test_excel_error_is_not_an_amount() -> None:
    with pytest.raises(AmountError):
        parse_amount(CellError("#DIV/0!"))


def test_decimal_from_xlsx_passes_through() -> None:
    assert parse_amount(Decimal("12.5")) == Decimal("12.5")


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_pt_br_round_trip_in_cents(cents: int) -> None:
    text = pt_br(Decimal(cents).scaleb(-2))

    assert total_cents(parse_amount(text) or Decimal(0)) == cents


# ---------------------------------------------------------------------- centavos
def test_detail_accepts_two_decimals_and_float_noise() -> None:
    assert detail_cents(Decimal("1234.56")) == 123_456
    assert detail_cents(Decimal("1234.5600000000002")) == 123_456  # ruído do float do Excel
    assert detail_cents(Decimal(10)) == 1_000


@pytest.mark.parametrize("amount", ["0.001", "10.005", "0.6963"])
def test_detail_rejects_more_than_two_decimals(amount: str) -> None:
    with pytest.raises(AmountError):
        detail_cents(Decimal(amount))


def test_total_rounds_half_up_to_cents() -> None:
    assert total_cents(Decimal("1234.5099999999998")) == 123_451
    assert total_cents(Decimal("0.005")) == 1
    assert total_cents(Decimal("-0.005")) == -1


def test_amount_over_the_money_limit_is_refused() -> None:
    with pytest.raises(AmountError):
        total_cents(Decimal("1e20"))


# ---------------------------------------------------------------------- rótulos e meses
def test_normalize_label_ignores_accents_case_and_spaces() -> None:
    assert normalize_label("  Devolução   de crédito ") == "DEVOLUCAO DE CREDITO"
    assert normalize_label(Decimal(1)) == ""
    assert normalize_label(None) == ""


def test_display_label_keeps_original_text_without_controls() -> None:
    assert display_label("  Aluguel" + chr(0x200B) + "  da   sala ") == "Aluguel da sala"


@pytest.mark.parametrize(
    ("label", "expected"), [("-", True), ("=", True), ("", True), ("%", True), ("A", False)]
)
def test_separator_lines(label: str, expected: bool) -> None:
    assert is_separator(label) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("JANEIRO ", 1), ("março", 3), ("MAR", 3), ("Dez.", 12), ("Total", None), (None, None)],
)
def test_month_number(value: str | None, expected: int | None) -> None:
    assert month_number(value) == expected


# ---------------------------------------------------------------------- comentários
def test_comment_drops_the_author_line_added_by_excel() -> None:
    comment = CellComment("Autora Fictícia:\nDuas compras no mês.", "Autora Fictícia")

    assert clean_comment(comment) == "Duas compras no mês."


def test_comment_with_author_on_the_same_line() -> None:
    assert clean_comment(CellComment("Autora Fictícia: compra parcelada", "Autora Fictícia")) == (
        "compra parcelada"
    )


def test_comment_without_author_is_kept_and_cleaned() -> None:
    assert clean_comment(CellComment("  Nota" + chr(0x202E) + " fictícia  ")) == "Nota fictícia"
    assert clean_comment(None) == ""


def test_long_comment_is_truncated_to_fit_the_notes() -> None:
    cleaned = clean_comment(CellComment("x" * 5_000))

    assert len(cleaned) == MAX_COMMENT_LENGTH
    assert cleaned.endswith("…")


# ---------------------------------------------------------------------- chave da célula
def test_cell_key_is_stable_and_distinguishes_each_part() -> None:
    key = cell_key("perfil", 2026, 1, "impostos|DAS")

    assert key == cell_key("perfil", 2026, 1, "impostos|DAS")
    assert len(key) == 64 and key == key.lower()
    others = {
        cell_key("outro", 2026, 1, "impostos|DAS"),
        cell_key("perfil", 2025, 1, "impostos|DAS"),
        cell_key("perfil", 2026, 2, "impostos|DAS"),
        cell_key("perfil", 2026, 1, "impostos|FGTS"),
    }
    assert key not in others and len(others) == 4
