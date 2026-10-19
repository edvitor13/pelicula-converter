"""Janela principal com os modos Película e Edição, de ponta a ponta.

Roda num subprocesso com QT_QPA_PLATFORM=offscreen (nenhuma janela aparece) e preferências num
.ini temporário (PELICULA_SETTINGS_DIR, herdado da conftest). O app sai com app.exit(0), sem
fechar a janela, para não gravar sessão (regra 12 do AGENTS.md).
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
video, outdir = sys.argv[2], sys.argv[3]
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula.ui import prefs
st = prefs.settings()
st.setValue("auto_update", "false")
st.setValue("language", "pt_BR")
from pelicula.ui.main_window import MainWindow
from pelicula import export, timeline
from pelicula.engine import Engine

out = {}

def pump(cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False

win = MainWindow()
win.resize(1400, 900)
win.show()
win.load_media(video)
out["loaded"] = pump(lambda: win.cur is not None)
out["film_source_is_file"] = win.src_seq is None
out["clips_after_open"] = len(win.model.seq.clips)
out["trivial"] = win.model.seq.is_trivial() == video

win.set_mode("edicao")
out["timeline_visible"] = win.tl_editor.isVisible()
out["bin_visible"] = win.left_stack.currentIndex() == 1
out["edit_source_is_seq"] = win.src_seq is not None
win.cur = None
win.request_frame(5)
out["edit_frame"] = pump(lambda: win.cur is not None)

# Divide no quadro 12 e apaga a segunda metade da imagem e do som (ligados).
win.frame_idx = 12
win.model.select([])
win.model.split_at(12)
out["clips_after_split"] = len(win.model.seq.clips)
right = [c for c in win.model.seq.clips if c.kind == timeline.VIDEO and c.start == 12]
win.model.select([right[0].id])
win.model.delete_selected(ripple=False)
out["clips_after_delete"] = len(win.model.seq.clips)
out["duration"] = win.model.seq.duration
out["info_frames"] = win.info.frames

# Ajuste de cor num clipe: a prévia remonta o quadro sem reabrir o vídeo.
left = [c for c in win.model.seq.clips if c.kind == timeline.VIDEO][0]
vals = dict(left.values)
vals["exposicao"] = 1.0
win.model.set_clip_values(left.id, vals)
win.cur = None
win.request_frame(3)
out["after_values"] = pump(lambda: win.cur is not None)

# Desfazer volta ao clipe sem ajuste.
win.undo()
out["undo_exposure"] = [c for c in win.model.seq.clips if c.kind == timeline.VIDEO][0].values["exposicao"]
win.redo()

# De volta ao modo Película: a montagem (não trivial) continua sendo a fonte.
win.set_mode("pelicula")
out["film_uses_seq"] = win.src_seq is not None
out["title_dirty"] = win.windowTitle().endswith("PeliculaConverter") and "•" in win.windowTitle()

# Exporta a montagem com o look atual, como a janela de exportação faria.
values, name = win._export_look()
info = win.info
s = export.ExportSettings.from_dict(export.quality_presets(info)[1][2].to_dict())  # MP4 H.264
s.audio = "aac192"
job = export.ExportJob(info=info, values=values, settings=s, out_path=os.path.join(outdir, "montagem.mp4"),
                       sequence=win.src_seq.copy())
eng = Engine()
export.run_job(job, eng)
eng.release()
out["export_status"] = job.status
out["export_error"] = job.error[-400:]
out["export_frames"] = job.done

# Projeto com a montagem: salva e reabre.
win._write_project(os.path.join(outdir, "edicao.plc"))
data = json.loads(open(os.path.join(outdir, "edicao.plc"), encoding="utf-8").read())
out["project_format"] = data.get("formato")
out["project_has_edit"] = bool(data.get("edicao"))
win.new_project = lambda: None
print("RESULT " + json.dumps(out))
sys.stdout.flush()
app.exit(0)
'''


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_edit_mode_end_to_end(gl_engine, sample_video, tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    res = subprocess.run([sys.executable, "-c", _SCRIPT, str(ROOT), sample_video, str(tmp_path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=170)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"sem resultado\nstdout:\n{res.stdout[-3000:]}\nstderr:\n{res.stderr[-3000:]}"
    out = json.loads(line[7:])
    assert out["loaded"] and out["film_source_is_file"]
    assert out["clips_after_open"] == 2 and out["trivial"]
    assert out["timeline_visible"] and out["bin_visible"] and out["edit_source_is_seq"]
    assert out["edit_frame"]
    assert out["clips_after_split"] == 4
    assert out["clips_after_delete"] == 2
    assert out["duration"] == 12 and out["info_frames"] == 12
    assert out["after_values"]
    assert out["undo_exposure"] == 0.0
    assert out["film_uses_seq"]
    assert out["export_status"] == "concluido", out["export_error"]
    assert out["export_frames"] == 12
    assert out["project_format"] == 2 and out["project_has_edit"]
