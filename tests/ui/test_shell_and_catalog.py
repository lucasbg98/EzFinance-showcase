"""Onboarding, menu lateral, cadastros e "Ocultar valores" (dados fictícios)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from appfin.bootstrap import AppConfig, build_app
from appfin.domain.enums import TaxRegime
from appfin.infrastructure.paths import AppPaths
from appfin.presentation.features.accounts.view import AccountDialog, AccountsPage
from appfin.presentation.features.categories.view import CategoriesPage
from appfin.presentation.features.company.view import CompanyForm
from appfin.presentation.features.contacts.view import ContactDialog, ContactsPage
from appfin.presentation.main_window import MainWindow
from appfin.presentation.shared.formatting import HIDDEN_AMOUNT
from appfin.presentation.shared.ui.inputs import MoneyEdit
from appfin.presentation.shell import AppShell
from tests.support import FAST_MINIMUM, FAST_PARAMS

STRONG = "girassol trator piano nuvem"
TIMEOUT = 5000


def _window(qtbot: QtBot, root: Path) -> MainWindow:
    config = AppConfig(paths=AppPaths(root), kdf_params=FAST_PARAMS, kdf_minimum=FAST_MINIMUM)
    container = build_app(config)
    window = MainWindow(container.session, 3, container.workspace_factory)
    qtbot.addWidget(window)
    window.show()
    return window


def _setup_vault(qtbot: QtBot, window: MainWindow) -> None:
    window.setup_view.password.setText(STRONG)
    window.setup_view.confirmation.setText(STRONG)
    qtbot.mouseClick(window.setup_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.recovery_view.key_label.text() != "", timeout=TIMEOUT)
    key = window.recovery_view.key_label.text()
    window.recovery_view.saved.setChecked(True)
    window.recovery_view.last_group.setText(key.split()[-1])
    qtbot.mouseClick(window.recovery_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.data_page is not None, timeout=TIMEOUT)


def _onboard(qtbot: QtBot, window: MainWindow) -> AppShell:
    form = window.data_page
    assert isinstance(form, CompanyForm)
    form.name.setText("Clínica Odontológica Fictícia")
    form.document.setText("11.222.333/0001-81")
    form.regime.select(TaxRegime.PRESUMIDO)
    qtbot.mouseClick(form.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: isinstance(window.data_page, AppShell), timeout=TIMEOUT)
    shell = window.data_page
    assert isinstance(shell, AppShell)
    return shell


def test_onboarding_creates_defaults_and_opens_accounts(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)

    shell = _onboard(qtbot, window)

    accounts = shell.page("accounts")
    assert isinstance(accounts, AccountsPage)
    assert [r.name for r in accounts.model.rows()] == ["Caixa do consultório"]
    shell.open("categories")
    categories = shell.page("categories")
    assert isinstance(categories, CategoriesPage)
    top_level = [
        categories.tree.topLevelItem(i).text(0) for i in range(categories.tree.topLevelItemCount())
    ]
    assert "Impostos" in top_level
    taxes = next(
        categories.tree.topLevelItem(i)
        for i in range(categories.tree.topLevelItemCount())
        if categories.tree.topLevelItem(i).text(0) == "Impostos"
    )
    assert {taxes.child(i).text(0) for i in range(taxes.childCount())} >= {"PIS", "COFINS"}


def test_onboarding_rejects_invalid_cnpj(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    form = window.data_page
    assert isinstance(form, CompanyForm)
    form.name.setText("Clínica")
    form.document.setText("11.222.333/0001-80")

    qtbot.mouseClick(form.submit, Qt.MouseButton.LeftButton)

    assert "inválido" in form.message.text()
    assert window.data_page is form


def test_unlock_goes_straight_to_shell_and_lock_destroys_it(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)

    window.lock()

    assert window.data_page is None
    qtbot.waitUntil(lambda: shell not in window.findChildren(AppShell), timeout=TIMEOUT)
    window.unlock_view.secret.setText(STRONG)
    qtbot.mouseClick(window.unlock_view.submit, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: isinstance(window.data_page, AppShell), timeout=TIMEOUT)


def test_account_dialog_and_hide_values(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)
    page = shell.page("accounts")
    assert isinstance(page, AccountsPage)

    dialog = AccountDialog(page._ws, None, page)
    dialog.name.setText("Banco do consultório")
    dialog.opening.set_cents(150_000)
    dialog._on_save()
    page.reload()

    texts = {
        page.model.data(page.model.index(row, 0)): page.model.data(page.model.index(row, 2))
        for row in range(page.model.rowCount())
    }
    assert texts["Banco do consultório"] == "R$ 1.500,00"

    window._hide_action.trigger()

    assert page.model.data(page.model.index(0, 2)) == HIDDEN_AMOUNT


def test_contact_dialog_validation_and_search(qtbot: QtBot, data_dir: Path) -> None:
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)
    shell.open("contacts")
    page = shell.page("contacts")
    assert isinstance(page, ContactsPage)

    invalid = ContactDialog(page._ws, None, page)
    invalid.name.setText("Paciente Fictício")
    invalid.document.setText("123.456.789-00")
    invalid._on_save()
    assert invalid.error.text() == "CPF/CNPJ inválido."

    for name in ("Paciente <b>Negrito</b>", "Laboratório Dente Bom"):
        dialog = ContactDialog(page._ws, None, page)
        dialog.name.setText(name)
        dialog._on_save()
        assert dialog.error.text() == "", dialog.error.text()
    page.reload()
    assert [c.name for c in page.model.rows()] == [
        "Laboratório Dente Bom",
        "Paciente <b>Negrito</b>",
    ]

    page.search.setText("dente")
    qtbot.waitUntil(lambda: len(page.model.rows()) == 1, timeout=TIMEOUT)


def test_money_edit_types_like_a_bank_app(qtbot: QtBot) -> None:
    field = MoneyEdit()
    qtbot.addWidget(field)

    qtbot.keyClicks(field, "12a3.45")
    assert field.cents() == 12_345 and field.text() == "123,45"

    qtbot.keyClick(field, Qt.Key.Key_Backspace)
    assert field.cents() == 1234

    qtbot.keyClick(field, Qt.Key.Key_Minus)
    assert field.cents() == 1234, "negativo só quando permitido"

    QApplication.clipboard().setText("R$ 2.500,10")
    qtbot.keyClick(field, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert field.cents() == 250_010

    QApplication.clipboard().setText("texto qualquer")
    qtbot.keyClick(field, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert field.cents() == 250_010, "colar texto inválido não altera o valor"


def test_category_dialog_creates_subcategory_with_enum_values(qtbot: QtBot, data_dir: Path) -> None:
    from appfin.domain.enums import CategoryKind
    from appfin.presentation.features.categories.view import CategoryDialog

    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)
    shell.open("categories")
    page = shell.page("categories")
    assert isinstance(page, CategoriesPage)
    groups = page._groups()
    expenses = next(g for g in groups if g.name == "Despesas operacionais")

    dialog = CategoryDialog(page._ws, None, groups, as_group=False, parent=page)
    dialog.name.setText("Uniformes")
    dialog.kind.select(CategoryKind.EXPENSE)
    dialog.parent_group.select(expenses.id)
    dialog._on_save()

    assert dialog.error.text() == ""
    saved = dialog.result_value
    assert saved.kind is CategoryKind.EXPENSE and saved.parent_id == expenses.id


def test_dialog_highlights_invalid_field_and_hides_optional_address(
    qtbot: QtBot, data_dir: Path
) -> None:
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)
    shell.open("contacts")
    page = shell.page("contacts")
    assert isinstance(page, ContactsPage)
    dialog = ContactDialog(page._ws, None, page)
    qtbot.addWidget(dialog)
    dialog.show()

    assert all(not row.isVisible() for row in dialog.address_rows), "endereço começa recolhido"
    dialog.address_toggle.click()
    assert all(row.isVisible() for row in dialog.address_rows)

    dialog.name.setText("Paciente Fictícia")
    dialog.document.setText("123.456.789-00")
    dialog._on_save()
    assert dialog.document.property("invalid") is True

    dialog.document.setText("529.982.247-25")
    dialog._on_save()
    assert dialog.document.property("invalid") is False
    assert dialog.result_value is not None


def test_category_kind_follows_selected_group(qtbot: QtBot, data_dir: Path) -> None:
    from appfin.domain.enums import CategoryKind
    from appfin.presentation.features.categories.view import CategoryDialog

    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)
    shell.open("categories")
    page = shell.page("categories")
    assert isinstance(page, CategoriesPage)
    groups = page._groups()
    dialog = CategoryDialog(page._ws, None, groups, as_group=False, parent=page)

    revenue = next(g for g in groups if g.kind is CategoryKind.INCOME)
    dialog.parent_group.select(revenue.id)
    assert dialog.kind.value() is CategoryKind.INCOME
    expense = next(g for g in groups if g.kind is CategoryKind.EXPENSE)
    dialog.parent_group.select(expense.id)
    assert dialog.kind.value() is CategoryKind.EXPENSE


def test_menu_switches_page_on_selection_for_accessibility(qtbot: QtBot, data_dir: Path) -> None:
    """Leitores de tela/UIA mudam a seleção (não o item atual): a página precisa trocar."""
    window = _window(qtbot, data_dir)
    _setup_vault(qtbot, window)
    shell = _onboard(qtbot, window)

    item = next(
        shell.menu.item(row)
        for row in range(shell.menu.count())
        if shell.menu.item(row).text() == "Contatos"
    )
    item.setSelected(True)

    assert isinstance(shell.stack.currentWidget(), ContactsPage)
