import pytest

from appfin.application.password_policy import MAX_LENGTH, assess_master_password


@pytest.mark.parametrize(
    "password",
    ["", "curta", "123456789012", "senhasenha123", "consultorio2026", "aaaaaaaaaaaaaaaa"],
)
def test_weak_passwords_are_rejected(password: str) -> None:
    assert not assess_master_password(password).is_acceptable


@pytest.mark.parametrize(
    "password",
    ["girassol trator piano nuvem", "Ventilador-Abacate-Rio-Marte-7"],
)
def test_strong_passphrases_are_accepted(password: str) -> None:
    result = assess_master_password(password)

    assert result.is_acceptable, result.problems
    assert result.score >= 3


def test_context_words_from_user_count_against_strength() -> None:
    weak = assess_master_password("SorrisoPerfeito2026", user_inputs=("SorrisoPerfeito",))

    assert not weak.is_acceptable


def test_leading_or_trailing_space_is_rejected() -> None:
    assert not assess_master_password(" girassol trator piano nuvem").is_acceptable


def test_overlong_password_is_rejected_without_analysis() -> None:
    assert not assess_master_password("x" * (MAX_LENGTH + 1)).is_acceptable
