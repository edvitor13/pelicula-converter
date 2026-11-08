"""Estabilização e rastreio da 1.9 na interface (F3, #68): os casos ficam em `movimento_ui_cases.py` e rodam uma vez num
subprocesso offscreen (`uicases`); cada caso vira um teste aqui."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("movimento_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("movimento_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_movimento_ui(results, name):
    check(results, name)
