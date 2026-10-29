"""Controles novos do Laboratório da 1.6 na interface (casos em `lab_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("lab_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("lab_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_lab_ui(results, name):
    check(results, name)
