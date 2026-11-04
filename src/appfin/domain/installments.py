"""Parcelamento: divisão exata em centavos + datas de vencimento.

- O resto em centavos vai para as primeiras parcelas (``Money.split``).
- Intervalo em **dias** (como no app de referência) ou em **meses** (mesmo dia do mês). Em meses,
  o dia é sempre calculado a partir do 1º vencimento: 31/01 → 28/02 → 31/03 (não "deriva"
  para o dia 28).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from appfin.domain.entities import MAX_INSTALLMENTS
from appfin.domain.enums import IntervalUnit
from appfin.domain.errors import ValidationError
from appfin.domain.money import Money


@dataclass(frozen=True, slots=True)
class PlannedInstallment:
    number: int
    amount: Money
    due_date: date


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def plan_installments(
    total: Money,
    count: int,
    first_due: date,
    unit: IntervalUnit = IntervalUnit.MONTH,
    interval: int = 1,
) -> list[PlannedInstallment]:
    if not 1 <= count <= MAX_INSTALLMENTS:
        raise ValidationError("count", f"Parcelas: de 1 a {MAX_INSTALLMENTS}.")
    if interval < 1:
        raise ValidationError("interval_value", "Intervalo inválido.")
    if not total.is_positive:
        raise ValidationError("amount", "Informe um valor maior que zero.")
    if total.cents < count:
        raise ValidationError("count", "Valor pequeno demais para tantas parcelas.")
    amounts = total.split(count)
    plan: list[PlannedInstallment] = []
    for index, amount in enumerate(amounts):
        if unit is IntervalUnit.MONTH:
            due = add_months(first_due, index * interval)
        else:
            due = first_due + timedelta(days=index * interval)
        plan.append(PlannedInstallment(index + 1, amount, due))
    return plan
