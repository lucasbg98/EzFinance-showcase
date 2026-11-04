"""Leitura segura de planilhas (CSV e XLSX) → ``SpreadsheetFile`` (grade de valores + comentários).

O arquivo é **não confiável** (skill ``security`` §6, plano de importação §8.2):
- limites de tamanho do arquivo, do conteúdo descompactado, de abas, linhas, colunas, células e
  comentários; bytes NUL e caracteres de controle são recusados;
- XLSX: ``openpyxl`` em ``read_only`` + ``data_only`` (só valores; fórmulas, macros e vínculos
  externos nunca são executados), com **defusedxml** obrigatório (XXE / "billion laughs");
  comentários e "fórmula sem valor calculado" vêm de uma leitura própria, também com defusedxml;
- o arquivo nunca é alterado; nada é gravado em disco; **nada daqui vai para log** (o nome do
  arquivo pode ter nome de pessoa: só o SHA-256 identifica o conteúdo).

Sem regra de negócio: conversão de valores e estrutura da planilha ficam no domínio.
"""

from __future__ import annotations

import csv
import hashlib
import io
import posixpath
import re
import zipfile
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

from appfin.domain.enums import ImportSource
from appfin.domain.spreadsheet_import.grid import (
    NO_CACHED_VALUE,
    CellComment,
    CellError,
    CellValue,
    Sheet,
    SpreadsheetFile,
)

