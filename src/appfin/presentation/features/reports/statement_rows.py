"""Linhas exibidas no DRE: grupos, subtotais e, nos grupos expandidos, as categorias.

Sem Qt: testável isoladamente. Os valores vêm do caso de uso; aqui só se decide o que aparece.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from appfin.application.read_models import StatementCategoryTotal
from appfin.domain.enums import DreGroup
from appfin.domain.income_statement import LineType, StatementLine
from appfin.domain.money import Money

NO_CATEGORY = "(sem categoria)"


class RowStyle(StrEnum):
    GROUP = LineType.GROUP.value
    SUBTOTAL = LineType.SUBTOTAL.value
    RESULT = LineType.RESULT.value
    CATEGORY = "category"


GroupKey = DreGroup | str


@dataclass(frozen=True, slots=True)
class StatementRow:
    label: str
    amount: Money
    style: RowStyle
    group: GroupKey | None = None
    category_id: str | None = None
    count: int | None = None
    expandable: bool = False
    expanded: bool = False


def build_statement_rows(
    lines: Sequence[StatementLine],
    details: Sequence[StatementCategoryTotal],
    expanded: Collection[GroupKey],
) -> list[StatementRow]:
    by_group: dict[GroupKey, list[StatementCategoryTotal]] = defaultdict(list)
    for detail in details:
        by_group[detail.group].append(detail)
    rows: list[StatementRow] = []
    for line in lines:
        children = by_group.get(line.group, []) if line.group is not None else []
        is_open = bool(children) and line.group in expanded
        rows.append(
            StatementRow(
                line.label,
                line.amount,
                RowStyle(line.line_type.value),
                group=line.group,
                expandable=bool(children),
                expanded=is_open,
            )
        )
        if is_open:
            rows.extend(_category_rows(children))
    return rows


def _category_rows(children: list[StatementCategoryTotal]) -> list[StatementRow]:
    names = Counter(child.category_name for child in children)
    ordered = sorted(children, key=lambda c: (-abs(c.net_cents), c.category_name or ""))
    return [
        StatementRow(
            _category_label(child, repeated=names[child.category_name] > 1),
            Money(child.net_cents),
            RowStyle.CATEGORY,
            group=child.group,
            category_id=child.category_id,
            count=child.count,
        )
        for child in ordered
    ]


def _category_label(child: StatementCategoryTotal, *, repeated: bool) -> str:
    name = child.category_name or NO_CATEGORY
    if repeated and child.group_name:
        return f"{name} ({child.group_name})"
    return name
