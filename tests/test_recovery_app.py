"""O app inteiro (`app.main()`) depois de um travamento, num subprocesso offscreen.

Uma sessão "travada" (marcador com pid que não existe + cópia automática) é deixada na pasta do app (uma pasta
temporária: `LOCALAPPDATA`/`XDG_DATA_HOME`); o app abre, o aviso de recuperação aparece antes da tela de
boas-vindas (a escolha "Recuperar" é feita pelo teste), o projeto volta modificado e, ao sair normalmente, a
sessão nova some sem deixar marcador. Pula sem OpenGL 3.3 (a janela não abre).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from pelicula import APP_NAME, project, recovery
from pelicula.ui import prefs

st = prefs.settings()
for key, value in (("language", "pt_BR"), ("auto_update", "false"), ("show_welcome", "true")):
    st.setValue(key, value)
from pelicula import __version__
st.setValue("last_seen_version", __version__)
st.sync()

# A sessão que "travou": marcador com pid 0 (não existe) e uma cópia com um ajuste não salvo.
root = recovery.recovery_dir()
dead = recovery.Session(root, "20260101000000dead0009")
p = project.Project()
p.values["grao_forca"] = 1.77
dead.autosave(recovery.make_payload(p.to_json(), "", {"modo": "pelicula"}, "x", dead.id))
(root / recovery.SESSIONS).mkdir(parents=True, exist_ok=True)
(root / recovery.SESSIONS / f"{dead.id}.json").write_text(json.dumps(
    {"app": APP_NAME, "sessao": dead.id, "pid": 0, "inicio": time.time() - 99}), encoding="utf-8")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from pelicula import app as app_main
from pelicula.ui import main_window, recovery_ui, welcome

out = {"asked": [], "welcome": 0, "critical": []}
main_window.MainWindow._check_deps = lambda self: None
main_window.MainWindow._auto_check_update = lambda self: None
QMessageBox.critical = staticmethod(lambda *a, **k: out["critical"].append(str(a[2])[:200]))
welcome.WelcomeDialog.exec = lambda self: out.__setitem__("welcome", out["welcome"] + 1) or 0

def fake_exec(self):
    out["asked"].append(self.info.text())
    self.choice = recovery_ui.RECOVER
    return 1
recovery_ui.RecoveryDialog.exec = fake_exec

def finish():
    win = next((w for w in QApplication.topLevelWidgets() if isinstance(w, main_window.MainWindow)), None)
    if win is not None:
        out["value"] = win.store.get("grao_forca")
        out["dirty_title"] = "•" in win.windowTitle() or win._saved_state == {}
        out["has_recovery"] = win.recovery is not None
        out["backend"] = win.notifier.backend.name
        out["markers_running"] = sorted(m.stem for m in (root / recovery.SESSIONS).glob("*.json"))
        win._saved_state = win._state()  # nada a perguntar ao sair
    QApplication.instance().exit(0)

_attach = recovery_ui.attach

def attach(win, settings, guard):
    QTimer.singleShot(2500, finish)  # a QApplication já existe aqui
    return _attach(win, settings, guard)
recovery_ui.attach = attach
rc = app_main.main()
out["rc"] = rc
out["markers_after"] = sorted(m.stem for m in (root / recovery.SESSIONS).glob("*.json"))
out["folders_after"] = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != recovery.SESSIONS)
logs = Path(os.environ["LOCALAPPDATA"]) / APP_NAME / "logs"
out["logs_after"] = sorted(p.name for p in logs.iterdir()) if logs.exists() else []
print("RESULT:" + json.dumps(out))
'''


def test_app_offers_recovery_after_a_crash_and_closes_clean(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1",
               PELICULA_SETTINGS_DIR=str(tmp_path / "prefs"), LOCALAPPDATA=str(tmp_path / "local"),
               XDG_DATA_HOME=str(tmp_path / "local"), APPDATA=str(tmp_path / "roaming"))
    env.pop("PELICULA_SCREENSHOT", None)
    proc = subprocess.run([sys.executable, "-c", _SCRIPT, str(ROOT)], cwd=str(ROOT), env=env, capture_output=True,
                          timeout=180)
    text = proc.stdout.decode("utf-8", "replace")
    line = next((x for x in text.splitlines() if x.startswith("RESULT:")), None)
    assert line, text[-3000:] + proc.stderr.decode("utf-8", "replace")[-3000:]
    out = json.loads(line[len("RESULT:"):])
    if out["critical"]:
        pytest.skip("OpenGL 3.3 indisponível: " + out["critical"][0])
    assert out["rc"] == 0
    assert len(out["asked"]) == 1 and "fechou" not in out["asked"][0]  # o texto é o da cópia
    assert out["welcome"] == 0  # recuperou: sem tela de boas-vindas
    assert out["value"] == pytest.approx(1.77) and out["dirty_title"] and out["has_recovery"]
    assert out["backend"] in ("bandeja", "dbus+bandeja")
    assert len(out["markers_running"]) == 1 and "20260101000000dead0009" not in out["markers_running"]
    assert out["markers_after"] == [] and out["folders_after"] == []  # fechamento normal: nada sobra
    assert not any(n.startswith("falha-") for n in out["logs_after"])
