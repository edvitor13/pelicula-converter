"""Página Componentes e ponte da fila de tarefas (casos em `componentes_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("componentes_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("componentes_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_componentes_ui(results, name):
    check(results, name)
