"""Estado do assistente de importação (MVVM): as escolhas da usuária e a prévia atual.

Python puro, testável sem janela. A regra fica no caso de uso (``SpreadsheetImportService``): aqui
só se guardam as decisões (ano, conta, meses, categorias, descrições, substituições desmarcadas,
categorias a mover) e se pede uma prévia nova a cada mudança.

Os dados da planilha ficam só em memória, neste objeto; ao bloquear o app, a tela é destruída e
eles vão junto.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from appfin.application.spreadsheet_import import (
    ImportPreview,
    ImportRequest,
    ImportResult,
    LineChoice,
    LineSource,
    PreviewItem,
    PreviewLine,
    SpreadsheetImportService,
)
from appfin.domain.spreadsheet_import.grid import SpreadsheetFile
from appfin.domain.spreadsheet_import.monthly_matrix import MonthStatus
from appfin.domain.spreadsheet_import.reconcile import ReconcileAction

ADJUSTABLE = (ReconcileAction.REPLACE, ReconcileAction.REMOVE)
_ATTENTION = (LineSource.MISSING, LineSource.BLOCK)


@dataclass(frozen=True, slots=True)
class LoadedFile:
    """Arquivo lido em segundo plano. ``file_name`` só sugere o ano (nunca é guardado/logado)."""

    file: SpreadsheetFile
    file_name: str = ""


class ImportWizardModel:
    def __init__(self, service: SpreadsheetImportService, today_year: Callable[[], int]) -> None:
        self._service = service
        self._today_year = today_year
        self.clear()

    # ------------------------------------------------------------------ ciclo
    def clear(self) -> None:
        """Esquece a planilha e as escolhas (cancelar, nova importação, bloqueio)."""
        self.loaded: LoadedFile | None = None
        self.sheet_index = 0
        self.year = self._today_year()
        self.account_id = ""
        self.month_statuses: dict[int, MonthStatus] = {}
        self.choices: dict[str, LineChoice] = {}
        self.descriptions: dict[str, str] = {}
        self.keep_row_keys: set[str] = set()
        self.move_category_ids: set[str] = set()
        self.preview: ImportPreview | None = None

    def load(self, loaded: LoadedFile, account_id: str) -> None:
        self.clear()
        self.loaded = loaded
        self.account_id = account_id
        self.year = (
            self._service.suggest_year(loaded.file, 0, loaded.file_name) or self._today_year()
        )

    @property
    def sheet_names(self) -> list[str]:
        return [sheet.name for sheet in self.loaded.file.sheets] if self.loaded else []

    def set_sheet(self, index: int) -> None:
        if index == self.sheet_index or self.loaded is None:
            return
        loaded = self.loaded
        self.load(loaded, self.account_id)  # outra aba: as escolhas da anterior não valem
        self.sheet_index = index
        self.year = self._service.suggest_year(loaded.file, index, loaded.file_name) or self.year

    # ------------------------------------------------------------------ decisões
    def request(self) -> ImportRequest:
        return ImportRequest(
            year=self.year,
            account_id=self.account_id,
            sheet_index=self.sheet_index,
            month_statuses=dict(self.month_statuses),
            choices=dict(self.choices),
            descriptions=dict(self.descriptions),
            move_category_ids=frozenset(self.move_category_ids),
            keep_row_keys=frozenset(self.keep_row_keys),
        )

    def set_month_status(self, month: int, status: MonthStatus) -> None:
        detected = self.preview.detected_months[month - 1] if self.preview else None
        if status is detected:
            self.month_statuses.pop(month, None)
        else:
            self.month_statuses[month] = status

    def set_line(self, line_key: str, choice: LineChoice | None, description: str | None) -> None:
        """Escolha da usuária para uma linha; ``None`` = manter como está."""
        if choice is not None:
            self.choices[line_key] = choice
        if description is not None:
            self.descriptions[line_key] = description

    def toggle_keep(self, item: PreviewItem) -> None:
        """Substituição/remoção marcada ↔ desmarcada (manter o que está no app)."""
        if item.action not in ADJUSTABLE:
            return
        if item.row_key in self.keep_row_keys:
            self.keep_row_keys.discard(item.row_key)
        else:
            self.keep_row_keys.add(item.row_key)

    def set_move(self, category_id: str, move: bool) -> None:
        if move:
            self.move_category_ids.add(category_id)
        else:
            self.move_category_ids.discard(category_id)

    # ------------------------------------------------------------------ caso de uso
    def refresh(self) -> ImportPreview:
        if self.loaded is None:
            raise RuntimeError("Nenhuma planilha carregada.")
        self.preview = self._service.preview(self.loaded.file, self.request())
        return self.preview

    def confirm(self) -> ImportResult:
        if self.loaded is None or self.preview is None:
            raise RuntimeError("Gere a prévia antes de confirmar.")
        return self._service.confirm(self.loaded.file, self.request(), self.preview.fingerprint)

    # ------------------------------------------------------------------ consultas da tela
    def attention_lines(self) -> list[PreviewLine]:
        """Linhas para revisar: primeiro as sem categoria, depois as sugeridas pelo bloco e as que
        criam categoria nova; o resto (regra ou perfil) vem depois."""
        if self.preview is None:
            return []

        def order(line: PreviewLine) -> tuple[int, int]:
            if line.source is LineSource.MISSING:
                rank = 0
            elif line.source is LineSource.BLOCK or line.new_category is not None:
                rank = 1
            else:
                rank = 2
            return rank, line.row

        return sorted(self.preview.lines, key=order)

    def needs_review(self) -> bool:
        """O passo "Categorias" só aparece quando há algo a decidir (§9 do plano)."""
        preview = self.preview
        if preview is None:
            return False
        return bool(
            preview.category_moves
            or preview.new_categories
            or any(line.source in _ATTENTION and not line.is_empty for line in preview.lines)
        )
