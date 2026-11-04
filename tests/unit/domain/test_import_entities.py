"""Entidades da importação de planilha (dados fictícios)."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from appfin.domain.entities import (
    MAX_PROFILE_LINES,
    ImportBatch,
    ImportCounts,
    ImportProfile,
    ImportReplacement,
    Transaction,
)
from appfin.domain.enums import ImportSource, TransactionKind
from appfin.domain.errors import BusinessRuleError, ValidationError
from appfin.domain.money import Money

SHA = "0123456789abcdef" * 4
NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _tx(**changes: object) -> Transaction:
    base = Transaction(
        id="t1",
        kind=TransactionKind.EXPENSE,
        description="Aluguel",
        amount=Money(150_000),
        accrual_date=date(2026, 1, 31),
        due_date=date(2026, 1, 31),
        account_id="acc",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _batch(**changes: object) -> ImportBatch:
    base = ImportBatch("b1", "p1", ImportSource.XLSX, SHA, 2026, NOW)
    return replace(base, **changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- lançamento importado
def test_imported_transaction_keeps_batch_and_cell_key() -> None:
    transaction = _tx(import_batch_id="b1", import_row_key=SHA)

    assert (transaction.import_batch_id, transaction.import_row_key) == ("b1", SHA)


@pytest.mark.parametrize("key", ["", "A" * 64, "a" * 63, "g" * 64, SHA + "0"])
def test_cell_key_must_be_lowercase_sha256_hex(key: str) -> None:
    with pytest.raises(ValidationError) as error:
        _tx(import_batch_id="b1", import_row_key=key)
    assert error.value.field == "import_row_key"


def test_cell_key_requires_a_batch() -> None:
    with pytest.raises(ValidationError) as error:
        _tx(import_row_key=SHA)
    assert error.value.field == "import_row_key"


# ---------------------------------------------------------------------- perfil
def test_profile_cleans_name_and_freezes_line_map() -> None:
    source = {" receitas|aluguel ": "cat-1"}
    profile = ImportProfile("p1", "  Fluxo de caixa  ", line_map=source)
    source["outra"] = "cat-2"

    assert profile.name == "Fluxo de caixa"
    assert dict(profile.line_map) == {"receitas|aluguel": "cat-1"}
    with pytest.raises(TypeError):
        profile.line_map["nova"] = "cat-3"  # type: ignore[index]


@pytest.mark.parametrize(
    "line_map",
    [{"": "cat-1"}, {"linha": ""}, {"x" * 201: "cat-1"}],
)
def test_profile_rejects_invalid_lines(line_map: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as error:
        ImportProfile("p1", "Fluxo", line_map=line_map)
    assert error.value.field == "line_map"


def test_profile_limits_number_of_lines() -> None:
    too_many = {f"linha {n}": "cat" for n in range(MAX_PROFILE_LINES + 1)}

    with pytest.raises(ValidationError):
        ImportProfile("p1", "Fluxo", line_map=too_many)


def test_profile_requires_name() -> None:
    with pytest.raises(ValidationError):
        ImportProfile("p1", "   ")


# ---------------------------------------------------------------------- lote
@pytest.mark.parametrize(
    "changes",
    [
        {"file_sha256": "planilha.xlsx"},
        {"period_year": 1999},
        {"period_year": 2101},
        {"imported_at": datetime(2026, 11, 3, 12)},  # sem fuso  # noqa: DTZ001
        {"profile_id": ""},
    ],
)
def test_batch_rejects_invalid_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _batch(**changes)


def test_counts_must_not_be_negative() -> None:
    with pytest.raises(ValidationError) as error:
        ImportCounts(created=3, skipped=-1)
    assert error.value.field == "skipped"


def test_batch_can_be_undone_once() -> None:
    later = datetime(2026, 11, 4, tzinfo=UTC)

    undone = _batch().mark_undone(later)

    assert undone.is_undone and undone.undone_at == later
    assert not _batch().is_undone
    with pytest.raises(BusinessRuleError):
        undone.mark_undone(later)


# ---------------------------------------------------------------------- substituição
def test_replacement_can_be_a_removal() -> None:
    assert ImportReplacement("b1", "old").new_transaction_id is None


def test_replacement_cannot_point_to_itself() -> None:
    with pytest.raises(ValidationError):
        ImportReplacement("b1", "t1", "t1")
