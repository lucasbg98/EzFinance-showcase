"""Leitura da matriz mensal sobre a planilha sintética com o layout completo (dados fictícios)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from appfin.domain.errors import ValidationError
from appfin.domain.spreadsheet_import.cash_flow_layout import CASH_FLOW_LAYOUT, CREDIT_REFUND
from appfin.domain.spreadsheet_import.grid import NO_CACHED_VALUE, CellError, CellValue, Sheet
from appfin.domain.spreadsheet_import.monthly_matrix import (
    Anchor,
    Block,
    IssueLevel,
    MatrixLayout,
    MatrixReading,
    MonthStatus,
    read_monthly_matrix,
)
from tests.spreadsheet_fixtures import CashFlowFixture, cash_flow_fixture

FIXTURE_ROWS = 106


def _read(fixture: CashFlowFixture) -> MatrixReading:
    return read_monthly_matrix(fixture.sheet(), CASH_FLOW_LAYOUT)


def _edit(fixture: CashFlowFixture, row: int, column: int, value: CellValue) -> Sheet:
    """Aba da fixture com uma célula trocada (``row`` 1 = primeira linha; ``column`` 0 = A)."""
    sheet = fixture.sheet()
    rows = [list(r) for r in sheet.rows]
    while len(rows[row - 1]) <= column:
        rows[row - 1].append(None)
    rows[row - 1][column] = value
    return Sheet(sheet.name, tuple(tuple(r) for r in rows), sheet.comments)


def _row_of(sheet: Sheet, label: str) -> int:
    return next(i for i, row in enumerate(sheet.rows, start=1) if len(row) > 1 and row[1] == label)


# ---------------------------------------------------------------------- caminho feliz
def test_full_layout_is_recognized_and_all_totals_match() -> None:
    fixture = cash_flow_fixture()

    reading = _read(fixture)

    assert len(fixture.sheet().rows) == FIXTURE_ROWS
    assert reading.is_valid, reading.issues
    assert len(reading.lines) == len(fixture.details) == 80
    assert len(reading.checks) == 10 * 12  # 10 linhas de total conferidas, mês a mês
    assert reading.months == (MonthStatus.REALIZED,) * 8 + (MonthStatus.PROJECTION,) * 4
    pending = sum(1 for line in reading.lines for cents in line.amounts[8:] if cents)
    assert pending == 28


def test_amounts_are_exact_cents_per_month() -> None:
    fixture = cash_flow_fixture()
    detail = fixture.detail("taxes", "CRO")

    line = next(line for line in _read(fixture).lines if line.label == "CRO")

    assert line.block == "impostos"
    assert list(line.amounts) == detail.cents
    assert line.row == 81


def test_credit_refund_is_subtracted_from_revenue_total() -> None:
    reading = _read(cash_flow_fixture())

    refund = next(line for line in reading.lines if line.key.endswith(CREDIT_REFUND))
    revenue_march = next(c for c in reading.checks if c.label == "RECEITA TOTAL" and c.month == 3)

    assert refund.sign == -1 and refund.amounts[2] == 12_345
    assert revenue_march.ok


def test_repeated_labels_get_the_owner_line_in_the_key() -> None:
    lines = [line for line in _read(cash_flow_fixture()).lines if line.block == "salarios"]

    thirteenth = [line for line in lines if line.label == "13º SALÁRIO"]

    assert [line.owner_label for line in thirteenth] == [
        "SALÁRIO AUXILIAR FICTÍCIA 1",
        "SALÁRIO AUXILIAR FICTÍCIA 2",
    ]
    assert len({line.key for line in lines}) == len(lines)
    assert thirteenth[0].key == "salarios|SALARIO AUXILIAR FICTICIA 1|13O SALARIO"


def test_keys_do_not_depend_on_row_position() -> None:
    """Inserir uma linha em branco antes do bloco não muda a chave das linhas."""
    fixture = cash_flow_fixture()
    sheet = fixture.sheet()
    rows = list(sheet.rows)
    rows.insert(20, (None, None))
    shifted = read_monthly_matrix(Sheet(sheet.name, tuple(rows)), CASH_FLOW_LAYOUT)

    assert [line.key for line in shifted.lines] == [line.key for line in _read(fixture).lines]
    assert shifted.is_valid


def test_comments_become_line_comments_without_author() -> None:
    reading = _read(cash_flow_fixture())

    commented = {
        (line.label, month): text
        for line in reading.lines
        for month, text in enumerate(line.comments, start=1)
        if text
    }

    assert commented == {
        ("CARTÃO CRÉDITO", 2): "Duas maquininhas no mês.",
        ("SÓCIA FICTÍCIA - GERAL", 5): "Repasse de pacientes da sócia\nreferente a abril e maio.",
        ("CRO", 3): "Anuidade com desconto.",
    }


def test_header_without_the_empty_column_a_is_found() -> None:
    sheet = cash_flow_fixture().sheet()
    without_a = Sheet(sheet.name, tuple(row[1:] for row in sheet.rows))

    reading = read_monthly_matrix(without_a, CASH_FLOW_LAYOUT)

    assert reading.is_valid
    assert len(reading.lines) == 80


def test_month_without_revenue_but_with_expenses_is_projection() -> None:
    fixture = cash_flow_fixture()
    for detail in fixture.block("revenue"):
        detail.cents[0] = 0

    statuses = _read(fixture).months

    assert statuses[0] is MonthStatus.PROJECTION


def test_month_without_values_is_empty() -> None:
    fixture = cash_flow_fixture()
    for detail in fixture.details:
        detail.cents[11] = 0

    assert _read(fixture).months[11] is MonthStatus.EMPTY


# ---------------------------------------------------------------------- conferência
def test_total_that_misses_a_line_fails_the_check() -> None:
    """Fórmula da planilha que não cobre a última linha (caso real da linha 25 em set a dez)."""
    fixture = cash_flow_fixture()
    sheet = fixture.sheet()
    misc_total_row = _row_of(sheet, "TOTAL DIVERSOS ")
    fixture.detail("misc", "AUXILIAR TEMPORÁRIA").cents[9] = 10_000
    stale_total = sheet.rows[misc_total_row - 1][2 + 9]  # total de outubro sem a linha nova

    reading = read_monthly_matrix(
        _edit(fixture, misc_total_row, 2 + 9, stale_total), CASH_FLOW_LAYOUT
    )

    failed = {(c.label, c.month) for c in reading.failed_checks}
    assert ("TOTAL DIVERSOS", 10) in failed
    assert not reading.is_valid


def test_total_without_cached_value_is_an_error() -> None:
    fixture = cash_flow_fixture()
    row = _row_of(fixture.sheet(), "TOTAL DE IMPOSTOS")

    reading = read_monthly_matrix(
        _edit(fixture, row, 2, CellError(NO_CACHED_VALUE)), CASH_FLOW_LAYOUT
    )

    assert any(issue.row == row and issue.month == 1 for issue in reading.errors)
    assert not reading.is_valid


def test_errors_in_indicator_rows_are_ignored() -> None:
    sheet = cash_flow_fixture().sheet()
    percent = sheet.rows[_row_of(sheet, "%") - 1]

    assert any(isinstance(value, CellError) for value in percent)  # #DIV/0! em set a dez
    assert read_monthly_matrix(sheet, CASH_FLOW_LAYOUT).errors == ()


# ---------------------------------------------------------------------- erros por célula
@pytest.mark.parametrize(
    ("value", "message"),
    [
        (Decimal("10.005"), "mais de 2 casas"),
        (Decimal("-5"), "negativo"),
        ("texto", "Valor inválido"),
        (CellError("#REF!"), "erro de fórmula"),
    ],
)
def test_invalid_detail_cell_blocks_the_import(value: CellValue, message: str) -> None:
    fixture = cash_flow_fixture()
    row = _row_of(fixture.sheet(), "ALUGUEL ")

    reading = read_monthly_matrix(_edit(fixture, row, 2 + 3, value), CASH_FLOW_LAYOUT)

    errors = [issue for issue in reading.errors if issue.row == row and issue.month == 4]
    assert errors and message in errors[0].message
    assert not reading.is_valid


def test_error_messages_never_repeat_cell_content() -> None:
    fixture = cash_flow_fixture()
    row = _row_of(fixture.sheet(), "ALUGUEL ")

    reading = read_monthly_matrix(_edit(fixture, row, 3, "CONTEUDO-SIGILOSO"), CASH_FLOW_LAYOUT)

    assert all("CONTEUDO-SIGILOSO" not in issue.message for issue in reading.issues)


def test_comment_on_empty_cell_is_a_warning() -> None:
    fixture = cash_flow_fixture()
    fixture.detail("taxes", "CRO").cents[2] = 0

    reading = _read(fixture)

    warnings = [issue for issue in reading.issues if issue.level is IssueLevel.WARNING]
    assert len(warnings) == 1 and warnings[0].month == 3
    assert reading.is_valid  # aviso não bloqueia


# ---------------------------------------------------------------------- estrutura
def test_missing_header_is_reported() -> None:
    reading = read_monthly_matrix(Sheet("Vazia", ((None, "nada aqui"),)), CASH_FLOW_LAYOUT)

    assert not reading.is_valid
    assert "meses" in reading.errors[0].message


def test_missing_anchor_is_reported() -> None:
    fixture = cash_flow_fixture()
    row = _row_of(fixture.sheet(), "INVESTIMENTOS ")

    reading = read_monthly_matrix(_edit(fixture, row, 1, "TOTAL INVESTIDO"), CASH_FLOW_LAYOUT)

    assert any("INVESTIMENTOS" in issue.message for issue in reading.errors)


def test_anchor_out_of_order_is_reported() -> None:
    fixture = cash_flow_fixture()
    sheet = fixture.sheet()
    rows = list(sheet.rows)
    receita = rows.pop(_row_of(sheet, "RECEITA TOTAL ") - 1)
    rows.insert(_row_of(sheet, "TOTAL DENTISTAS"), receita)

    reading = read_monthly_matrix(Sheet(sheet.name, tuple(rows)), CASH_FLOW_LAYOUT)

    assert not reading.is_valid
    assert any("fora da ordem" in issue.message for issue in reading.errors)


def test_values_in_a_row_without_label_are_an_error() -> None:
    fixture = cash_flow_fixture()
    row = _row_of(fixture.sheet(), "-")

    reading = read_monthly_matrix(_edit(fixture, row, 4, Decimal(10)), CASH_FLOW_LAYOUT)

    assert any(issue.row == row for issue in reading.errors)


def test_values_outside_a_known_block_are_an_error() -> None:
    fixture = cash_flow_fixture()
    sheet = fixture.sheet()
    rows = list(sheet.rows)
    position = _row_of(sheet, "MARGEM DE CONTRIBUIÇÃO ")  # entre a margem e o %: nenhum bloco
    rows.insert(position, (None, "LINHA SOLTA", Decimal(5)))

    reading = read_monthly_matrix(Sheet(sheet.name, tuple(rows)), CASH_FLOW_LAYOUT)

    assert any(issue.row == position + 1 for issue in reading.errors)


def test_layout_must_reference_known_blocks() -> None:
    with pytest.raises(ValidationError):
        MatrixLayout("x", "a", "a", (Block("a"),), (Anchor("TOTAL", checks=("b",)),))
