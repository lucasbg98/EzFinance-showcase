"""Logs sem dados sensíveis (docs/PROJETO.md §7.8; skill ``security`` §8).

Regras aplicadas em código, não por disciplina:

- O app registra **eventos** (``log_event("vault.unlock", outcome="failed")``), não texto livre.
- Só campos de uma **lista de permissão** passam; valores de texto precisam casar com um padrão
  restrito (códigos técnicos). O resto é descartado e contado em ``dropped_fields``.
- Exceções viram só o **nome do tipo**; a mensagem (que pode conter dados) nunca é gravada.
- Mensagens de bibliotecas de terceiros são reduzidas a ``logger`` + nível; o texto é descartado.
- Sem envio remoto: só arquivo local com rotação.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

APP_LOGGER: Final = "appfin"
ALLOWED_FIELDS: Final = frozenset(
    {
        "outcome",
        "duration_ms",
        "count",
        "attempt",
        "error_type",
        "error_code",
        "schema_version",
        "app_version",
        "reason",
        # contagens da importação de planilha (só números; nunca o conteúdo)
        "created",
        "replaced",
        "removed",
        "skipped",
        "kept",
    }
)
_EVENT_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_SAFE_TEXT: Final = re.compile(r"^[A-Za-z0-9_.:\-]{0,64}$")
_MAX_BYTES: Final = 1_000_000
_BACKUP_COUNT: Final = 5
_FIELDS_ATTR: Final = "appfin_fields"


def get_logger() -> logging.Logger:
    return logging.getLogger(APP_LOGGER)


def log_event(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Registra um evento técnico. Campos fora da lista de permissão são descartados."""
    log_event_fields(event, fields, level)


def log_event_fields(event: str, fields: Mapping[str, object], level: int = logging.INFO) -> None:
    if not _EVENT_PATTERN.fullmatch(event):
        event = "invalid_event_name"
    safe, dropped = sanitize_fields(fields)
    if dropped:
        safe["dropped_fields"] = dropped
    get_logger().log(level, event, extra={_FIELDS_ATTR: safe})


def log_exception(event: str, error: BaseException, **fields: object) -> None:
    """Registra uma falha só com o tipo da exceção — nunca a mensagem nem o traceback."""
    log_event(event, level=logging.ERROR, error_type=type(error).__name__, **fields)


def sanitize_fields(fields: Mapping[str, object]) -> tuple[dict[str, object], int]:
    safe: dict[str, object] = {}
    dropped = 0
    for key, value in fields.items():
        if key in ALLOWED_FIELDS and _is_safe_value(value):
            safe[key] = value
        else:
            dropped += 1
    return safe, dropped


def _is_safe_value(value: object) -> bool:
    if isinstance(value, bool | int):
        return True
    if isinstance(value, float):
        return value == value  # rejeita NaN
    return isinstance(value, str) and bool(_SAFE_TEXT.fullmatch(value))


class JsonEventFormatter(logging.Formatter):
    """Uma linha JSON por evento, só com dados já sanitizados."""

    def format(self, record: logging.LogRecord) -> str:
        is_app_record = record.name == APP_LOGGER or record.name.startswith(APP_LOGGER + ".")
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
        }
        if is_app_record:
            payload["event"] = record.msg if isinstance(record.msg, str) else "invalid_event"
            fields = getattr(record, _FIELDS_ATTR, {})
            if isinstance(fields, dict):
                safe, dropped = sanitize_fields(fields)
                payload.update(safe)
                if dropped:
                    payload["dropped_fields"] = dropped
        else:
            # Texto de bibliotecas de terceiros pode conter qualquer coisa: só a origem e o nível.
            payload["event"] = "external_log"
            payload["source"] = record.name[:64]
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(log_dir: Path, level: int = logging.INFO) -> logging.Handler:
    """Configura o log em arquivo com rotação. Retorna o handler (útil para encerrar nos testes)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "appfin.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(JsonEventFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    get_logger().setLevel(level)
    logging.captureWarnings(capture=True)
    return handler
