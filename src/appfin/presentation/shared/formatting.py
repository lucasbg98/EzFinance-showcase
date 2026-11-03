"""Único módulo de formatação da interface (skill ``frontend-architecture``): moeda, datas,
documentos e telefones em pt-BR. Valores passam por aqui para respeitar "Ocultar valores".
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QObject, Signal

from appfin.br_format import (
    MONTHS,
    format_cents,
    format_date,
    format_document,
    format_phone,
    long_date,
    month_label,
)
from appfin.domain.errors import InvalidAmountError, ValidationError
from appfin.domain.money import MAX_ABS_CENTS, Money

HIDDEN_AMOUNT = "R$ •••••"

__all__ = [
    "HIDDEN_AMOUNT",
    "MONTHS",
    "ValuesVisibility",
    "format_cents",
    "format_date",
    "format_document",
    "format_money",
    "format_phone",
    "long_date",
    "month_label",
    "parse_money",
]


class ValuesVisibility(QObject):
    """Estado global do botão "Ocultar valores" (decisão D8)."""

    changed = Signal(bool)

    def __init__(self, hidden: bool = False) -> None:
        super().__init__()
        self._hidden = hidden

    @property
    def hidden(self) -> bool:
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        if hidden != self._hidden:
            self._hidden = hidden
            self.changed.emit(hidden)


def format_money(cents: int, visibility: ValuesVisibility | None = None) -> str:
    if visibility is not None and visibility.hidden:
        return HIDDEN_AMOUNT
    return format_cents(cents)


def parse_money(text: str, *, allow_negative: bool = False) -> int:
    """ "1.234,56" / "R$ 10" / "10,5" → centavos. Sem ``float``; rejeita mais de 2 casas."""
    cleaned = text.replace("R$", "").replace(" ", "").replace(chr(0xA0), "").strip()
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("-")
    if not cleaned or not all(ch.isdigit() or ch in ".," for ch in cleaned):
        raise ValidationError("amount", "Valor inválido.")
    if "," in cleaned:
        integer, _, fraction = cleaned.rpartition(",")
        cleaned = integer.replace(".", "") + "." + fraction
    else:
        cleaned = cleaned.replace(".", "")
    try:
        cents = Money.from_decimal(Decimal(cleaned)).cents
    except (InvalidOperation, ValueError, InvalidAmountError) as exc:
        raise ValidationError("amount", "Valor inválido.") from exc
    if negative:
        if not allow_negative:
            raise ValidationError("amount", "O valor não pode ser negativo.")
        cents = -cents
    if abs(cents) > MAX_ABS_CENTS:
        raise ValidationError("amount", "Valor acima do limite.")
    return cents
