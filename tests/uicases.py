"""Roda um arquivo de casos de interface num subprocesso offscreen e devolve o resultado de cada caso.

Os widgets do Qt precisam de uma QApplication própria, criada antes de qualquer QGuiApplication de
outros testes; por isso os casos ficam em `<nome>_ui_cases.py` (não coletados sozinhos) e um
`test_<nome>_ui.py` curto os roda uma vez e transforma cada caso num teste:

    from uicases import case_names, check, run_cases
    CASES = Path(__file__).with_name("settings_ui_cases.py")

    @pytest.fixture(scope="module")
    def results(tmp_path_factory):
        return run_cases(CASES, tmp_path_factory.mktemp("settings_ui"))

    @pytest.mark.parametrize("name", case_names(CASES))
    def test_settings_ui(results, name):
        check(results, name)

O subprocesso herda PELICULA_SETTINGS_DIR do conftest: nada toca as preferências do usuário.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def case_names(path: Path) -> list[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]


def run_cases(path: Path, out_dir: Path) -> dict[str, tuple[str, str]]:
    pytest.importorskip("PySide6.QtWidgets")
    xml = Path(out_dir) / "casos.xml"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", f"python_files={Path(path).name}",
           str(path), f"--junitxml={xml}"]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, timeout=600)
    if not xml.exists():
        raise AssertionError("os casos da interface não rodaram:\n"
                             + proc.stdout.decode("utf-8", "replace")[-4000:]
                             + proc.stderr.decode("utf-8", "replace")[-4000:])
    found: dict[str, tuple[str, str]] = {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        status, msg = "passed", ""
        for tag in ("failure", "error", "skipped"):
            el = case.find(tag)
            if el is not None:
                status = "skipped" if tag == "skipped" else "failed"
                msg = (el.get("message") or "") + "\n" + (el.text or "")
                break
        found[case.get("name", "")] = (status, msg)
    return found


def check(results: dict[str, tuple[str, str]], name: str) -> None:
    status, msg = results.get(name, ("missing", "o caso não foi executado"))
    if status == "skipped":
        pytest.skip(msg.strip()[:300])
    assert status == "passed", f"{name}: {msg.strip()[-3000:]}"
