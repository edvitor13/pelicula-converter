"""Filtro de ajustes na interface: os casos ficam em `busca_ajustes_ui_cases.py` (subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("busca_ajustes_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("busca_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_busca_ajustes_ui(results, name):
    check(results, name)
