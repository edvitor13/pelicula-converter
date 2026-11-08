"""1.9 (F3): estabilização do clipe (`estabilizacao.py`; ARQUITETURA §51.2).

Sem ffmpeg: o `.trf` em texto da vid.stab (`data/estabilizacao/tremor_320x180.trf`, gravado pelo `vidstabdetect` de um
vídeo sintético com deslocamentos conhecidos), a recusa de taxa variável, a geometria (desligada = os uniforms de
sempre, neutra, dividir/aparar/velocidade não mudam a correção de um quadro) e o aviso do módulo. Com o ffmpeg: a análise
de verdade (vid.stab, pulada se o filtro faltar, e o caminho em numpy) e, na GPU, o tremor corrigido e prévia ==
exportação.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

import movimento_sinteticos as ms
from pelicula import compositor, editparams, estabilizacao, modules, movimento, vfx
from pelicula import timeline as tl

DATA = Path(__file__).parent / "data" / "estabilizacao"
# Os recortes (x, y) da textura em cada quadro do vídeo que gerou o .trf: a câmera andou (x, y) − (x_ant, y_ant).
TREMOR = [(40, 30), (47, 28), (44, 34), (40, 40), (50, 36), (52, 30), (45, 31), (41, 33)]


def file_source(path="C:/videos/tremido.mp4", w=320, h=180, frames=8, fps=24.0) -> tl.Source:
    return tl.Source(path=path, width=w, height=h, fps=fps, fps_str=f"{int(fps)}/1", frames=frames,
                     duration=frames / fps, has_video=True)


def with_analysis(src: tl.Source, motions: np.ndarray) -> tl.Source:
    src.analysis[estabilizacao.KIND] = {"versao": 1, "metodo": "numpy", "carimbo": {}, "altura": src.height,
                                        "quadros": len(motions), "parametros": {},
                                        "movimento": vfx.pack(np.asarray(motions, np.float32))}
    return src


def shake(n=8, seed=1) -> np.ndarray:
    """Tremor sem panorâmica: a câmera treme em volta de um lugar só (posições sorteadas; o movimento é a diferença)."""
    rng = np.random.default_rng(seed)
    pos = np.zeros((n, 3))
    pos[1:] = rng.uniform([-14, -9, -0.4], [14, 9, 0.4], (n - 1, 3))
    mot = np.zeros((n, 4), np.float32)
    mot[1:, :2] = np.diff(pos[:, :2], axis=0)
    mot[1:, 2] = np.radians(np.diff(pos[:, 2]))
    return mot


def seq_with(src: tl.Source, **values) -> tuple[tl.Sequence, tl.Clip]:
    seq = tl.Sequence(width=src.width, height=src.height, fps_str=src.fps_str)
    seq.sources[src.path] = src
    c = seq.insert_media(src, at=0, with_audio=False)[0]
    if values:
        seq.set_values(c.id, {**c.values, **values})
    return seq, c


def uniforms(seq, t, w=None, h=None, neutral=False):
    out = {}
    for layer in seq.layers_at(t):
        src = seq.sources[layer.clip.src]
        u, _mip = compositor.clip_uniforms(seq, layer, src.width, src.height, w or seq.width, h or seq.height,
                                           neutral=neutral)
        out[layer.clip.id] = u
    return out


# ------------------------------------------------------------------ esquema, módulo, registro
def test_params_are_neutral_and_sparse():
    d = editparams.VIDEO.defaults()
    assert d["estab_on"] is False and d["estab_suavizar"] == 1.0 and d["estab_rotacao"] is True
    assert d["estab_bordas"] == "ampliar" and d["estab_zoom_extra"] == 0.0
    assert set(estabilizacao.KEYS) <= editparams.SPARSE_KEYS
    assert editparams.stored_values("video", d) == editparams.stored_values("video", editparams.VIDEO.defaults())
    assert "estab_on" not in editparams.stored_values("video", d)
    sec = next(s for s in editparams.VIDEO_SECTIONS if s.key == "estabilizar")
    assert sec.toggle == "estab_on" and sec.key not in editparams.COLOR_SECTIONS


def test_module_is_beta_and_off_and_registered():
    m = modules.get("movimento")
    assert m.status == modules.BETA and m.group == "efeitos_visuais" and not modules.default_enabled("movimento")
    assert "estabilizacao" in vfx.EFFECT_PACKAGES
    vfx.load_effects()
    assert estabilizacao.EFFECT_ID in vfx.GEOMETRY and estabilizacao.EFFECT_ID in vfx.EFFECTS
    src = with_analysis(file_source(), shake())
    seq, c = seq_with(src)
    assert "movimento" not in modules.used_by({}, seq)
    seq.set_values(c.id, {**c.values, "estab_on": True})
    assert "movimento" in modules.used_by({}, seq)
    # sem passos na GPU: o plano da pilha continua vazio
    layer = seq.layers_at(0)[0]
    assert vfx.plan(vfx.Ctx(seq, layer, 0, 320, 180, 320, 180)) == []


def test_format_7_only_when_used():
    src = file_source()
    seq, c = seq_with(src)
    assert "ajustes_clipe_1_9" not in seq.features() and "analise_fonte" not in seq.features()
    with_analysis(src, shake())
    assert "analise_fonte" in seq.features()
    seq.set_values(c.id, {**c.values, "estab_on": True})
    assert "ajustes_clipe_1_9" in seq.features()


# ------------------------------------------------------------------ .trf da vid.stab
def test_parse_trf_reads_the_ascii_file():
    frames = estabilizacao.parse_trf((DATA / "tremor_320x180.trf").read_text())
    assert len(frames) == len(TREMOR)
    assert frames[0].shape == (0, 7) and all(len(f) > 10 for f in frames[1:])
    first = frames[1][0]
    assert tuple(first[:2]) == (7.0, -2.0) and first[4] == 32.0   # v = o quanto a câmera andou; campo de 32 px


def test_parse_trf_refuses_other_formats_and_broken_lines():
    with pytest.raises(ValueError):
        estabilizacao.parse_trf("TRF1\x00\x01binario")
    with pytest.raises(ValueError):
        estabilizacao.parse_trf("VID.STAB 1\nFrame 1 (List 2 [(LM 1 2 3 4 32 0.5 0.1)])\n")
    got = estabilizacao.parse_trf("VID.STAB 1\n# comentário\nFrame 1 (List 0 [])\nFrame 3 (List 1 [(LM 1 2 3 4 32 0.5 0.1)])\n")
    assert [len(f) for f in got] == [0, 0, 1]  # quadro sem linha = sem vetores


def test_motions_from_trf_match_the_known_shake():
    frames = estabilizacao.parse_trf((DATA / "tremor_320x180.trf").read_text())
    mot = estabilizacao.motions_from_trf(frames, (320, 180), 320, 180)
    assert mot.shape == (8, 4) and mot.dtype == np.float32 and np.all(mot[0] == 0)
    s = 1080 / 180
    for k in range(1, len(TREMOR)):
        cam = np.subtract(TREMOR[k], TREMOR[k - 1])
        # a cena anda o contrário da câmera, em px@1080
        assert np.allclose(mot[k, :2], -cam * s, atol=0.6), (k, mot[k], cam)
        assert abs(mot[k, 2]) < 1e-3 and abs(mot[k, 3]) < 1e-3


def test_frame_count_refuses_variable_frame_rate():
    m = np.zeros((10, 4), np.float32)
    assert len(estabilizacao._fit_count(m, 10)) == 10
    assert len(estabilizacao._fit_count(m[:9], 10)) == 10      # um a menos: completa com a identidade
    assert len(estabilizacao._fit_count(np.zeros((11, 4)), 10)) == 10
    with pytest.raises(estabilizacao.AnalysisError):
        estabilizacao._fit_count(m[:7], 10)


def test_check_source_refuses_images_and_generated():
    with pytest.raises(estabilizacao.AnalysisError):
        estabilizacao.check_source(tl.Source(path="C:/foto.png", width=10, height=10, is_image=True))
    with pytest.raises(estabilizacao.AnalysisError):
        estabilizacao.check_source(tl.Source.virtual("cor", 10, 10))
    estabilizacao.check_source(file_source())


def test_describe_and_stale(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"123")
    src = file_source(str(p))
    assert "sem análise" in estabilizacao.describe(src)
    with_analysis(src, shake())
    src.analysis[estabilizacao.KIND]["carimbo"] = vfx.stamp(str(p))
    assert "Analisado" in estabilizacao.describe(src)
    p.write_bytes(b"12345")
    assert "mudou" in estabilizacao.describe(src)


# ------------------------------------------------------------------ geometria
def test_off_or_without_analysis_keeps_the_uniforms():
    src = file_source()
    seq, c = seq_with(src)
    base = uniforms(seq, 3)
    with_analysis(src, shake())
    assert uniforms(seq, 3) == base                        # analisado, desligado
    seq.set_values(c.id, {**c.values, "estab_on": True})
    on = uniforms(seq, 3)
    assert on != base
    assert uniforms(seq, 3, neutral=True) == base          # "Desligar todos os efeitos": a geometria de antes
    seq2, c3 = seq_with(file_source(path="C:/sem.mp4"), estab_on=True)  # ligado sem análise: nada muda
    ref, _c = seq_with(file_source(path="C:/sem.mp4"))
    assert list(uniforms(seq2, 3).values())[0] == list(uniforms(ref, 3).values())[0]


def test_correction_undoes_the_camera_on_a_scene_point():
    """Suavizar muito: um ponto fixo da cena anda liso na tela (sobra só a tendência, em linha reta)."""
    mot = shake(24, seed=4)
    src = with_analysis(file_source(frames=24), mot)
    seq, c = seq_with(src, estab_on=True, estab_suavizar=10.0, estab_bordas="preto")
    center = movimento.frame_center(320, 180)
    path = movimento.trajectory(mot, center)
    w1 = 1080 * 320 / 180
    scene = np.array([700.0, 400.0, 1.0])   # um ponto da cena, px@1080 do primeiro quadro
    where = []
    for t in range(24):
        layer = seq.layers_at(t)[0]
        u, _m = compositor.clip_uniforms(seq, layer, 320, 180, 320, 180)
        m = np.array(u["u_xf"]).reshape(3, 3).T                 # px da tela → uv do quadro original
        in_frame = movimento.similarity_matrix(path[layer.src_frame], center) @ scene   # px@1080 do quadro
        uv = np.array([in_frame[0] / w1, in_frame[1] / 1080.0, 1.0])
        where.append((np.linalg.inv(m) @ uv)[:2])
    where = np.array(where)
    raw = np.array([(movimento.similarity_matrix(p, center) @ scene)[:2] for p in path]) * (180 / 1080)
    assert np.abs(np.diff(where, 2, axis=0)).max() < 0.05 * np.abs(np.diff(raw, 2, axis=0)).max()


def test_auto_zoom_hides_the_borders_in_every_frame():
    mot = shake(16, seed=2)
    src = with_analysis(file_source(frames=16), mot)
    seq, c = seq_with(src, estab_on=True, estab_suavizar=2.0)
    corners = np.array([[0, 0, 1], [320, 0, 1], [0, 180, 1], [320, 180, 1]], float).T
    for t in range(16):
        layer = seq.layers_at(t)[0]
        u, _m = compositor.clip_uniforms(seq, layer, 320, 180, 320, 180)
        uv = np.array(u["u_xf"]).reshape(3, 3).T @ corners
        assert uv[:2].min() >= -1e-6 and uv[:2].max() <= 1 + 1e-6, t
        assert u["u_exact"] == 0
    z = estabilizacao.zoom_of(src, seq.clips[0].values)
    assert 1.0 < z <= movimento.MAX_ZOOM
    more = dict(seq.clips[0].values, estab_zoom_extra=0.1)
    assert estabilizacao.zoom_of(src, more) == pytest.approx(z * 1.1)
    black = dict(seq.clips[0].values, estab_bordas="preto")
    assert estabilizacao.zoom_of(src, black) == pytest.approx(1.0)


def test_the_correction_of_a_frame_does_not_change_with_split_trim_or_speed():
    mot = shake(48, seed=6)
    src = with_analysis(file_source(frames=48), mot)
    seq, c = seq_with(src, estab_on=True)

    def by_src(s):
        out = {}
        for t in range(s.duration):
            for layer in s.layers_at(t):
                u, _m = compositor.clip_uniforms(s, layer, 320, 180, 320, 180)
                # a correção é a matriz do quadro × enquadramento: com o mesmo enquadramento, a mesma matriz
                out[layer.src_frame] = u["u_xf"]
        return out

    whole = by_src(seq)
    split = seq.copy()
    split.split(20)
    assert by_src(split) == whole
    trimmed = seq.copy()
    trimmed.trim_start(trimmed.clips[0].id, 10)
    got = by_src(trimmed)
    assert got and all(got[k] == whole[k] for k in got)
    fast = seq.copy()
    fast.set_speed(fast.clips[0].id, 2.0)
    got = by_src(fast)
    assert got and all(got[k] == whole[k] for k in got)


def test_rotation_off_keeps_the_frame_straight():
    mot = shake(16, seed=8)
    src = with_analysis(file_source(frames=16), mot)
    seq, c = seq_with(src, estab_on=True, estab_rotacao=False)
    corr = estabilizacao.corrections_for(src, seq.clips[0].values)
    w1 = 1080 * 320 / 180
    s = np.diag([w1, 1080.0, 1.0])
    for m in corr:
        px = s @ m @ np.linalg.inv(s)
        assert abs(px[0, 1]) < 1e-9 and abs(px[1, 0]) < 1e-9   # sem rotação (só escala e translação)


# ------------------------------------------------------------------ com o ffmpeg
def _write_video(ffmpeg: str, frames: list[np.ndarray], out: Path, codec: str = "ffv1") -> Path:
    h, w = frames[0].shape
    raw = (np.clip(np.stack(frames), 0, 1) * 255).round().astype(np.uint8)
    rgb = np.repeat(raw[..., None], 3, axis=3).tobytes()
    args = [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "24", "-i", "-"]
    args += ["-c:v", "ffv1", "-pix_fmt", "yuv444p"] if codec == "ffv1" else ["-c:v", "libx264", "-crf", "8",
                                                                             "-pix_fmt", "yuv420p"]
    subprocess.run(args + [str(out)], input=rgb, check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def shaky_video(ffmpeg_ok, tmp_path_factory):
    mot = shake(16, seed=9)
    frames = ms.shaken(mot.astype(np.float64), 640, 360, seed=9, margin=120)
    path = _write_video(ffmpeg_ok, frames, tmp_path_factory.mktemp("estab") / "tremido.mkv")
    from pelicula import media
    return tl.Source.from_info(media.probe(str(path))), mot


@pytest.mark.ffmpeg
def test_numpy_analysis_of_a_real_file(shaky_video):
    src, mot = shaky_video
    entry = estabilizacao.analyze(src, method="numpy")
    got = vfx.unpack(entry["movimento"])
    assert entry["metodo"] == "numpy" and entry["quadros"] == src.frames == 16 and entry["carimbo"]
    assert got.shape == (16, 4) and np.allclose(got[:, :2], mot[:, :2], atol=1.0)
    assert np.allclose(got[:, 2], mot[:, 2], atol=0.002)


@pytest.mark.ffmpeg
def test_vidstab_analysis_of_a_real_file(shaky_video):
    if not estabilizacao.available():
        pytest.skip("ffmpeg sem o vidstabdetect")
    src, mot = shaky_video
    seen = []
    entry = estabilizacao.analyze(src, report=lambda d, t: seen.append((d, t)), method="vidstab")
    got = vfx.unpack(entry["movimento"])
    assert entry["metodo"] == "vidstab" and entry["parametros"] == estabilizacao.VIDSTAB and seen
    assert got.shape == (16, 4)
    # a vid.stab mede vetores inteiros na imagem de análise (360 linhas aqui: 3 px@1080 por pixel)
    assert np.allclose(got[:, :2], mot[:, :2], atol=3.0)
    assert np.allclose(got[:, 2], mot[:, 2], atol=0.004)


@pytest.mark.ffmpeg
def test_cancel_stops_the_analysis(shaky_video):
    import threading
    from pelicula.jobs import Cancelled
    src, _mot = shaky_video
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        estabilizacao.analyze(src, cancel=ev, method="numpy")
    if estabilizacao.available():
        with pytest.raises(Cancelled):
            estabilizacao.analyze(src, cancel=ev, method="vidstab")


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_shake_is_corrected_on_the_gpu(gl_engine, shaky_video):
    """Na tela, quadros seguidos de um vídeo tremido ficam quase iguais depois da estabilização (o miolo do quadro)."""
    from pelicula import sequence
    src, mot = shaky_video
    src = tl.Source.from_info(src.to_info())
    with_analysis(src, mot)
    seq, c = seq_with(src)
    w, h = 640, 360

    def frames(on: bool):
        seq.set_values(c.id, {**seq.clips[0].values, "estab_on": on, "estab_suavizar": 10.0, "estab_bordas": "preto"})
        out = []
        for t in range(12):
            img = gl_engine.compose(sequence.grab(seq, t, w, h, 8), seq, w, h, 8)
            out.append(img[60:300, 120:520].astype(np.float64).mean(axis=2))
        return out

    raw = frames(False)
    fixed = frames(True)
    d_raw = np.mean([np.abs(a - b).mean() for a, b in zip(raw, raw[1:])])
    d_fixed = np.mean([np.abs(a - b).mean() for a, b in zip(fixed, fixed[1:])])
    assert d_fixed < 0.35 * d_raw, (d_fixed, d_raw)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_preview_equals_export(gl_engine, shaky_video):
    from pelicula import export, media, sequence
    from pelicula.frame import Recipe
    src, mot = shaky_video
    src = tl.Source.from_info(src.to_info())
    with_analysis(src, mot)
    seq, c = seq_with(src, estab_on=True, estab_suavizar=0.5)
    seq.split(7)
    w, h = 640, 360
    info = sequence.media_info(seq)
    frames = export.frame_pipeline(info, None, export.ExportSettings(), seq, 1.0, 8)
    reader, _skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    try:
        exported = [frames.render(gl_engine, reader.read(), i) for i in range(10)]
    finally:
        reader.close()
    for t in range(10):
        r = Recipe.for_source(None, 24.0, 8, legal=sequence.legal_range(seq), seq=seq, size=(w, h))
        prev = r.render(gl_engine, sequence.grab(seq, t, w, h, 8, shutter=r.shutter), t)
        assert np.array_equal(prev, exported[t]), f"quadro {t}"
