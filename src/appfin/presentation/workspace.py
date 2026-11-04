"""Serviços disponíveis para as telas enquanto o app está desbloqueado."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from appfin.application.backup import BackupService
from appfin.application.catalog import CatalogService
from appfin.application.receipts import ReceiptService
from appfin.application.reports import ReportService
from appfin.application.spreadsheet_import import SpreadsheetImportService
from appfin.application.transactions import TransactionService
from appfin.presentation.shared.formatting import ValuesVisibility


class AppControl(Protocol):
    """Ações que só a janela principal pode fazer (trocar de tela, pausar o bloqueio)."""

    def apply_restore(self) -> None: ...

    def discard_restore(self) -> None: ...

    def set_auto_lock_paused(self, paused: bool) -> None: ...

    def prepare_recovery_key(self, password: str) -> str: ...

    def confirm_recovery_key(self) -> None: ...

    def cancel_recovery_key(self) -> None: ...


class DetachedAppControl:
    """Usado quando não há janela principal (testes de telas isoladas)."""

    def apply_restore(self) -> None:
        raise RuntimeError("Restauração indisponível fora da janela principal.")

    def discard_restore(self) -> None:
        return None

    def set_auto_lock_paused(self, paused: bool) -> None:  # noqa: ARG002 - sem janela
        return None

    def prepare_recovery_key(self, password: str) -> str:  # noqa: ARG002 - sem janela
        raise RuntimeError("Indisponível fora da janela principal.")

    def confirm_recovery_key(self) -> None:
        raise RuntimeError("Indisponível fora da janela principal.")

    def cancel_recovery_key(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class Workspace:
    catalog: CatalogService
    transactions: TransactionService
    reports: ReportService
    receipts: ReceiptService
    backups: BackupService
    imports: SpreadsheetImportService
    visibility: ValuesVisibility
    today: Callable[[], date]
    app: AppControl = field(default_factory=DetachedAppControl)


WorkspaceFactory = Callable[[ValuesVisibility, AppControl | None], Workspace]
