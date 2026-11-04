"""Mensagens para a usuária: amigáveis, em texto simples, sem detalhe técnico."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from appfin import PRODUCT_NAME
from appfin.domain.errors import (
    BusinessRuleError,
    ConcurrencyConflictError,
    NotFoundError,
    ValidationError,
)
from appfin.infrastructure.app_logging import log_exception


def friendly_message(error: Exception, event: str) -> str:
    """Erro de regra vira a própria mensagem; o resto é registrado (sem dados) e vira código."""
    if isinstance(error, ValidationError):
        return error.message
    if isinstance(error, BusinessRuleError | NotFoundError | ConcurrencyConflictError):
        return str(error)
    log_exception(event, error, error_code="E-UNEXPECTED")
    return "Ocorreu um erro inesperado. (código E-UNEXPECTED)"


def show_error(parent: QWidget, error: Exception, event: str) -> None:
    _box(parent, QMessageBox.Icon.Warning, "Atenção", friendly_message(error, event))


def show_info(parent: QWidget, text: str) -> None:
    _box(parent, QMessageBox.Icon.Information, PRODUCT_NAME, text)


def confirm(parent: QWidget, text: str, *, accept: str, decline: str = "Cancelar") -> bool:
    """Confirmação de ação destrutiva: botões com texto explícito; padrão = cancelar."""
    box = QMessageBox(QMessageBox.Icon.Question, "Confirmar", text, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    yes = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton(decline, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes


def _box(parent: QWidget, icon: QMessageBox.Icon, title: str, text: str) -> None:
    box = QMessageBox(icon, title, text, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.exec()
