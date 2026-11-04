"""Grade de células lida de uma planilha: o que o leitor seguro entrega ao domínio.

Só valores (texto, número exato, erro do Excel) e comentários. Fórmulas, estilos e macros nunca
chegam aqui. Tudo que vem da planilha é **dado não confiável** e pode conter nomes de pessoas:
nunca vai para log.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from appfin.domain.enums import ImportSource

NO_CACHED_VALUE = "#SEM_VALOR"  # fórmula salva sem o valor calculado (arquivo não salvo pelo Excel)


@dataclass(frozen=True, slots=True)
class CellError:
    """Erro de fórmula do Excel (``#DIV/0!``, ``#REF!``…) ou ``NO_CACHED_VALUE``."""

    code: str


# Texto | número exato | erro | vazio. Números do XLSX chegam como ``Decimal`` (nunca ``float``).
CellValue = str | Decimal | CellError | None


@dataclass(frozen=True, slots=True)
class CellComment:
    """Comentário de célula como está no arquivo; ``author`` serve para limpar a 1ª linha."""

    text: str
    author: str = ""


@dataclass(frozen=True, slots=True)
class Sheet:
    """Uma aba. ``rows`` e ``comments`` usam posições a partir de 0 (linha, coluna)."""

    name: str
    rows: tuple[tuple[CellValue, ...], ...]
    comments: Mapping[tuple[int, int], CellComment] = field(default_factory=dict)

    def cell(self, row: int, column: int) -> CellValue:
        if row >= len(self.rows) or column >= len(self.rows[row]):
            return None
        return self.rows[row][column]

    def comment(self, row: int, column: int) -> CellComment | None:
        return self.comments.get((row, column))


@dataclass(frozen=True, slots=True)
class SpreadsheetFile:
    """Arquivo lido. Sem nome nem caminho do arquivo: o SHA-256 identifica o conteúdo."""

    source: ImportSource
    sha256: str
    sheets: tuple[Sheet, ...]
    has_macros: bool = False  # .xlsm: só os valores foram lidos; macros nunca rodam
