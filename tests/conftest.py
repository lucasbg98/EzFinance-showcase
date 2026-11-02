"""Configuração compartilhada dos testes.

Os testes usam parâmetros de Argon2id **baixos** para rodar rápido. O código de produção recusa
esses parâmetros (``MINIMUM_SECURE_PARAMS``); por isso os testes passam o piso explicitamente.
Dados de teste são sempre sintéticos.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Garante que nenhum teste toque o diretório de dados real da usuária.
os.environ.pop("APPFIN_DATA_DIR", None)


@pytest.fixture
def data_dir(tmp_path: Path) -> Iterator[Path]:
    directory = tmp_path / "appfin-data"
    directory.mkdir()
    yield directory
