"""Gráfico de barras agrupadas desenhado com QPainter.

Leve e sem dependência extra (o módulo QtCharts exigiria o pacote ``pyside6-addons``, bem maior).
Respeita "Ocultar valores": o eixo de valores e as dicas deixam de mostrar quantias.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QHelpEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from appfin.presentation.shared.formatting import ValuesVisibility, format_money

_MARGIN_LEFT = 78
_MARGIN_RIGHT = 16
_MARGIN_TOP = 36
_MARGIN_BOTTOM = 30


@dataclass(frozen=True, slots=True)
class Series:
    name: str
    color: str
    values: list[int]  # centavos, um por categoria do eixo X


def nice_ceiling(value: int) -> int:
    """Teto "redondo" para o eixo (ex.: 37.400 → 40.000), em centavos, só com inteiros."""
    if value <= 0:
        return 100
    magnitude = int("1" + "0" * (len(str(value)) - 1))  # 10^(dígitos-1), sempre int
    for candidate in (magnitude, 2 * magnitude, 5 * magnitude // 2, 5 * magnitude, 10 * magnitude):
        if candidate >= value:
            return candidate
    return 10 * magnitude


class BarChart(QWidget):
    def __init__(self, visibility: ValuesVisibility, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._visibility = visibility
        self._labels: list[str] = []
        self._series: list[Series] = []
        self._bars: list[tuple[QRectF, str]] = []  # áreas para as dicas (tooltip)
        self.title = ""
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName("Gráfico de barras")
        visibility.changed.connect(lambda _hidden: self.update())

    def set_data(self, labels: list[str], series: list[Series], title: str = "") -> None:
        if any(len(s.values) != len(labels) for s in series):
            raise ValueError("Cada série precisa de um valor por rótulo.")
        self._labels = labels
        self._series = series
        self.title = title
        self.update()

    @property
    def maximum(self) -> int:
        values = [v for s in self._series for v in s.values]
        return nice_ceiling(max(values, default=0))

    # ------------------------------------------------------------------ desenho
    def paintEvent(self, _event: object) -> None:  # noqa: N802 - API Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        area = QRectF(
            _MARGIN_LEFT,
            _MARGIN_TOP,
            max(10.0, self.width() - _MARGIN_LEFT - _MARGIN_RIGHT),
            max(10.0, self.height() - _MARGIN_TOP - _MARGIN_BOTTOM),
        )
        self._draw_title_and_legend(painter)
        self._draw_axis(painter, area)
        self._draw_bars(painter, area)
        painter.end()

    def _draw_title_and_legend(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#1F2933"))
        painter.drawText(QPointF(16, 22), self.title)
        painter.setFont(self.font())
        x = self.width() - _MARGIN_RIGHT
        for series in reversed(self._series):
            width = painter.fontMetrics().horizontalAdvance(series.name)
            x -= width
            painter.setPen(QColor("#52606D"))
            painter.drawText(QPointF(x, 22), series.name)
            x -= 16
            painter.fillRect(QRectF(x, 12, 11, 11), QColor(series.color))
            x -= 18

    @staticmethod
    def tick_count(maximum: int) -> int:
        """Divisões que geram valores redondos: teto começando em 5 ou 25 → 5 partes; senão 4."""
        leading = str(maximum).rstrip("0")
        return 5 if leading in ("5", "25") else 4

    def _draw_axis(self, painter: QPainter, area: QRectF) -> None:
        maximum = self.maximum
        ticks = self.tick_count(maximum)
        hidden = self._visibility.hidden
        grid = QPen(QColor("#E4E7EB"))
        for tick in range(ticks + 1):
            y = area.bottom() - area.height() * tick / ticks
            painter.setPen(grid)
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor("#52606D"))
            text = "•••" if hidden else _short_money(maximum * tick // ticks)
            painter.drawText(
                QRectF(0, y - 9, _MARGIN_LEFT - 8, 18),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                text,
            )

    def _draw_bars(self, painter: QPainter, area: QRectF) -> None:
        self._bars = []
        if not self._labels or not self._series:
            return
        maximum = self.maximum
        slot = area.width() / len(self._labels)
        group = slot * 0.7
        bar = group / len(self._series)
        for index, label in enumerate(self._labels):
            left = area.left() + slot * index + (slot - group) / 2
            for position, series in enumerate(self._series):
                value = series.values[index]
                height = area.height() * (value / maximum) if maximum else 0
                rect = QRectF(left + bar * position + 1, area.bottom() - height, bar - 2, height)
                painter.fillRect(rect, QColor(series.color))
                hover = QRectF(rect.left(), area.top(), rect.width(), area.height())
                tooltip = f"{series.name} — {label}: {format_money(value, self._visibility)}"
                self._bars.append((hover, tooltip))
            painter.setPen(QColor("#52606D"))
            painter.drawText(
                QRectF(area.left() + slot * index, area.bottom() + 6, slot, 18),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                label,
            )

    def event(self, event: object) -> bool:
        if isinstance(event, QHelpEvent):
            for rect, text in self._bars:
                if rect.contains(QPointF(event.pos())):
                    QToolTip.showText(event.globalPos(), text, self)
                    return True
            QToolTip.hideText()
            return True
        return super().event(event)  # type: ignore[arg-type]


def _short_money(cents: int) -> str:
    """Rótulo curto do eixo (R$ 40 mil, R$ 1,2 mi, R$ 500), só com inteiros (sem float)."""
    reais = cents // 100
    if reais >= 1_000_000:
        tenths = reais // 100_000
        return f"R$ {tenths // 10},{tenths % 10} mi"
    if reais >= 10_000:
        return f"R$ {reais // 1000} mil"
    if reais >= 1_000:
        tenths = reais // 100
        return f"R$ {tenths // 10},{tenths % 10} mil"
    return f"R$ {reais}"
