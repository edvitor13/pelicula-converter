"""Efeitos sonoros e sons CC0 na interface (1.8, #39): os casos ficam em `sfx_ui_cases.py` e rodam uma vez num
subprocesso offscreen (`uicases`); cada caso vira um teste aqui."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("sfx_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("sfx_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_sfx_ui(results, name):
    check(results, name)
