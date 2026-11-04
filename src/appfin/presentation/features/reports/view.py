"""Relatórios: DRE (caixa ou competência), totais por categoria e contas vencidas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget

from appfin.application.export_table import Cell, ColumnKind, ExportColumn, ExportTable
from appfin.application.read_models import (
    CategoryTotal,
    StatementCategoryTotal,
    StatementTransactionsFilter,
    TransactionFilter,
    TransactionRow,
)
from appfin.br_format import format_percent_tenths, percent_tenths
from appfin.domain.enums import ReportBasis, TransactionKind, TransactionStatus
from appfin.domain.income_statement import StatementLine
from appfin.presentation.features.reports.statement_details import StatementTransactionsDialog
from appfin.presentation.features.reports.statement_rows import (
    GroupKey,
    RowStyle,
    StatementRow,
    build_statement_rows,
)
from appfin.presentation.features.reports.style import NEGATIVE, POSITIVE
from appfin.presentation.shared.formatting import format_date, format_money
from appfin.presentation.shared.ui.export_flow import export_table
from appfin.presentation.shared.ui.forms import ValueCombo, combo, plain_label
from appfin.presentation.shared.ui.period import PeriodPicker
from appfin.presentation.shared.ui.table import Column, RowsTableModel, TablePanel, make_table
from appfin.presentation.workspace import Workspace

BASIS_NAMES = {ReportBasis.CASH: "caixa", ReportBasis.ACCRUAL: "competência"}
BASIS_HELP = {
    ReportBasis.CASH: "Regime de caixa: só o que foi pago/recebido, pela data do pagamento.",
    ReportBasis.ACCRUAL: (
        "Regime de competência: tudo o que foi lançado (pago ou não), pela data de competência."
    ),
}


def percent_text(part: int, whole: int) -> str:
    """Percentual com uma casa, só com inteiros: 1234/10000 → "12,3%"."""
    return format_percent_tenths(percent_tenths(part, whole))


def _basis_box() -> ValueCombo:
    return combo(
        [("Caixa (pagamentos)", ReportBasis.CASH), ("Competência", ReportBasis.ACCRUAL)],
        "Regime",
    )


# ---------------------------------------------------------------------- DRE
STATEMENT_HINT = (
    "Dê duplo clique (ou Enter) num grupo com ▸ para ver as categorias; "
    "numa categoria, para ver os lançamentos."
)
_CATEGORY_INDENT = "        "


def statement_label(row: StatementRow) -> str:
    """Texto da 1ª coluna: seta nos grupos que expandem, recuo nas categorias."""
    if row.style is RowStyle.CATEGORY:
        return _CATEGORY_INDENT + row.label
    if row.expandable:
        return ("▾ " if row.expanded else "▸ ") + row.label
    return "   " + row.label if row.style is RowStyle.GROUP else row.label


class IncomeStatementTab(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self.period = PeriodPicker(ws.today())
        self.basis = _basis_box()
        self.help = plain_label("", "muted")
        self._gross = 0
        self._lines: list[StatementLine] = []
        self._details: list[StatementCategoryTotal] = []
        self.expanded: set[GroupKey] = set()
        columns = [
            Column(
                "Linha",
                statement_label,
                stretch=True,
                bold=lambda row: row.style in (RowStyle.SUBTOTAL, RowStyle.RESULT),
            ),
            Column(
                "Valor",
                lambda row: format_money(row.amount.cents, ws.visibility),
                align_right=True,
                bold=lambda row: row.style in (RowStyle.SUBTOTAL, RowStyle.RESULT),
                color=self._color,
            ),
            Column(
                "% da receita bruta",
                lambda row: percent_text(row.amount.cents, self._gross),
                align_right=True,
            ),
        ]
        self.model = RowsTableModel(columns, self)
        self.table = make_table(self.model, columns)
        self.table.setAccessibleName("Demonstrativo de resultado (DRE)")
        bar = QHBoxLayout()
        bar.addWidget(self.period)
        bar.addStretch(1)
        bar.addWidget(plain_label("Regime:", "muted", wrap=False))
        bar.addWidget(self.basis)
        self.expand_button = QPushButton("Expandir tudo")
        self.collapse_button = QPushButton("Recolher tudo")
        self.export_button = QPushButton("Exportar")
        for button in (self.expand_button, self.collapse_button, self.export_button):
            bar.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.help)
        layout.addWidget(plain_label(STATEMENT_HINT, "muted"))
        layout.addWidget(self.table, 1)
        self.period.changed.connect(self.reload)
        self.basis.currentIndexChanged.connect(lambda _i: self.reload())
        self.expand_button.clicked.connect(self.expand_all)
        self.collapse_button.clicked.connect(self.collapse_all)
        self.export_button.clicked.connect(self.export)
        self.table.activated.connect(self._on_activated)
        ws.visibility.changed.connect(lambda _h: self.model.refresh())
        self.reload()

    # ------------------------------------------------------------------ expandir / detalhar
    def toggle(self, group: GroupKey) -> None:
        self.expanded ^= {group}
        self._render(keep=group)

    def expand_all(self) -> None:
        self.expanded = {detail.group for detail in self._details}
        self._render()

    def collapse_all(self) -> None:
        self.expanded = set()
        self._render()

    def open_category(self, row: StatementRow) -> None:
        start, end = self.period.range()
        basis = self.basis.value()
        criteria = StatementTransactionsFilter(start, end, basis, row.category_id)
        title = f"{row.label} — {self.period.label.text()} ({BASIS_NAMES[basis]})"
        dialog = StatementTransactionsDialog(self._ws, criteria, title, row.count or 0, self)
        dialog.exec()
        if dialog.changed:
            self.reload()

    def _on_activated(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        row: StatementRow = self.model.row_at(index.row())
        if row.expandable and row.group is not None:
            self.toggle(row.group)
        elif row.style is RowStyle.CATEGORY:
            self.open_category(row)

    # ------------------------------------------------------------------ dados
    def export(self) -> None:
        """Exporta o que está na tela: grupos expandidos levam as categorias junto."""
        basis = self.basis.value()
        table = ExportTable(
            "DRE",
            [
                ExportColumn("Linha"),
                ExportColumn("Valor", ColumnKind.MONEY),
                ExportColumn("% da receita bruta", ColumnKind.PERCENT),
            ],
            [
                [
                    (_CATEGORY_INDENT + row.label) if row.style is RowStyle.CATEGORY else row.label,
                    row.amount.cents,
                    percent_tenths(row.amount.cents, self._gross),
                ]
                for row in self.model.rows()
            ],
        )
        start, _end = self.period.range()
        export_table(
            self,
            table,
            f"DRE {start:%Y-%m} {'caixa' if basis is ReportBasis.CASH else 'competencia'}",
        )

    @staticmethod
    def _color(row: StatementRow) -> str | None:
        if row.style in (RowStyle.GROUP, RowStyle.CATEGORY):
            return None
        return NEGATIVE if row.amount.cents < 0 else POSITIVE

    def reload(self) -> None:
        basis = self.basis.value()
        start, end = self.period.range()
        self._lines = self._ws.reports.income_statement(start, end, basis)
        self._details = self._ws.reports.income_statement_details(start, end, basis)
        self._gross = self._lines[0].amount.cents if self._lines else 0
        self.help.setText(BASIS_HELP[basis])
        self._render()

    def _render(self, keep: GroupKey | None = None) -> None:
        rows = build_statement_rows(self._lines, self._details, self.expanded)
        self.model.set_rows(rows)
        if keep is None:
            return
        for position, row in enumerate(rows):
            if row.style is not RowStyle.CATEGORY and row.group == keep:
                self.table.selectRow(position)
                break


# ---------------------------------------------------------------------- categorias
@dataclass(frozen=True, slots=True)
class CategoryLine:
    label: str
    count: int | None
    cents: int
    share_tenths: int | None
    style: str  # "header" | "item" | "total" | "result"


def build_category_lines(
    totals: list[CategoryTotal], kind_names: dict[TransactionKind, str]
) -> list[CategoryLine]:
    lines: list[CategoryLine] = []
    sums: dict[TransactionKind, int] = {}
    for kind in (TransactionKind.INCOME, TransactionKind.EXPENSE):
        items = [t for t in totals if t.kind is kind]
        total = sum(t.total_cents for t in items)
        sums[kind] = total
        lines.append(CategoryLine(kind_names[kind], None, 0, None, "header"))
        for item in items:
            name = item.category_name or "(sem categoria)"
            label = f"{item.group_name} / {name}" if item.group_name else name
            lines.append(
                CategoryLine(
                    label,
                    item.count,
                    item.total_cents,
                    percent_tenths(item.total_cents, total),
                    "item",
                )
            )
        lines.append(
            CategoryLine(f"Total de {kind_names[kind].lower()}", None, total, None, "total")
        )
    result = sums[TransactionKind.INCOME] - sums[TransactionKind.EXPENSE]
    lines.append(CategoryLine("Resultado (receitas - despesas)", None, result, None, "result"))
    return lines


class CategoryTab(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self.period = PeriodPicker(ws.today())
        self.basis = _basis_box()
        columns = [
            Column("Categoria", self._label, stretch=True, bold=lambda r: r.style != "item"),
            Column("Qtde.", lambda r: "" if r.count is None else str(r.count), align_right=True),
            Column(
                "Total",
                lambda r: "" if r.style == "header" else format_money(r.cents, ws.visibility),
                align_right=True,
                bold=lambda r: r.style != "item",
                color=lambda r: (NEGATIVE if r.cents < 0 else POSITIVE)
                if r.style == "result"
                else None,
            ),
            Column("% do total", lambda r: format_percent_tenths(r.share_tenths), align_right=True),
        ]
        self.model = RowsTableModel(columns, self)
        self.table = make_table(self.model, columns)
        bar = QHBoxLayout()
        bar.addWidget(self.period)
        bar.addStretch(1)
        bar.addWidget(plain_label("Regime:", "muted", wrap=False))
        bar.addWidget(self.basis)
        self.export_button = QPushButton("Exportar")
        bar.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        self.period.changed.connect(self.reload)
        self.basis.currentIndexChanged.connect(lambda _i: self.reload())
        ws.visibility.changed.connect(lambda _h: self.model.refresh())
        self.reload()

    def export(self) -> None:
        rows: list[list[Cell]] = [
            [r.label, r.count, None if r.style == "header" else r.cents, r.share_tenths]
            for r in self.model.rows()
        ]
        table = ExportTable(
            "Por categoria",
            [
                ExportColumn("Categoria"),
                ExportColumn("Qtde.", ColumnKind.INTEGER),
                ExportColumn("Total", ColumnKind.MONEY),
                ExportColumn("% do total", ColumnKind.PERCENT),
            ],
            rows,
        )
        start, _end = self.period.range()
        export_table(self, table, f"Categorias {start:%Y-%m}")

    @staticmethod
    def _label(row: CategoryLine) -> str:
        return ("    " + row.label) if row.style == "item" else row.label

    def reload(self) -> None:
        start, end = self.period.range()
        totals = self._ws.reports.category_totals(start, end, self.basis.value())
        names = {TransactionKind.INCOME: "Receitas", TransactionKind.EXPENSE: "Despesas"}
        self.model.set_rows(build_category_lines(totals, names))


# ---------------------------------------------------------------------- vencidas
class OverdueTab(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self.kind = combo(
            [
                ("Receber e pagar", None),
                ("Só contas a receber", TransactionKind.INCOME),
                ("Só contas a pagar", TransactionKind.EXPENSE),
            ],
            "Tipo",
        )
        columns = [
            Column("Tipo", lambda r: "Receber" if r.kind is TransactionKind.INCOME else "Pagar"),
            Column("Vencimento", lambda r: format_date(r.due_date)),
            Column("Dias de atraso", lambda r: str(self._days_late(r)), align_right=True),
            Column("Descrição", lambda r: r.description, stretch=True),
            Column("Contato", lambda r: r.contact_name or ""),
            Column("Conta", lambda r: r.account_name),
            Column(
                "Valor",
                lambda r: format_money(r.amount_cents, ws.visibility),
                align_right=True,
                color=lambda _r: NEGATIVE,
            ),
        ]
        self.model = RowsTableModel(columns, self)
        self.panel = TablePanel(
            make_table(self.model, columns), self.model, "Nenhuma conta vencida. Tudo em dia!"
        )
        self.total = plain_label("", "muted")
        bar = QHBoxLayout()
        bar.addWidget(plain_label("Mostrar:", "muted", wrap=False))
        bar.addWidget(self.kind)
        bar.addStretch(1)
        self.export_button = QPushButton("Exportar")
        bar.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.panel, 1)
        layout.addWidget(self.total)
        self.kind.currentIndexChanged.connect(lambda _i: self.reload())
        self.export_button.clicked.connect(self.export)
        ws.visibility.changed.connect(lambda _h: self._render_total())
        self.rows: list[TransactionRow] = []
        self.reload()

    def export(self) -> None:
        table = ExportTable(
            "Vencidas",
            [
                ExportColumn("Tipo"),
                ExportColumn("Vencimento", ColumnKind.DATE),
                ExportColumn("Dias de atraso", ColumnKind.INTEGER),
                ExportColumn("Descrição"),
                ExportColumn("Contato"),
                ExportColumn("Conta"),
                ExportColumn("Valor", ColumnKind.MONEY),
            ],
            [
                [
                    "Receber" if r.kind is TransactionKind.INCOME else "Pagar",
                    r.due_date,
                    self._days_late(r),
                    r.description,
                    r.contact_name or "",
                    r.account_name,
                    r.amount_cents,
                ]
                for r in self.rows
            ],
        )
        export_table(self, table, f"Vencidas {self._ws.today():%Y-%m-%d}")

    def _days_late(self, row: TransactionRow) -> int:
        return (self._ws.today() - row.due_date).days

    def reload(self) -> None:
        kind = self.kind.value()
        kinds = (
            frozenset({kind})
            if kind is not None
            else frozenset({TransactionKind.INCOME, TransactionKind.EXPENSE})
        )
        criteria = TransactionFilter(
            start=date(2000, 1, 1),
            end=self._ws.today(),
            kinds=kinds,
            statuses=frozenset({TransactionStatus.PENDING}),
            overdue_only=True,
            limit=1000,
        )
        self.rows = self._ws.reports.transactions(criteria)
        self.model.set_rows(self.rows)
        self._render_total()

    def _render_total(self) -> None:
        self.model.refresh()
        receive = sum(r.amount_cents for r in self.rows if r.kind is TransactionKind.INCOME)
        pay = sum(r.amount_cents for r in self.rows if r.kind is TransactionKind.EXPENSE)
        vis = self._ws.visibility
        self.total.setText(
            f"{len(self.rows)} vencida(s) — a receber {format_money(receive, vis)} · "
            f"a pagar {format_money(pay, vis)}"
            if self.rows
            else ""
        )


class ReportsPage(QWidget):
    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self.tabs = QTabWidget()
        self.income_statement = IncomeStatementTab(ws)
        self.categories = CategoryTab(ws)
        self.overdue = OverdueTab(ws)
        self.tabs.addTab(self.income_statement, "DRE")
        self.tabs.addTab(self.categories, "Por categoria")
        self.tabs.addTab(self.overdue, "Vencidas")
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Relatórios e DRE", "title"))
        layout.addWidget(
            plain_label(
                "Demonstrativo de resultado, totais por categoria e contas em atraso.", "muted"
            )
        )
        layout.addWidget(self.tabs, 1)

    def reload(self) -> None:
        for tab in (self.income_statement, self.categories, self.overdue):
            tab.reload()
