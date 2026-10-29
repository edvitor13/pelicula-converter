"""Frente E da 1.6 na janela: módulos novos, máquina do tempo e o cartão da manivela.

Os casos ficam em `filme_ui_cases.py` e rodam num subprocesso offscreen (com preferências num .ini próprio); eles
se pulam sem OpenGL 3.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("filme_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("filme_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_filme_ui(results, name):
    check(results, name)
