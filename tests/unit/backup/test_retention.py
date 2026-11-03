"""Nomes e retenção dos backups (7 diários, 4 semanais, 12 mensais)."""

# Os nomes dos backups usam hora local (sem fuso) de propósito: são para a usuária ler.
# ruff: noqa: DTZ001

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from appfin.infrastructure.backup.retention import (
    backup_name,
    list_backups,
    parse_backup_name,
    to_delete,
)


def test_name_round_trip() -> None:
    moment = datetime(2026, 3, 15, 9, 5, 7)

    assert backup_name(moment) == "AppFinanceiro-backup-20260315-090507.afbkp"
    assert parse_backup_name(backup_name(moment, 2)) == moment
    for other in ("foto.jpg", "AppFinanceiro-backup-20261399-000000.afbkp", "x.afbkp"):
        assert parse_backup_name(other) is None


def test_keeps_daily_weekly_and_monthly(tmp_path: Path) -> None:
    start = datetime(2026, 3, 15, 18, 0)
    # Dois backups por dia durante 500 dias (o mais novo de cada dia às 18h).
    backups = []
    for day in range(500):
        for hour in (18, 9):
            moment = (start - timedelta(days=day)).replace(hour=hour)
            backups.append((moment, tmp_path / backup_name(moment)))

    deleted = set(to_delete(backups))
    kept = sorted((m for m, p in backups if p not in deleted), reverse=True)

    recent = sorted((m for m, _p in backups), reverse=True)[:10]
    assert kept[:10] == recent, "os 10 mais recentes ficam (inclusive do mesmo dia)"
    older = [m for m in kept if m not in recent]
    assert all(m.hour == 18 for m in older), "de cada período fica o mais novo"
    assert {m.date() for m in kept} >= {(start - timedelta(days=d)).date() for d in range(7)}
    assert len({(m.year, m.month) for m in kept}) == 12
    assert len(kept) <= 10 + 7 + 4 + 12
    assert min(kept) >= datetime(2025, 4, 1)


def test_only_app_files_are_listed(tmp_path: Path) -> None:
    (tmp_path / "AppFinanceiro-backup-20260315-090507.afbkp").write_bytes(b"x")
    (tmp_path / "planilha.xlsx").write_bytes(b"x")
    (tmp_path / "AppFinanceiro-backup-20260315-090507.afbkp.tmp").write_bytes(b"x")

    assert [p.name for _m, p in list_backups(tmp_path)] == [
        "AppFinanceiro-backup-20260315-090507.afbkp"
    ]
    assert list_backups(tmp_path / "nao-existe") == []
