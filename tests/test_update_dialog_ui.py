"""Janela de atualização (casos em `update_dialog_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("update_dialog_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("update_dialog_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_update_dialog_ui(results, name):
    check(results, name)
