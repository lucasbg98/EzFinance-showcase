"""Leitor seguro de planilhas: formatos, limites e arquivos hostis (tudo sintético)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from appfin.domain.enums import ImportSource
from appfin.domain.spreadsheet_import.cash_flow_layout import CASH_FLOW_LAYOUT
from appfin.domain.spreadsheet_import.grid import NO_CACHED_VALUE, CellError
from appfin.domain.spreadsheet_import.monthly_matrix import read_monthly_matrix
from appfin.domain.spreadsheet_import.parse import total_cents
from appfin.infrastructure.importers import safe_reader
from appfin.infrastructure.importers.safe_reader import SpreadsheetReadError, read_spreadsheet
from tests.spreadsheet_fixtures import COMMENT_AUTHOR, cash_flow_fixture, write_csv, write_xlsx

BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>\n'
)


@pytest.fixture
def xlsx(tmp_path: Path) -> Path:
    return write_xlsx(tmp_path / "fluxo.xlsx", cash_flow_fixture())


def _code(path: Path) -> str:
    with pytest.raises(SpreadsheetReadError) as error:
        read_spreadsheet(path)
    return error.value.code


def _rewrite(source: Path, target: Path, change: Callable[[str, bytes], bytes | None]) -> Path:
    """Copia o pacote trocando partes: ``change(nome, conteúdo)`` devolve o novo (None = remove)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            data = change(info.filename, old.read(info))
            if data is not None:
                new.writestr(info.filename, data)
    target.write_bytes(buffer.getvalue())
    return target


def _sheet_xml(name: str) -> bool:
    return name.startswith("xl/worksheets/sheet") and name.endswith(".xml")


def _in_cents(rows: tuple[tuple[object, ...], ...]) -> list[list[object]]:
    return [[total_cents(v) if isinstance(v, Decimal) else v for v in row] for row in rows]


# ---------------------------------------------------------------------- XLSX
def test_xlsx_values_are_exact_decimals_and_comments_are_read(xlsx: Path) -> None:
    fixture = cash_flow_fixture()
    expected_rows, expected_comments = fixture.grid()

    file = read_spreadsheet(xlsx)

    sheet = file.sheets[0]
    assert file.source is ImportSource.XLSX
    assert file.sha256 == hashlib.sha256(xlsx.read_bytes()).hexdigest()
    assert not file.has_macros
    assert sheet.name == "JAN26"
    # O openpyxl grava os totais com menos dígitos que o Excel: compara em centavos.
    assert _in_cents(sheet.rows) == _in_cents(safe_reader._trim(expected_rows))
    reading = read_monthly_matrix(sheet, CASH_FLOW_LAYOUT)
    expected = read_monthly_matrix(fixture.sheet(), CASH_FLOW_LAYOUT)
    assert reading.is_valid
    assert reading.lines == expected.lines  # detalhes exatos, com os comentários
    assert dict(sheet.comments) == expected_comments
    assert all(c.author == COMMENT_AUTHOR for c in sheet.comments.values())


def test_excel_errors_become_cell_errors(xlsx: Path) -> None:
    sheet = read_spreadsheet(xlsx).sheets[0]

    errors = [v for row in sheet.rows for v in row if isinstance(v, CellError)]

    assert errors and {e.code for e in errors} == {"#DIV/0!"}


