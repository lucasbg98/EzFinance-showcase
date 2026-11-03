"""Cartão de indicador (rótulo + valor), usado nos resumos e no dashboard."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout

from appfin.presentation.shared.formatting import ValuesVisibility, format_money
from appfin.presentation.shared.ui.forms import plain_label


class StatCard(QFrame):
    def __init__(self, title: str, visibility: ValuesVisibility, *, tone: str = "") -> None:
        super().__init__()
        self.setObjectName("statCard")
        self._visibility = visibility
        self._cents = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        self.title = plain_label(title, "statTitle")
        self.value = plain_label("", f"statValue{tone.capitalize()}" if tone else "statValue")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        visibility.changed.connect(lambda _hidden: self._render())
        self._render()

    def set_cents(self, cents: int) -> None:
        self._cents = cents
        self._render()

    def _render(self) -> None:
        self.value.setText(format_money(self._cents, self._visibility))
