"""Planilha "matriz mensal": uma linha por item, uma coluna por mês (plano de importação §2 e §3).

Puro: recebe a grade (``Sheet``) e a estrutura esperada (``MatrixLayout``) e devolve as linhas de
detalhe com os valores em centavos, a situação de cada mês, a **conferência** dos totais da própria
planilha e a lista de problemas. Não decide categoria nem grava nada (isso é do caso de uso).

Como a estrutura é reconhecida:
- o cabeçalho é a linha com JANEIRO…DEZEMBRO; a coluna à esquerda de JANEIRO tem os rótulos;
- as **âncoras** são as linhas de total/indicador, procuradas pelo rótulo normalizado e na ordem
  do layout; cada âncora pode abrir um bloco (as linhas de detalhe seguintes pertencem a ele) e
  conferir a soma de blocos;
- o resto (com rótulo) é linha de detalhe do bloco aberto. Negrito e posição fixa não são usados.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from appfin.domain.errors import ValidationError
from appfin.domain.spreadsheet_import.grid import CellValue, Sheet
from appfin.domain.spreadsheet_import.parse import (
    AmountError,
    clean_comment,
    detail_cents,
    display_label,
    is_separator,
    month_number,
    normalize_label,
    parse_amount,
    total_cents,
)

MONTH_COUNT = 12
HEADER_SEARCH_ROWS = 30
MAX_ISSUES = 200


# ---------------------------------------------------------------------- layout (estrutura esperada)
@dataclass(frozen=True, slots=True)
class Block:
    """Grupo de linhas de detalhe. ``subtract``: rótulos (normalizados) que o total subtrai."""

    name: str
    subtract: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Anchor:
    """Linha estrutural, achada pelo rótulo normalizado. Nunca vira lançamento."""

    label: str
    opens: str | None = None  # bloco das linhas de detalhe seguintes (None = nenhum)
    checks: tuple[str, ...] = ()  # blocos cuja soma, mês a mês, deve ser igual a esta linha
    minus: tuple[str, ...] = ()  # blocos subtraídos nessa conta (ex.: lucro = receitas - custos)


@dataclass(frozen=True, slots=True)
class MatrixLayout:
    name: str
    first_block: str  # bloco aberto pelo cabeçalho dos meses
    revenue_block: str  # mês com valor > 0 neste bloco = mês realizado
    blocks: tuple[Block, ...]
    anchors: tuple[Anchor, ...]  # na ordem em que aparecem na planilha

    def __post_init__(self) -> None:
        names = [block.name for block in self.blocks]
        if len(set(names)) != len(names):
            raise ValidationError("blocks", "Bloco repetido no layout.")
        labels = [anchor.label for anchor in self.anchors]
        if len(set(labels)) != len(labels):
            raise ValidationError("anchors", "Âncora repetida no layout.")
        referenced = {self.first_block, self.revenue_block}
        for anchor in self.anchors:
            referenced.update(anchor.checks, anchor.minus)
            if anchor.minus and not anchor.checks:
                raise ValidationError("anchors", "Âncora que só subtrai blocos.")
            if anchor.opens is not None:
                referenced.add(anchor.opens)
        if not referenced <= set(names):
            raise ValidationError("blocks", "Layout cita um bloco inexistente.")

    def block(self, name: str) -> Block:
        return next(block for block in self.blocks if block.name == name)


# ---------------------------------------------------------------------- resultado
class MonthStatus(StrEnum):
    REALIZED = "realized"  # tem receita: lançamentos pagos
    PROJECTION = "projection"  # só despesas: lançamentos pendentes
    EMPTY = "empty"


class IssueLevel(StrEnum):
    ERROR = "error"  # bloqueia a importação
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    """Problema para a prévia. A mensagem nunca repete o conteúdo da célula."""

    level: IssueLevel
    message: str
    row: int | None = None  # número da linha na planilha (1 = primeira)
    month: int | None = None


@dataclass(frozen=True, slots=True)
class MatrixLine:
    """Linha de detalhe. ``amounts``/``comments``: 12 posições (jan…dez); 0 = sem valor."""

    row: int
    label: str  # rótulo original (para descrição e tela)
    key: str  # chave estável da linha: bloco + rótulo normalizado (+ linha "dona" se repetido)
    block: str
    owner_label: str  # rótulo da linha "dona" quando o rótulo se repete no bloco; senão ""
    sign: int  # -1 = a planilha subtrai esta linha do total do bloco
    amounts: tuple[int, ...]
    comments: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not any(self.amounts)


@dataclass(frozen=True, slots=True)
class TotalCheck:
    """Conferência de uma linha de total num mês: soma das linhas do app versus a planilha."""

    row: int
    label: str
    month: int
    expected_cents: int
    sheet_cents: int | None  # None = a célula do total tem erro

    @property
    def ok(self) -> bool:
        return self.sheet_cents == self.expected_cents


@dataclass(frozen=True, slots=True)
class MatrixReading:
    months: tuple[MonthStatus, ...] = ()
    lines: tuple[MatrixLine, ...] = ()
    checks: tuple[TotalCheck, ...] = ()
    issues: tuple[Issue, ...] = ()

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.level is IssueLevel.ERROR)

    @property
    def failed_checks(self) -> tuple[TotalCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    @property
    def is_valid(self) -> bool:
        """ "Sem erros" (P12): nenhum problema bloqueante e todos os totais conferem."""
        return bool(self.lines) and not self.errors and not self.failed_checks


# ---------------------------------------------------------------------- leitura
@dataclass
class _RawLine:
    row: int
    normalized: str
    label: str
    block: str
    amounts: list[int]
    comments: list[str]


@dataclass
class _Reader:
    sheet: Sheet
    layout: MatrixLayout
    issues: list[Issue] = field(default_factory=list)
    dropped: int = 0

    def issue(
        self, level: IssueLevel, message: str, row: int | None, month: int | None = None
    ) -> None:
        if len(self.issues) >= MAX_ISSUES:
            self.dropped += 1
            return
        self.issues.append(Issue(level, message, row, month))

    def error(self, message: str, row: int | None, month: int | None = None) -> None:
        self.issue(IssueLevel.ERROR, message, row, month)


def read_monthly_matrix(sheet: Sheet, layout: MatrixLayout) -> MatrixReading:
    reader = _Reader(sheet, layout)
    header = _find_header(sheet)
    if header is None:
        reader.error("Não encontrei a linha com os meses (JANEIRO a DEZEMBRO).", None)
        return MatrixReading(issues=tuple(reader.issues))
    header_row, label_column = header
    month_columns = tuple(range(label_column + 1, label_column + 1 + MONTH_COUNT))
    raw_lines, anchor_rows = _scan(reader, header_row, label_column, month_columns)
    lines = _build_lines(raw_lines, layout)
    checks = _check_totals(reader, anchor_rows, lines, month_columns)
    if reader.dropped:
        reader.issues.append(
            Issue(IssueLevel.ERROR, f"E mais {reader.dropped} problema(s) não listados.")
        )
    return MatrixReading(
        months=_month_statuses(lines, layout),
        lines=tuple(lines),
        checks=tuple(checks),
        issues=tuple(reader.issues),
    )


def _find_header(sheet: Sheet) -> tuple[int, int] | None:
    """(linha, coluna dos rótulos) do cabeçalho: 12 meses seguidos, na ordem."""
    for row_index, row in enumerate(sheet.rows[:HEADER_SEARCH_ROWS]):
        months = [month_number(value) for value in row]
        for column in range(1, len(row) - MONTH_COUNT + 1):
            if months[column : column + MONTH_COUNT] == list(range(1, MONTH_COUNT + 1)):
                return row_index, column - 1
    return None


def _scan(
    reader: _Reader, header_row: int, label_column: int, month_columns: tuple[int, ...]
) -> tuple[list[_RawLine], dict[str, int]]:
    layout = reader.layout
    anchor_labels = {anchor.label for anchor in layout.anchors}
    next_anchor = 0
    block: str | None = layout.first_block
    raw_lines: list[_RawLine] = []
    anchor_rows: dict[str, int] = {}
    for row_index in range(header_row + 1, len(reader.sheet.rows)):
        row_number = row_index + 1
        raw_label = reader.sheet.cell(row_index, label_column)
        normalized = normalize_label(raw_label)
        values = [reader.sheet.cell(row_index, column) for column in month_columns]
        expected = layout.anchors[next_anchor] if next_anchor < len(layout.anchors) else None
        if expected is not None and normalized == expected.label:
            anchor_rows[expected.label] = row_index
            block = expected.opens
            next_anchor += 1
            continue
        if normalized in anchor_labels:
            reader.error(
                "Linha de total fora da ordem esperada pelo modelo da planilha.", row_number
            )
            continue
        if not normalized or is_separator(normalized):
            if _has_values(values):
                reader.error("Linha sem rótulo com valores.", row_number)
            continue
        if block is None:
            if _has_values(values):
                reader.error(
                    "Linha com valores fora de um bloco conhecido da planilha.", row_number
                )
            continue
        raw_lines.append(
            _detail(reader, row_index, raw_label, normalized, block, values, month_columns)
        )
    for anchor in layout.anchors[next_anchor:]:
        reader.error(f'Não encontrei a linha "{anchor.label}" do modelo da planilha.', None)
    return raw_lines, anchor_rows


def _has_values(values: Iterable[CellValue]) -> bool:
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            amount = parse_amount(value)
        except AmountError:
            return True
        if amount:
            return True
    return False


def _detail(
    reader: _Reader,
    row_index: int,
    raw_label: CellValue,
    normalized: str,
    block: str,
    values: list[CellValue],
    month_columns: tuple[int, ...],
) -> _RawLine:
    row_number = row_index + 1
    amounts: list[int] = []
    comments: list[str] = []
    for month, (value, column) in enumerate(zip(values, month_columns, strict=True), start=1):
        cents = 0
        try:
            amount = parse_amount(value)
            if amount is not None:
                cents = detail_cents(amount)
        except AmountError as exc:
            reader.error(str(exc), row_number, month)
        if cents < 0:
            reader.error("Valor negativo numa linha de detalhe.", row_number, month)
            cents = 0
        comment = clean_comment(reader.sheet.comment(row_index, column))
        if comment and not cents:
            reader.issue(
                IssueLevel.WARNING, "Comentário em célula sem valor (ignorado).", row_number, month
            )
            comment = ""
        amounts.append(cents)
        comments.append(comment)
    return _RawLine(row_number, normalized, display_label(raw_label), block, amounts, comments)


def _build_lines(raw_lines: list[_RawLine], layout: MatrixLayout) -> list[MatrixLine]:
    """Chave estável: ``bloco|rótulo``; rótulo repetido no bloco ganha a linha "dona" anterior."""
    counts = Counter((raw.block, raw.normalized) for raw in raw_lines)
    owners: dict[str, _RawLine] = {}
    seen: Counter[str] = Counter()
    lines: list[MatrixLine] = []
    for raw in raw_lines:
        owner: _RawLine | None = None
        if counts[(raw.block, raw.normalized)] == 1:
            owners[raw.block] = raw
            key = f"{raw.block}|{raw.normalized}"
        else:
            owner = owners.get(raw.block)
            key = f"{raw.block}|{owner.normalized if owner else ''}|{raw.normalized}"
        seen[key] += 1
        if seen[key] > 1:
            key = f"{key}#{seen[key]}"
        sign = -1 if raw.normalized in layout.block(raw.block).subtract else 1
        lines.append(
            MatrixLine(
                row=raw.row,
                label=raw.label,
                key=key,
                block=raw.block,
                owner_label=owner.label if owner else "",
                sign=sign,
                amounts=tuple(raw.amounts),
                comments=tuple(raw.comments),
            )
        )
    return lines


def _check_totals(
    reader: _Reader,
    anchor_rows: dict[str, int],
    lines: list[MatrixLine],
    month_columns: tuple[int, ...],
) -> list[TotalCheck]:
    checks: list[TotalCheck] = []
    for anchor in reader.layout.anchors:
        row_index = anchor_rows.get(anchor.label)
        if not anchor.checks or row_index is None:
            continue
        members = [
            (1 if line.block in anchor.checks else -1, line)
            for line in lines
            if line.block in anchor.checks or line.block in anchor.minus
        ]
        for month, column in enumerate(month_columns, start=1):
            expected = sum(side * line.sign * line.amounts[month - 1] for side, line in members)
            sheet_cents: int | None
            try:
                amount = parse_amount(reader.sheet.cell(row_index, column))
                sheet_cents = 0 if amount is None else total_cents(amount)
            except AmountError:
                sheet_cents = None
                reader.error(
                    "Total sem valor calculado ou com erro (abra e salve a planilha no Excel).",
                    row_index + 1,
                    month,
                )
            checks.append(TotalCheck(row_index + 1, anchor.label, month, expected, sheet_cents))
    return checks


def _month_statuses(lines: list[MatrixLine], layout: MatrixLayout) -> tuple[MonthStatus, ...]:
    statuses: list[MonthStatus] = []
    for month in range(MONTH_COUNT):
        revenue = sum(
            line.amounts[month]
            for line in lines
            if line.block == layout.revenue_block and line.sign > 0
        )
        if revenue > 0:
            statuses.append(MonthStatus.REALIZED)
        elif any(line.amounts[month] for line in lines):
            statuses.append(MonthStatus.PROJECTION)
        else:
            statuses.append(MonthStatus.EMPTY)
    return tuple(statuses)
