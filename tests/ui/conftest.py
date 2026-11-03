"""Fixtures dos testes de interface: workspace real (SQLCipher) com data fixa."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from appfin.bootstrap import AppConfig, build_app
from appfin.domain.entities import Company
from appfin.domain.enums import TaxRegime
from appfin.infrastructure.paths import AppPaths
from appfin.presentation.shared.formatting import ValuesVisibility
from appfin.presentation.workspace import Workspace
from tests.support import FAST_MINIMUM, FAST_PARAMS

TODAY = date(2026, 3, 15)


@pytest.fixture
def ws(data_dir: Path) -> Iterator[Workspace]:
    config = AppConfig(paths=AppPaths(data_dir), kdf_params=FAST_PARAMS, kdf_minimum=FAST_MINIMUM)
    container = build_app(config, today=lambda: TODAY)
    container.session.create("girassol trator piano nuvem")
    workspace = container.workspace_factory(ValuesVisibility())
    workspace.catalog.save_company(Company(name="Clínica Fictícia"))
    workspace.catalog.initialize_defaults(TaxRegime.SIMPLES)
    yield workspace
    container.session.lock()
