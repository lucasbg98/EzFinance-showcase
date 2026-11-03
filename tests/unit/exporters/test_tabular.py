"""CSV/Excel: formato brasileiro e proteção contra injeção de fórmula (dados fictícios)."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from appfin.application.export_table import ColumnKind, ExportColumn, ExportTable
from appfin.infrastructure.exporters.tabular import neutralize, to_csv, to_xlsx

TABLE = ExportTable(
    "Contas a receber: 03/2026",
    [
        ExportColumn("Vencimento", ColumnKind.DATE),
        ExportColumn("Descrição"),
        ExportColumn("Valor", ColumnKind.MONEY),
        ExportColumn("Qtde.", ColumnKind.INTEGER),
    ],
    [
        [date(2026, 3, 10), '=HYPERLINK("http://exemplo")', 123_456, 2],
        [date(2026, 3, 11), 'Canal; com "aspas"', -5, None],
        [None, "@SUM(A1)", 0, 1],
    ],
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+5", "'+5"),
        ("-2", "'-2"),
        ("@x", "'@x"),
        (chr(9) + "x", "'" + chr(9) + "x"),
        (chr(13) + "x", "'" + chr(13) + "x"),
        ("Tratamento", "Tratamento"),
        ("", ""),
    ],
)
def test_neutralize(text: str, expected: str) -> None:
    assert neutralize(text) == expected


def test_csv_is_excel_brazil_friendly() -> None:
    data = to_csv(TABLE)

    assert data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8-sig").split("\r\n")
    assert lines[0] == "Vencimento;Descrição;Valor;Qtde."
    assert lines[1] == '10/03/2026;"\'=HYPERLINK(""http://exemplo"")";1234,56;2'
    assert lines[2] == '11/03/2026;"Canal; com ""aspas""";-0,05;'
    assert lines[3] == ";'@SUM(A1);0,00;1"


def test_xlsx_keeps_text_as_text_and_numbers_as_numbers() -> None:
    sheet = load_workbook(io.BytesIO(to_xlsx(TABLE))).active
    assert sheet is not None

    assert sheet.title == "Contas a receber 032026"
    assert [c.value for c in sheet[1]] == ["Vencimento", "Descrição", "Valor", "Qtde."]
    formula_cell = sheet["B2"]
    assert formula_cell.data_type == "s" and formula_cell.value == '=HYPERLINK("http://exemplo")'
    assert sheet["B4"].data_type == "s"
    assert sheet["C2"].value == Decimal("1234.56") or sheet["C2"].value == 1234.56
    assert sheet["C2"].number_format.startswith('"R$"')
    assert sheet["A2"].value.date() == date(2026, 3, 10)
    assert sheet["D2"].value == 2 and sheet["D3"].value is None


def test_xlsx_has_no_formulas_anywhere() -> None:
    raw = to_xlsx(TABLE)
    import zipfile

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    assert b"<f>" not in sheet_xml and b"<f " not in sheet_xml


def test_rows_must_match_columns() -> None:
    with pytest.raises(ValueError, match="um valor por coluna"):
        ExportTable("x", [ExportColumn("a")], [["1", "2"]])


def test_percent_column_is_numeric_and_not_neutralized() -> None:
    table = ExportTable("DRE", [ExportColumn("%", ColumnKind.PERCENT)], [[-3765], [123], [None]])

    lines = to_csv(table).decode("utf-8-sig").split("\r\n")
    # Linha com um único campo vazio sai como '""' (o csv evita confundir com linha em branco).
    assert lines[1:4] == ["-376,5%", "12,3%", '""']
    sheet = load_workbook(io.BytesIO(to_xlsx(table))).active
    assert sheet is not None
    assert float(sheet["A2"].value) == -3.765 and sheet["A2"].number_format == "0.0%"
