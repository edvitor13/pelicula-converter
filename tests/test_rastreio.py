"""1.9 (F3): rastreio de ponto (`rastreio.py`; ARQUITETURA §51.3).

Sem ffmpeg nem GPU: um alvo com textura que anda e gira (quadros sintéticos) é seguido a menos de 1 px@1080, o rastro se
perde com aviso quando o alvo some, o JSON do clipe, a simplificação das chaves (RDP) e o "Aplicar a…" — o próprio clipe
fica com o ponto parado na tela, um título acima segue o ponto, as chaves continuam certas depois de aparar e de mudar a
velocidade, e tudo é um passo do desfazer. Com o ffmpeg, um rastreio lendo um arquivo de verdade.
"""

from __future__ import annotations

import math
import subprocess

import numpy as np
import pytest

import movimento_sinteticos as ms
from pelicula import editparams, keyframes, rastreio, vfx
from pelicula import timeline as tl

W, H = 960, 540
PX = H / 1080.0   # pixels destas imagens por px@1080


def scene_frames(path, rot_deg=None, n=None, seed=3, size=(W, H)):
    """Quadros de uma cena com textura vista por uma câmera que anda `path[k]` (px das imagens) e gira `rot_deg[k]` em
    volta do meio. Devolve os quadros e a função que leva um ponto do quadro 0 ao quadro k."""
    w, h = size
    n = len(path) if n is None else n
    rot = np.zeros(n) if rot_deg is None else np.asarray(rot_deg, float)
    big = ms.texture(h + 400, w + 400, seed)
    c = np.array([w / 2.0, h / 2.0])
    mats = []
    for k in range(n):
        a = math.radians(rot[k])
        r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        m = np.eye(3)
        m[:2, :2] = r
        m[:2, 2] = c - r @ c + np.asarray(path[k], float)   # cena (quadro 0) → quadro k
        mats.append(m)
    frames = [ms.warp(big, np.linalg.inv(m), w, h, (200.0, 200.0)) for m in mats]

    def where(k, p):
        q = mats[k] @ [p[0], p[1], 1.0]
        return q[:2]

    return frames, where


def getter(frames):
    def get_range(a, b):
        return ((k, frames[k]) for k in range(a, b + 1))
    return get_range


def test_follows_a_moving_target_within_one_pixel_at_1080():
    n = 24
    path = [(30 * math.sin(k / 3.0), 18 * math.cos(k / 4.0) - 18 + 2.5 * k) for k in range(n)]
    frames, where = scene_frames(path)
    p0 = np.array([400.0, 260.0])
    ref = 9
    pref = where(ref, p0)
    tr = rastreio.track(getter(frames), (W, H), ref, (pref[0] / W, pref[1] / H), 0, n - 1, box=64, search=48)
    assert tr.first == 0 and tr.last == n - 1 and not tr.lost and tr.score[ref] == 1.0
    for k in range(n):
        u, v = tr.at(k)
        err = np.hypot(u * W - where(k, p0)[0], v * H - where(k, p0)[1]) / PX
        assert err < 1.0, (k, err)


def test_follows_a_rotating_target():
    n = 16
    frames, where = scene_frames([(2.0 * k, 0.0) for k in range(n)], rot_deg=[1.2 * k for k in range(n)])
    p0 = np.array([610.0, 330.0])
    tr = rastreio.track(getter(frames), (W, H), 0, (p0[0] / W, p0[1] / H), 0, n - 1, box=56, search=40)
    assert tr.last == n - 1 and not tr.lost
    errs = [np.hypot(tr.at(k)[0] * W - where(k, p0)[0], tr.at(k)[1] * H - where(k, p0)[1]) / PX for k in range(n)]
    assert max(errs) < 1.0, errs


def test_lost_target_stops_with_a_message():
    n = 12
    frames, where = scene_frames([(3.0 * k, 0.0) for k in range(n)])
    rng = np.random.default_rng(0)
    for k in range(7, n):
        frames[k] = rng.random((H, W)).astype(np.float32)   # o alvo some
    p0 = np.array([480.0, 270.0])
    tr = rastreio.track(getter(frames), (W, H), 2, (p0[0] / W, p0[1] / H), 0, n - 1)
    assert tr.first == 0 and tr.last == 6 and "7" in tr.lost


def test_refuses_a_flat_point_or_the_border():
    flat = [np.full((H, W), 0.5, np.float32)] * 3
    with pytest.raises(rastreio.TrackError):
        rastreio.track(getter(flat), (W, H), 0, (0.5, 0.5), 0, 2)
    frames, _w = scene_frames([(0.0, 0.0)] * 3)
    with pytest.raises(rastreio.TrackError):
        rastreio.track(getter(frames), (W, H), 0, (0.005, 0.5), 0, 2)


