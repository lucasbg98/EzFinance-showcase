"""Seletor de período para relatórios: mês ou ano, com navegação anterior/próximo."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from appfin.application.reports import month_range
from appfin.presentation.shared.formatting import month_label
from appfin.presentation.shared.ui.forms import combo


class PeriodMode(StrEnum):
    MONTH = "month"
    YEAR = "year"


class PeriodPicker(QWidget):
    changed = Signal()

    def __init__(self, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._today = today
        self.year, self.month = today.year, today.month
        self.mode_box = combo([("Mensal", PeriodMode.MONTH), ("Anual", PeriodMode.YEAR)], "Período")
        self.previous = QPushButton("<")
        self.previous.setAccessibleName("Período anterior")
        self.next = QPushButton(">")
        self.next.setAccessibleName("Próximo período")
        self.current = QPushButton("Atual")
        self.label = QLabel()
        self.label.setObjectName("monthLabel")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumWidth(170)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.mode_box, self.previous, self.label, self.next, self.current):
            layout.addWidget(widget)
        self.mode_box.currentIndexChanged.connect(lambda _i: self._emit())
        self.previous.clicked.connect(lambda: self.shift(-1))
        self.next.clicked.connect(lambda: self.shift(1))
        self.current.clicked.connect(self.reset)
        self._render()

    @property
    def mode(self) -> PeriodMode:
        value = self.mode_box.value()
        return value if isinstance(value, PeriodMode) else PeriodMode.MONTH

    def set_mode(self, mode: PeriodMode) -> None:
        self.mode_box.select(mode)

    def range(self) -> tuple[date, date]:
        if self.mode is PeriodMode.YEAR:
            return date(self.year, 1, 1), date(self.year, 12, 31)
        return month_range(self.year, self.month)

    def shift(self, steps: int) -> None:
        if self.mode is PeriodMode.YEAR:
            self.year += steps
        else:
            index = self.year * 12 + (self.month - 1) + steps
            self.year, self.month = index // 12, index % 12 + 1
        self._emit()

    def reset(self) -> None:
        self.year, self.month = self._today.year, self._today.month
        self._emit()

    def _emit(self) -> None:
        self._render()
        self.changed.emit()

    def _render(self) -> None:
        if self.mode is PeriodMode.YEAR:
            self.label.setText(f"Ano de {self.year}")
        else:
            self.label.setText(month_label(self.year, self.month))
