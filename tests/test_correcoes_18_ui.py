"""Correções da 1.8 na interface: importar só põe na Mídia (#64).

Os casos ficam em `correcoes_18_ui_cases.py` e rodam uma vez num subprocesso offscreen (`uicases`); cada caso vira um
teste aqui.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("correcoes_18_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("correcoes_18_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_correcoes_18_ui(results, name):
    check(results, name)
