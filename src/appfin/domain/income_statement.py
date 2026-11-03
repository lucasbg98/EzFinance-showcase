"""DRE do consultório (skill ``dominio-consultorio``).

Entrada: totais já agregados no banco por grupo do DRE e direção (entrada/saída).
Cada grupo vale ``entradas - saídas`` (sinal real). Transferências nunca entram.
Lançamentos de categorias sem grupo aparecem em "Não classificados" e entram no resultado,
para o DRE sempre fechar com a soma das receitas e despesas do período.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from appfin.domain.enums import DreGroup
from appfin.domain.money import Money


class LineType(StrEnum):
    GROUP = "group"
    SUBTOTAL = "subtotal"
    RESULT = "result"


@dataclass(frozen=True, slots=True)
class StatementLine:
    label: str
    amount: Money
    line_type: LineType
    group: DreGroup | None = None


@dataclass(frozen=True, slots=True)
class GroupTotals:
    inflow_cents: int = 0
    outflow_cents: int = 0

    @property
    def net(self) -> Money:
        return Money(self.inflow_cents - self.outflow_cents)


UNCLASSIFIED = "unclassified"
_LABELS = {
    DreGroup.GROSS_REVENUE: "(+) Receita bruta",
    DreGroup.DEDUCTIONS: "(-) Deduções",
    DreGroup.TAXES: "(-) Impostos",
    DreGroup.DIRECT_COSTS: "(-) Custos diretos",
    DreGroup.OPERATING_EXPENSES: "(-) Despesas operacionais",
    DreGroup.SELLING_EXPENSES: "(-) Despesas comerciais",
    DreGroup.INVESTMENTS: "(-) Investimentos",
    DreGroup.OTHER_RESULTS: "(±) Resultado financeiro e diversos",
}


def build_income_statement(totals: Mapping[DreGroup | str, GroupTotals]) -> list[StatementLine]:
    def net(key: DreGroup | str) -> Money:
        return totals.get(key, GroupTotals()).net

    def line(group: DreGroup) -> StatementLine:
        return StatementLine(_LABELS[group], net(group), LineType.GROUP, group)

    gross = net(DreGroup.GROSS_REVENUE)
    net_revenue = gross + net(DreGroup.DEDUCTIONS) + net(DreGroup.TAXES)
    gross_profit = net_revenue + net(DreGroup.DIRECT_COSTS)
    operating = gross_profit + net(DreGroup.OPERATING_EXPENSES) + net(DreGroup.SELLING_EXPENSES)
    after_investments = operating + net(DreGroup.INVESTMENTS)
    unclassified = net(UNCLASSIFIED)
    result = after_investments + net(DreGroup.OTHER_RESULTS) + unclassified

    lines = [
        line(DreGroup.GROSS_REVENUE),
        line(DreGroup.DEDUCTIONS),
        line(DreGroup.TAXES),
        StatementLine("(=) Receita líquida", net_revenue, LineType.SUBTOTAL),
        line(DreGroup.DIRECT_COSTS),
        StatementLine("(=) Lucro bruto", gross_profit, LineType.SUBTOTAL),
        line(DreGroup.OPERATING_EXPENSES),
        line(DreGroup.SELLING_EXPENSES),
        StatementLine("(=) Resultado operacional", operating, LineType.SUBTOTAL),
        line(DreGroup.INVESTMENTS),
        StatementLine("(=) Resultado após investimentos", after_investments, LineType.SUBTOTAL),
        line(DreGroup.OTHER_RESULTS),
    ]
    if not unclassified.is_zero:
        lines.append(StatementLine("(±) Não classificados", unclassified, LineType.GROUP))
    lines.append(StatementLine("(=) Resultado do período", result, LineType.RESULT))
    return lines
