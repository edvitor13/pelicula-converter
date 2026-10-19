"""Interface do modo Edição: modelo, linha do tempo, mídia, inspetor, rodas, monitores e sequência.

Os casos ficam em `edit_ui_cases.py` e rodam uma vez num subprocesso com QT_QPA_PLATFORM=offscreen
(os widgets precisam de uma QApplication própria e nenhuma janela aparece). Cada caso vira um teste
aqui, então uma falha mostra o nome e a mensagem do caso.
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
CASES = ROOT / "tests" / "edit_ui_cases.py"


def _case_names() -> list[str]:
    tree = ast.parse(CASES.read_text(encoding="utf-8"))
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict[str, tuple[str, str]]:
    pytest.importorskip("PySide6.QtWidgets")
    out = tmp_path_factory.mktemp("edit_ui")
    xml = out / "casos.xml"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "python_files=edit_ui_cases.py",
           str(CASES), f"--junitxml={xml}"]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, timeout=600)
    if not xml.exists():
        raise AssertionError("os casos da interface não rodaram:\n"
                             + proc.stdout.decode("utf-8", "replace")[-4000:]
                             + proc.stderr.decode("utf-8", "replace")[-4000:])
    found: dict[str, tuple[str, str]] = {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        name = case.get("name", "")
        status, msg = "passed", ""
        for tag in ("failure", "error", "skipped"):
            el = case.find(tag)
            if el is not None:
                status = "skipped" if tag == "skipped" else "failed"
                msg = (el.get("message") or "") + "\n" + (el.text or "")
                break
        found[name] = (status, msg)
    return found


@pytest.mark.parametrize("name", _case_names())
def test_edit_ui(results, name):
    status, msg = results.get(name, ("missing", "o caso não foi executado"))
    if status == "skipped":
        pytest.skip(msg.strip()[:300])
    assert status == "passed", f"{name}: {msg.strip()[-3000:]}"
