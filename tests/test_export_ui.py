"""Janela de exportação por plataforma e área segura da prévia (casos em `export_ui_cases.py`, num subprocesso
offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("export_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("export_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_export_ui(results, name):
    check(results, name)