def test_cancel_raises():
    from pelicula.jobs import Cancelled
    frames, _w = scene_frames([(k, 0.0) for k in range(6)])
    with pytest.raises(Cancelled):
        rastreio.track(getter(frames), (W, H), 0, (0.5, 0.5), 0, 5, cancel=lambda: True)


def test_rdp_keeps_corners_and_drops_straight_runs():
    t = np.arange(21, dtype=float)
    x = np.where(t <= 10, t * 2.0, 20.0 + (t - 10) * -1.0)
    pts = np.column_stack([t, x, np.zeros_like(t)])
    assert rastreio.rdp(pts, 0.5) == [0, 10, 20]
    noisy = pts.copy()
    noisy[5, 1] += 3.0
    assert 5 in rastreio.rdp(noisy, 0.5)
    assert rastreio.rdp(pts[:2], 0.5) == [0, 1]


def test_track_json_round_trip_and_store():
    tr = rastreio.Track(ref=4, first=2, uv=np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]),
                        score=np.array([0.9, 1.0, 0.8]), box=48.0, lost="perdeu", target={"tipo": "acima", "clipe": "x"})
    back = rastreio.Track.from_json(tr.to_json())
    assert back.ref == 4 and back.first == 2 and back.last == 4 and back.box == 48.0 and back.lost == "perdeu"
    assert np.allclose(back.uv, tr.uv, atol=1e-6) and back.target == tr.target
    assert back.at(3) == pytest.approx((0.3, 0.4)) and back.at(5) is None and back.at(1) is None
    assert rastreio.Track.from_json({"uv": "lixo"}) is None
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = seq.insert_media(tl.Source.virtual("cor", W, H, "24/1"), at=0)[0]
    rastreio.store(c, tr)
    assert "rastros" in c.fx and "efeitos_clipe_dados" in seq.features()
    again = tl.Sequence.from_json(seq.to_json())
    assert rastreio.track_of(again.find(c.id)).first == 2
    rastreio.store(c, None)
    assert c.fx == {} and "efeitos_clipe_dados" not in seq.features()


# ------------------------------------------------------------------ aplicar
def file_source(path="C:/videos/cena.mp4", w=W, h=H, frames=48) -> tl.Source:
    return tl.Source(path=path, width=w, height=h, fps=24.0, fps_str="24/1", frames=frames, duration=frames / 24.0,
                     has_video=True)


def tracked_seq(n=48, start=0):
    """Um clipe de vídeo (sem ler o arquivo) com um rastro sintético: o ponto anda numa curva conhecida em uv."""
    src = file_source(frames=n)
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    seq.sources[src.path] = src
    c = seq.insert_media(src, at=start, with_audio=False)[0]
    k = np.arange(n)
    uv = np.column_stack([0.5 + 0.06 * np.sin(k / 12.0), 0.45 + 0.04 * np.cos(k / 10.0) + 0.002 * k])
    rastreio.store(c, rastreio.Track(ref=10, first=0, uv=uv, score=np.ones(n)))
    return seq, c


def _screen(seq, clip, t):
    return rastreio.canvas_point(seq, clip, t, rastreio.track_of(clip).at(seq.src_frame(clip, t)))


def test_apply_to_the_clip_itself_keeps_the_point_still():
    seq, c = tracked_seq()
    seq.set_values(c.id, {**c.values, "escala": 1.3, "rotacao": 4.0})
    t_ref = 10
    before = _screen(seq, c, t_ref)
    n = rastreio.apply(seq, c.id, "proprio", c.id)
    assert 2 <= n < 48 and set(c.keys) == {"pos_x", "pos_y"}
    assert rastreio.track_of(c).target == {"tipo": "proprio", "clipe": c.id}
    for t in range(c.start, c.end):
        assert np.hypot(*(_screen(seq, c, t) - before)) * (1080 / H) < rastreio.TOLERANCE_PX + 1e-6, t


