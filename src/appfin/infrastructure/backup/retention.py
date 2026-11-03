"""Nomes dos arquivos de backup e política de retenção (docs/PROJETO.md §7.9).

Retenção: os **10 mais recentes** (vários no mesmo dia, ex.: antes de restaurar e ao fechar) e,
além deles, o mais recente de cada um dos últimos **7 dias**, de cada uma das últimas **4 semanas**
e de cada um dos últimos **12 meses** em que houve backup (docs/PROJETO.md §7.9). Só arquivos com
o nome exato gerado pelo app entram na conta; nada mais na pasta é tocado.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

EXTENSION = ".afbkp"
_PREFIX = "AppFinanceiro-backup-"
_NAME = re.compile(r"^AppFinanceiro-backup-(\d{8})-(\d{6})(?:-(\d+))?" + re.escape(EXTENSION) + "$")
KEEP_RECENT = 10
KEEP_DAILY = 7
KEEP_WEEKLY = 4
KEEP_MONTHLY = 12


def backup_name(moment: datetime, sequence: int = 0) -> str:
    stamp = moment.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{sequence}" if sequence else ""
    return f"{_PREFIX}{stamp}{suffix}{EXTENSION}"


def parse_backup_name(name: str) -> datetime | None:
    match = _NAME.match(name)
    if match is None:
        return None
    try:
        # Hora local de propósito: o nome do arquivo é para a usuária ler.
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")  # noqa: DTZ007
    except ValueError:
        return None


def list_backups(folder: Path) -> list[tuple[datetime, Path]]:
    """Backups do app na pasta, do mais novo para o mais antigo."""
    if not folder.is_dir():
        return []
    found = []
    for entry in folder.iterdir():
        moment = parse_backup_name(entry.name)
        if moment is not None and entry.is_file():
            found.append((moment, entry))
    found.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    return found


def to_delete(backups: list[tuple[datetime, Path]]) -> list[Path]:
    """Arquivos fora da retenção (``backups`` do mais novo para o mais antigo)."""
    keep: set[Path] = {path for _moment, path in backups[:KEEP_RECENT]}
    for key_of, limit in (
        (lambda m: m.date(), KEEP_DAILY),
        (lambda m: m.isocalendar()[:2], KEEP_WEEKLY),
        (lambda m: (m.year, m.month), KEEP_MONTHLY),
    ):
        seen: list[object] = []
        for moment, path in backups:
            bucket = key_of(moment)
            if bucket in seen:
                continue
            if len(seen) == limit:
                break
            seen.append(bucket)
            keep.add(path)
    return [path for _moment, path in backups if path not in keep]
