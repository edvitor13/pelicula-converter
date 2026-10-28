"""Interface da frente alfa-títulos da 1.5: sequências de imagens, fundo transparente, geradores e títulos.

Os casos ficam em `alfa_titulos_ui_cases.py` e rodam uma vez num subprocesso offscreen (`uicases`); cada caso vira
um teste aqui.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("alfa_titulos_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("alfa_titulos_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_alfa_titulos_ui(results, name):
    check(results, name)
