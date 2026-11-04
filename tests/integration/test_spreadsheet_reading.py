"""Leitura de planilha de ponta a ponta: nada da planilha vai para log (teste canário)."""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from appfin.domain.spreadsheet_import.cash_flow_layout import CASH_FLOW_LAYOUT
from appfin.domain.spreadsheet_import.monthly_matrix import read_monthly_matrix
from appfin.infrastructure.importers.safe_reader import SpreadsheetReadError, read_spreadsheet
from tests.spreadsheet_fixtures import cash_flow_fixture, pt_br, write_csv, write_xlsx

CANARY_FILE = "PACIENTE-FICTICIO-CANARIO"


def test_reading_spreadsheets_logs_nothing_from_their_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fixture = cash_flow_fixture()
    files = [
        write_xlsx(tmp_path / f"{CANARY_FILE}.xlsx", fixture),
        write_csv(tmp_path / f"{CANARY_FILE}.csv", fixture),
    ]
    secrets = [d.label.strip() for d in fixture.details] + [
        text.splitlines()[0] for text in fixture.comments.values()
    ]
    amounts = [pt_br(Decimal(d.cents[0]).scaleb(-2)) for d in fixture.details if d.cents[0]]

    with caplog.at_level(logging.DEBUG):
        for path in files:
            reading = read_monthly_matrix(read_spreadsheet(path).sheets[0], CASH_FLOW_LAYOUT)
            assert reading.is_valid

    logged = caplog.text
    assert CANARY_FILE not in logged
    assert not [secret for secret in secrets if secret in logged]
    assert not [amount for amount in amounts if amount in logged]


def test_refusal_message_never_has_the_file_name(tmp_path: Path) -> None:
    path = tmp_path / f"{CANARY_FILE}.xlsx"
    path.write_bytes(b"PK\x03\x04quebrado")

    with pytest.raises(SpreadsheetReadError) as error:
        read_spreadsheet(path)

    assert CANARY_FILE not in error.value.message
    assert CANARY_FILE not in str(error.value)
