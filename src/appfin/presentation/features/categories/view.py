"""Categorias em dois níveis (grupo → categoria), com tipo e grupo do DRE."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from appfin.domain.entities import NEW_ID, Category
from appfin.domain.enums import CategoryKind, DreGroup
from appfin.presentation.shared.ui.feedback import show_error
from appfin.presentation.shared.ui.forms import (
    Field,
    FormDialog,
    combo,
    plain_label,
    select_data,
    text_field,
)
from appfin.presentation.workspace import Workspace

KIND_LABELS = {
    CategoryKind.INCOME: "Receita",
    CategoryKind.EXPENSE: "Despesa",
    CategoryKind.BOTH: "Receita e despesa",
}
DRE_LABELS = {
    DreGroup.GROSS_REVENUE: "Receita bruta",
    DreGroup.DEDUCTIONS: "Deduções",
    DreGroup.TAXES: "Impostos",
    DreGroup.DIRECT_COSTS: "Custos diretos",
    DreGroup.OPERATING_EXPENSES: "Despesas operacionais",
    DreGroup.SELLING_EXPENSES: "Despesas comerciais",
    DreGroup.INVESTMENTS: "Investimentos",
    DreGroup.OTHER_RESULTS: "Financeiro e diversos",
}


class CategoryDialog(FormDialog):
    def __init__(
        self,
        ws: Workspace,
        category: Category | None,
        groups: list[Category],
        *,
        as_group: bool,
        parent: QWidget,
    ) -> None:
        editing_group = category.is_group if category else as_group
        noun = "grupo" if editing_group else "categoria"
        title = (
            f"Editar {noun}" if category else ("Novo grupo" if editing_group else "Nova categoria")
        )
        super().__init__(
            title,
            parent,
            subtitle=(
                "Grupos reúnem categorias (ex.: Despesas operacionais)."
                if editing_group
                else "Classifica receitas e despesas e define a linha do DRE."
            ),
            save_text=f"Salvar {noun}",
        )
        self._ws = ws
        self._category = category
        self._is_group = editing_group
        self.name = text_field(60, "Nome")
        self.kind = combo([(label, kind) for kind, label in KIND_LABELS.items()], "Tipo")
        self.dre = combo(
            [("Usar o do grupo" if not editing_group else "Nenhum", None)]
            + [(label, group) for group, label in DRE_LABELS.items()],
            "Grupo do DRE",
        )
        self.parent_group = combo([(g.name, g.id) for g in groups], "Grupo")
        self.add_row(Field("Nome", self.name, "name", required=True))
        if editing_group:
            self.add_row(
                Field("Tipo", self.kind, "kind"), Field("Linha do DRE", self.dre, "dre_group")
            )
        else:
            self.add_row(
                Field("Grupo", self.parent_group, "parent_id", required=True),
                Field("Tipo", self.kind, "kind"),
            )
            self.add_row(Field("Linha do DRE", self.dre, "dre_group"))
        self._groups_by_id = {g.id: g for g in groups}
        if not editing_group:
            # O tipo acompanha o grupo escolhido (ex.: "Custos diretos" → Despesa).
            self.parent_group.currentIndexChanged.connect(self._follow_group_kind)
            if category is None:
                self._follow_group_kind()
        if category:
            self.name.setText(category.name)
            select_data(self.kind, category.kind)
            select_data(self.dre, category.dre_group)
            if category.parent_id:
                select_data(self.parent_group, category.parent_id)
        self.on_save(self._save)

    def _follow_group_kind(self) -> None:
        group = self._groups_by_id.get(self.parent_group.value())
        if group is not None:
            self.kind.select(group.kind)

    def _save(self) -> Category:
        parent_id = None if self._is_group else self.parent_group.value()
        base = self._category or Category(NEW_ID, self.name.text() or "?", self.kind.value())
        category = replace(
            base,
            name=self.name.text(),
            kind=self.kind.value(),
            parent_id=parent_id,
            dre_group=self.dre.value(),
        )
        return self._ws.catalog.save_category(category)


class CategoriesPage(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self._categories: dict[str, Category] = {}
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nome", "Tipo", "Grupo do DRE", "Situação"])
        self.tree.setAlternatingRowColors(True)
        self.show_archived = QCheckBox("Mostrar arquivadas")
        self.new_group = QPushButton("+ Novo grupo")
        self.new_category = QPushButton("+ Nova categoria")
        self.new_category.setObjectName("primary")
        self.edit_button = QPushButton("Editar")
        self.archive_button = QPushButton("Arquivar / reativar")
        bar = QHBoxLayout()
        for widget in (self.new_category, self.new_group, self.edit_button, self.archive_button):
            bar.addWidget(widget)
        bar.addStretch(1)
        bar.addWidget(self.show_archived)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Categorias", "title"))
        layout.addWidget(
            plain_label(
                "Classificam receitas e despesas e definem onde cada valor aparece no DRE. "
                "Categorias em uso não são excluídas: arquive.",
                "muted",
            )
        )
        layout.addLayout(bar)
        layout.addWidget(self.tree)
        self.new_group.clicked.connect(lambda: self._open(None, as_group=True))
        self.new_category.clicked.connect(lambda: self._open(None, as_group=False))
        self.edit_button.clicked.connect(self._edit_selected)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit_selected())
        self.archive_button.clicked.connect(self._toggle_archive)
        self.show_archived.toggled.connect(lambda _: self.reload())
        self.reload()

    def reload(self) -> None:
        include = self.show_archived.isChecked()
        categories = self._ws.catalog.list_categories(include_archived=include)
        self._categories = {c.id: c for c in categories}
        self.tree.clear()
        groups = sorted((c for c in categories if c.is_group), key=lambda c: c.name.lower())
        for group in groups:
            group_item = self._item(group)
            self.tree.addTopLevelItem(group_item)
            for child in sorted(
                (c for c in categories if c.parent_id == group.id), key=lambda c: c.name.lower()
            ):
                group_item.addChild(self._item(child))
        self.tree.expandAll()
        for column in range(4):
            self.tree.resizeColumnToContents(column)

    def _item(self, category: Category) -> QTreeWidgetItem:
        dre = DRE_LABELS.get(category.dre_group, "") if category.dre_group else ""
        item = QTreeWidgetItem(
            [
                category.name,
                KIND_LABELS[category.kind],
                dre,
                "Arquivada" if category.archived else "",
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, category.id)
        if category.is_group:
            font = item.font(0)
            font.setBold(True)
            for column in range(4):
                item.setFont(column, font)
        return item

    def _selected(self) -> Category | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        return self._categories.get(item.data(0, Qt.ItemDataRole.UserRole))

    def _groups(self) -> list[Category]:
        return sorted(
            (c for c in self._categories.values() if c.is_group and not c.archived),
            key=lambda c: c.name.lower(),
        )

    def _open(self, category: Category | None, *, as_group: bool) -> None:
        dialog = CategoryDialog(self._ws, category, self._groups(), as_group=as_group, parent=self)
        if dialog.exec():
            self.reload()

    def _edit_selected(self) -> None:
        category = self._selected()
        if category:
            self._open(category, as_group=category.is_group)

    def _toggle_archive(self) -> None:
        category = self._selected()
        if category is None:
            return
        try:
            self._ws.catalog.set_category_archived(category.id, not category.archived)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "category.archive")
        self.reload()
