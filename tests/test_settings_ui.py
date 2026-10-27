"""Janela de Configurações e suas páginas (casos em `settings_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("settings_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("settings_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_settings_ui(results, name):
    check(results, name)
