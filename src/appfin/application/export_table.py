"""Tabela para exportar (CSV/Excel): descrição neutra de colunas e linhas, sem formatação de tela.

Valores monetários vão em centavos (int) e datas como ``date``: o gerador decide o formato. Assim
a exportação usa os valores reais mesmo com "Ocultar valores" ligado na tela.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

Cell = str | int | date | None


class ColumnKind(StrEnum):
    TEXT = "text"
    MONEY = "money"  # centavos (int)
    DATE = "date"
    INTEGER = "integer"
    PERCENT = "percent"  # décimos de ponto percentual (int): 123 = 12,3%


@dataclass(frozen=True, slots=True)
class ExportColumn:
    header: str
    kind: ColumnKind = ColumnKind.TEXT


@dataclass(frozen=True, slots=True)
class ExportTable:
    title: str
    columns: list[ExportColumn]
    rows: list[list[Cell]] = field(default_factory=list)

    def __post_init__(self) -> None:
        width = len(self.columns)
        if any(len(row) != width for row in self.rows):
            raise ValueError("Toda linha precisa ter um valor por coluna.")