def test_apply_to_a_title_above_follows_the_point():
    seq, c = tracked_seq()
    title = seq.insert_media(tl.Source.virtual("texto", W, H, "24/1"), at=5, vtrack=1, with_audio=False)[0]
    title.dur = 30
    seq.set_values(title.id, {**title.values, "pos_x": 0.1, "pos_y": -0.2})
    assert [d.id for t, d in rastreio.targets_for(seq, c) if t.id == "acima"] == [title.id]
    rastreio.apply(seq, c.id, "acima", title.id)
    vals = seq.values_at(title, 10)
    assert vals["pos_x"] == pytest.approx(0.1, abs=1e-6) and vals["pos_y"] == pytest.approx(-0.2, abs=1e-6)
    p_ref = _screen(seq, c, 10)
    for t in range(title.start, title.end):
        v = seq.values_at(title, t)
        moved = np.array([(v["pos_x"] - 0.1) * W, (v["pos_y"] + 0.2) * H])
        assert np.hypot(*(moved - (_screen(seq, c, t) - p_ref))) * (1080 / H) < rastreio.TOLERANCE_PX + 1e-6, t
    # fora do trecho do título nada foi assado; o rastreado não ganhou chaves
    assert not c.keys and all(title.start <= seq.seq_time(title, k.t) < title.end for k in title.keys["pos_x"])


def test_keys_survive_trim_and_speed():
    seq, c = tracked_seq()
    before = _screen(seq, c, 10)
    rastreio.apply(seq, c.id, "proprio", c.id)
    seq.trim_start(c.id, 6)
    c = seq.find(c.id)
    for t in range(c.start, c.end):
        assert np.hypot(*(_screen(seq, c, t) - before)) * (1080 / H) < rastreio.TOLERANCE_PX + 1e-6, t
    seq.set_speed(c.id, 2.0)
    c = seq.find(c.id)
    for t in range(c.start, c.end):
        assert np.hypot(*(_screen(seq, c, t) - before)) * (1080 / H) < 1.0, t


def test_apply_is_one_undo_step_and_reapply_follows_edits():
    seq, c = tracked_seq()
    title = seq.insert_media(tl.Source.virtual("texto", W, H, "24/1"), at=0, vtrack=1, with_audio=False)[0]
    title.dur = 40
    hist = tl.History(seq)
    rastreio.apply(seq, c.id, "acima", title.id)
    assert hist.push(seq)
    restored = hist.undo(seq)
    t2 = restored.find(title.id)
    assert not t2.keys and not rastreio.track_of(restored.find(c.id)).target
    # Reaplicar: depois de mover o título, as chaves voltam a cobrir o trecho dele
    seq.move(title.id, 8)
    title = seq.find(title.id)
    rastreio.reapply(seq, c.id)
    ks = title.keys["pos_x"]
    assert seq.seq_time(title, ks[0].t) == pytest.approx(8) and seq.seq_time(title, ks[-1].t) == pytest.approx(47)


def test_apply_refusals():
    seq, c = tracked_seq()
    with pytest.raises(rastreio.TrackError):
        rastreio.reapply(seq, c.id)
    other = seq.insert_media(tl.Source.virtual("texto", W, H, "24/1"), at=60, vtrack=1, with_audio=False)[0]
    with pytest.raises(rastreio.TrackError):
        rastreio.apply(seq, c.id, "acima", other.id)       # não passa junto
    seq.track(tl.VIDEO, 0).locked = True
    with pytest.raises(rastreio.TrackError):
        rastreio.apply(seq, c.id, "proprio", c.id)
    plain = tl.Sequence(width=W, height=H, fps_str="24/1")
    p = plain.insert_media(tl.Source.virtual("cor", W, H, "24/1"), at=0)[0]
    with pytest.raises(rastreio.TrackError):
        rastreio.apply(plain, p.id, "proprio", p.id)


def test_existing_keys_outside_the_span_stay():
    seq, c = tracked_seq()
    title = seq.insert_media(tl.Source.virtual("texto", W, H, "24/1"), at=0, vtrack=1, with_audio=False)[0]
    title.dur = 48
    title.keys = keyframes.clean_keys(editparams.VIDEO, {"opacidade": [[0, 0.0], [10, 1.0]]})
    rastreio.apply(seq, c.id, "acima", title.id)
    assert "opacidade" in title.keys and "pos_x" in title.keys


def test_mask_target_hook_in_clip_units():
    """O alvo da máscara (F2) entra com uma linha; aqui com chaves que já existem, para provar o caminho do uv."""
    seq, c = tracked_seq()
    target = rastreio.Target("teste_uv", "teste", ("pos_x", "pos_y"), rastreio.same_clip, rastreio.uv_value,
                             relative=False, units="clipe")
    rastreio.TARGETS["teste_uv"] = target
    try:
        rastreio.apply(seq, c.id, "teste_uv", c.id)
        tr = rastreio.track_of(c)
        v = seq.values_at(c, 20)
        assert v["pos_x"] == pytest.approx(tr.at(20)[0], abs=0.01) and v["pos_y"] == pytest.approx(tr.at(20)[1],
                                                                                                    abs=0.01)
    finally:
        rastreio.TARGETS.pop("teste_uv", None)


