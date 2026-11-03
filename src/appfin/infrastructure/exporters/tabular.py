"""Exportação CSV e Excel (.xlsx) com proteção contra injeção de fórmula.

- CSV no padrão do Excel brasileiro: separador ";", UTF-8 com BOM, decimal com vírgula.
- Texto que começa com = + - @ TAB ou CR recebe "'" na frente no CSV (skill ``security`` §6).
- No .xlsx, todo texto é gravado explicitamente como **texto** (tipo "s"): nunca vira fórmula.
- Valores monetários são números de verdade no .xlsx (formato R$), datas são datas.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from appfin.application.export_table import Cell, ColumnKind, ExportTable
from appfin.br_format import format_date, format_percent_tenths

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_MONEY_FORMAT = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
_SHEET_TITLE_MAX = 31
# Caracteres proibidos em nome de aba do Excel (chr(92) é a barra invertida).
_FORBIDDEN_SHEET_CHARS = frozenset("[]:*?/") | {chr(92)}


def neutralize(text: str) -> str:
    return "'" + text if text.startswith(_DANGEROUS_PREFIXES) else text


def _money_text(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    return f"{sign}{units},{rest:02d}"


def _csv_cell(value: Cell, kind: ColumnKind) -> str:
    if value is None:
        return ""
    if kind is ColumnKind.MONEY and isinstance(value, int):
        return _money_text(value)
    if kind is ColumnKind.PERCENT and isinstance(value, int):
        return format_percent_tenths(value)
    if isinstance(value, date):
        return format_date(value)
    return neutralize(str(value))


def to_csv(table: ExportTable) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([neutralize(c.header) for c in table.columns])
    for row in table.rows:
        writer.writerow(
            [_csv_cell(value, col.kind) for value, col in zip(row, table.columns, strict=True)]
        )
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(table: ExportTable) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _safe_sheet_title(table.title)
    bold = Font(bold=True)
    for index, column in enumerate(table.columns, start=1):
        cell = sheet.cell(row=1, column=index)
        _set_text(cell, column.header)
        cell.font = bold
    for row_index, row in enumerate(table.rows, start=2):
        for col_index, (value, column) in enumerate(zip(row, table.columns, strict=True), start=1):
            cell = sheet.cell(row=row_index, column=col_index)
            if value is None:
                continue
            if column.kind is ColumnKind.MONEY and isinstance(value, int):
                cell.value = Decimal(value) / 100
                cell.number_format = _MONEY_FORMAT
            elif column.kind is ColumnKind.PERCENT and isinstance(value, int):
                cell.value = Decimal(value) / 1000
                cell.number_format = "0.0%"
            elif isinstance(value, date):
                cell.value = value
                cell.number_format = "DD/MM/YYYY"
            elif column.kind is ColumnKind.INTEGER and isinstance(value, int):
                cell.value = value
            else:
                _set_text(cell, str(value))
    for index, column in enumerate(table.columns, start=1):
        widest = max([len(column.header)] + [len(str(r[index - 1] or "")) for r in table.rows])
        sheet.column_dimensions[get_column_letter(index)].width = min(max(widest + 2, 10), 60)
    sheet.freeze_panes = "A2"
    workbook.properties.creator = "AppFinanceiro"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _set_text(cell: object, text: str) -> None:
    """Grava como texto literal: impede que "=..." seja interpretado como fórmula."""
    cell.value = text  # type: ignore[attr-defined]
    cell.data_type = "s"  # type: ignore[attr-defined]


def _safe_sheet_title(title: str) -> str:
    cleaned = "".join(ch for ch in title if ch not in _FORBIDDEN_SHEET_CHARS).strip()
    return (cleaned or "Planilha")[:_SHEET_TITLE_MAX]
