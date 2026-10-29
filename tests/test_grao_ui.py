"""Controles de grão e textura da 1.6 na interface (casos em `grao_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("grao_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("grao_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_grao_ui(results, name):
    check(results, name)
