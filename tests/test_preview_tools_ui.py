"""Ferramentas da prévia (zebra, falsa cor e referência): só na tela, nos dois modos, com o módulo "scopes".

Os casos ficam em `preview_tools_ui_cases.py` e rodam num subprocesso offscreen (com preferências num .ini próprio);
sem OpenGL 3.3 eles se pulam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("preview_tools_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("previa_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_preview_tools_ui(results, name):
    check(results, name)
