"""Ponto único de composição: monta as dependências reais do app (injeção manual)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from appfin.application.backup import BackupService
from appfin.application.catalog import CatalogService
from appfin.application.receipts import ReceiptService
from appfin.application.reports import ReportService
from appfin.application.session import AppSession
from appfin.application.spreadsheet_import import SpreadsheetImportService
from appfin.application.transactions import TransactionService
from appfin.infrastructure.backup.engine import FileBackupEngine, complete_pending_restore
from appfin.infrastructure.crypto.kdf import MINIMUM_SECURE_PARAMS, PRODUCTION_PARAMS, KdfParams
from appfin.infrastructure.ids import uuid7
from appfin.infrastructure.key_vault import FileKeyVault
from appfin.infrastructure.paths import AppPaths, default_paths
from appfin.infrastructure.persistence.data_store import SqlCipherDataStore
from appfin.infrastructure.persistence.queries import SqlReportQueries
from appfin.infrastructure.persistence.repositories import SqlUnitOfWork
from appfin.infrastructure.system import LoggingEventLog, SystemClock
from appfin.presentation.auto_lock import DEFAULT_AUTO_LOCK_MINUTES
from appfin.presentation.shared.formatting import ValuesVisibility
from appfin.presentation.workspace import (
    AppControl,
    DetachedAppControl,
    Workspace,
    WorkspaceFactory,
)


@dataclass(frozen=True, slots=True)
class AppConfig:
    paths: AppPaths = field(default_factory=default_paths)
    kdf_params: KdfParams = PRODUCTION_PARAMS
    kdf_minimum: KdfParams = MINIMUM_SECURE_PARAMS
    auto_lock_minutes: float = DEFAULT_AUTO_LOCK_MINUTES


@dataclass(frozen=True, slots=True)
class AppContainer:
    session: AppSession
    workspace_factory: WorkspaceFactory


def build_app(config: AppConfig, today: Callable[[], date] | None = None) -> AppContainer:
    """``today`` permite fixar a data nos testes; no app, é a data local do computador."""
    # Uma restauração interrompida (ex.: queda de energia no meio da troca) termina aqui, antes de
    # qualquer arquivo ser aberto.
    complete_pending_restore(config.paths)
    vault = FileKeyVault(config.paths.vault_file, config.kdf_params, config.kdf_minimum)
    clock = SystemClock()
    store = SqlCipherDataStore(config.paths.database_file)
    engine = FileBackupEngine(
        config.paths, lambda: store.connection, clock.now, minimum=config.kdf_minimum
    )
    # Backup automático antes de migrar o esquema de um banco que já tem dados (§7.9).
    store.before_migration = lambda connection, key: engine.create_from(
        connection, key, [config.paths.backup_dir]
    )
    session = AppSession(
        vault, store, clock, LoggingEventLog(), engine, local_backup_dir=config.paths.backup_dir
    )

    def local_today() -> date:
        # Data local do computador (datas de calendário), não UTC.
        return date.today()  # noqa: DTZ011 - data de calendário local, de propósito

    today = today or local_today

    def workspace(visibility: ValuesVisibility, app: AppControl | None = None) -> Workspace:
        """Só pode ser chamado com o app desbloqueado (a conexão do banco está aberta)."""
        connection = store.connection

        def uow() -> SqlUnitOfWork:
            return SqlUnitOfWork(connection, clock.now)

        backups = BackupService(
            session.create_backup,
            session.prepare_restore,
            uow,
            config.paths.backup_dir,
            clock.now,
        )

        def audit(event: str, outcome: str) -> None:
            store.record_audit(event, outcome, clock.now())

        return Workspace(
            catalog=CatalogService(uow, uuid7),
            transactions=TransactionService(uow, uuid7, today),
            reports=ReportService(lambda: SqlReportQueries(connection), today),
            receipts=ReceiptService(uow, uuid7, today),
            backups=backups,
            imports=SpreadsheetImportService(
                uow,
                uuid7,
                clock.now,
                backup=lambda: backups.backup_now("before_import"),
                events=LoggingEventLog(),
                audit=audit,
            ),
            visibility=visibility,
            today=today,
            app=app or DetachedAppControl(),
        )

    return AppContainer(session, workspace)


def build_session(config: AppConfig) -> AppSession:
    return build_app(config).session
