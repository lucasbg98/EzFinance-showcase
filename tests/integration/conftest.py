"""Fixtures de integração: banco SQLCipher real, temporário, já migrado."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from appfin.application.catalog import CatalogService
from appfin.application.reports import ReportService
from appfin.application.transactions import TransactionService
from appfin.domain.enums import TaxRegime
from appfin.infrastructure.crypto.secret import SecretBytes
from appfin.infrastructure.ids import uuid7
from appfin.infrastructure.persistence.database import open_encrypted
from appfin.infrastructure.persistence.migrator import migrate
from appfin.infrastructure.persistence.queries import SqlReportQueries
from appfin.infrastructure.persistence.repositories import SqlUnitOfWork

TODAY = date(2026, 3, 15)


@dataclass
class App:
    db: Any
    catalog: CatalogService
    transactions: TransactionService
    reports: ReportService

    def uow(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.db, lambda: datetime(2026, 3, 15, 12, tzinfo=UTC))


@pytest.fixture
def app(tmp_path: Path) -> Iterator[App]:
    db = open_encrypted(tmp_path / "app.db", SecretBytes(bytes(range(32))))
    migrate(db)

    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(db, lambda: datetime(2026, 3, 15, 12, tzinfo=UTC))

    instance = App(
        db=db,
        catalog=CatalogService(uow, uuid7),
        transactions=TransactionService(uow, uuid7, lambda: TODAY),
        reports=ReportService(lambda: SqlReportQueries(db), lambda: TODAY),
    )
    instance.catalog.initialize_defaults(TaxRegime.SIMPLES)
    yield instance
    db.close()
