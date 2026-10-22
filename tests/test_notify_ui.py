"""Notificações na interface (casos em `notify_ui_cases.py`, num subprocesso offscreen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from uicases import case_names, check, run_cases

CASES = Path(__file__).with_name("notify_ui_cases.py")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return run_cases(CASES, tmp_path_factory.mktemp("notify_ui"))


@pytest.mark.parametrize("name", case_names(CASES))
def test_notify_ui(results, name):
    check(results, name)