def test_formula_without_cached_value_is_flagged(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Total", 1, 2, "=B1+C1"])
    path = tmp_path / "sem_cache.xlsx"
    workbook.save(path)

    row = read_spreadsheet(path).sheets[0].rows[0]

    assert row == ("Total", Decimal(1), Decimal(2), CellError(NO_CACHED_VALUE))


def test_formula_with_cached_value_reads_the_value(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Total", 1, 2, "=B1+C1"])
    source = tmp_path / "sem_cache.xlsx"
    workbook.save(source)

    def add_cache(name: str, data: bytes) -> bytes:
        if not _sheet_xml(name):
            return data
        return data.replace(b"<f>B1+C1</f><v />", b"<f>B1+C1</f><v>3</v>")

    path = _rewrite(source, tmp_path / "com_cache.xlsx", add_cache)

    assert read_spreadsheet(path).sheets[0].rows[0][3] == Decimal(3)


def test_xlsm_is_read_as_values_only_with_flag(xlsx: Path, tmp_path: Path) -> None:
    macro = tmp_path / "fluxo.xlsm"
    macro.write_bytes(xlsx.read_bytes())

    file = read_spreadsheet(macro)

    assert file.has_macros
    assert len(file.sheets[0].rows) == 106


def test_all_worksheets_are_listed_in_order(tmp_path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "JAN26"
    workbook.create_sheet("Rascunho").append(["x"])
    workbook.save(tmp_path / "abas.xlsx")

    file = read_spreadsheet(tmp_path / "abas.xlsx")

    assert [sheet.name for sheet in file.sheets] == ["JAN26", "Rascunho"]


def test_reading_never_changes_the_file(xlsx: Path) -> None:
    before = (xlsx.read_bytes(), xlsx.stat().st_mtime_ns)

    read_spreadsheet(xlsx)

    assert (xlsx.read_bytes(), xlsx.stat().st_mtime_ns) == before


# ---------------------------------------------------------------------- XLSX hostil
def test_zip_bomb_is_refused_before_parsing(xlsx: Path, tmp_path: Path) -> None:
    bomb = tmp_path / "bomba.xlsx"
    bomb.write_bytes(xlsx.read_bytes())
    with zipfile.ZipFile(bomb, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/media/zeros.bin", b"\0" * (safe_reader.MAX_UNCOMPRESSED_BYTES + 1))

    assert bomb.stat().st_size < safe_reader.MAX_XLSX_BYTES
    assert _code(bomb) == "zip_too_large"


@pytest.mark.parametrize("part", ["xl/styles.xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"])
def test_xml_bomb_is_refused(xlsx: Path, tmp_path: Path, part: str) -> None:
    def poison(name: str, data: bytes) -> bytes:
        if name != part:
            return data
        body = data.split(b"?>", 1)[-1]
        return BILLION_LAUGHS.encode() + body.replace(b">", b">&lol2;", 1)

    assert _code(_rewrite(xlsx, tmp_path / "bomba_xml.xlsx", poison)) == "xlsx_corrupted"


def test_xml_bomb_in_comments_is_refused(xlsx: Path, tmp_path: Path) -> None:
    def poison(name: str, data: bytes) -> bytes:
        if "comment" not in name or not name.endswith(".xml"):
            return data
        return BILLION_LAUGHS.encode() + data.split(b"?>", 1)[-1]

    assert _code(_rewrite(xlsx, tmp_path / "bomba_comentario.xlsx", poison)) == "xlsx_corrupted"


def test_external_entity_is_refused(xlsx: Path, tmp_path: Path) -> None:
    secret = tmp_path / "segredo.txt"
    secret.write_text("CONTEUDO-SECRETO", encoding="utf-8")

    def xxe(name: str, data: bytes) -> bytes:
        if not _sheet_xml(name):
            return data
        doctype = f'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>'
        body = data.split(b"?>", 1)[-1].replace(b"<t>", b"<t>&xxe;", 1)
        return doctype.encode() + body

    assert _code(_rewrite(xlsx, tmp_path / "xxe.xlsx", xxe)) == "xlsx_corrupted"


def test_corrupted_xlsx_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "quebrada.xlsx"
    path.write_bytes(b"PK\x03\x04" + b"lixo" * 100)

    assert _code(path) == "xlsx_corrupted"


def test_missing_workbook_part_is_refused(xlsx: Path, tmp_path: Path) -> None:
    def drop(name: str, data: bytes) -> bytes | None:
        return None if name == "xl/workbook.xml" else data

    assert _code(_rewrite(xlsx, tmp_path / "sem_workbook.xlsx", drop)) == "xlsx_corrupted"


def test_text_file_renamed_to_xlsx_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "texto.xlsx"
    path.write_text("não é planilha", encoding="utf-8")

    assert _code(path) == "xlsx_corrupted"


def test_xlsx_without_defusedxml_is_refused(xlsx: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import openpyxl.xml

    monkeypatch.setattr(openpyxl.xml, "DEFUSEDXML", False)

    assert _code(xlsx) == "defusedxml_missing"


def test_openpyxl_uses_defusedxml() -> None:
    import openpyxl.xml

    assert openpyxl.xml.DEFUSEDXML


def test_xlsx_with_too_many_rows_is_refused(xlsx: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_reader, "MAX_ROWS", 50)

    assert _code(xlsx) == "too_many_rows"


def test_xlsx_too_large_is_refused(xlsx: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_reader, "MAX_XLSX_BYTES", 1_000)

    assert _code(xlsx) == "file_too_large"


# ---------------------------------------------------------------------- formatos recusados
def test_old_xls_is_refused_by_extension_and_by_content(tmp_path: Path) -> None:
    by_name = tmp_path / "antiga.xls"
    by_name.write_bytes(b"qualquer coisa")
    disguised = tmp_path / "disfarcada.xlsx"
    disguised.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1") + b"\0" * 512)

    assert _code(by_name) == "xls_unsupported"
    assert _code(disguised) == "xls_unsupported"


@pytest.mark.parametrize("name", ["dados.txt", "dados.ods", "dados"])
def test_unknown_types_are_refused(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"a;b")

    assert _code(path) == "unsupported_type"


def test_empty_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "vazio.csv"
    path.write_bytes(b"")

    assert _code(path) == "file_empty"


def test_zip_named_csv_is_refused(xlsx: Path, tmp_path: Path) -> None:
    path = tmp_path / "planilha.csv"
    path.write_bytes(xlsx.read_bytes())

    assert _code(path) == "csv_is_zip"


# ---------------------------------------------------------------------- CSV
@pytest.mark.parametrize(
    ("encoding", "bom"), [("cp1252", False), ("utf-8", False), ("utf-8", True)]
)
def test_csv_encodings_give_the_same_grid(tmp_path: Path, encoding: str, bom: bool) -> None:
    path = write_csv(tmp_path / "fluxo.csv", cash_flow_fixture(), encoding=encoding, bom=bom)

    fixture = cash_flow_fixture()
    expected = read_monthly_matrix(fixture.sheet(), CASH_FLOW_LAYOUT)

    file = read_spreadsheet(path)

    sheet = file.sheets[0]
    assert file.source is ImportSource.CSV
    assert sheet.comments == {}  # CSV não tem comentários
    assert sheet.rows[0][:2] == (None, "JANEIRO ")  # a coluna A vazia não existe no CSV
    reading = read_monthly_matrix(sheet, CASH_FLOW_LAYOUT)
    assert reading.is_valid
    assert [(line.key, line.amounts) for line in reading.lines] == [
        (line.key, line.amounts) for line in expected.lines
    ]


def test_csv_with_nul_byte_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "nul.csv"
    path.write_bytes(b"a;b\x00;c\r\n")

    assert _code(path) == "nul_byte"


def test_csv_with_control_character_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "controle.csv"
    path.write_bytes(b"a;b\x1bc\r\n")

    assert _code(path) == "control_chars"


def test_csv_with_unknown_encoding_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "codificacao.csv"
    path.write_bytes(b"a;\x81\x8d\x8f\r\n")  # bytes indefinidos em cp1252 e inválidos em UTF-8

    assert _code(path) == "csv_encoding"


def test_malformed_csv_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "aspas.csv"
    path.write_bytes(b'a;"b"c;d\r\n')

    assert _code(path) == "csv_malformed"


def test_csv_limits(tmp_path: Path) -> None:
    rows = tmp_path / "linhas.csv"
    rows.write_bytes(b"x;1\r\n" * (safe_reader.MAX_ROWS + 1))
    columns = tmp_path / "colunas.csv"
    columns.write_bytes(b";" * safe_reader.MAX_COLUMNS + b"x\r\n")
    long_cell = tmp_path / "celula.csv"
    long_cell.write_bytes(b"a;" + b"x" * (safe_reader.MAX_CELL_CHARS + 1) + b"\r\n")

    assert _code(rows) == "too_many_rows"
    assert _code(columns) == "too_many_columns"
    assert _code(long_cell) == "cell_too_long"


def test_trailing_empty_rows_and_columns_are_trimmed(tmp_path: Path) -> None:
    path = tmp_path / "sobra.csv"
    path.write_bytes(b"a;1;;\r\n;;;\r\n" + b";;;\r\n" * (safe_reader.MAX_ROWS + 10))

    file = read_spreadsheet(path)

    assert file.sheets[0].rows == (("a", "1"),)


def test_control_characters_refused_are_exactly_c0_and_c1_except_tab_lf_cr() -> None:
    refused = {code for code in range(0x300) if safe_reader._CONTROL.search(chr(code))}
    expected = (set(range(0x20)) - {0x09, 0x0A, 0x0D}) | set(range(0x7F, 0xA0))

    assert refused == expected
