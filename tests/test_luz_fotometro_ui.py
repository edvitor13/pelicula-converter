"""Luz por plano e fotômetro da película na janela (1.6).

Os casos ficam em `luz_fotometro_ui_cases.py` e rodam num subprocesso offscreen (com preferências num .ini próprio);
eles se pulam sem OpenGL 3.3 ou sem ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("luz_fotometro_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("luz_fotometro_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_luz_fotometro_ui(results, name):
    check(results, name)
