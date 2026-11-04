"""Estrutura principal do app desbloqueado: menu lateral + área de conteúdo.

As páginas são criadas sob demanda e recarregadas ao serem abertas. Ao bloquear, a janela
principal destrói o shell inteiro (nenhum dado fica em memória nas telas).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from appfin.presentation.features.accounts.view import AccountsPage
from appfin.presentation.features.backup.view import BackupPage
from appfin.presentation.features.categories.view import CategoriesPage
from appfin.presentation.features.company.view import CompanyForm
from appfin.presentation.features.contacts.view import ContactsPage
from appfin.presentation.features.dashboard.view import DashboardPage
from appfin.presentation.features.reports.view import ReportsPage
from appfin.presentation.features.spreadsheet_import.view import SpreadsheetImportPage
from appfin.presentation.features.transactions.view import payables_page, receivables_page
from appfin.presentation.shared.ui.forms import plain_label
from appfin.presentation.workspace import Workspace

PageFactory = Callable[[Workspace], QWidget]


class ComingSoonPage(QWidget):
    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(title, "title"))
        layout.addWidget(plain_label(text, "muted"))
        layout.addStretch(1)


def _soon(title: str, increment: str) -> PageFactory:
    return lambda _ws: ComingSoonPage(
        title, f"Esta tela chega no incremento {increment} da fase 1."
    )


SECTIONS: list[tuple[str, str, PageFactory]] = [
    ("dashboard", "Início", DashboardPage),
    ("receivables", "Contas a receber", receivables_page),
    ("payables", "Contas a pagar", payables_page),
    ("reports", "Relatórios e DRE", ReportsPage),
    ("import", "Importar planilha", SpreadsheetImportPage),
    ("contacts", "Contatos", ContactsPage),
    ("categories", "Categorias", CategoriesPage),
    ("accounts", "Contas", AccountsPage),
    ("company", "Dados do consultório", CompanyForm),
    ("backup", "Backup e segurança", BackupPage),
]


class AppShell(QWidget):
    def __init__(self, workspace: Workspace, initial: str = "contacts") -> None:
        super().__init__()
        self._ws = workspace
        self._pages: dict[str, QWidget] = {}
        self.menu = QListWidget()
        self.menu.setObjectName("sideMenu")
        self.menu.setFixedWidth(210)
        self.menu.setAccessibleName("Menu principal")
        self.stack = QStackedWidget()
        for key, label, _factory in SECTIONS:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.menu.addItem(item)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.menu)
        content = QVBoxLayout()
        content.setContentsMargins(16, 12, 16, 12)
        content.addWidget(self.stack)
        layout.addLayout(content, 1)
        # Seleção (não só "item atual"): também responde a leitores de tela e automação (UIA).
        self.menu.itemSelectionChanged.connect(self._on_selection)
        self.open(initial)

    def open(self, key: str) -> None:
        for row in range(self.menu.count()):
            if self.menu.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.menu.setCurrentRow(row)
                return

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    def _on_selection(self) -> None:
        selected = self.menu.selectedItems()
        if selected:
            self._on_menu(selected[0])

    def _on_menu(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        if self.menu.currentItem() is not current:
            self.menu.setCurrentItem(current)
        key = current.data(Qt.ItemDataRole.UserRole)
        page = self._pages.get(key)
        if page is None:
            factory = next(f for k, _label, f in SECTIONS if k == key)
            page = factory(self._ws)
            if hasattr(page, "set_navigator"):
                page.set_navigator(self.open)
            self._pages[key] = page
            self.stack.addWidget(page)
        elif hasattr(page, "reload"):
            page.reload()
        self.stack.setCurrentWidget(page)
