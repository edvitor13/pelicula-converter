"""Leitura dos arquivos na 1.6: log com super-brancos (float) e a faixa legal expandida exata em 16 bits.

Os vídeos de teste são FFV1 (sem perda) gerados aqui pelo ffmpeg com códigos YUV de 10 bits escolhidos a dedo,
inclusive acima do branco nominal (940) e abaixo do preto (64), marcados como Rec.709 em faixa legal.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import entrada_base as eb
from pelicula import export, media, presets
from pelicula.frame import Recipe

ROOT = Path(__file__).resolve().parents[1]
CODES = np.array([0, 4, 64, 100, 420, 512, 598, 700, 900, 940, 960, 1000, 1019, 1023, 64, 940])
W, H = 16, 4


def _video(tmp_path: Path, pix: str = "yuv444p10le", name: str = "log.mkv", u: int = 512, v: int = 512,
           patch: int = 1, h: int = H) -> str:
    """W·patch × h: cada código de `CODES` numa faixa de `patch` colunas."""
    codes = np.zeros((h, W * patch, 3), np.uint16)
    codes[..., 0] = np.repeat(CODES, patch)
    codes[..., 1] = u
    codes[..., 2] = v
    path = tmp_path / name
    eb.synthetic_video(path, pix, codes)
    return str(path)


@pytest.fixture
def zscale(ffmpeg_ok):
    if not media.has_zscale():
        pytest.skip("o ffmpeg desta máquina não tem o zscale (zimg)")
    return ffmpeg_ok


# ------------------------------------------------------------------ quando a leitura é em float
class _Info:
    def __init__(self, pix="yuv420p10le", rng="tv", image=False):
        self.pix_fmt, self.color_range, self.is_image = pix, rng, image


@pytest.mark.parametrize("profile,info,want", [
    ("slog3", _Info(), True),
    ("logc3", _Info(), True),
    ("applelog", _Info("yuv420p"), True),          # 8 bits também guarda os super-brancos
    ("rec709", _Info(), False),                    # padrão: leitura de sempre
    (None, _Info(), False),
    ("linear", _Info(), False),
    ("hlg", _Info(), False),                       # HDR: leitura de sempre (veja ARQUITETURA §29)
    ("pq", _Info(), False),
    ("slog3", _Info(rng="pc"), False),             # faixa cheia: nada a expandir
    ("slog3", _Info("yuvj420p", ""), False),
    ("slog3", _Info("rgb48le", ""), False),        # RGB (DPX, TIFF…)
    ("cineon", _Info("rgb48le", "", image=True), False),
])
def test_float_input_only_for_log_in_legal_range(profile, info, want, monkeypatch):
    monkeypatch.setattr(media, "_FILTERS", {"zscale", "scale"})
    assert media.float_input(info, profile) is want


def test_float_input_needs_zscale(monkeypatch):
    monkeypatch.setattr(media, "_FILTERS", {"scale"})
    assert media.float_input(_Info(), "slog3") is False


def test_filter_list_is_parsed_and_reset(monkeypatch):
    monkeypatch.setattr(media, "_FILTERS", {"x"})
    media.reset_cache()
    assert media._FILTERS is None


# ------------------------------------------------------------------ super-brancos
@pytest.mark.ffmpeg
@pytest.mark.parametrize("pix", ["yuv444p10le", "yuv422p10le", "yuv420p10le"])
def test_log_reading_keeps_codes_above_940_and_below_64(zscale, tmp_path, pix):
    info = media.probe(_video(tmp_path, pix))
    assert media.legal_range(info) and media.float_input(info, "slog3")
    want = (CODES - 64) / 876.0
    for depth in (8, 16):
        img = media.grab_frame(info, 0, W, H, depth, profile="slog3")
        assert img.dtype == np.float32 and img.shape == (H, W, 3)
        for c in range(3):  # croma neutro: R = G = B = (código − 64)/876, sem corte
            assert np.abs(img[0, :, c] - want).max() < 2e-6, (pix, depth, img[0, :, c])
    assert img.max() > 1.09 and img.min() < -0.07


@pytest.mark.ffmpeg
def test_log_reading_converts_color_with_the_file_matrix(zscale, tmp_path):
    """Croma fora do neutro: a matriz BT.709 com a faixa legal (Cb, Cr ÷ 896), sem corte."""
    info = media.probe(_video(tmp_path, u=512 + 200, v=512 - 150))
    img = media.grab_frame(info, 0, W, H, 8, profile="vlog")
    e = (CODES - 64) / 876.0
    cb, cr = 200 / 896.0, -150 / 896.0
    r = e + 2 * (1 - 0.2126) * cr
    b = e + 2 * (1 - 0.0722) * cb
    g = (e - 0.2126 * r - 0.0722 * b) / 0.7152
    assert np.abs(img[0] - np.stack([r, g, b], -1)).max() < 2e-6


@pytest.mark.ffmpeg
def test_rec709_reading_is_unchanged(zscale, tmp_path):
    """Rec.709 (o padrão) e sem perfil: a mesma leitura inteira de antes, bit a bit."""
    info = media.probe(_video(tmp_path))
    for depth in (8, 16):
        old = media.grab_frame(info, 0, W, H, depth)
        assert old.dtype == (np.uint8 if depth == 8 else np.uint16)
        for prof in ("rec709", "linear", "hlg", "pq"):
            assert np.array_equal(media.grab_frame(info, 0, W, H, depth, profile=prof), old)


@pytest.mark.ffmpeg
def test_without_zscale_log_falls_back_to_the_old_reading(ffmpeg_ok, tmp_path, monkeypatch):
    info = media.probe(_video(tmp_path))
    monkeypatch.setattr(media, "_FILTERS", {"scale"})
    img = media.grab_frame(info, 0, W, H, 8, profile="slog3")
    assert img.dtype == np.uint8 and img[0, 9:14, 1].tolist() == [255] * 5  # 940…1023 cortados (como antes)


@pytest.mark.ffmpeg
def test_full_range_log_is_read_as_before(zscale, tmp_path):
    """Faixa cheia (código/1023 sem expansão): nada passa de 1, a leitura de sempre."""
    path = tmp_path / "cheia.mkv"
    codes = np.zeros((H, W, 3), np.uint16)
    codes[..., 0], codes[..., 1:] = CODES, 512
    raw = np.concatenate([codes[..., i].ravel() for i in range(3)]).astype("<u2").tobytes()
    tags = ["-color_range", "pc", "-colorspace", "bt709"]
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv444p10le", "-s",
                    f"{W}x{H}", *tags, "-i", "pipe:0", "-c:v", "ffv1", *tags, str(path)], input=raw, check=True)
    info = media.probe(str(path))
    assert not media.legal_range(info) and not media.float_input(info, "slog3")
    assert media.grab_frame(info, 0, W, H, 8, profile="slog3").dtype == np.uint8


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("entrada", ["slog3", "logc3", "vlog", "applelog"])
def test_super_whites_reach_the_look(zscale, gl_engine, tmp_path, entrada):
    """Do arquivo ao quadro: acima de 940 cada código dá uma luz diferente (antes, todos iguais ao 940)."""
    info = media.probe(_video(tmp_path, patch=8, h=8))
    vals = dict(presets.builtin_values("vision3_500t"), entrada=entrada, exposicao=-4.0)
    vals.update({k: False for k in vals if k.endswith("_on") and k != "cor_on"})  # só a cor (sem grão nem halo)
    recipe = Recipe.for_source(vals, 24.0, 16, legal=media.legal_range(info))
    w, h = W * 8, 8
    new = recipe.render(gl_engine, media.grab_frame(info, 0, w, h, 16, profile=entrada), 0)[4, 4::8]
    old = recipe.render(gl_engine, media.grab_frame(info, 0, w, h, 16), 0)[4, 4::8]
    lum_new = new[9:14].astype(float).mean(axis=1)   # códigos 940, 960, 1000, 1019, 1023
    lum_old = old[9:14].astype(float).mean(axis=1)
    assert np.all(np.diff(lum_new) > 0), lum_new
    assert np.all(np.diff(lum_old[1:]) <= 0), lum_old  # o corte de antes (o resto é a vinheta da bitola)
    # Abaixo do branco nominal a leitura nova é a mesma luz da antiga (só a quantização muda).
    assert np.abs(new[3:9].astype(float) - old[3:9].astype(float)).max() < 400


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_and_its_preview_read_log_in_float(zscale, gl_engine, tmp_path):
    info = media.probe(_video(tmp_path))
    vals = dict(presets.builtin_values("vision3_500t"), entrada="slog3")
    s = export.ExportSettings()
    frames = export.frame_pipeline(info, vals, s)
    assert frames.profile == "slog3"
    reader, skip = export.open_reader(info, frames, 0, 1, None, media.Perf())
    try:
        img = reader.read()
    finally:
        reader.close()
    assert img.dtype == np.float32 and skip == 0
    out = frames.render(gl_engine, img, 0)
    prev = export.preview_frame(gl_engine, info, vals, s, 0, depth=frames.depth)
    assert np.array_equal(out, prev)
    rec = dict(vals, entrada="rec709")
    reader, _skip = export.open_reader(info, export.frame_pipeline(info, rec, s), 0, 1, None, media.Perf())
    try:
        assert reader.read().dtype != np.float32
    finally:
        reader.close()


# ------------------------------------------------------------------ 16 bits exatos
def _expect16(codes, bits):
    lo, span = (64, 876) if bits == 10 else (16, 219)
    return np.clip(np.round((codes - lo) / span * 65535.0), 0, 65535)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("pix", ["yuv444p10le", "yuv422p10le", "yuv420p10le", "yuv420p"])
@pytest.mark.parametrize("hq", [False, True])
def test_16bit_reading_expands_legal_range_exactly(zscale, tmp_path, pix, hq):
    """Branco (940/235) = 65535, preto (64/16) = 0 e cada cinza no valor exato; antes o branco ficava em
    65280–65283 (0,4% abaixo) no swscale."""
    if pix == "yuv420p":
        codes = np.zeros((H, W, 3), np.uint16)
        codes8 = np.array([0, 8, 16, 30, 60, 100, 126, 128, 150, 180, 200, 220, 230, 235, 240, 255])
        codes[..., 0], codes[..., 1:] = codes8, 128
        path = tmp_path / "v8.mkv"
        eb.synthetic_video(path, pix, codes)
        info, want = media.probe(str(path)), _expect16(codes8, 8)
    else:
        info, want = media.probe(_video(tmp_path, pix)), _expect16(CODES, 10)
    img = media.grab_frame(info, 0, W, H, 16, hq=hq)
    assert img.dtype == np.uint16
    for c in range(3):
        assert np.array_equal(img[0, :, c], want), (pix, img[0, :, c], want)


@pytest.mark.ffmpeg
def test_16bit_reading_is_exact_after_resizing(zscale, tmp_path):
    """Faixas largas reduzidas à metade: o centro de cada faixa continua no valor exato."""
    info = media.probe(_video(tmp_path, "yuv420p10le", patch=32, h=8))
    for hq in (False, True):
        img = media.grab_frame(info, 0, W * 16, 4, 16, hq=hq)
        got = img[2, 8::16, 1]
        assert np.array_equal(got, _expect16(CODES, 10)), (hq, got)


@pytest.mark.ffmpeg
def test_16bit_export_reader_uses_the_exact_expansion(zscale, tmp_path):
    info = media.probe(_video(tmp_path))
    s = export.ExportSettings(codec="prores")
    frames = export.frame_pipeline(info, dict(presets.builtin_values("vision3_500t")), s)
    assert frames.depth == 16
    reader, _skip = export.open_reader(info, frames, 0, 1, None, media.Perf())
    try:
        assert reader.exact16 and not reader.float
        img = reader.read()
    finally:
        reader.close()
    assert img.dtype == np.uint16 and img[0, 9, 1] == 65535 and img[0, 2, 1] == 0


@pytest.mark.ffmpeg
def test_16bit_without_zscale_keeps_the_old_reading(ffmpeg_ok, tmp_path, monkeypatch):
    info = media.probe(_video(tmp_path))
    monkeypatch.setattr(media, "_FILTERS", {"scale"})
    r = media.FrameReader(info, W, H, 16, 0, 1)
    try:
        assert not r.exact16
        img = r.read()
    finally:
        r.close()
    assert img.dtype == np.uint16 and 65000 < int(img[0, 9, 1]) <= 65535


@pytest.mark.ffmpeg
def test_16bit_full_range_and_8bit_reading_do_not_use_zscale(zscale, tmp_path):
    info = media.probe(_video(tmp_path))
    r8 = media.FrameReader(info, W, H, 8, 0, 1)
    try:
        assert not r8.exact16 and not r8.float and r8.pix == "rgb24"
    finally:
        r8.close()
    ra = media.FrameReader(info, W, H, 16, 0, 1, alpha=True)   # sem alfa no arquivo: os 3 canais de sempre
    try:
        assert ra.exact16
    finally:
        ra.close()


def test_burned_subtitles_compose_over_float_frames():
    from pelicula import subtitles, textrender
    frame = np.full((40, 80, 3), 1.05, np.float32)
    rgba = np.zeros((10, 20, 4), np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = 255
    out = subtitles.composite(frame, subtitles.Overlay(textrender.TextImage(rgba, 0, 0, None), 5, 5))
    assert out.dtype == np.float32
    assert np.allclose(out[5:15, 5:25], 1.0) and np.allclose(out[0, 0], 1.05)  # fora do texto: sem corte


_GUI = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
path = sys.argv[2]
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula.ui import prefs
st = prefs.settings()
st.setValue("auto_update", "false")
st.setValue("language", "pt_BR")
import numpy as np
from pelicula.ui.main_window import MainWindow

def pump(cond, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False

win = MainWindow()
win.resize(1200, 800)
win.show()
win.confirm_discard = lambda: True
win.handle_files([path])
assert pump(lambda: win.cur is not None), "o quadro não chegou"
assert win.cur.dtype == np.uint8, win.cur.dtype            # Rec.709: a leitura de sempre
win.store.set("entrada", "slog3")
win.store.commit()
assert pump(lambda: win.cur is not None and win.cur.dtype == np.float32), "o quadro não foi lido de novo em float"
assert win.cur.max() > 1.05
assert not win.cur_q.isNull()
win.store.set("entrada", "rec709")
win.store.commit()
assert pump(lambda: win.cur.dtype == np.uint8), "o quadro não voltou para 8 bits"
win.store.set("entrada", "vlog")
win.store.commit()
assert pump(lambda: win.cur.dtype == np.float32)
img = win.still_frame(0)                                     # "Salvar quadro": 16 bits, leitura em float
assert img.dtype == np.uint16 and img.shape[:2] == (36, 64), (img.dtype, img.shape)
print("OK")
app.exit(0)
'''


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_main_window_reads_log_in_float_and_back(zscale, gl_engine, tmp_path):
    path = _video(tmp_path, patch=4, h=36)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PELICULA_SETTINGS_DIR=str(tmp_path / "cfg"),
               APPDATA=str(tmp_path / "appdata"), PELICULA_LANG="pt_BR")
    res = subprocess.run([sys.executable, "-c", _GUI, str(ROOT), path], cwd=str(ROOT), env=env,
                         capture_output=True, timeout=180)
    out = res.stdout.decode("utf-8", "replace")
    assert res.returncode == 0 and "OK" in out, res.stderr.decode("utf-8", "replace")[-3000:] + out[-1000:]
