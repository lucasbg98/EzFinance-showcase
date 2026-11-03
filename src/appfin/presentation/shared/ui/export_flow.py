"""Fluxo de salvar arquivos exportados (CSV, Excel, PDF).

Arquivos exportados saem **sem a proteção do app** (skill ``security`` §5): a usuária é avisada
antes. A gravação é atômica (arquivo temporário + troca), para não deixar arquivo pela metade.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QWidget

from appfin.application.export_table import ExportTable
from appfin.infrastructure.app_logging import log_event
from appfin.infrastructure.exporters.tabular import to_csv, to_xlsx
from appfin.presentation.shared.ui.feedback import confirm, show_error

PLAINTEXT_WARNING = (
    "O arquivo será salvo SEM a proteção do app (sem criptografia) e pode conter dados de "
    "pacientes. Guarde-o em local seguro e apague quando não precisar mais."
)

# Ganchos substituíveis nos testes (evitam abrir diálogos de verdade).
ask_confirmation: Callable[[QWidget, str], bool] = lambda parent, text: confirm(  # noqa: E731
    parent, text, accept="Continuar"
)
ask_path: Callable[[QWidget, str, str, str], str] = lambda parent, title, name, filters: (  # noqa: E731
    QFileDialog.getSaveFileName(parent, title, name, filters)[0]
)
open_file: Callable[[Path], object] = lambda path: QDesktopServices.openUrl(  # noqa: E731
    QUrl.fromLocalFile(str(path))
)


def default_location(file_name: str) -> str:
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return str(Path(documents or Path.home()) / file_name)


def write_atomically(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def export_table(parent: QWidget, table: ExportTable, base_name: str) -> Path | None:
    """Pergunta onde salvar e grava em Excel (.xlsx) ou CSV, conforme a extensão escolhida."""
    if not ask_confirmation(parent, PLAINTEXT_WARNING):
        return None
    chosen = ask_path(
        parent,
        "Exportar",
        default_location(f"{base_name}.xlsx"),
        "Planilha Excel (*.xlsx);;CSV separado por ponto e vírgula (*.csv)",
    )
    if not chosen:
        return None
    path = Path(chosen)
    if path.suffix.lower() not in (".xlsx", ".csv"):
        path = path.with_suffix(".xlsx")
    try:
        data = to_csv(table) if path.suffix.lower() == ".csv" else to_xlsx(table)
        write_atomically(path, data)
    except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
        show_error(parent, error, "export.table")
        return None
    log_event("export.table", outcome="ok", count=len(table.rows))
    return path


def save_pdf(parent: QWidget, data: bytes, file_name: str, *, open_after: bool) -> Path | None:
    if not ask_confirmation(parent, PLAINTEXT_WARNING):
        return None
    chosen = ask_path(parent, "Salvar recibo", default_location(file_name), "PDF (*.pdf)")
    if not chosen:
        return None
    path = Path(chosen)
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    try:
        write_atomically(path, data)
    except Exception as error:  # noqa: BLE001 - mensagem amigável + log sem dados
        show_error(parent, error, "export.receipt")
        return None
    log_event("export.receipt", outcome="ok")
    if open_after:
        open_file(path)
    return path
