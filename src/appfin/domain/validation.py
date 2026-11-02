"""Validação de textos e documentos (CPF/CNPJ) usada pelas entidades."""

from __future__ import annotations

import re
import unicodedata

from appfin.domain.errors import ValidationError

# Caracteres removidos dos textos: controles C0/C1 (exceto TAB e quebra de linha), invisíveis
# de largura zero, marcas de direção e controles bidirecionais ("Trojan Source"), BOM.
# Definidos por código numérico de propósito: o arquivo-fonte fica 100% ASCII nesta parte
# (verificado em tests/unit/test_source_hygiene.py).
_INVISIBLE_RANGES = (
    (0x00, 0x08),
    (0x0B, 0x1F),
    (0x7F, 0x9F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2066, 0x2069),
    (0xFEFF, 0xFEFF),
)
_CONTROL = re.compile(
    "[" + "".join(f"{re.escape(chr(a))}-{re.escape(chr(b))}" for a, b in _INVISIBLE_RANGES) + "]"
)
_DIGITS = re.compile(r"\D")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,253}\.[^@\s]{2,}$")


def clean_text(value: str | None, field: str, *, max_length: int, required: bool = False) -> str:
    """Normaliza (NFC), remove caracteres de controle/invisíveis e espaços nas pontas."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(field, "Valor de texto inválido.")
    cleaned = _CONTROL.sub("", unicodedata.normalize("NFC", value)).strip()
    if required and not cleaned:
        raise ValidationError(field, "Campo obrigatório.")
    if len(cleaned) > max_length:
        raise ValidationError(field, f"Use no máximo {max_length} caracteres.")
    return cleaned


def clean_multiline(value: str | None, field: str, *, max_length: int) -> str:
    """Como ``clean_text``, mas preserva quebras de linha (observações)."""
    lines = [clean_text(line, field, max_length=max_length) for line in (value or "").splitlines()]
    text = "\n".join(lines).strip()
    if len(text) > max_length:
        raise ValidationError(field, f"Use no máximo {max_length} caracteres.")
    return text


def only_digits(value: str) -> str:
    return _DIGITS.sub("", value or "")


def clean_email(value: str | None, field: str = "email") -> str:
    email = clean_text(value, field, max_length=254)
    if email and not _EMAIL.fullmatch(email):
        raise ValidationError(field, "E-mail inválido.")
    return email


def clean_document(value: str | None, field: str = "document") -> str:
    """CPF (11) ou CNPJ (14) com dígitos verificadores. Vazio é permitido (campo opcional)."""
    digits = only_digits(value or "")
    if not digits:
        return ""
    if len(digits) == 11 and is_valid_cpf(digits):
        return digits
    if len(digits) == 14 and is_valid_cnpj(digits):
        return digits
    raise ValidationError(field, "CPF/CNPJ inválido.")


def is_valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit() or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def is_valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or not digits.isdigit() or digits == digits[0] * 14:
        return False
    weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_2 = [6, *weights_1]
    for weights, position in ((weights_1, 12), (weights_2, 13)):
        total = sum(int(d) * w for d, w in zip(digits[:position], weights, strict=True))
        remainder = total % 11
        check = 0 if remainder < 2 else 11 - remainder
        if check != int(digits[position]):
            return False
    return True
