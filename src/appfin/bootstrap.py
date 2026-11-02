"""Ponto único de composição: monta as dependências reais do app (injeção manual)."""

from __future__ import annotations

from dataclasses import dataclass, field

from appfin.application.session import AppSession
from appfin.infrastructure.crypto.kdf import MINIMUM_SECURE_PARAMS, PRODUCTION_PARAMS, KdfParams
from appfin.infrastructure.key_vault import FileKeyVault
from appfin.infrastructure.paths import AppPaths, default_paths
from appfin.infrastructure.persistence.data_store import SqlCipherDataStore
from appfin.infrastructure.system import LoggingEventLog, SystemClock
from appfin.presentation.auto_lock import DEFAULT_AUTO_LOCK_MINUTES


@dataclass(frozen=True, slots=True)
class AppConfig:
    paths: AppPaths = field(default_factory=default_paths)
    kdf_params: KdfParams = PRODUCTION_PARAMS
    kdf_minimum: KdfParams = MINIMUM_SECURE_PARAMS
    auto_lock_minutes: float = DEFAULT_AUTO_LOCK_MINUTES


def build_session(config: AppConfig) -> AppSession:
    vault = FileKeyVault(config.paths.vault_file, config.kdf_params, config.kdf_minimum)
    store = SqlCipherDataStore(config.paths.database_file)
    return AppSession(vault, store, SystemClock(), LoggingEventLog())
