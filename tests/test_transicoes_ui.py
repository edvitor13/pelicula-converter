"""Transições de película na interface: inspetor, menu do corte, linha do tempo e o módulo na janela.

Os casos ficam em `transicoes_ui_cases.py` e rodam num subprocesso offscreen (com preferências num .ini
próprio); os da janela principal se pulam sem OpenGL 3.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("transicoes_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("transicoes_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_transicoes_ui(results, name):
    check(results, name)
