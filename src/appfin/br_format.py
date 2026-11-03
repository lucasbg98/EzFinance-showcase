"""Formatação brasileira pura (sem Qt): usada pela interface, pelo PDF e pelas planilhas."""

from __future__ import annotations

from datetime import date

MONTHS = (
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
)


def format_cents(cents: int, *, with_symbol: bool = True) -> str:
    """12345678 → "R$ 123.456,78"; negativos com sinal antes do símbolo."""
    sign = "-" if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    integer = f"{units:,}".replace(",", ".")
    body = f"{integer},{rest:02d}"
    return f"{sign}R$ {body}" if with_symbol else f"{sign}{body}"


def format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def month_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} de {year}"


def format_document(digits: str) -> str:
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return digits


def format_phone(digits: str) -> str:
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return digits


def long_date(value: date) -> str:
    """03/11/2026 → "3 de novembro de 2026"."""
    return f"{value.day} de {MONTHS[value.month - 1].lower()} de {value.year}"


def percent_tenths(part: int, whole: int) -> int | None:
    """Percentual em décimos de ponto, só com inteiros: 1234/10000 → 123 (12,3%).

    Arredonda sobre o valor absoluto (a divisão inteira do Python arredonda negativos para baixo).
    ``None`` quando o total é zero.
    """
    if whole == 0:
        return None
    tenths = (abs(part) * 1000 + abs(whole) // 2) // abs(whole)
    return -tenths if (part < 0) != (whole < 0) else tenths


def format_percent_tenths(tenths: int | None) -> str:
    """123 → "12,3%"; zero nunca leva sinal."""
    if tenths is None:
        return ""
    sign = "-" if tenths < 0 else ""
    return f"{sign}{abs(tenths) // 10},{abs(tenths) % 10}%"
