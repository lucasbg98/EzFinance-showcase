"""Conversões puras da planilha: valores pt-BR → centavos, rótulos, meses, comentários, chaves.

Dinheiro: sempre ``Decimal`` → centavos inteiros, nunca ``float``. O ``Decimal`` dos números do
XLSX vem da representação mais curta do ``float`` gravado pelo Excel, por isso os totais trazem
"ruído" (ex.: ``1234.5099999999998``): os totais são arredondados para centavos; nas linhas de
detalhe, só esse ruído (< 0,000001) é tolerado, e mais de 2 casas é erro.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from appfin.domain.errors import DomainError
from appfin.domain.money import MAX_ABS_CENTS
from appfin.domain.spreadsheet_import.grid import CellComment, CellError, CellValue
from appfin.domain.validation import clean_multiline

CENT = Decimal("0.01")
FLOAT_NOISE = Decimal("0.000001")
MAX_COMMENT_LENGTH = 900  # cabe na observação (1.000) junto com "Importado da planilha (linha N)"

MONTHS = (
    "JANEIRO",
    "FEVEREIRO",
    "MARCO",
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
_MONTH_ALIASES = {name: number for number, name in enumerate(MONTHS, start=1)} | {
    name[:3]: number for number, name in enumerate(MONTHS, start=1)
}

# pt-BR: "1.234,56", "1234,56", "1234", "0,5". Ponto só como separador de milhar.
_PT_BR_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")
_SPACES = re.compile(r"\s+")
_NO_BREAK_SPACE = chr(0xA0)  # usado pelo Excel pt-BR no formato contábil


class AmountError(DomainError):
    """Célula que não é um valor em reais válido. A mensagem é amigável e não repete a célula."""


# ---------------------------------------------------------------------- valores
def parse_amount(value: CellValue) -> Decimal | None:
    """Valor da célula como ``Decimal`` exato; ``None`` = vazio. ``R$ -`` (contábil) = zero."""
    if value is None:
        return None
    if isinstance(value, CellError):
        raise AmountError("Célula com erro de fórmula.")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise AmountError("Número inválido.")
        return value
    return _parse_text(value)


def _parse_text(text: str) -> Decimal | None:
    body = _SPACES.sub("", text.replace(_NO_BREAK_SPACE, " "))
    if not body:
        return None
    negative = body.startswith("-")  # "-R$ 1,00"
    body = body.removeprefix("-")
    if body.upper().startswith("R$"):
        body = body[2:]
    if not negative and body.startswith("-"):  # "R$ -1,00"
        negative, body = True, body[1:]
    if not body:  # "R$ -" (ou só "-"): é como o formato contábil mostra o zero
        return Decimal(0)
    if not _PT_BR_NUMBER.fullmatch(body):
        raise AmountError("Valor inválido: use o formato R$ 1.234,56.")
    try:
        amount = Decimal(body.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover - a regex já garante o formato
        raise AmountError("Valor inválido.") from exc
    return -amount if negative else amount


def detail_cents(amount: Decimal) -> int:
    """Centavos exatos de uma linha de detalhe (lançamento). Mais de 2 casas = erro."""
    rounded = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if abs(amount - rounded) >= FLOAT_NOISE:
        raise AmountError("Valor com mais de 2 casas decimais.")
    return _checked(rounded)


def total_cents(amount: Decimal) -> int:
    """Centavos de uma linha de total (só conferência): arredonda o ruído de ponto flutuante."""
    return _checked(amount.quantize(CENT, rounding=ROUND_HALF_UP))


def _checked(rounded: Decimal) -> int:
    cents = int(rounded * 100)
    if abs(cents) > MAX_ABS_CENTS:
        raise AmountError("Valor acima do limite.")
    return cents


# ---------------------------------------------------------------------- rótulos e meses
def normalize_label(value: CellValue) -> str:
    """Rótulo para comparação: sem acentos, maiúsculo, espaços simples. A tela mostra o original."""
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACES.sub(" ", plain).strip().upper()


def is_separator(normalized_label: str) -> bool:
    """Linha só com símbolos (ex.: ``-`` ou ``=``) usada como espaçador visual."""
    return not any(ch.isalnum() for ch in normalized_label)


def display_label(value: CellValue) -> str:
    """Rótulo original, sem caracteres de controle e com espaços simples (para descrição/tela)."""
    if not isinstance(value, str):
        return ""
    return _SPACES.sub(" ", clean_multiline(value, "label", max_length=10_000)).strip()


def month_number(value: CellValue) -> int | None:
    """``JANEIRO``/``Jan``/``março`` → 1…12; qualquer outra coisa → ``None``."""
    return _MONTH_ALIASES.get(normalize_label(value).rstrip("."))


# ---------------------------------------------------------------------- comentários
def clean_comment(comment: CellComment | None) -> str:
    """Texto do comentário para a observação: sem a linha "Autor:" que o Excel insere."""
    if comment is None:
        return ""
    lines = comment.text.splitlines()
    author = comment.author.strip()
    if lines and author and lines[0].strip().rstrip(":").strip() == author:
        lines = lines[1:]
    elif lines and author and lines[0].strip().startswith(author + ":"):
        lines[0] = lines[0].strip()[len(author) + 1 :]
    text = clean_multiline("\n".join(lines), "notes", max_length=100_000)
    if len(text) > MAX_COMMENT_LENGTH:
        text = text[: MAX_COMMENT_LENGTH - 1].rstrip() + "…"
    return text


# ---------------------------------------------------------------------- identidade da célula
def cell_key(profile_id: str, year: int, month: int, line_key: str) -> str:
    """``import_row_key``: SHA-256 de ``perfil | ano-mês | chave da linha`` (§6.1 do plano)."""
    material = f"{profile_id}|{year:04d}-{month:02d}|{line_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
