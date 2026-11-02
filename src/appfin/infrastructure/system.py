"""Implementações simples das portas de relógio e log de eventos."""

from __future__ import annotations

from datetime import UTC, datetime

from appfin.infrastructure.app_logging import log_event_fields


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class LoggingEventLog:
    def record(self, event: str, **fields: object) -> None:
        log_event_fields(event, fields)
