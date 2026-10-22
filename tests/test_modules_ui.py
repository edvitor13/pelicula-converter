"""Módulos na interface: página Recursos, perfil do primeiro acesso e a janela principal.

Os casos ficam em `modules_ui_cases.py` e rodam num subprocesso offscreen (com preferências num
.ini próprio); os da janela principal se pulam sem OpenGL 3.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("modules_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("modules_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_modules_ui(results, name):
    check(results, name)
