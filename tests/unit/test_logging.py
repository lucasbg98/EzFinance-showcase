"""Teste com dados canário: nada sensível pode chegar ao arquivo de log."""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from appfin.infrastructure.app_logging import configure_logging, log_event, log_exception

CANARIES = [
    "Maria-Paciente-Ficticia",
    "123.456.789-09",
    "R$ 1.234,56",
    "cavalo bateria grampo correto",
    "tok_secret_abcdef",
]


@pytest.fixture
def log_file(tmp_path: Path) -> Iterator[Path]:
    handler = configure_logging(tmp_path)
    yield tmp_path / "appfin.log"
    handler.close()
    logging.getLogger().removeHandler(handler)


def _read(path: Path) -> list[dict[str, object]]:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_canaries_never_reach_the_log(log_file: Path) -> None:
    log_event("vault.unlock", outcome="failed", patient_name=CANARIES[0], cpf=CANARIES[1])
    log_event("transaction.saved", amount=CANARIES[2], reason=CANARIES[3])
    log_exception("sync.failed", ValueError(f"token {CANARIES[4]} invalido para {CANARIES[0]}"))
    logging.getLogger("terceiros.lib").warning("erro com %s", CANARIES[0])
    logging.getLogger("appfin.sub").error("mensagem livre com %s", CANARIES[1])

    content = log_file.read_text(encoding="utf-8")

    for canary in CANARIES:
        assert canary not in content


def test_allowed_fields_are_kept_and_others_counted(log_file: Path) -> None:
    log_event("vault.unlock", outcome="ok", duration_ms=812, description="segredo")

    (entry,) = _read(log_file)

    assert entry["event"] == "vault.unlock"
    assert entry["outcome"] == "ok"
    assert entry["duration_ms"] == 812
    assert entry["dropped_fields"] == 1
    assert "description" not in entry


def test_exception_logs_only_type(log_file: Path) -> None:
    log_exception("db.open", RuntimeError("caminho C:/Users/fulano/arquivo"))

    (entry,) = _read(log_file)

    assert entry["error_type"] == "RuntimeError"
    assert "fulano" not in json.dumps(entry)


def test_invalid_event_name_is_replaced(log_file: Path) -> None:
    log_event("Paciente Maria pagou")

    (entry,) = _read(log_file)

    assert entry["event"] == "invalid_event_name"


def test_third_party_messages_are_reduced_to_source(log_file: Path) -> None:
    logging.getLogger("urllib3").warning("GET https://x/?token=abc")

    (entry,) = _read(log_file)

    assert entry == {
        "ts": entry["ts"],
        "level": "WARNING",
        "event": "external_log",
        "source": "urllib3",
    }
