"""Tabela genérica (model/view do Qt: só as linhas visíveis são desenhadas).

O texto das células é sempre exibido como texto simples (DisplayRole não interpreta HTML).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableView,
    QWidget,
)

Index = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True, slots=True)
class Column:
    header: str
    text: Callable[[Any], str]
    align_right: bool = False
    color: Callable[[Any], str | None] | None = None
    stretch: bool = False


class RowsTableModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[Column], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[Any] = []

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_at(self, row: int) -> Any:
        return self._rows[row]

    def rows(self) -> list[Any]:
        return list(self._rows)

    def refresh(self) -> None:
        """Redesenha (ex.: ao alternar "Ocultar valores") sem recarregar do banco."""
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, len(self._columns) - 1)
            )

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008 - API Qt
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008 - API Qt
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        column = self._columns[index.column()]
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.text(row)
        if role == Qt.ItemDataRole.TextAlignmentRole and column.align_right:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and column.color is not None:
            color = column.color(row)
            return QColor(color) if color else None
        return None

    def headerData(  # noqa: N802 - API Qt
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section].header
        return None


def make_table(
    model: RowsTableModel, columns: Sequence[Column], *, multi: bool = False
) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection
        if multi
        else QAbstractItemView.SelectionMode.SingleSelection
    )
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setAlternatingRowColors(True)
    view.verticalHeader().setVisible(False)
    view.setWordWrap(False)
    view.verticalHeader().setDefaultSectionSize(34)
    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)
    for index, column in enumerate(columns):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if column.stretch
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(index, mode)
    return view


def selected_rows(view: QTableView) -> list[int]:
    return sorted({index.row() for index in view.selectionModel().selectedRows()})


class TablePanel(QStackedWidget):
    """Tabela que mostra uma mensagem amigável quando não há linhas."""

    def __init__(self, view: QTableView, model: RowsTableModel, empty_text: str) -> None:
        super().__init__()
        self._model = model
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("emptyState")
        self.empty.setTextFormat(Qt.TextFormat.PlainText)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.addWidget(view)
        self.addWidget(self.empty)
        model.modelReset.connect(self._update)
        self._update()

    def set_empty_text(self, text: str) -> None:
        self.empty.setText(text)

    def _update(self) -> None:
        self.setCurrentIndex(0 if self._model.rowCount() else 1)
