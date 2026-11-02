"""Construção de formulários: campos com limite de tamanho, textos sempre simples e um diálogo
padrão que mostra o erro de validação do domínio na própria tela.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from appfin.domain.errors import DomainError
from appfin.presentation.shared.ui.feedback import friendly_message


def plain_label(text: str = "", object_name: str = "", *, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    if object_name:
        label.setObjectName(object_name)
    return label


def set_message(label: QLabel, text: str, *, ok: bool = False) -> None:
    """Mensagem de status: verde (ok) ou vermelha (erro); reaplica o estilo do tema."""
    label.setObjectName("ok" if ok else "error")
    label.style().unpolish(label)
    label.style().polish(label)
    label.setText(text)


def text_field(max_length: int, accessible_name: str, placeholder: str = "") -> QLineEdit:
    field = QLineEdit()
    field.setMaxLength(max_length)
    field.setAccessibleName(accessible_name)
    if placeholder:
        field.setPlaceholderText(placeholder)
    return field


def notes_field(max_length: int, accessible_name: str) -> QPlainTextEdit:
    field = QPlainTextEdit()
    field.setAccessibleName(accessible_name)
    field.setTabChangesFocus(True)
    field.setFixedHeight(70)

    def enforce_limit() -> None:
        text = field.toPlainText()
        if len(text) > max_length:
            field.setPlainText(text[:max_length])

    field.textChanged.connect(enforce_limit)
    return field


class ValueCombo(QComboBox):
    """Combo que devolve o **objeto Python original** de cada opção.

    O ``QComboBox`` converte os dados guardados (ex.: um ``StrEnum`` vira ``str``), o que quebra
    comparações como ``valor is LegalType.PJ``. Aqui os valores ficam numa lista Python.
    """

    def __init__(self, options: Iterable[tuple[str, Any]], accessible_name: str) -> None:
        super().__init__()
        self.setAccessibleName(accessible_name)
        self._values: list[Any] = []
        for label, value in options:
            self.add_option(label, value)

    def add_option(self, label: str, value: Any) -> None:
        self._values.append(value)
        self.addItem(label)

    def value(self) -> Any:
        index = self.currentIndex()
        return self._values[index] if 0 <= index < len(self._values) else None

    def index_of(self, value: Any) -> int:
        for index, candidate in enumerate(self._values):
            if candidate == value:
                return index
        return -1

    def select(self, value: Any) -> None:
        index = self.index_of(value)
        if index >= 0:
            self.setCurrentIndex(index)


def combo(options: Iterable[tuple[str, Any]], accessible_name: str) -> ValueCombo:
    return ValueCombo(options, accessible_name)


def select_data(box: ValueCombo, value: Any) -> None:
    box.select(value)


class FormDialog(QDialog):
    """Diálogo de cadastro: ``save`` chama o caso de uso; erro de regra aparece no rodapé."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.error = plain_label("", "error")
        self.buttons = QDialogButtonBox()
        self.save_button = self.buttons.addButton("Salvar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("primary")
        self.buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)
        self.result_value: Any = None
        self._save_handler: Callable[[], Any] | None = None

    def on_save(self, save: Callable[[], Any]) -> None:
        self._save_handler = save

    def _on_save(self) -> None:
        if self._save_handler is None:
            raise RuntimeError("FormDialog sem ação de salvar (on_save).")
        self.error.setText("")
        try:
            self.result_value = self._save_handler()
        except (DomainError, ValueError) as error:
            self.error.setText(friendly_message(error, "form.save"))
            return
        self.accept()
