"""Localização dos arquivos do app.

Padrão: ``%APPDATA%\\AppFinanceiro`` (pasta do usuário do Windows, protegida pelas permissões dele).
``APPFIN_DATA_DIR`` permite apontar para uma pasta de **teste** (nunca usar com dados reais em dev).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "AppFinanceiro"
DATA_DIR_ENV = "APPFIN_DATA_DIR"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path

    @property
    def vault_file(self) -> Path:
        return self.root / "vault.json"

    @property
    def database_file(self) -> Path:
        return self.root / "appfin.db"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    @property
    def backup_dir(self) -> Path:
        """Backups locais (cifrados). Protegem contra erro humano, não contra perda do disco."""
        return self.root / "backups"

    @property
    def lock_file(self) -> Path:
        return self.root / "appfin.lock"


def default_update_cache() -> Path:
    """Cache de atualizações em ``%LOCALAPPDATA%`` (não sincroniza em perfis móveis)."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).resolve() / "updates"
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / APP_DIR_NAME / "updates"


def default_paths() -> AppPaths:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return AppPaths(Path(override).resolve())
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return AppPaths(base / APP_DIR_NAME)
