"""1.8, som de película na janela: o cartão do módulo Beta e o som da prévia (arquivo e montagem).

Os casos ficam em `som_pelicula_ui_cases.py` e rodam num subprocesso offscreen (com preferências num .ini próprio);
eles se pulam sem OpenGL 3.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("som_pelicula_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("som_pelicula_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_som_pelicula_ui(results, name):
    check(results, name)
