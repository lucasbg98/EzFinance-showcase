"""Diálogo de uma linha da planilha: escolher a categoria (existente ou nova) e a descrição."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from appfin.application.spreadsheet_import import (
    MAX_CATEGORY_NAME,
    MAX_DESCRIPTION,
    LineChoice,
    LineSource,
    NewCategory,
    PreviewLine,
)
from appfin.domain.entities import Category
from appfin.domain.enums import CategoryKind, DreGroup, TransactionKind
from appfin.domain.errors import ValidationError
from appfin.domain.validation import clean_text
from appfin.presentation.features.categories.view import DRE_LABELS
from appfin.presentation.features.spreadsheet_import.texts import KIND_LABELS, block_label
from appfin.presentation.features.transactions.dialog import category_options
from appfin.presentation.shared.ui.forms import (
    Field,
    FormDialog,
    SearchCombo,
    combo,
    text_field,
)

NEW = "__nova__"


class LineDialog(FormDialog):
    """Devolve em ``result_value`` o par (escolha, descrição); ``None`` = manter a sugestão."""

    def __init__(
        self, line: PreviewLine, categories: list[Category], parent: QWidget | None = None
    ) -> None:
        super().__init__(
            "Linha da planilha",
            parent,
            subtitle=f"Linha {line.row} · {block_label(line.block)} · {KIND_LABELS[line.kind]}",
            save_text="Aplicar",
            width=620,
        )
        self._line = line
        self.add_banner(line.label)  # rótulo da planilha: sempre texto simples
        self.description = text_field(MAX_DESCRIPTION, "Descrição dos lançamentos")
        self.description.setText(line.description)
        options = category_options(categories, line.kind)
        self.category = SearchCombo(
            [*options, ("+ Criar categoria nova…", NEW)],
            "Categoria",
            field_name="category_id",
            not_found_message="Escolha uma categoria da lista.",
        )
        self.new_name = text_field(MAX_CATEGORY_NAME, "Nome da categoria nova")
        self.new_group = combo(
            [(label, group) for group, label in DRE_LABELS.items()], "Grupo do DRE"
        )
        self.add_row(Field("Descrição dos lançamentos", self.description, "description"))
        self.add_row(Field("Categoria", self.category, "category_id", required=True))
        self.new_row = self.add_row(
            Field("Nome da categoria nova", self.new_name, "name", stretch=3),
            Field("Grupo do DRE", self.new_group, "dre_group", stretch=2),
        )
        self._preselect()
        self.category.currentIndexChanged.connect(lambda _i: self._update_new_row())
        self._update_new_row()
        self.on_save(self._save)

    def _preselect(self) -> None:
        line = self._line
        if line.new_category is not None:
            self.category.select(NEW)
            self.new_name.setText(line.new_category.name)
            self.new_group.select(line.new_category.dre_group)
            return
        if line.category_id is not None and self.category.index_of(line.category_id) >= 0:
            self.category.select(line.category_id)
        else:
            self.category.setCurrentIndex(-1)
            self.category.setEditText("")
        self.new_name.setText(line.label[:MAX_CATEGORY_NAME])

    def _update_new_row(self) -> None:
        self.new_row.setVisible(self.category.value() == NEW)
        if self.isVisible():
            self.fit_to_content()

    def _save(self) -> tuple[LineChoice | None, str | None]:
        description = clean_text(
            self.description.text(), "description", max_length=MAX_DESCRIPTION, required=True
        )
        chosen = self.category.checked_value()
        if chosen == NEW:
            group = self.new_group.value()
            if not isinstance(group, DreGroup):
                raise ValidationError("dre_group", "Escolha o grupo do DRE.")
            kind = (
                CategoryKind.INCOME
                if self._line.kind is TransactionKind.INCOME
                else CategoryKind.EXPENSE
            )
            new = NewCategory(self.new_name.text(), kind, group)
            choice: LineChoice | None = LineChoice(new_category=new)
            if new == self._line.new_category and self._line.source is not LineSource.CHOICE:
                choice = None
        else:
            choice = LineChoice(category_id=str(chosen))
            if chosen == self._line.category_id and self._line.source is not LineSource.CHOICE:
                choice = None
        changed = description != self._line.description
        return choice, description if changed else None
