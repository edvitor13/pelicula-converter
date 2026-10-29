"""1.6, frente E: formatos de foto no scan (`scanformatos.py`): 135, meio quadro e 120.

Medidas (quadro, passo, furos), tira deitada nos formatos de foto em 35 mm e no 6 × 6, a janela do quadro com o
tamanho certo em duas resoluções, o grão pela largura do quadro, as bitolas novas no fim das listas e o BASE de
sempre sem a tira deitada.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import grao, look, params, scanformatos, shaders
from pelicula.engine import Engine

NEW = {"135": (36.0, 24.0, 38.0, True), "meio_quadro": (18.0, 24.0, 19.0, True),
       "120_66": (56.0, 56.0, 60.0, True), "120_645": (56.0, 41.5, 45.0, False)}


def test_formats_dimensions():
    for fmt, (w, h, pitch, rot) in NEW.items():
        f = look.SCAN_FORMATS[fmt]
        x0, x1, ih, _c = f["img"]
        across, along = x1 - x0, ih
        # deitada: o comprimento ao longo da película é a largura da imagem
        assert (along, across) == (w, h) if rot else (across, along) == (w, h), fmt
        assert f["pitch"] == pitch and f["pitch"] > along
        assert x0 >= 0 and x1 <= f["film_w"]
        assert (fmt in scanformatos.ROTATED) == rot
    k = look.SCAN_FORMATS["135"]
    assert k["pitch"] / k["perf_period"] == 8 and look.SCAN_FORMATS["meio_quadro"]["pitch"] / k["perf_period"] == 4
    assert k["perf"] == look.SCAN_FORMATS["35mm"]["perf"], "furos KS, os mesmos do 35 mm"
    for fmt in ("120_66", "120_645"):
        assert look.SCAN_FORMATS[fmt]["perf"][0] < 0, "sem furos (fora da película)"


def test_gauges_appended_and_grain_by_frame_width():
    keys = [k for k, _l in params.BITOLAS]
    assert keys[-3:] == ["135", "meio_quadro", "120"] and keys[:8] == [
        "nenhuma", "8mm", "super8", "16mm", "super16", "35mm", "65mm", "imax"]
    assert set(keys) == set(look.GAUGES) and set(keys) == set(look.GAUGE_SCAN)
    assert grao.frame_width_mm("135") == 36.0 and grao.frame_width_mm("meio_quadro") == 24.0
    assert grao.frame_width_mm("120") == 56.0
    # quadro maior, grão menor: na ordem das larguras
    sizes = {k: look.GAUGES[k]["grain_size"] for k in ("meio_quadro", "35mm", "135", "120")}
    assert sizes["meio_quadro"] > sizes["35mm"] > sizes["135"] > sizes["120"]
    choices = [c for c, _l in params.PARAMS["scan_formato"].choices]
    assert choices[-4:] == ["135", "meio_quadro", "120_66", "120_645"]


def test_edge_text_and_rotation_flag():
    for fmt in NEW:
        v = params.sanitize({"scan_on": True, "scan_formato": fmt})
        assert look.edge_text(v) == scanformatos.EDGE_TEXTS[fmt]
        U = look.build_plan(v, 320, 180, 0, 24.0).uniforms
        assert U.get("u_scan_rot", 0) == (1 if fmt in scanformatos.ROTATED else 0)
    v = params.sanitize({"scan_on": True, "bitola": "135"})
    assert look.scan_format(v) == "135"
    U = look.build_plan(params.sanitize({"scan_on": True}), 320, 180, 0, 24.0).uniforms
    assert "u_scan_rot" not in U, "35 mm: o plano de sempre"


def test_rotated_source_is_a_text_variant():
    src = scanformatos.rotated(shaders.BASE)
    assert "u_res.yx" in src and src != shaders.BASE
    from pelicula import planes
    assert "u_res.yx" in scanformatos.rotated(planes.BASE_CP)


def _window(engine, fmt, w, h):
    v = params.sanitize({"scan_on": True, "scan_formato": fmt, "scan_ajuste": "caber", "scan_vizinhos": False})
    plan = look.build_plan(v, w, h, 0, 24.0)
    engine.set_input(np.full((h, w, 3), 128, np.uint8))
    light = engine.scene_light(plan)
    a = light[..., 3] > 0.5
    ys, xs = np.nonzero(a)
    # o quadro do centro (os vizinhos estão desligados)
    return xs.max() - xs.min() + 1, ys.max() - ys.min() + 1, light


@pytest.mark.gpu
@pytest.mark.parametrize("size", [(640, 360), (1280, 720)])
@pytest.mark.parametrize("fmt", list(NEW))
def test_frame_window_has_the_real_size(gl_engine, fmt, size):
    w, h = size
    fw, fh, _light = _window(gl_engine, fmt, w, h)
    iw, ih, _pitch, rot = NEW[fmt]
    f = look.SCAN_FORMATS[fmt]
    across_px = (h if rot else w)  # a largura da película (× 1,05) ocupa a altura (deitada) ou a largura
    mmpp = f["film_w"] * 1.05 / across_px
    if not rot and ih / mmpp > h:
        assert fh == h, "o quadro passa da altura da tela"
        assert fw == pytest.approx(iw / mmpp, abs=2.5)
    else:
        assert fw == pytest.approx(iw / mmpp, abs=2.5) and fh == pytest.approx(ih / mmpp, abs=2.5)


@pytest.mark.gpu
def test_135_perforations_run_along_the_top_and_bottom(gl_engine):
    w, h = 640, 360
    v = params.sanitize({"scan_on": True, "scan_formato": "135"})
    plan = look.build_plan(v, w, h, 0, 24.0)
    gl_engine.set_input(np.full((h, w, 3), 128, np.uint8))
    lum = gl_engine.scene_light(plan)[..., :3].mean(axis=2)
    mmpp = 35 * 1.05 / h
    off = (h - 35 / mmpp) / 2  # a película centrada na altura
    row = int(off + 3.41 / mmpp)   # centro dos furos de cima
    holes = lum[row] > lum.max() * 0.5
    edges = np.flatnonzero(np.diff(holes.astype(int)) == 1)
    period = np.median(np.diff(edges))
    assert period == pytest.approx(4.75 / mmpp, abs=1.5), "um furo a cada 4,75 mm ao longo da tira deitada"
    col = lum[:, w // 2]
    assert col[h // 2] < lum[row].max() * 0.5, "no meio, a imagem (cinza), não um furo"
