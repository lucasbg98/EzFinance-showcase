"""Valor por extenso em português do Brasil (para recibos).

Regras: "cem" sozinho e "cento" com complemento; "mil" sem "um"; "e" entre centenas, dezenas e
unidades; entre grupos, "e" só quando o último grupo é menor que 100 ou centena exata
("mil e cem", "mil e vinte", mas "mil duzentos e trinta"); "de reais" após milhão/bilhão exatos.
"""

from __future__ import annotations

from appfin.domain.errors import InvalidAmountError
from appfin.domain.money import MAX_ABS_CENTS

_UNITS = (
    "zero",
    "um",
    "dois",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
)
_TENS = (
    "",
    "",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
)
_HUNDREDS = (
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
)
_SCALES = (("bilhão", "bilhões"), ("milhão", "milhões"), ("mil", "mil"), ("", ""))


def _below_thousand(number: int) -> str:
    if number == 100:
        return "cem"
    hundreds, rest = divmod(number, 100)
    parts = []
    if hundreds:
        parts.append(_HUNDREDS[hundreds])
    if rest:
        if rest < 20:
            parts.append(_UNITS[rest])
        else:
            tens, units = divmod(rest, 10)
            parts.append(_TENS[tens] + (f" e {_UNITS[units]}" if units else ""))
    return " e ".join(parts)


def integer_in_words(number: int) -> str:
    if number < 0:
        raise InvalidAmountError("Valor negativo não tem extenso.")
    if number == 0:
        return "zero"
    groups: list[int] = []
    for _ in range(len(_SCALES)):
        number, group = divmod(number, 1000)
        groups.append(group)
    if number:
        raise InvalidAmountError("Valor acima do limite.")
    groups.reverse()  # bilhões, milhões, milhares, unidades
    pieces: list[tuple[int, str]] = []
    for group, (singular, plural) in zip(groups, _SCALES, strict=True):
        if not group:
            continue
        if singular == "mil":
            text = "mil" if group == 1 else f"{_below_thousand(group)} mil"
        elif singular:
            text = f"{_below_thousand(group)} {singular if group == 1 else plural}"
        else:
            text = _below_thousand(group)
        pieces.append((group, text))
    result = pieces[0][1]
    for index, (group, text) in enumerate(pieces[1:], start=1):
        last = index == len(pieces) - 1
        joiner = " e " if last and (group < 100 or group % 100 == 0) else " "
        result += joiner + text
    return result


def amount_in_words(cents: int) -> str:
    """12345 → "cento e vinte e três reais e quarenta e cinco centavos"."""
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0 or cents > MAX_ABS_CENTS:
        raise InvalidAmountError("Valor inválido para extenso.")
    reais, centavos = divmod(cents, 100)
    parts = []
    if reais or not centavos:
        words = integer_in_words(reais)
        exact_large = reais >= 1_000_000 and reais % 1_000_000 == 0
        unit = "real" if reais == 1 else ("de reais" if exact_large else "reais")
        parts.append(f"{words} {unit}")
    if centavos:
        parts.append(f"{integer_in_words(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
    return " e ".join(parts)