MiB = 1024 * 1024
MAX_CSV_BYTES = 5 * MiB
MAX_XLSX_BYTES = 20 * MiB
MAX_UNCOMPRESSED_BYTES = 50 * MiB
MAX_ZIP_ENTRIES = 500
MAX_SHEETS = 20
MAX_ROWS = 5_000
MAX_COLUMNS = 50
MAX_CELL_CHARS = 1_000
MAX_COMMENT_CHARS = 5_000
MAX_COMMENTS = 5_000

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")  # .xls (Excel 97 a 2003) e outros formatos OLE
_EXCEL_ERRORS = frozenset(
    {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA"}
)
# Controles C0/C1 (exceto TAB, LF e CR): nunca aparecem numa planilha legítima. Definidos por
# código numérico, como em ``domain/validation.py`` (intervalos explícitos, sem caracteres soltos).
_CONTROL_RANGES = ((0x00, 0x08), (0x0B, 0x0C), (0x0E, 0x1F), (0x7F, 0x9F))
_CONTROL = re.compile(
    "[" + "".join(f"{re.escape(chr(a))}-{re.escape(chr(b))}" for a, b in _CONTROL_RANGES) + "]"
)
_CELL_REF = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")


class SpreadsheetReadError(Exception):
    """Arquivo recusado. ``message`` é amigável (tela); ``code`` é técnico (log), sem dados."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------- entrada
def read_spreadsheet(path: Path) -> SpreadsheetFile:
    """Lê ``.csv``, ``.xlsx`` ou ``.xlsm`` (só valores). ``.xls`` antigo é recusado."""
    suffix = path.suffix.lower()
    if suffix == ".xls":
        raise _old_excel()
    if suffix not in (".csv", ".xlsx", ".xlsm"):
        raise SpreadsheetReadError(
            "unsupported_type", "Formato não suportado. Use .xlsx (recomendado) ou .csv."
        )
    data = _read_limited(path, MAX_CSV_BYTES if suffix == ".csv" else MAX_XLSX_BYTES)
    if data.startswith(_OLE_MAGIC):
        raise _old_excel()
    if suffix == ".csv":
        if data.startswith(_ZIP_MAGIC):
            raise SpreadsheetReadError(
                "csv_is_zip", "O arquivo não é um CSV. Se for do Excel, salve como .xlsx."
            )
        return read_csv_bytes(data)
    return read_xlsx_bytes(data, has_macros=suffix == ".xlsm")


def _old_excel() -> SpreadsheetReadError:
    return SpreadsheetReadError(
        "xls_unsupported",
        "Formato .xls antigo não é suportado. Abra no Excel e salve como .xlsx.",
    )


def _read_limited(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise SpreadsheetReadError("open_failed", "Não foi possível abrir o arquivo.") from exc
    if len(data) > limit:
        raise SpreadsheetReadError(
            "file_too_large", f"Arquivo grande demais (máximo {limit // MiB} MB)."
        )
    if not data:
        raise SpreadsheetReadError("file_empty", "O arquivo está vazio.")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------- células
def _text_cell(text: str) -> CellValue:
    if _CONTROL.search(text):
        raise SpreadsheetReadError(
            "control_chars", "O arquivo tem caracteres inválidos (de controle) numa célula."
        )
    if len(text) > MAX_CELL_CHARS:
        raise SpreadsheetReadError(
            "cell_too_long", f"Uma célula passa de {MAX_CELL_CHARS} caracteres."
        )
    stripped = text.strip()
    if not stripped:
        return None
    if stripped in _EXCEL_ERRORS:
        return CellError(stripped)
    return text


def _trim(rows: list[list[CellValue]]) -> tuple[tuple[CellValue, ...], ...]:
    """Remove colunas vazias à direita de cada linha e linhas vazias no fim."""
    trimmed: list[tuple[CellValue, ...]] = []
    for row in rows:
        end = len(row)
        while end and row[end - 1] is None:
            end -= 1
        trimmed.append(tuple(row[:end]))
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return tuple(trimmed)


def _check_shape(row_number: int, row: list[CellValue]) -> list[CellValue]:
    """Aplica os limites de linhas e colunas (só conta o que tem conteúdo)."""
    has_content = any(value is not None for value in row)
    if row_number > MAX_ROWS and has_content:
        raise SpreadsheetReadError("too_many_rows", f"A planilha passa de {MAX_ROWS} linhas.")
    if any(value is not None for value in row[MAX_COLUMNS:]):
        raise SpreadsheetReadError(
            "too_many_columns", f"A planilha passa de {MAX_COLUMNS} colunas."
        )
    return row[:MAX_COLUMNS]


# ---------------------------------------------------------------------- CSV
def read_csv_bytes(data: bytes) -> SpreadsheetFile:
    """CSV do Excel pt-BR: separador ``;``; UTF-8 (com ou sem BOM) ou Windows-1252."""
    if b"\x00" in data:
        raise SpreadsheetReadError("nul_byte", "O arquivo não é um CSV de texto válido.")
    text = _decode(data)
    rows: list[list[CellValue]] = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
        for row_number, raw in enumerate(reader, start=1):
            row = _check_shape(row_number, [_text_cell(value) for value in raw])
            if row_number <= MAX_ROWS:
                rows.append(row)
    except csv.Error as exc:
        raise SpreadsheetReadError("csv_malformed", "O CSV está malformado.") from exc
    sheet = Sheet(name="CSV", rows=_trim(rows))
    return SpreadsheetFile(ImportSource.CSV, _sha256(data), (sheet,))


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        encodings: tuple[str, ...] = ("utf-8-sig",)
    else:
        encodings = ("utf-8", "cp1252")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SpreadsheetReadError(
        "csv_encoding", "Codificação do CSV não reconhecida (use UTF-8 ou o padrão do Excel)."
    )


# ---------------------------------------------------------------------- XLSX
def read_xlsx_bytes(data: bytes, *, has_macros: bool = False) -> SpreadsheetFile:
    _require_defusedxml()
    archive = _open_zip(data)
    try:
        parts = _sheet_parts(archive)
        workbook = _load_workbook(data)
        try:
            if any(name not in workbook.sheetnames for name, _part in parts):
                raise _corrupted()
            sheets = tuple(_read_sheet(archive, workbook[name], name, part) for name, part in parts)
        finally:
            workbook.close()
    finally:
        archive.close()
    if not sheets:
        raise SpreadsheetReadError("no_sheets", "A planilha não tem abas com dados.")
    return SpreadsheetFile(ImportSource.XLSX, _sha256(data), sheets, has_macros=has_macros)


def _require_defusedxml() -> None:
    """Sem defusedxml o openpyxl usaria o parser XML padrão: recusar em vez de arriscar."""
    import openpyxl.xml  # import tardio: openpyxl só carrega quando usado (skill performance)

    if not openpyxl.xml.DEFUSEDXML:
        raise SpreadsheetReadError(
            "defusedxml_missing", "Componente de segurança ausente: reinstale o aplicativo."
        )


def _open_zip(data: bytes) -> zipfile.ZipFile:
    if not data.startswith(_ZIP_MAGIC):
        raise _corrupted()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise _corrupted() from exc
    if len(entries) > MAX_ZIP_ENTRIES:
        archive.close()
        raise SpreadsheetReadError("zip_entries", "Planilha com estrutura inválida.")
    # Tamanhos declarados: o zipfile nunca entrega mais que isso (e confere o CRC).
    if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
        archive.close()
        raise SpreadsheetReadError(
            "zip_too_large", "Conteúdo da planilha grande demais depois de descompactado."
        )
    if any(entry.flag_bits & 0x1 for entry in entries):
        archive.close()
        raise SpreadsheetReadError(
            "zip_encrypted",
            "Planilha protegida por senha. Remova a senha no Excel e tente de novo.",
        )
    return archive


def _corrupted() -> SpreadsheetReadError:
    return SpreadsheetReadError(
        "xlsx_corrupted", "O arquivo .xlsx está corrompido ou não é do Excel."
    )


def _load_workbook(data: bytes) -> Any:
    import openpyxl

    try:
        return openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True, keep_links=False, keep_vba=False
        )
    except Exception as exc:  # arquivo hostil pode disparar qualquer erro do parser
        raise _corrupted() from exc


def _read_sheet(archive: zipfile.ZipFile, worksheet: Any, name: str, part: str) -> Sheet:
    rows: list[list[CellValue]] = []
    try:
        worksheet.reset_dimensions()  # não confiar na dimensão declarada no arquivo
        for row_number, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
            row = _check_shape(row_number, [_xlsx_value(value) for value in values])
            if row_number <= MAX_ROWS:
                rows.append(row)
    except SpreadsheetReadError:
        raise
    except Exception as exc:  # XML malformado/hostil dentro da aba
        raise _corrupted() from exc
    for row_index, column in _formulas_without_value(archive, part):
        if row_index < len(rows) and column < len(rows[row_index]):
            rows[row_index][column] = CellError(NO_CACHED_VALUE)
    comments = _comments(archive, part)
    return Sheet(name=_sheet_name(name), rows=_trim(rows), comments=comments)


def _sheet_name(name: str) -> str:
    if _CONTROL.search(name) or len(name) > 100:
        raise SpreadsheetReadError("sheet_name", "Nome de aba inválido.")
    return name


def _xlsx_value(value: object) -> CellValue:
    if value is None:
        return None
    if isinstance(value, bool):
        return _text_cell(str(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # repr = menor texto que volta ao mesmo float: o "ruído" fica visível e o domínio decide.
        decimal = Decimal(repr(value))
        if not decimal.is_finite():
            return CellError("#NUM!")
        return decimal
    if isinstance(value, str):
        return _text_cell(value)
    return _text_cell(str(value))  # datas/horas: texto (não são valores em reais)


# ---------------------------------------------------------------------- partes do pacote (XML)
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attribute(element: Any, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return str(value)
    return None


def _parse(archive: zipfile.ZipFile, part: str) -> Any:
    """XML de uma parte do pacote via defusedxml (sem DTD, sem entidades)."""
    from defusedxml import ElementTree  # import tardio

    try:
        with archive.open(part) as handle:
            return ElementTree.parse(handle, forbid_dtd=True).getroot()
    except KeyError as exc:
        raise _corrupted() from exc
    except Exception as exc:  # DTD/entidades proibidas, XML malformado, CRC inválido
        raise _corrupted() from exc


def _iter_elements(archive: zipfile.ZipFile, part: str) -> Iterator[Any]:
    from defusedxml import ElementTree

    try:
        with archive.open(part) as handle:
            for _event, element in ElementTree.iterparse(handle, events=("end",), forbid_dtd=True):
                yield element
    except KeyError as exc:
        raise _corrupted() from exc
    except SpreadsheetReadError:
        raise
    except Exception as exc:
        raise _corrupted() from exc


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """Id → (tipo, caminho da parte) do arquivo ``_rels`` de ``part``."""
    folder, file_name = posixpath.split(part)
    rels_part = posixpath.join(folder, "_rels", file_name + ".rels")
    if rels_part not in archive.namelist():
        return {}
    root = _parse(archive, rels_part)
    found: dict[str, tuple[str, str]] = {}
    for element in root:
        if _local(element.tag) != "Relationship" or element.get("TargetMode") == "External":
            continue
        target = element.get("Target", "")
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.join(folder, target)
        found[element.get("Id", "")] = (element.get("Type", ""), posixpath.normpath(resolved))
    return found


def _sheet_parts(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(nome da aba, parte XML) na ordem do arquivo, só abas de planilha."""
    workbook_part = "xl/workbook.xml"
    root = _parse(archive, workbook_part)
    relationships = _relationships(archive, workbook_part)
    parts: list[tuple[str, str]] = []
    for element in root.iter():
        if _local(element.tag) != "sheet":
            continue
        rel = relationships.get(_attribute(element, "id") or "")
        if rel is None or not rel[0].endswith("/worksheet"):
            continue  # gráfico, diálogo, macro…: ignorados
        parts.append((element.get("name", ""), rel[1]))
    if len(parts) > MAX_SHEETS:
        raise SpreadsheetReadError("too_many_sheets", f"A planilha passa de {MAX_SHEETS} abas.")
    return parts


def _cell_position(reference: str | None) -> tuple[int, int] | None:
    match = _CELL_REF.fullmatch(reference or "")
    if match is None:
        return None
    letters, digits = match.groups()
    column = 0
    for letter in letters:
        column = column * 26 + (ord(letter) - ord("A") + 1)
    return int(digits) - 1, column - 1


def _formulas_without_value(archive: zipfile.ZipFile, part: str) -> list[tuple[int, int]]:
    """Células com fórmula salva sem o valor calculado (arquivo gerado fora do Excel)."""
    missing: list[tuple[int, int]] = []
    for element in _iter_elements(archive, part):
        if _local(element.tag) != "c":
            continue
        names = {_local(child.tag) for child in element}
        has_value = any(_local(child.tag) == "v" and child.text for child in element)
        if "f" in names and not has_value:
            position = _cell_position(element.get("r"))
            if position is not None:
                missing.append(position)
        element.clear()
    return missing


def _comments(archive: zipfile.ZipFile, sheet_part: str) -> dict[tuple[int, int], CellComment]:
    found: dict[tuple[int, int], CellComment] = {}
    for kind, comments_part in _relationships(archive, sheet_part).values():
        if not kind.endswith("/comments") or comments_part not in archive.namelist():
            continue
        root = _parse(archive, comments_part)
        authors = [
            "".join(author.itertext()) for author in root.iter() if _local(author.tag) == "author"
        ]
        for comment in root.iter():
            if _local(comment.tag) != "comment":
                continue
            if len(found) >= MAX_COMMENTS:
                raise SpreadsheetReadError(
                    "too_many_comments", "A planilha tem comentários demais."
                )
            position = _cell_position(comment.get("ref"))
            if position is None:
                continue
            text = _comment_text(comment)
            author_id = comment.get("authorId", "")
            author = (
                authors[int(author_id)]
                if author_id.isdigit() and int(author_id) < len(authors)
                else ""
            )
            found[position] = CellComment(text=text, author=_comment_part(author))
    return found


def _comment_text(comment: Any) -> str:
    """Texto do comentário: ``<text><t/></text>`` ou trechos ``<r><t/></r>``; ignora ``rPh``."""
    pieces: list[str] = []
    for body in comment:
        if _local(body.tag) != "text":
            continue
        for node in body:
            name = _local(node.tag)
            if name == "t":
                pieces.append(node.text or "")
            elif name == "r":
                pieces.extend(t.text or "" for t in node if _local(t.tag) == "t")
    return _comment_part("".join(pieces))


def _comment_part(text: str) -> str:
    if _CONTROL.search(text.replace("\r", "")):
        raise SpreadsheetReadError("control_chars", "Comentário com caracteres inválidos.")
    if len(text) > MAX_COMMENT_CHARS:
        raise SpreadsheetReadError(
            "comment_too_long", f"Um comentário passa de {MAX_COMMENT_CHARS} caracteres."
        )
    return text
