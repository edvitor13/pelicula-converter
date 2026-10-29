"""Interface da entrada da câmera na 1.6: os casos ficam em `entrada_ui_cases.py` e rodam num subprocesso
offscreen (`uicases.run_cases`); cada caso vira um teste aqui."""

from __future__ import annotations

from pathlib import Path

import pytest
from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("entrada_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("entrada_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_entrada_ui(results, name):
    check(results, name)
