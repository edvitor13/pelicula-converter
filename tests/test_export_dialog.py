"""Janela de exportação: cada resolução mostra o tamanho que sai (o número vale para o lado menor).

Roda num subprocesso com QT_QPA_PLATFORM=offscreen (os widgets precisam de uma QApplication
própria) e preferências num .ini temporário (PELICULA_SETTINGS_DIR, herdado da conftest).
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
import json, os, sys
sys.path.insert(0, sys.argv[1])
folder, lang = sys.argv[2], sys.argv[3]
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula import export, i18n, media
i18n.set_language(lang)
export.measure_speed = lambda *a, **k: 0.0  # a estimativa de tempo não interessa aqui
from pelicula.ui.export_dialog import ExportDialog


def info(w, h, image=False):
    return media.MediaInfo(path=os.path.join(folder, "entrada.png" if image else "entrada.mp4"), width=w, height=h,
                           fps=24.0, fps_str="24/1", frames=1 if image else 48, duration=0.0 if image else 2.0,
                           pix_fmt="yuv420p", bit_depth=8, codec="png" if image else "h264", profile="", bitrate=0,
                           color_space="bt709", color_range="tv", color_transfer="bt709", color_primaries="bt709",
                           has_audio=False, audio_codec="", container="mov,mp4", is_image=image)


out = {}
for name, (w, h, image, quality) in {"vertical": (1080, 1920, False, "social"),
                                     "deitado": (1920, 1080, False, "social"),
                                     "gif_vertical": (1080, 1920, False, "gif"),
                                     "foto_em_pe": (3000, 4000, True, "img_png")}.items():
    dlg = ExportDialog(None, info(w, h, image), {}, "Teste", None, last_dir=folder, last_quality=quality)
    dlg._est_timer.stop()
    res = dlg.res
    if image:
        res.setCurrentIndex(res.findData("1080"))
    out[name] = {"quality": dlg.quality.currentData(), "res": res.currentText(),
                 "items": {res.itemData(i): res.itemText(i) for i in range(res.count())},
                 "summary": dlg.summary.text(), "tip": res.toolTip(), "desc": dlg.qdesc.text()}
    dlg.deleteLater()
print("RESULT " + json.dumps(out, ensure_ascii=False))
app.exit(0)
'''


def _run(tmp_path, lang: str) -> dict:
    script = tmp_path / "dialogo.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    res = subprocess.run([sys.executable, str(script), str(ROOT), str(tmp_path), lang], capture_output=True, env=env,
                         timeout=180, cwd=str(tmp_path))
    lines = [ln for ln in res.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("RESULT ")]
    assert res.returncode == 0 and lines, res.stderr.decode("utf-8", "replace")[-3000:]
    return json.loads(lines[-1][7:])


@pytest.mark.ffmpeg
def test_resolution_choices_show_the_real_output_size(ffmpeg_ok, tmp_path):
    data = _run(tmp_path, "pt_BR")
    v, d = data["vertical"], data["deitado"]
    assert v["quality"] == d["quality"] == "social"
    # vertical: "Redes sociais 1080p" continua 1080 × 1920 (antes encolhia para 608 × 1080)
    assert v["res"] == "1080p — 1080 × 1920" and "1080×1920" in v["summary"]
    assert v["items"]["original"] == "Original — 1080 × 1920"
    assert v["items"]["2160"] == "4K (2160p) — 2160 × 3840" and v["items"]["720"] == "720p — 720 × 1280"
    assert "lado menor" in v["tip"] and "1080 × 1920" in v["desc"]
    # deitado: tudo como sempre foi
    assert d["res"] == "1080p — 1920 × 1080" and "1920×1080" in d["summary"]
    assert d["items"]["480"] == "480p — 852 × 480"
    # GIF (sem dimensões pares) e imagem em pé
    assert data["gif_vertical"]["res"] == "480p — 480 × 853"
    assert data["foto_em_pe"]["res"] == "1080p — 1080 × 1440" and "1080×1440" in data["foto_em_pe"]["summary"]


@pytest.mark.ffmpeg
def test_resolution_texts_are_translated(ffmpeg_ok, tmp_path):
    data = _run(tmp_path, "en")
    v = data["vertical"]
    assert v["res"] == "1080p — 1080 × 1920"
    assert "short" in v["tip"] and "1080 × 1920" in v["desc"]
    assert "Saída" not in v["summary"]
