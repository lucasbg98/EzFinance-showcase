"""Value object de dinheiro.

Regra inegociável do projeto: dinheiro é sempre **centavos inteiros**; nunca ``float``.
``Decimal`` só é aceito na conversão de entrada (texto/planilha → centavos), e só se for exato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from appfin.domain.errors import CurrencyMismatchError, InvalidAmountError

DEFAULT_CURRENCY = "BRL"
# Teto de sanidade: R$ 100 bilhões em centavos. Evita valores absurdos vindos de importação.
MAX_ABS_CENTS = 10_000_000_000_000
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_CENTS_PER_UNIT = 100


@dataclass(frozen=True, slots=True)
class Money:
    """Quantia em centavos inteiros numa moeda ISO-4217."""

    cents: int
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        # bool é subclasse de int em Python; rejeitar explicitamente.
        if not isinstance(self.cents, int) or isinstance(self.cents, bool):
            raise InvalidAmountError("O valor deve ser um número inteiro de centavos.")
        if abs(self.cents) > MAX_ABS_CENTS:
            raise InvalidAmountError("Valor acima do limite permitido.")
        if not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise InvalidAmountError("Moeda inválida.")

    # ------------------------------------------------------------------ construção
    @classmethod
    def zero(cls, currency: str = DEFAULT_CURRENCY) -> Money:
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, amount: Decimal, currency: str = DEFAULT_CURRENCY) -> Money:
        """Converte um ``Decimal`` exato (no máximo 2 casas) em centavos, sem arredondar."""
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise InvalidAmountError("Valor decimal inválido.")
        try:
            cents_decimal = amount * _CENTS_PER_UNIT
            if cents_decimal != cents_decimal.to_integral_value():
                raise InvalidAmountError("O valor tem mais de duas casas decimais.")
            return cls(int(cents_decimal), currency)
        except InvalidOperation as exc:
            raise InvalidAmountError("Valor decimal inválido.") from exc

    # ------------------------------------------------------------------ consultas
    @property
    def is_zero(self) -> bool:
        return self.cents == 0

    @property
    def is_positive(self) -> bool:
        return self.cents > 0

    @property
    def is_negative(self) -> bool:
        return self.cents < 0

    # ------------------------------------------------------------------ aritmética
    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.cents, self.currency)

    def split(self, parts: int) -> list[Money]:
        """Divide em ``parts`` parcelas cuja soma é exatamente o total.

        O resto em centavos vai para as **primeiras** parcelas
        (R$ 100,00 em 3x → 33,34 + 33,33 + 33,33).
        """
        if isinstance(parts, bool) or not isinstance(parts, int) or parts < 1:
            raise InvalidAmountError("A quantidade de parcelas deve ser um inteiro maior que zero.")
        if self.cents < 0:
            raise InvalidAmountError("Não é possível parcelar um valor negativo.")
        base, remainder = divmod(self.cents, parts)
        return [
            Money(base + (1 if index < remainder else 0), self.currency) for index in range(parts)
        ]

    def _require_same_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError("Operação permitida apenas entre valores Money.")
        if other.currency != self.currency:
            raise CurrencyMismatchError("Operação entre moedas diferentes.")
