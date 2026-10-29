"""Cor simples no inspetor do modo Edição: barra, conta-gotas, igualar, grupos, "Automático" e o módulo.

Os casos ficam em `color_tools_ui_cases.py` e rodam num subprocesso offscreen (com preferências num .ini próprio);
sem OpenGL 3.3 ou sem ffmpeg os da janela se pulam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("color_tools_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("cor_simples_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_color_tools_ui(results, name):
    check(results, name)
