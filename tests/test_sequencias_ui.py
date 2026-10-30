"""Várias sequências na interface (1.7, #57): os casos ficam em `sequencias_ui_cases.py` e rodam uma vez num subprocesso
offscreen (`uicases`); cada caso vira um teste aqui."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("sequencias_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("sequencias_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_sequencias_ui(results, name):
    check(results, name)
