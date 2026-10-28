"""Janela principal na base da 1.5: receita do quadro, chaves de animação e transparência.

Os casos ficam em `fundacao_ui_cases.py` e rodam uma vez num subprocesso offscreen (`uicases`); cada caso vira
um teste aqui.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("fundacao_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("fundacao_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_fundacao_ui(results, name):
    check(results, name)
