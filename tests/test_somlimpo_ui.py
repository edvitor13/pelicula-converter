"""Interface da limpeza do som (1.8): aprender o ruído, zumbido, predefinições do "eq" e sincronizar pelo som.

Os casos ficam em `somlimpo_ui_cases.py` e rodam uma vez num subprocesso offscreen (`uicases`); cada caso vira um
teste aqui.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("somlimpo_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("somlimpo_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_somlimpo_ui(results, name):
    check(results, name)
