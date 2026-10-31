"""Correções da 1.7 na interface: modo e Ctrl+Z (#50), som da prévia (#51), âncora do zoom (#53) e Exportar durante uma
exportação (#59).

Os casos ficam em `correcoes_17_ui_cases.py` e rodam uma vez num subprocesso offscreen (`uicases`); cada caso vira um
teste aqui.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("correcoes_17_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("correcoes_17_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_correcoes_17_ui(results, name):
    check(results, name)