def test_the_mask_follows_the_track_in_clip_px():
    """Integração F2 + F3: o alvo "mascara" só aparece com forma no clipe e grava o centro em px@1080 do clipe
    (`mascaras_clipe.clip_px`), somando ao lugar em que a máscara estava no quadro de referência."""
    from pelicula import mascaras_clipe, sequence
    seq, c = tracked_seq()
    assert "mascara" not in [t.id for t, _d in rastreio.targets_for(seq, c)]
    seq.set_values(c.id, {**c.values, "mascara_forma": "elipse", "mascara_x": 30.0, "mascara_y": -20.0})
    assert ("mascara", c.id) in [(t.id, d.id) for t, d in rastreio.targets_for(seq, c)]
    rastreio.apply(seq, c.id, "mascara", c.id)
    assert "mascara_x" in c.keys and "mascara_y" in c.keys
    tr = rastreio.track_of(c)
    tw, th = sequence.decode_size(seq, c, seq.width, seq.height)
    frames = [t for t in range(c.start, c.end) if tr.at(seq.src_frame(c, t)) is not None]
    ref = rastreio._ref_frame(seq, c, tr, frames)
    p_ref = mascaras_clipe.clip_px(tr.at(seq.src_frame(c, ref)), tw, th)
    for t in (frames[0], frames[len(frames) // 2], frames[-1]):
        want = np.array([30.0, -20.0]) + mascaras_clipe.clip_px(tr.at(seq.src_frame(c, t)), tw, th) - p_ref
        v = seq.values_at(c, t)
        assert np.hypot(v["mascara_x"] - want[0], v["mascara_y"] - want[1]) < 1.0, t


# ------------------------------------------------------------------ com o ffmpeg
@pytest.mark.ffmpeg
def test_run_reads_the_file(ffmpeg_ok, tmp_path):
    n = 12
    frames, where = scene_frames([(4.0 * k, 1.5 * k) for k in range(n)], size=(640, 360))
    raw = (np.clip(np.stack(frames), 0, 1) * 255).round().astype(np.uint8)
    out = tmp_path / "alvo.mkv"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "640x360", "-r", "24",
                    "-i", "-", "-c:v", "ffv1", str(out)], input=raw.tobytes(), check=True, capture_output=True)
    from pelicula import media
    src = tl.Source.from_info(media.probe(str(out)))
    p0 = np.array([300.0, 170.0])
    seen = []
    tr = rastreio.run(src, 5, (where(5, p0)[0] / 640, where(5, p0)[1] / 360), 0, n - 1,
                      report=lambda d, t: seen.append(d))
    assert tr.first == 0 and tr.last == n - 1 and seen
    for k in range(n):
        u, v = tr.at(k)
        assert np.hypot(u * 640 - where(k, p0)[0], v * 360 - where(k, p0)[1]) * (1080 / 360) < 1.5, k
    with pytest.raises(rastreio.TrackError):
        rastreio.run(tl.Source.virtual("cor", 10, 10), 0, (0.5, 0.5), 0, 1)


def test_clip_uv_and_canvas_point_are_inverse():
    seq, c = tracked_seq()
    seq.set_values(c.id, {**c.values, "escala": 0.7, "rotacao": -12.0, "pos_x": 0.1})
    uv = (0.3, 0.6)
    p = rastreio.canvas_point(seq, c, 5, uv)
    back = rastreio.clip_uv(seq, c, 5, p[0] / W, p[1] / H)
    assert back == pytest.approx(uv, abs=1e-9)
    assert rastreio.clip_uv(seq, c, 5, 0.001, 0.001) is None


def test_stabilized_clip_moves_the_canvas_point():
    """A geometria da estabilização entra no ponto da tela (o título segue o que o usuário vê)."""
    from pelicula import estabilizacao
    seq, c = tracked_seq()
    src = seq.sources[c.src]
    mot = np.zeros((48, 4), np.float32)
    mot[1::2, 0] = 20.0
    mot[2::2, 0] = -20.0
    src.analysis[estabilizacao.KIND] = {"movimento": vfx.pack(mot)}
    a = rastreio.canvas_point(seq, c, 7, (0.5, 0.5))
    seq.set_values(c.id, {**c.values, "estab_on": True})
    b = rastreio.canvas_point(seq, c, 7, (0.5, 0.5))
    assert np.hypot(*(a - b)) > 1.0
