"""Campos de entrada reutilizáveis: valor em R$, data e navegação por mês."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from appfin.domain.errors import ValidationError
from appfin.domain.money import MAX_ABS_CENTS
from appfin.presentation.shared.formatting import format_cents, month_label, parse_money

_NAVIGATION_KEYS = {
    Qt.Key.Key_Tab,
    Qt.Key.Key_Backtab,
    Qt.Key.Key_Return,
    Qt.Key.Key_Enter,
    Qt.Key.Key_Escape,
    Qt.Key.Key_Up,
    Qt.Key.Key_Down,
}


class MoneyEdit(QLineEdit):
    """Valor em reais digitado como em app de banco: os dígitos entram pelos centavos.

    "1" → 0,01; "12" → 0,12; "1234" → 12,34. Backspace remove o último dígito. "-" inverte o sinal
    (só se ``allow_negative``). Colar aceita "1.234,56". O valor é guardado em centavos (int).
    """

    cents_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, allow_negative: bool = False) -> None:
        super().__init__(parent)
        self._cents = 0
        self._allow_negative = allow_negative
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setPlaceholderText("0,00")
        self._render()

    def cents(self) -> int:
        return self._cents

    def set_cents(self, cents: int) -> None:
        if abs(cents) > MAX_ABS_CENTS or (cents < 0 and not self._allow_negative):
            raise ValidationError("amount", "Valor inválido.")
        self._cents = cents
        self._render()
        self.cents_changed.emit(cents)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - API Qt
        key = event.key()
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            candidate = abs(self._cents) * 10 + (key - Qt.Key.Key_0)
            if candidate <= MAX_ABS_CENTS:
                self.set_cents(-candidate if self._cents < 0 else candidate)
        elif key == Qt.Key.Key_Backspace:
            self.set_cents(int(self._cents / 10))
        elif key == Qt.Key.Key_Delete:
            self.set_cents(0)
        elif key == Qt.Key.Key_Minus and self._allow_negative:
            self.set_cents(-self._cents)
        elif key in _NAVIGATION_KEYS:
            super().keyPressEvent(event)
        # Qualquer outra tecla é ignorada: o campo só contém o valor formatado.

    def _paste(self) -> None:
        text = QGuiApplication.clipboard().text()
        try:
            self.set_cents(parse_money(text, allow_negative=self._allow_negative))
        except ValidationError:
            return

    def _render(self) -> None:
        self.setText(format_cents(self._cents, with_symbol=False))
        self.setCursorPosition(len(self.text()))


class DateEdit(QDateEdit):
    """Data no formato dd/mm/aaaa com calendário."""

    def __init__(self, value: date | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("dd/MM/yyyy")
        self.setCalendarPopup(True)
        self.setMinimumDate(QDate(2000, 1, 1))
        self.setMaximumDate(QDate(2100, 12, 31))
        self.set_date(value or date.today())  # noqa: DTZ011 - data de calendário local

    def value(self) -> date:
        qdate = self.date()
        return date(qdate.year(), qdate.month(), qdate.day())

    def set_date(self, value: date) -> None:
        self.setDate(QDate(value.year, value.month, value.day))


class MonthNavigator(QWidget):
    """< Março de 2026 > [Mês atual]"""

    changed = Signal(int, int)

    def __init__(self, today: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._today = today
        self._year, self._month = today.year, today.month
        self.previous = QPushButton("<")
        self.previous.setAccessibleName("Mês anterior")
        self.next = QPushButton(">")
        self.next.setAccessibleName("Próximo mês")
        self.current = QPushButton("Mês atual")
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setObjectName("monthLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumWidth(170)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.previous, self.label, self.next, self.current):
            layout.addWidget(widget)
        self.previous.clicked.connect(lambda: self.shift(-1))
        self.next.clicked.connect(lambda: self.shift(1))
        self.current.clicked.connect(lambda: self.set_month(self._today.year, self._today.month))
        self._render()

    @property
    def year(self) -> int:
        return self._year

    @property
    def month(self) -> int:
        return self._month

    def shift(self, months: int) -> None:
        index = self._year * 12 + (self._month - 1) + months
        self.set_month(index // 12, index % 12 + 1)

    def set_month(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        self._render()
        self.changed.emit(year, month)

    def _render(self) -> None:
        self.label.setText(month_label(self._year, self._month))
