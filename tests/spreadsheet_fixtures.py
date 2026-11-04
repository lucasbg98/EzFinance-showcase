"""Planilha "Fluxo de caixa" **sintética** com o layout completo (106 linhas) para os testes.

Rótulos, valores e comentários são inventados (nunca dados reais: CLAUDE.md). A estrutura segue a
planilha do consultório (plano de importação §2.3): coluna A vazia, rótulos na B, meses de C a N;
totais calculados como o Excel faria (soma de ``float``, com o ruído de ponto flutuante); jan a ago
realizados (com receita) e set a dez só com algumas despesas fixas (projeção).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from appfin.domain.spreadsheet_import.grid import CellComment, CellError, CellValue, Sheet

MONTH_HEADERS = (
    "JANEIRO ",
    "FEVEREIRO",
    "MARÇO",
    "ABRIL",
    "MAIO",
    "JUNHO",
    "JULHO",
    "AGOSTO",
    "SETEMBRO",
    "OUTUBRO",
    "NOVEMBRO",
    "DEZEMBRO",
)
REALIZED_MONTHS = range(8)  # índices 0..7 = jan..ago
LABEL_COLUMN = 1  # coluna B
FIRST_MONTH_COLUMN = 2
COMMENT_AUTHOR = "Autora Fictícia"

# (bloco, rótulo do total que abre o bloco ou None, rótulos de detalhe)
REVENUE_LABELS = (
    "DISTRIBUIÇÃO DE SOBRAS",
    "CHEQUES À VISTA",
    "CHEQUES A PRAZO",
    "CARTÃO CRÉDITO",
    "CARTÃO DÉBITO",
    "DINHEIRO",
    "PIX / DOC",
    "ESTORNOS E DIVERSOS",
    "RECEBIDOS SÓCIA FICTÍCIA",
    "DEVOLUÇÃO DE CRÉDITO",
)
DENTIST_LABELS = ("DENTISTA FICTÍCIA A", "DENTISTA FICTÍCIO B", "DENTISTA FICTÍCIA C")
PROSTHETIC_LABELS = tuple(f"LABORATÓRIO FICTÍCIO {n}" for n in range(1, 7))
MISC_LABELS = (
    "TÁXI ENCOMENDA",
    "CORREIOS",
    "SUPERMERCADO",
    "PAPELARIA",
    "GRÁFICA",
    "CONFRATERNIZAÇÕES",
    "SÓCIA FICTÍCIA - GERAL",
    "UTILIDADES",
    "AUXILIAR TEMPORÁRIA",
)
SUPPLY_LABELS = tuple(f"FORNECEDOR FICTÍCIO {n}" for n in range(1, 13))
FIXED_LABELS = (
    "ALUGUEL ",
    "CONDOMÍNIO",
    "DESCARTE DE LIXO",
    "INTERNET",
    "TELEFONE FIXO",
    "TELEFONE MÓVEL",
    "MARKETING",
    "CONSERTOS E MANUTENÇÃO",
    "SOFTWARE",
)
SALARY_LABELS = (
    "SALÁRIO AUXILIAR FICTÍCIA 1",
    "13º SALÁRIO",
    "FÉRIAS / 1/3 FÉRIAS",
    "SALÁRIO AUXILIAR FICTÍCIA 2",
    "13º SALÁRIO",
    "FÉRIAS / 1/3 FÉRIAS",
    "VALE-TRANSPORTE",
    "PRÓ-LABORE SÓCIA FICTÍCIA",
)
TAX_LABELS = (
    "DARF",
    "DAS / SIMPLES",
    "FGTS",
    "GPS",
    "CONTADOR",
    "IMPOSTO DE RENDA FÍSICA",
    "PGRSS",
    "CONSELHO DE ENGENHARIA",
    "RECEITA FEDERAL",
    "ATESTADO / PCMSO",
    "CRO",
    "TAXAS PREFEITURA",
    "TARIFAS BANCÁRIAS",
    "TARIFA CARTÃO DE CRÉDITO",
    "ALUGUEL MÁQUINA DE CARTÃO",
    "SENSOR",
)
INVESTMENT_LABELS = (
    "AQUISIÇÕES DIVERSAS",
    "REFORMAS ESTRUTURAIS",
    "KITS PACIENTES",
    "CURSOS",
    "UNIFORMES",
)
# Despesas fixas com valor também em set a dez (projeção): (bloco, rótulo)
PROJECTED = {
    ("fixed", "ALUGUEL "),
    ("fixed", "DESCARTE DE LIXO"),
    ("fixed", "INTERNET"),
    ("fixed", "SOFTWARE"),
    ("salaries", "SALÁRIO AUXILIAR FICTÍCIA 1"),
    ("salaries", "SALÁRIO AUXILIAR FICTÍCIA 2"),
    ("taxes", "ALUGUEL MÁQUINA DE CARTÃO"),
}


@dataclass
class Detail:
    block: str
    label: str
    cents: list[int]  # 12 meses


@dataclass
class CashFlowFixture:
    """Linhas de detalhe editáveis; ``grid()`` monta a aba com os totais calculados."""

    details: list[Detail]
    comments: dict[tuple[str, int, int], str] = field(default_factory=dict)  # (bloco, ordem, mês)

    def detail(self, block: str, label: str, occurrence: int = 1) -> Detail:
        found = [d for d in self.details if d.block == block and d.label == label]
        return found[occurrence - 1]

    def block(self, block: str) -> list[Detail]:
        return [d for d in self.details if d.block == block]

    # ------------------------------------------------------------------ montagem
    def grid(self) -> tuple[list[list[CellValue]], dict[tuple[int, int], CellComment]]:
        rows: list[list[CellValue]] = []
        comments: dict[tuple[int, int], CellComment] = {}
        totals: dict[str, list[float]] = {}

        def add(label: str | None, values: list[CellValue] | None = None) -> int:
            rows.append([None, label, *(values or [None] * 12)])
            return len(rows) - 1

        def add_block(block: str, *, gap: bool = False) -> None:
            for order, detail in enumerate(self.block(block)):
                if gap and order:
                    add(None)  # linha em branco entre os itens (como na planilha)
                row = add(detail.label, [_amount(c) for c in detail.cents])
                for month in range(12):
                    text = self.comments.get((block, order, month))
                    if text:
                        comments[(row, FIRST_MONTH_COLUMN + month)] = CellComment(
                            f"{COMMENT_AUTHOR}:\n{text}", COMMENT_AUTHOR
                        )

        def total(block: str, sign_of: dict[str, int] | None = None) -> list[float]:
            sums = [0.0] * 12
            for detail in self.block(block):
                sign = (sign_of or {}).get(detail.label, 1)
                for month, cents in enumerate(detail.cents):
                    sums[month] += sign * cents / 100  # soma de float, como o Excel
            totals[block] = sums
            return sums

        def total_of(detail: Detail) -> list[float]:
            return [cents / 100 for cents in detail.cents]

        def plus(*parts: list[float]) -> list[float]:
            return [sum(values) for values in zip(*parts, strict=True)]

        def minus(a: list[float], b: list[float]) -> list[float]:
            return [x - y for x, y in zip(a, b, strict=True)]

        rows.append([None, None, *MONTH_HEADERS])
        add_block("revenue")
        revenue = total("revenue", {"DEVOLUÇÃO DE CRÉDITO": -1})
        add("RECEITA TOTAL ", _floats(revenue))
        add("-")
        variable = []
        for block, label in (
            ("dentists", "TOTAL DENTISTAS"),
            ("prosthetics", "TOTAL PROTÉTICOS"),
            ("misc", "TOTAL DIVERSOS "),
            ("supplies", "TOTAL MATERIAL ODONTOLOGICO"),
        ):
            sums = total(block)
            variable.append(sums)
            add(label, _floats(sums))
            add_block(block)
        variable_total = plus(*variable)
        add("CUSTOS VARIÁVEIS ", _floats(variable_total))
        add("=")
        margin = minus(revenue, variable_total)
        add("MARGEM DE CONTRIBUIÇÃO ", _floats(margin))
        add("%", [_ratio(m, r) for m, r in zip(margin, revenue, strict=True)])
        add_block("fixed")
        fixed = total("fixed")
        salaries = total("salaries")
        add("TOTAL SALÁRIOS", _floats(salaries))
        add_block("salaries")
        taxes = total("taxes")
        add("TOTAL DE IMPOSTOS", _floats(taxes))
        add_block("taxes")
        fixed_total = plus(fixed, salaries, taxes)
        add("CUSTOS FIXOS ", _floats(fixed_total))
        add(None)
        before_investments = minus(margin, fixed_total)
        add("LUCRO ANTES DOS INVESTIMENTOS ", _floats(before_investments))
        add(None)
        add_block("investments")
        investments = total("investments")
        add("INVESTIMENTOS ", _floats(investments))
        add(None)
        operating = minus(before_investments, investments)
        add("LUCRO OPERACIONAL ", _floats(operating))
        add(None)
        add_block("non_operating", gap=True)
        add(None)
        entries, exits = (total_of(d) for d in self.block("non_operating"))
        add("LUCRO TOTAL FINAL ", _floats(minus(plus(operating, entries), exits)))
        add(None)
        add("PONTO DE EQUILIBRIO", [_ratio(f, 1.0) for f in fixed_total])
        return rows, comments

    def sheet(self, name: str = "JAN26") -> Sheet:
        rows, comments = self.grid()
        return Sheet(name, tuple(tuple(row) for row in rows), comments)


def _amount(cents: int) -> CellValue:
    return Decimal(cents).scaleb(-2) if cents else None


def _floats(values: list[float]) -> list[CellValue]:
    return [Decimal(repr(value)) if value else None for value in values]


def _ratio(numerator: float, denominator: float) -> CellValue:
    return CellError("#DIV/0!") if not denominator else Decimal(repr(numerator / denominator))


def cash_flow_fixture(seed: int = 2026) -> CashFlowFixture:
    rng = random.Random(seed)  # noqa: S311 - dados sintéticos, sem uso de segurança
    details: list[Detail] = []
    blocks = (
        ("revenue", REVENUE_LABELS),
        ("dentists", DENTIST_LABELS),
        ("prosthetics", PROSTHETIC_LABELS),
        ("misc", MISC_LABELS),
        ("supplies", SUPPLY_LABELS),
        ("fixed", FIXED_LABELS),
        ("salaries", SALARY_LABELS),
        ("taxes", TAX_LABELS),
        ("investments", INVESTMENT_LABELS),
        ("non_operating", ("ENTRADAS NÃO OPERACIONAIS ", "SAÍDAS NÃO OPERACIONAIS ")),
    )
    for block, labels in blocks:
        for label in labels:
            cents = [0] * 12
            for month in range(12):
                realized = month in REALIZED_MONTHS
                if (realized and rng.random() < 0.6) or (
                    not realized and (block, label) in PROJECTED
                ):
                    cents[month] = rng.randint(100, 900_000)
            details.append(Detail(block, label, cents))
    fixture = CashFlowFixture(details)
    fixture.detail("revenue", "DEVOLUÇÃO DE CRÉDITO").cents = [0, 0, 12_345] + [0] * 9
    fixture.detail("misc", "AUXILIAR TEMPORÁRIA").cents[8:] = [0, 0, 0, 0]
    for block, label, month, text in (
        ("revenue", "CARTÃO CRÉDITO", 1, "Duas maquininhas no mês."),
        (
            "misc",
            "SÓCIA FICTÍCIA - GERAL",
            4,
            "Repasse de pacientes da sócia\nreferente a abril e maio.",
        ),
        ("taxes", "CRO", 2, "Anuidade com desconto."),
    ):
        detail = fixture.detail(block, label)
        if not detail.cents[month]:
            detail.cents[month] = 50_000
        order = fixture.block(block).index(detail)
        fixture.comments[(block, order, month)] = text
    return fixture


# ---------------------------------------------------------------------- arquivos
def write_xlsx(path: Path, fixture: CashFlowFixture, *, sheet_title: str = "JAN26") -> Path:
    from openpyxl import Workbook
    from openpyxl.comments import Comment

    rows, comments = fixture.grid()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title
    for row_index, row in enumerate(rows):
        for column, value in enumerate(row):
            if value is None:
                continue
            cell = sheet.cell(row_index + 1, column + 1)
            if isinstance(value, Decimal):
                cell.value = float(value)
            elif isinstance(value, CellError):
                cell.value = value.code
                cell.data_type = "e"
            else:
                cell.value = value
    for (row_index, column), comment in comments.items():
        sheet.cell(row_index + 1, column + 1).comment = Comment(comment.text, comment.author)
    workbook.save(path)
    return path


def pt_br(value: CellValue) -> str:
    """Como o Excel pt-BR exporta o formato contábil para CSV."""
    if value is None:
        return ""
    if isinstance(value, CellError):
        return value.code
    if isinstance(value, str):
        return value
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not rounded:
        return "R$ -"
    sign = "-" if rounded < 0 else ""
    integer, cents = f"{abs(rounded):.2f}".split(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    return f"{sign}R$ {grouped},{cents}"


def write_csv(
    path: Path, fixture: CashFlowFixture, *, encoding: str = "cp1252", bom: bool = False
) -> Path:
    """CSV ``;`` sem a coluna A vazia (o Excel a descarta ao exportar)."""
    rows, _comments = fixture.grid()
    with path.open("w", encoding="utf-8-sig" if bom else encoding, newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\r\n")
        for row in rows:
            writer.writerow([pt_br(value) for value in row[1:]])
    return path
