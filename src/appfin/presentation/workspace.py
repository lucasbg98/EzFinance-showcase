"""Serviços disponíveis para as telas enquanto o app está desbloqueado."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from appfin.application.catalog import CatalogService
from appfin.application.receipts import ReceiptService
from appfin.application.reports import ReportService
from appfin.application.transactions import TransactionService
from appfin.presentation.shared.formatting import ValuesVisibility


@dataclass(frozen=True, slots=True)
class Workspace:
    catalog: CatalogService
    transactions: TransactionService
    reports: ReportService
    receipts: ReceiptService
    visibility: ValuesVisibility
    today: Callable[[], date]


WorkspaceFactory = Callable[[ValuesVisibility], Workspace]
