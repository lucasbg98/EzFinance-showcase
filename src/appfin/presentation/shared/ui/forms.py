"""Construção de formulários: campos com limite de tamanho, textos sempre simples e um diálogo
padrão que mostra o erro de validação do domínio na própria tela.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from appfin.domain.errors import DomainError, ValidationError
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


def search_field(placeholder: str, accessible_name: str) -> QLineEdit:
    """Campo de busca com ícone de lupa nativo (não cobre o texto) e botão de limpar."""
    from importlib import resources

    field = text_field(100, accessible_name, placeholder)
    field.setObjectName("search")
    field.setClearButtonEnabled(True)
    icon_path = resources.files("appfin.resources").joinpath("icons", "search.svg")
    field.addAction(QIcon(str(icon_path)), QLineEdit.ActionPosition.LeadingPosition)
    return field


def notes_field(max_length: int, accessible_name: str) -> QPlainTextEdit:
    field = QPlainTextEdit()
    field.setAccessibleName(accessible_name)
    field.setTabChangesFocus(True)
    field.setFixedHeight(72)

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


@dataclass(frozen=True, slots=True)
class Field:
    """Campo do formulário: rótulo acima do controle; ``name`` liga o campo ao erro do domínio."""

    label: str
    widget: QWidget
    name: str = ""
    required: bool = False
    stretch: int = 1


def chip(text: str, accessible_name: str = "") -> QPushButton:
    """Botão alternável em formato de pílula (seleção múltipla mais clara que checkbox)."""
    button = QPushButton(text)
    button.setObjectName("chip")
    button.setCheckable(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAccessibleName(accessible_name or text)
    return button


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class FormDialog(QDialog):
    """Modal de cadastro padrão do app.

    Estrutura: cabeçalho (título + subtítulo) · corpo com seções e linhas de campos (rótulo acima)
    · mensagem de erro · rodapé com "Cancelar" e a ação principal. Um ``ValidationError`` do domínio
    destaca o campo correspondente (borda vermelha) e leva o foco até ele.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        subtitle: str = "",
        save_text: str = "Salvar",
        width: int = 560,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("formDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self._fields: dict[str, QWidget] = {}

        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 18, 24, 14)
        header_layout.setSpacing(2)
        header_layout.addWidget(plain_label(title, "dialogTitle"))
        if subtitle:
            header_layout.addWidget(plain_label(subtitle, "muted"))

        self.body = QVBoxLayout()
        self.body.setContentsMargins(24, 16, 24, 8)
        self.body.setSpacing(12)
        self.error = plain_label("", "error")
        self.body_end = QVBoxLayout()
        self.body_end.setContentsMargins(24, 0, 24, 12)
        self.body_end.addWidget(self.error)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 12)
        footer_layout.addStretch(1)
        self.cancel_button = QPushButton("Cancelar")
        self.save_button = QPushButton(save_text)
        self.save_button.setObjectName("primary")
        self.save_button.setDefault(True)
        footer_layout.addWidget(self.cancel_button)
        footer_layout.addWidget(self.save_button)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._on_save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addLayout(self.body)
        layout.addStretch(1)
        layout.addLayout(self.body_end)
        layout.addWidget(footer)
        self.result_value: Any = None
        self._save_handler: Callable[[], Any] | None = None

    # ------------------------------------------------------------------ montagem
    def add_banner(self, text: str) -> QFrame:
        banner = QFrame()
        banner.setObjectName("infoBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 9, 12, 9)
        banner_layout.addWidget(plain_label(text, "bannerText"))
        self.body.addWidget(banner)
        return banner

    def add_section(self, title: str) -> QLabel:
        label = plain_label(title, "sectionTitle")
        self.body.addWidget(label)
        return label

    def add_row(self, *fields: Field) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for item in fields:
            column = QVBoxLayout()
            column.setSpacing(4)
            caption = plain_label(item.label + (" *" if item.required else ""), "fieldLabel")
            caption.setBuddy(item.widget)
            column.addWidget(caption)
            column.addWidget(item.widget)
            layout.addLayout(column, item.stretch)
            if item.name:
                self._fields[item.name] = item.widget
        self.body.addWidget(row)
        return row

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    # ------------------------------------------------------------------ salvar
    def on_save(self, save: Callable[[], Any]) -> None:
        self._save_handler = save

    def _on_save(self) -> None:
        if self._save_handler is None:
            raise RuntimeError("FormDialog sem ação de salvar (on_save).")
        self._clear_invalid()
        self.error.setText("")
        try:
            self.result_value = self._save_handler()
        except (DomainError, ValueError) as error:
            self.error.setText(friendly_message(error, "form.save"))
            if isinstance(error, ValidationError):
                self._mark_invalid(error.field)
            return
        self.accept()

    def _mark_invalid(self, field_name: str) -> None:
        widget = self._fields.get(field_name)
        if widget is None:
            return
        widget.setProperty("invalid", True)
        _repolish(widget)
        widget.setFocus()

    def _clear_invalid(self) -> None:
        for widget in self._fields.values():
            if widget.property("invalid"):
                widget.setProperty("invalid", False)
                _repolish(widget)
