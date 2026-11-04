"""Histórico de importações, com "Desfazer" (só contagens: o lote não guarda nome de arquivo)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from appfin.application.spreadsheet_import import UndoCheck
from appfin.domain.entities import ImportBatch
from appfin.presentation.features.backup.view import format_moment
from appfin.presentation.features.spreadsheet_import import texts
from appfin.presentation.shared.formatting import format_date, format_money
from appfin.presentation.shared.ui.feedback import confirm, show_error, show_info
from appfin.presentation.shared.ui.forms import plain_label
from appfin.presentation.shared.ui.table import (
    Column,
    RowsTableModel,
    TablePanel,
    make_table,
    selected_rows,
)
from appfin.presentation.workspace import Workspace

MAX_LISTED = 10


def _status(batch: ImportBatch) -> str:
    return f"Desfeita em {format_moment(batch.undone_at)}" if batch.undone_at else "Ativa"


COLUMNS = [
    Column("Importada em", lambda b: format_moment(b.imported_at)),
    Column("Arquivo", lambda b: texts.SOURCE_FILE_LABELS[b.source]),
    Column("Ano", lambda b: str(b.period_year)),
    Column("Novos", lambda b: str(b.counts.created), align_right=True),
    Column("Substituídos", lambda b: str(b.counts.replaced), align_right=True),
    Column("Removidos", lambda b: str(b.counts.removed), align_right=True),
    Column("Já importados", lambda b: str(b.counts.skipped), align_right=True),
    Column("Mantidos", lambda b: str(b.counts.kept), align_right=True),
    Column("Situação", _status, stretch=True),
]


class ImportHistory(QWidget):
    undone = Signal()

    def __init__(self, ws: Workspace) -> None:
        super().__init__()
        self._ws = ws
        self.model = RowsTableModel(COLUMNS, self)
        self.table = make_table(self.model, COLUMNS)
        self.panel = TablePanel(self.table, self.model, "Nenhuma planilha importada ainda.")
        self.undo_button = QPushButton("Desfazer importação…")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(plain_label(texts.UNDO_HELP, "muted"))
        layout.addWidget(self.panel, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.undo_button)
        layout.addLayout(buttons)
        self.undo_button.clicked.connect(self.undo_selected)
        self.table.selectionModel().selectionChanged.connect(lambda *_a: self._update_buttons())
        self.refresh()

    def refresh(self) -> None:
        try:
            batches = self._ws.imports.history()
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "import.history")
            batches = []
        self.model.set_rows(batches)
        self._update_buttons()

    def selected(self) -> ImportBatch | None:
        rows = selected_rows(self.table)
        return self.model.row_at(rows[0]) if rows else None

    def select_row(self, row: int) -> None:
        self.table.selectRow(row)

    def _update_buttons(self) -> None:
        batch = self.selected()
        self.undo_button.setEnabled(batch is not None and not batch.is_undone)

    def undo_selected(self) -> None:
        batch = self.selected()
        if batch is None or batch.is_undone:
            return
        try:
            check = self._ws.imports.undo_check(batch.id)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "import.undo")
            return
        if not check.ok:
            show_info(self, self.blocked_text(check))
            return
        created = batch.counts.created + batch.counts.replaced
        question = (
            f"Desfazer a importação de {format_moment(batch.imported_at)}? "
            f"{created} lançamento(s) serão excluídos"
            + (
                f" e {batch.counts.replaced + batch.counts.removed} lançamento(s) anteriores "
                "voltam a valer."
                if batch.counts.replaced or batch.counts.removed
                else "."
            )
        )
        if not confirm(self, question, accept="Desfazer importação"):
            return
        try:
            self._ws.imports.undo(batch.id)
        except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
            show_error(self, error, "import.undo")
            self.refresh()
            return
        self.refresh()
        self.undone.emit()
        show_info(self, "Importação desfeita.")

    def blocked_text(self, check: UndoCheck) -> str:
        """Por que não dá para desfazer, listando os lançamentos alterados no app."""
        if check.already_undone:
            return "Esta importação já foi desfeita."
        if check.newer_batch:
            return "Desfaça antes a importação mais recente desta planilha (mesmo ano)."
        lines = ["Esta importação não pode ser desfeita porque há lançamentos mexidos no app:"]
        for transaction in check.changed_in_app[:MAX_LISTED]:
            amount = format_money(transaction.amount.cents, self._ws.visibility)
            lines.append(
                f"• {format_date(transaction.due_date)} · {transaction.description} · {amount}"
            )
        if len(check.changed_in_app) > MAX_LISTED:
            lines.append(f"• e mais {len(check.changed_in_app) - MAX_LISTED}.")
        if check.deleted_in_app:
            lines.append(f"• {check.deleted_in_app} lançamento(s) excluído(s) no app.")
        lines.append(
            "Por segurança, o app não desfaz trabalho feito nele: ajuste esses lançamentos "
            "diretamente em Contas a receber ou Contas a pagar."
        )
        return "\n".join(lines)
