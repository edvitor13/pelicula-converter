"""Janela do Recorte por IA (casos em `corridorkey_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("corridorkey_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("corridorkey_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_corridorkey_ui(results, name):
    check(results, name)
