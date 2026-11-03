"""Backups do dia a dia: destinos, backup automático e status (docs/PROJETO.md §7.9).

- Destinos: a pasta local do app (sempre) + uma pasta escolhida pela usuária (pen drive, OneDrive).
  A pasta local sozinha não protege contra perda do disco; por isso a tela insiste na 2ª pasta.
- Automático: a cada 24 h de uso e ao fechar o app (quem agenda é a interface).
- A criação em si fica na sessão (que guarda a chave de dados).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from appfin.application.ports import BackupManifest, BackupReport
from appfin.domain.repositories import UnitOfWork

FOLDER_KEY = "backup.folder"
LAST_SUCCESS_KEY = "backup.last_success_at"
LAST_FAILURE_KEY = "backup.last_failure_at"
AUTO_INTERVAL = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class BackupStatus:
    local_dir: Path
    folder: Path | None
    last_success_at: datetime | None
    last_failure_at: datetime | None

    @property
    def last_attempt_failed(self) -> bool:
        if self.last_failure_at is None:
            return False
        # >=: falha parcial grava as duas marcas no mesmo instante.
        return self.last_success_at is None or self.last_failure_at >= self.last_success_at


class BackupService:
    def __init__(
        self,
        create: Callable[[Sequence[Path], str], BackupReport],
        prepare_restore: Callable[..., BackupManifest],
        uow: Callable[[], UnitOfWork],
        local_dir: Path,
        now: Callable[[], datetime],
    ) -> None:
        self._create = create
        self._prepare_restore = prepare_restore
        self._uow = uow
        self._local_dir = local_dir
        self._now = now

    def status(self) -> BackupStatus:
        with self._uow() as uow:
            folder = uow.settings.get(FOLDER_KEY)
            success = uow.settings.get(LAST_SUCCESS_KEY)
            failure = uow.settings.get(LAST_FAILURE_KEY)
        return BackupStatus(
            self._local_dir,
            Path(folder) if folder else None,
            _parse(success),
            _parse(failure),
        )

    def set_folder(self, folder: Path | None) -> None:
        if folder is not None and not folder.is_absolute():
            raise ValueError("Escolha uma pasta completa (com a unidade).")
        with self._uow() as uow:
            uow.settings.set(FOLDER_KEY, str(folder) if folder else None)
            uow.commit()

    def backup_now(self, reason: str = "manual") -> BackupReport:
        status = self.status()
        destinations = [self._local_dir]
        if status.folder is not None:
            destinations.append(status.folder)
        try:
            report = self._create(destinations, reason)
        except Exception:
            self._remember(LAST_FAILURE_KEY)
            raise
        self._remember(LAST_SUCCESS_KEY)
        if report.failed:
            # A cópia local saiu, mas a pasta escolhida falhou: conta como atenção pendente.
            self._remember(LAST_FAILURE_KEY)
        return report

    def is_due(self) -> bool:
        last = self.status().last_success_at
        return last is None or self._now() - last >= AUTO_INTERVAL

    def prepare_restore(
        self, file: Path, *, password: str | None = None, recovery_key: str | None = None
    ) -> BackupManifest:
        return self._prepare_restore(file, password=password, recovery_key=recovery_key)

    def _remember(self, key: str) -> None:
        with self._uow() as uow:
            uow.settings.set(key, self._now().isoformat())
            uow.commit()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
