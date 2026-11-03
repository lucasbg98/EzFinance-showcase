import pytest
from hypothesis import given
from hypothesis import strategies as st

from appfin.domain.amount_in_words import amount_in_words, integer_in_words
from appfin.domain.errors import InvalidAmountError


@pytest.mark.parametrize(
    ("cents", "words"),
    [
        (0, "zero reais"),
        (1, "um centavo"),
        (50, "cinquenta centavos"),
        (100, "um real"),
        (150, "um real e cinquenta centavos"),
        (1_000, "dez reais"),
        (2_101, "vinte e um reais e um centavo"),
        (10_000, "cem reais"),
        (10_100, "cento e um reais"),
        (123_456, "mil duzentos e trinta e quatro reais e cinquenta e seis centavos"),
        (100_000, "mil reais"),
        (110_000, "mil e cem reais"),
        (102_000, "mil e vinte reais"),
        (150_000, "mil e quinhentos reais"),
        (1_999_900, "dezenove mil novecentos e noventa e nove reais"),
        (10_000_000, "cem mil reais"),
        (100_000_000, "um milhão de reais"),
        (250_000_000, "dois milhões e quinhentos mil reais"),
        (100_100_000, "um milhão e mil reais"),
        (
            123_456_789_00,
            "cento e vinte e três milhões quatrocentos e cinquenta e seis mil setecentos e oitenta e nove reais",  # noqa: E501
        ),
        (1_000_000_000_00, "um bilhão de reais"),
    ],
)
def test_amount_in_words(cents: int, words: str) -> None:
    assert amount_in_words(cents) == words


@pytest.mark.parametrize(
    ("number", "words"),
    [
        (14, "quatorze"),
        (16, "dezesseis"),
        (90, "noventa"),
        (99, "noventa e nove"),
        (200, "duzentos"),
    ],
)
def test_integer_words(number: int, words: str) -> None:
    assert integer_in_words(number) == words


@pytest.mark.parametrize("cents", [-1, True, 1.5])
def test_invalid_values(cents: object) -> None:
    with pytest.raises(InvalidAmountError):
        amount_in_words(cents)  # type: ignore[arg-type]


@given(st.integers(min_value=0, max_value=10**13))
def test_always_produces_clean_text(cents: int) -> None:
    text = amount_in_words(cents)

    assert text and "  " not in text and not text.startswith(" ") and not text.endswith(" ")
    assert " e e " not in text and text.endswith(("real", "reais", "centavo", "centavos"))
