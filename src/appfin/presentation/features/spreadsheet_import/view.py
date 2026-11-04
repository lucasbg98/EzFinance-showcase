"""Importar planilha: assistente em passos + histórico (plano de importação §9).

1. Arquivo (.xlsx recomendado ou .csv): lido em segundo plano, nunca executado nem alterado;
2. Período e destino: ano, conta e situação de cada mês (realizado, projeção ou fora);
3. Categorias: só aparece quando há algo a decidir (linha sem categoria, sugestão pelo bloco,
   categoria nova, categoria padrão a mover);
4. Prévia e conferência: nada é gravado; confirmar só sem erros;
5. Concluído: contagens. O histórico permite desfazer.

O assistente é uma **página** (não um modal): ao bloquear o app, ela é destruída junto com a
planilha em memória e nada é gravado. A leitura do arquivo (disco + XML) roda fora da thread da
interface; prévia e confirmação usam o banco, que só a thread da interface acessa (skill
``concurrency``). Todo texto vindo da planilha é exibido como texto simples.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from appfin.application.spreadsheet_import import (
    ImportPreview,
    ImportResult,
    PreviewItem,
    PreviewLine,
)
from appfin.domain.entities import Category
from appfin.domain.spreadsheet_import.monthly_matrix import MonthStatus
from appfin.domain.spreadsheet_import.reconcile import ReconcileAction
from appfin.infrastructure.importers.safe_reader import SpreadsheetReadError, read_spreadsheet
from appfin.presentation.features.categories.view import DRE_LABELS
from appfin.presentation.features.spreadsheet_import import texts
from appfin.presentation.features.spreadsheet_import.history import ImportHistory
from appfin.presentation.features.spreadsheet_import.line_dialog import LineDialog
from appfin.presentation.features.spreadsheet_import.view_model import (
    ADJUSTABLE,
    ImportWizardModel,
    LoadedFile,
)
from appfin.presentation.shared.formatting import MONTHS, format_money
from appfin.presentation.shared.ui.feedback import confirm, friendly_message, show_error
from appfin.presentation.shared.ui.forms import ValueCombo, combo, plain_label, set_message
from appfin.presentation.shared.ui.table import (
    Column,
    RowsTableModel,
    TablePanel,
    make_table,
    selected_rows,
)
from appfin.presentation.shared.worker import Runner, qt_runner
from appfin.presentation.workspace import Workspace

# Gancho substituível nos testes (evita abrir o diálogo do sistema).
ask_spreadsheet_file: Callable[[QWidget], str] = lambda parent: QFileDialog.getOpenFileName(  # noqa: E731
    parent,
    "Escolher planilha",
    "",
    "Planilhas (*.xlsx *.xlsm *.csv);;Excel (*.xlsx *.xlsm);;CSV (*.csv)",
)[0]
FIRST_YEAR, LAST_YEAR = 2000, 2100


class Step(IntEnum):
    FILE = 0
    PERIOD = 1
    CATEGORIES = 2
    PREVIEW = 3
    DONE = 4


STEP_TITLES = {
    Step.FILE: "Passo 1 · Arquivo",
    Step.PERIOD: "Passo 2 · Período e destino",
    Step.CATEGORIES: "Passo 3 · Categorias",
    Step.PREVIEW: "Passo 4 · Prévia e conferência",
    Step.DONE: "Importação concluída",
}


@dataclass(frozen=True, slots=True)
class CheckRow:
    """Uma linha do quadro "Planilha versus app"."""

    month: int
    label: str
    sheet_cents: int | None
    app_cents: int
    ok: bool


def _month(month: int) -> str:
    return MONTHS[month - 1] if 1 <= month <= len(MONTHS) else "—"


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


# ---------------------------------------------------------------------- assistente
class ImportWizard(QWidget):
    imported = Signal()
    history_requested = Signal()

    def __init__(self, ws: Workspace, runner: Runner | None = None) -> None:
        super().__init__()
        self._ws = ws
        self._runner = runner or qt_runner(self)
        self.model = ImportWizardModel(ws.imports, lambda: ws.today().year)
        self._busy = False
        self._categories: dict[str, Category] = {}
        self.result: ImportResult | None = None

        self.step_title = plain_label("", "sectionTitle")
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_file_step())
        self.stack.addWidget(self._build_period_step())
        self.stack.addWidget(self._build_categories_step())
        self.stack.addWidget(self._build_preview_step())
        self.stack.addWidget(self._build_done_step())

        self.back_button = QPushButton("Voltar")
        self.restart_button = QPushButton("Recomeçar")
        self.next_button = QPushButton("Continuar")
        self.next_button.setObjectName("primary")
        footer = QHBoxLayout()
        footer.addWidget(self.restart_button)
        footer.addStretch(1)
        footer.addWidget(self.back_button)
        footer.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.step_title)
        layout.addWidget(self.stack, 1)
        layout.addLayout(footer)

        self.back_button.clicked.connect(self.go_back)
        self.next_button.clicked.connect(self.go_next)
        self.restart_button.clicked.connect(self.restart)
        ws.visibility.changed.connect(lambda _hidden: self._refresh_amounts())
        self._show(Step.FILE)

    # ------------------------------------------------------------------ passo 1: arquivo
    def _build_file_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(plain_label(texts.INTRO, ""))
        layout.addWidget(plain_label(texts.FILE_HELP, "muted"))
        self.choose_button = QPushButton("Escolher planilha…")
        self.choose_button.setObjectName("primary")
        row = QHBoxLayout()
        row.addWidget(self.choose_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.file_status = plain_label("", "muted")
        layout.addWidget(self.file_status)
        layout.addStretch(1)
        self.choose_button.clicked.connect(self.choose_file)
        return page

    def choose_file(self) -> None:
        if self._busy:
            return
        chosen = ask_spreadsheet_file(self)
        if chosen:
            self.read_file(Path(chosen))

    def read_file(self, path: Path) -> None:
        """Lê o arquivo fora da thread da interface. O nome só sugere o ano (não é logado)."""
        self._set_busy(True, "Lendo a planilha… aguarde")
        name = path.name
        self._runner(
            lambda: LoadedFile(read_spreadsheet(path), name), self._on_loaded, self._on_read_failed
        )

    def _on_loaded(self, loaded: Any) -> None:
        self._set_busy(False)
        accounts = [a for a in self._ws.catalog.list_accounts() if not a.archived]
        self.model.load(loaded, accounts[0].id if accounts else "")
        set_message(self.file_status, "Planilha lida.", ok=True)
        if not self._refresh():
            return
        self._fill_period_step()
        self._show(Step.PERIOD)

    def _on_read_failed(self, error: Exception) -> None:
        self._set_busy(False)
        if isinstance(error, SpreadsheetReadError):
            set_message(self.file_status, error.message)
        else:
            set_message(self.file_status, friendly_message(error, "import.read"))

    # ------------------------------------------------------------------ passo 2: período
    def _build_period_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.macro_warning = plain_label(
            "Arquivo com macros (.xlsm): só os valores foram lidos; nenhuma macro foi executada.",
            "error",
        )
        layout.addWidget(self.macro_warning)
        top = QGridLayout()
        self.sheet = combo([], "Aba da planilha")
        self.year = QSpinBox()
        self.year.setRange(FIRST_YEAR, LAST_YEAR)
        self.year.setAccessibleName("Ano da planilha")
        self.account = combo([], "Conta de destino")
        self.sheet_caption = plain_label("Aba", "fieldLabel")
        top.addWidget(self.sheet_caption, 0, 0)
        top.addWidget(self.sheet, 1, 0)
        top.addWidget(plain_label("Ano da planilha *", "fieldLabel"), 0, 1)
        top.addWidget(self.year, 1, 1)
        top.addWidget(plain_label("Conta de destino *", "fieldLabel"), 0, 2)
        top.addWidget(self.account, 1, 2)
        top.setColumnStretch(2, 1)
        layout.addLayout(top)
        layout.addWidget(
            plain_label(
                "Situação de cada mês, detectada pela planilha (realizado = tem receita). "
                "Ajuste se precisar, ou deixe um mês fora da importação.",
                "muted",
            )
        )
        grid = QGridLayout()
        self.month_boxes: list[ValueCombo] = []
        options = [(label, status) for status, label in texts.MONTH_STATUS_LABELS.items()]
        for index in range(12):
            box = combo(options, f"Situação de {_month(index + 1)}")
            self.month_boxes.append(box)
            row, column = index % 6, (index // 6) * 2
            grid.addWidget(plain_label(_month(index + 1), "fieldLabel"), row, column)
            grid.addWidget(box, row, column + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.sheet.currentIndexChanged.connect(self._on_sheet_changed)
        return page

    def _fill_period_step(self) -> None:
        preview = self.model.preview
        names = self.model.sheet_names
        self.sheet.blockSignals(True)
        self.sheet.set_options([(name, index) for index, name in enumerate(names)])
        self.sheet.select(self.model.sheet_index)
        self.sheet.blockSignals(False)
        self.sheet.setVisible(len(names) > 1)
        self.sheet_caption.setVisible(len(names) > 1)
        self.year.setValue(self.model.year)
        accounts = [a for a in self._ws.catalog.list_accounts() if not a.archived]
        self.account.set_options([(a.name, a.id) for a in accounts])
        self.account.select(self.model.account_id)
        self.macro_warning.setVisible(bool(preview and preview.has_macros))
        if preview is not None:
            for index, box in enumerate(self.month_boxes):
                box.select(preview.months[index])

    def _on_sheet_changed(self, _index: int) -> None:
        index = self.sheet.value()
        if isinstance(index, int) and index != self.model.sheet_index:
            self.model.set_sheet(index)
            if self._refresh():
                self._fill_period_step()

    def _apply_period(self) -> None:
        self.model.year = self.year.value()
        self.model.account_id = str(self.account.value() or "")
        preview = self.model.preview
        for index, box in enumerate(self.month_boxes):
            status = box.value()
            if isinstance(status, MonthStatus) and preview is not None:
                self.model.set_month_status(index + 1, status)

    # ------------------------------------------------------------------ passo 3: categorias
    def _build_categories_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(plain_label(texts.CATEGORIES_HELP, "muted"))
        columns = [
            Column("Linha", lambda line: str(line.row), align_right=True),
            Column("Rótulo na planilha", lambda line: line.label, stretch=True),
            Column("Bloco", lambda line: texts.block_label(line.block)),
            Column("Tipo", lambda line: texts.KIND_LABELS[line.kind]),
            Column("Categoria", self._category_text, stretch=True),
            Column(
                "Situação",
                lambda line: texts.SOURCE_LABELS[line.source],
                color=lambda line: "#B42318" if not line.is_resolved else None,
            ),
        ]
        self.lines_model = RowsTableModel(columns, self)
        self.lines_table = make_table(self.lines_model, columns)
        layout.addWidget(TablePanel(self.lines_table, self.lines_model, "Nenhuma linha."), 1)
        self.edit_line_button = QPushButton("Alterar linha…")
        row = QHBoxLayout()
        self.lines_summary = plain_label("", "muted")
        row.addWidget(self.lines_summary, 1)
        row.addWidget(self.edit_line_button)
        layout.addLayout(row)
        self.moves_title = plain_label(
            "Categorias padrão que estão em outro grupo do DRE (marque para mover):", "fieldLabel"
        )
        layout.addWidget(self.moves_title)
        self.moves_box = QVBoxLayout()
        layout.addLayout(self.moves_box)
        self.move_checks: dict[str, QCheckBox] = {}
        self.edit_line_button.clicked.connect(self.edit_selected_line)
        self.lines_table.doubleClicked.connect(lambda _i: self.edit_selected_line())
        return page

    def _category_text(self, line: PreviewLine) -> str:
        if line.new_category is not None:
            group = DRE_LABELS.get(line.new_category.dre_group, "")
            return f"Nova: {line.new_category.name} ({group})"
        category = self._categories.get(line.category_id or "")
        if category is None:
            return "—"
        parent = self._categories.get(category.parent_id or "")
        return f"{parent.name} / {category.name}" if parent else category.name

    def _fill_categories_step(self) -> None:
        self._categories = {
            c.id: c for c in self._ws.catalog.list_categories(include_archived=True)
        }
        lines = self.model.attention_lines()
        self.lines_model.set_rows(lines)
        missing = sum(1 for line in lines if not line.is_resolved and not line.is_empty)
        self.lines_summary.setText(
            f"{missing} linha(s) sem categoria." if missing else "Todas as linhas têm categoria."
        )
        preview = self.model.preview
        moves = preview.category_moves if preview else ()
        while self.moves_box.count():
            item = self.moves_box.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        self.move_checks = {}
        for move in moves:
            origin = (
                DRE_LABELS.get(move.from_group, "sem grupo") if move.from_group else "sem grupo"
            )
            check = QCheckBox(f"{move.name}: {origin} → {DRE_LABELS[move.to_group]}")
            check.setChecked(move.category_id in self.model.move_category_ids)
            self.moves_box.addWidget(check)
            self.move_checks[move.category_id] = check
        self.moves_title.setVisible(bool(moves))

    def edit_selected_line(self) -> None:
        rows = selected_rows(self.lines_table)
        if not rows:
            return
        line = self.lines_model.row_at(rows[0])
        categories = list(self._categories.values())
        dialog = LineDialog(line, categories, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        choice, description = dialog.result_value
        self.model.set_line(line.key, choice, description)
        self._apply_moves()
        if self._refresh():
            self._fill_categories_step()

    def _apply_moves(self) -> None:
        for category_id, check in self.move_checks.items():
            self.model.set_move(category_id, check.isChecked())

    # ------------------------------------------------------------------ passo 4: prévia
    def _build_preview_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(plain_label(texts.PREVIEW_HELP, "muted"))
        self.counts_label = plain_label("", "")
        self.verdict = plain_label("", "")
        layout.addWidget(self.counts_label)
        layout.addWidget(self.verdict)
        self.preview_tabs = QTabWidget()
        layout.addWidget(self.preview_tabs, 1)

        items_page = QWidget()
        items_layout = QVBoxLayout(items_page)
        items_layout.setContentsMargins(0, 8, 0, 0)
        self.item_filter = combo(
            [("Só o que muda", "changes"), ("Todos os lançamentos", "all")], "Mostrar"
        )
        filter_row = QHBoxLayout()
        filter_row.addWidget(plain_label("Mostrar", "fieldLabel"))
        filter_row.addWidget(self.item_filter)
        filter_row.addStretch(1)
        items_layout.addLayout(filter_row)
        visibility = self._ws.visibility
        item_columns = [
            Column("Linha", lambda i: str(i.row) if i.row else "—", align_right=True),
            Column("Mês", lambda i: _month(i.month)),
            Column("Descrição", lambda i: i.description, stretch=True),
            Column(
                "Ação",
                self._action_text,
                color=lambda i: texts.ACTION_COLORS.get(i.effective_action),
            ),
            Column(
                "Valor",
                lambda i: ""
                if i.amount_cents is None
                else format_money(i.amount_cents, visibility),
                align_right=True,
            ),
            Column(
                "No app hoje",
                lambda i: ""
                if i.current_amount_cents is None
                else format_money(i.current_amount_cents, visibility),
                align_right=True,
            ),
            Column("Situação", lambda i: "" if i.amount_cents is None else self._paid_text(i)),
            Column("Observação", lambda i: _first_line(i.notes)),
        ]
        self.items_model = RowsTableModel(item_columns, self)
        self.items_table = make_table(self.items_model, item_columns)
        self.items_panel = TablePanel(
            self.items_table, self.items_model, "Nada a gravar: esta planilha já está importada."
        )
        items_layout.addWidget(self.items_panel, 1)
        self.preview_tabs.addTab(items_page, "Lançamentos")

        check_columns = [
            Column("Mês", lambda c: _month(c.month)),
            Column("Linha da planilha", lambda c: c.label, stretch=True),
            Column(
                "Planilha",
                lambda c: "erro"
                if c.sheet_cents is None
                else format_money(c.sheet_cents, visibility),
                align_right=True,
            ),
            Column("App", lambda c: format_money(c.app_cents, visibility), align_right=True),
            Column(
                "Resultado",
                lambda c: texts.OK_MARK if c.ok else texts.FAIL_MARK,
                color=lambda c: None if c.ok else "#B42318",
            ),
        ]
        self.checks_model = RowsTableModel(check_columns, self)
        self.checks_table = make_table(self.checks_model, check_columns)
        self.preview_tabs.addTab(
            TablePanel(self.checks_table, self.checks_model, "Nenhuma conferência."),
            "Planilha versus app",
        )

        issue_columns = [
            Column("Tipo", lambda p: texts.LEVEL_LABELS[p.level]),
            Column("Linha", lambda p: str(p.row) if p.row else "—", align_right=True),
            Column("Mês", lambda p: _month(p.month) if p.month else "—"),
            Column("Problema", lambda p: p.message, stretch=True),
        ]
        self.issues_model = RowsTableModel(issue_columns, self)
        self.issues_table = make_table(self.issues_model, issue_columns)
        self.preview_tabs.addTab(
            TablePanel(self.issues_table, self.issues_model, "Nenhum problema encontrado."),
            "Problemas",
        )
        self.item_filter.currentIndexChanged.connect(lambda _i: self._fill_items())
        self.items_table.doubleClicked.connect(lambda _i: self.toggle_selected_item())
        return page

    @staticmethod
    def _action_text(item: PreviewItem) -> str:
        if not item.selected:
            return f"{texts.ACTION_LABELS[ReconcileAction.KEEP]} (desmarcado)"
        return texts.ACTION_LABELS[item.action]

    @staticmethod
    def _paid_text(item: PreviewItem) -> str:
        return "Pago" if item.is_paid else "Pendente"

    def _fill_preview_step(self) -> None:
        preview = self.model.preview
        if preview is None:
            return
        counts = preview.counts
        self.counts_label.setText(
            f"Novos: {counts.created} · Substituir: {counts.replaced} · Remover: "
            f"{counts.removed} · Já importados: {counts.skipped} · Manter o do app: {counts.kept}"
        )
        self._fill_items()
        self.checks_model.set_rows(self._check_rows(preview))
        self.issues_model.set_rows(list(preview.issues))
        problems = len(preview.issues)
        self.preview_tabs.setTabText(2, f"Problemas ({problems})" if problems else "Problemas")
        set_message(self.verdict, self._verdict_text(preview), ok=preview.can_confirm)
        self._update_buttons()

    def _fill_items(self) -> None:
        preview = self.model.preview
        if preview is None:
            return
        only_changes = self.item_filter.value() == "changes"
        rows = [
            item
            for item in preview.items
            if not only_changes or item.action is not ReconcileAction.SKIP
        ]
        rows.sort(key=lambda i: (i.month, i.row))
        self.items_model.set_rows(rows)

    @staticmethod
    def _check_rows(preview: ImportPreview) -> list[CheckRow]:
        rows = [
            CheckRow(
                c.month,
                texts.TOTAL_LABELS.get(c.label, c.label),
                c.sheet_cents,
                c.expected_cents,
                c.ok,
            )
            for c in preview.checks
        ] + [
            CheckRow(
                c.month,
                texts.DRE_CHECK_LABELS.get(c.label, c.label),
                c.sheet_cents,
                c.app_cents,
                c.ok,
            )
            for c in preview.dre_checks
        ]
        return sorted(rows, key=lambda r: (r.ok, r.month))

    @staticmethod
    def _verdict_text(preview: ImportPreview) -> str:
        failed = sum(1 for c in preview.checks if not c.ok)
        dre_total = len(preview.dre_checks)
        dre_ok = sum(1 for c in preview.dre_checks if c.ok)
        checks = (
            f"Totais da planilha: {len(preview.checks) - failed} de {len(preview.checks)} "
            f"conferem · DRE: {dre_ok} de {dre_total}."
        )
        if preview.can_confirm:
            if not preview.has_transaction_changes and not preview.new_categories:
                return f"{checks} Nada a gravar: esta planilha já está importada."
            return f"{checks} Tudo certo para importar."
        reasons = []
        if preview.errors:
            reasons.append(f"{len(preview.errors)} erro(s)")
        if failed:
            reasons.append(f"{failed} total(is) que não conferem")
        if any(not c.ok and c.blocking for c in preview.dre_checks):
            reasons.append("resultado do DRE diferente da planilha")
        return (
            f"{checks} A importação está bloqueada: {', '.join(reasons) or 'sem lançamentos'}. "
            "Veja a aba Problemas; corrija a planilha (ou as categorias) e tente de novo."
        )

    def toggle_selected_item(self) -> None:
        rows = selected_rows(self.items_table)
        if not rows:
            return
        item = self.items_model.row_at(rows[0])
        if item.action not in ADJUSTABLE:
            return
        self.model.toggle_keep(item)
        if self._refresh():
            self._fill_preview_step()

    def confirm_import(self) -> None:
        preview = self.model.preview
        if preview is None or not preview.can_confirm or self._busy:
            return
        counts = preview.counts
        question = (
            f"Gravar {counts.created} lançamento(s) novo(s), substituir {counts.replaced} e "
            f"remover {counts.removed}?"
            + (
                f" Serão criadas {len(preview.new_categories)} categoria(s)."
                if preview.new_categories
                else ""
            )
            + " Antes, o app faz um backup automático. Você pode desfazer depois, no Histórico."
        )
        if not confirm(self, question, accept="Importar"):
            return
        self._set_busy(True, "Importando… aguarde")
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.result = self.model.confirm()
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            QGuiApplication.restoreOverrideCursor()
            self._set_busy(False)
            show_error(self, error, "import.confirm")
            if self._refresh():
                self._fill_preview_step()
            return
        QGuiApplication.restoreOverrideCursor()
        self._set_busy(False)
        self._fill_done_step(self.result)
        self._show(Step.DONE)
        self.imported.emit()

    # ------------------------------------------------------------------ passo 5: concluído
    def _build_done_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.done_text = plain_label("", "")
        layout.addWidget(self.done_text)
        self.again_button = QPushButton("Importar outra planilha")
        self.history_button = QPushButton("Ver histórico")
        row = QHBoxLayout()
        row.addWidget(self.again_button)
        row.addWidget(self.history_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.again_button.clicked.connect(self.restart)
        self.history_button.clicked.connect(self.history_requested.emit)
        return page

    def _fill_done_step(self, result: ImportResult) -> None:
        counts = result.counts
        parts = [
            text
            for amount, text in (
                (counts.created, f"{counts.created} lançamento(s) novo(s)"),
                (counts.replaced, f"{counts.replaced} substituído(s)"),
                (counts.removed, f"{counts.removed} removido(s)"),
                (counts.skipped, f"{counts.skipped} já importado(s)"),
                (counts.kept, f"{counts.kept} mantido(s) como estavam no app"),
                (result.categories_created, f"{result.categories_created} categoria(s) criada(s)"),
                (result.categories_moved, f"{result.categories_moved} categoria(s) movida(s)"),
            )
            if amount
        ]
        title = "Importação gravada" if result.batch is not None else "Nenhum lançamento mudou"
        text = f"{title}: {', '.join(parts)}." if parts else f"{title}."
        self.done_text.setText(text + " Os lançamentos já aparecem nas outras telas e no DRE.")

    # ------------------------------------------------------------------ navegação
    def go_next(self) -> None:
        if self._busy:
            return
        step = Step(self.stack.currentIndex())
        if step is Step.PERIOD:
            self._apply_period()
            if self._refresh():
                self._enter_after_period()
        elif step is Step.CATEGORIES:
            self._apply_moves()
            if self._refresh():
                self._fill_preview_step()
                self._show(Step.PREVIEW)
        elif step is Step.PREVIEW:
            self.confirm_import()

    def _enter_after_period(self) -> None:
        if self.model.needs_review():
            self._fill_categories_step()
            self._show(Step.CATEGORIES)
        else:
            self._fill_preview_step()
            self._show(Step.PREVIEW)

    def go_back(self) -> None:
        if self._busy:
            return
        step = Step(self.stack.currentIndex())
        if step is Step.PREVIEW and self.model.needs_review():
            self._fill_categories_step()
            self._show(Step.CATEGORIES)
        elif step in (Step.PREVIEW, Step.CATEGORIES):
            self._fill_period_step()
            self._show(Step.PERIOD)
        elif step is Step.PERIOD:
            self.restart()

    def restart(self) -> None:
        if self._busy:
            return
        self.model.clear()
        self.result = None
        for model in (self.lines_model, self.items_model, self.checks_model, self.issues_model):
            model.set_rows([])
        self.file_status.setText("")
        self._show(Step.FILE)

    def current_step(self) -> Step:
        return Step(self.stack.currentIndex())

    def _show(self, step: Step) -> None:
        self.stack.setCurrentIndex(int(step))
        self.step_title.setText(STEP_TITLES[step])
        self._update_buttons()

    def _update_buttons(self) -> None:
        step = Step(self.stack.currentIndex())
        self.back_button.setVisible(step in (Step.PERIOD, Step.CATEGORIES, Step.PREVIEW))
        self.restart_button.setVisible(step in (Step.PERIOD, Step.CATEGORIES, Step.PREVIEW))
        self.next_button.setVisible(step in (Step.PERIOD, Step.CATEGORIES, Step.PREVIEW))
        preview = self.model.preview
        if step is Step.PREVIEW:
            self.next_button.setText("Confirmar importação")
            has_work = bool(
                preview
                and (
                    preview.has_transaction_changes
                    or preview.new_categories
                    or preview.move_category_ids
                )
            )
            self.next_button.setEnabled(bool(preview and preview.can_confirm and has_work))
        else:
            self.next_button.setText("Continuar")
            self.next_button.setEnabled(not self._busy)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.choose_button.setEnabled(not busy)
        if busy and text:
            set_message(self.file_status, text, ok=True)
        self._update_buttons()

    def _refresh(self) -> bool:
        """Nova prévia com as escolhas atuais. Erro = mensagem amigável e fica no passo atual."""
        try:
            self.model.refresh()
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "import.preview")
            return False
        return True

    def _refresh_amounts(self) -> None:
        for model in (self.items_model, self.checks_model):
            model.refresh()


# ---------------------------------------------------------------------- página
class SpreadsheetImportPage(QWidget):
    def __init__(self, ws: Workspace, runner: Runner | None = None) -> None:
        super().__init__()
        self.wizard = ImportWizard(ws, runner)
        self.history = ImportHistory(ws)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.wizard, "Importar")
        self.tabs.addTab(self.history, "Histórico")
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Importar planilha", "title"))
        layout.addWidget(
            plain_label('Carga da planilha "Fluxo de caixa" e histórico das importações.', "muted")
        )
        layout.addWidget(self.tabs, 1)
        self.wizard.imported.connect(self.history.refresh)
        self.wizard.history_requested.connect(lambda: self.tabs.setCurrentWidget(self.history))
        self.tabs.currentChanged.connect(lambda _i: self.history.refresh())

    def reload(self) -> None:
        self.history.refresh()
