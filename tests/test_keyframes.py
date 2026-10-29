"""Chaves de animação (keyframes.py): curvas, limpeza, âncora nas edições, avaliação única, som e look."""

from __future__ import annotations

import json
import math
import subprocess

import numpy as np
import pytest

from pelicula import audiomix, compositor, editparams, export, frame, keyframes, params, project, sequence
from pelicula import timeline as tl
from pelicula.keyframes import Key

W, H = 320, 180


def video_seq(frames=240, image=False):
    s = tl.Source("C:/v/cena.png" if image else "C:/v/a.mp4", W, H, 24.0, "24/1", 1 if image else frames,
                  0.0 if image else frames / 24, is_image=image, has_audio=not image)
    seq = tl.Sequence.for_source(s)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    return seq, v


def curve(seq, c, key, frames=None):
    return {t: seq.values_at(c, t)[key] for t in (frames if frames is not None else range(c.start, c.end))}


def animated(seq, c, key="opacidade", keys=((10, 0.0, "linear"), (50, 1.0, "suavizar"), (90, 0.25, "linear"))):
    for t, v, e in keys:
        assert seq.set_key(c.id, key, c.start + t, v, e)
    return c


# ------------------------------------------------------------------ curvas e valores
def test_easings_are_exactly_four_and_monotonic():
    assert keyframes.EASINGS == ("linear", "suavizar_entrada", "suavizar_saida", "suavizar")
    assert set(keyframes.EASING_LABELS) == set(keyframes.EASINGS)
    for e in keyframes.EASINGS:
        ws = [keyframes.ease(e, i / 20) for i in range(21)]
        assert ws[0] == 0.0 and ws[-1] == 1.0 and ws == sorted(ws)
    assert keyframes.ease("suavizar_entrada", 0.5) == 0.25
    assert keyframes.ease("suavizar_saida", 0.5) == 0.75
    assert keyframes.ease("suavizar", 0.5) == 0.5 and keyframes.ease("suavizar", 0.25) < 0.25


def test_value_at_holds_the_ends_and_interpolates_with_the_left_key_curve():
    ks = [Key(0, 0.0), Key(10, 1.0, "suavizar_entrada"), Key(20, 0.0)]
    assert keyframes.value_at(ks, -5) == 0.0 and keyframes.value_at(ks, 99) == 0.0
    assert keyframes.value_at(ks, 5) == 0.5                 # linear (curva da chave em 0)
    assert keyframes.value_at(ks, 15) == pytest.approx(0.75)  # 1 − 0,5² (curva da chave em 10)
    assert keyframes.value_at(None, 3, default=7) == 7
    assert keyframes.value_at([Key(4, 2.0)], 100) == 2.0


def test_lists_interpolate_per_component_and_choices_step():
    ks = [Key(0, [0.0, 0.0, 1.0]), Key(10, [1.0, 0.5, 0.0])]
    assert keyframes.value_at(ks, 5, "color") == [0.5, 0.25, 0.5]
    wheel = [Key(0, [0.0, 0.0]), Key(4, [0.8, -0.4])]
    assert keyframes.value_at(wheel, 1, "wheel") == pytest.approx([0.2, -0.1])
    steps = [Key(0, "a"), Key(10, "b")]
    assert [keyframes.value_at(steps, t, "choice") for t in (0, 9.99, 10)] == ["a", "a", "b"]
    assert keyframes.value_at([Key(0, False), Key(3, True)], 2, "bool") is False
    assert keyframes.value_at([Key(0, 0), Key(10, 9)], 5, "int") in (4, 5)


def test_clean_track_sanitizes_against_the_schema():
    p = editparams.VIDEO.params["opacidade"]
    raw = [[5, 2.0], [1, -3, "suavizar"], ["x", 0.5], [2, "nan"], [3], "lixo", [1, 0.5, "inventada"],
           [float("inf"), 0.1], [7, 0.3, "suavizar_saida"]]
    assert keyframes.clean_track(p, raw) == [Key(1.0, 0.5, "linear"), Key(5.0, 1.0), Key(7.0, 0.3, "suavizar_saida")]
    wheel = editparams.VIDEO.params["roda_meios"]
    assert keyframes.clean_track(wheel, [[0, [3.0, 4.0]]]) == [Key(0.0, [0.6, 0.8])]
    # só ajustes animáveis entram (velocidade, escolhas e liga/desliga não)
    keys = keyframes.clean_keys(editparams.VIDEO, {"velocidade": [[0, 2]], "mesclagem": [[0, "tela"]],
                                                   "espelhar_h": [[0, True]], "exposicao": [[0, 9.0]],
                                                   "inexistente": [[0, 1]], "pos_x": "lixo"})
    assert keys == {"exposicao": [Key(0.0, 4.0)]}
    assert keyframes.clean_keys(editparams.VIDEO, None) == {} and keyframes.clean_keys(editparams.VIDEO, []) == {}


def test_json_is_compact_and_round_trips():
    keys = {"opacidade": [Key(0.0, 0.0), Key(12.0, 1.0, "suavizar"), Key(30.5, 0.5)],
            "roda_sombras": [Key(0.0, [0.1, 0.2])]}
    js = keyframes.to_json(keys)
    assert js == {"opacidade": [[0, 0.0], [12, 1.0, "suavizar"], [30.5, 0.5]], "roda_sombras": [[0, [0.1, 0.2]]]}
    assert json.dumps(js, ensure_ascii=True) == json.dumps(js, ensure_ascii=False)  # chaves e curvas em ASCII
    assert keyframes.from_json(editparams.VIDEO, json.loads(json.dumps(js))) == keys


def test_animatable_params_are_marked():
    video = set(keyframes.animatable(editparams.VIDEO))
    assert {"pos_x", "pos_y", "escala", "rotacao", "opacidade", "exposicao", "temperatura", "roda_sombras",
            "roda_luzes_luz", "curva_realces", "hsl_azul_sat", "nitidez", "vinheta"} <= video
    for k in ("velocidade", "congelar", "mesclagem", "encaixe", "espelhar_h", "corte_esq", "fade_in", "entrada_tipo",
              "entrada_dur", "transicao"):
        assert k not in video
    assert set(keyframes.animatable(editparams.AUDIO)) == {"volume"}
    film = keyframes.animatable(params.FILM)
    assert all(p.kind in ("float", "color") for p in film.values())
    assert {"exposicao", "temperatura", "contraste", "saturacao"} <= set(film)
    for k, p in params.PARAMS.items():
        if p.kind in ("choice", "bool", "file", "int"):  # escolhas, chaves e sementes não animam
            assert k not in film


def test_ffmpeg_expr_is_the_same_math_as_value_at():
    ks = [Key(3, -6.0), Key(10, 0.0, "suavizar_entrada"), Key(24, -30.0, "suavizar"), Key(40, -12.0, "suavizar_saida"),
          Key(41, 3.0)]
    expr = keyframes.ffmpeg_expr(ks, "T")
    assert ":" not in expr  # vai entre aspas no grafo; sem dois-pontos de opção
    py = expr.replace("if(", "IF(").replace("lt(", "LT(")
    for t in np.linspace(-5, 50, 221):
        got = eval(py, {"IF": lambda c, a, b: a if c else b, "LT": lambda a, b: a < b, "T": float(t)})  # noqa: S307
        assert got == pytest.approx(keyframes.value_at(ks, float(t)), abs=1e-6), t


# ------------------------------------------------------------------ âncora nas edições
def test_no_keys_is_neutral():
    seq, v = video_seq()
    assert seq.values_at(v, 10) is v.values
    assert all(layer.values is layer.clip.values for layer in seq.layers_at(10))
    assert "chaves" not in json.dumps(seq.to_json()) and not seq.features()
    assert seq.is_trivial() is not None


def test_keys_go_to_json_and_mark_the_feature():
    seq, v = video_seq()
    animated(seq, v)
    seq.trim_start(v.id, 6)
    d = seq.to_json()
    cd = next(c for c in d["clipes"] if c["id"] == v.id)
    assert cd["chaves"]["opacidade"][0] == [10, 0.0] and cd["chaves_ref"] == 6
    assert d["formato"] == tl.FORMAT_15 and "chaves" in seq.features()
    back = tl.Sequence.from_json(json.loads(json.dumps(d)))
    bv = back.find(v.id)
    assert bv.keys == v.keys and bv.key_off == 6 and curve(back, bv, "opacidade") == curve(seq, v, "opacidade")
    assert seq.is_trivial() is None
    p = project.Project(media_path="C:/v/a.mp4", sequence=d, mode="edicao")
    assert p.to_json()["formato"] == project.FORMAT_15 and "chaves" in p.to_json()["recursos"]


def test_move_moves_the_animation():
    seq, v = video_seq()
    animated(seq, v)
    before = curve(seq, v, "opacidade")
    seq.move(v.id, 30)
    assert v.start == 30 and v.key_off == 0
    assert curve(seq, v, "opacidade") == {t + 30: x for t, x in before.items()}


def test_trim_start_keeps_the_animation_on_the_picture():
    seq, v = video_seq()
    animated(seq, v)
    before = curve(seq, v, "opacidade")
    src_before = {t: seq.src_frame(v, t) for t in range(v.start, v.end)}
    seq.trim_start(v.id, 25)
    assert v.start == 25 and v.key_off == 25
    after = curve(seq, v, "opacidade")
    assert after == {t: before[t] for t in range(25, v.end)}
    assert all(seq.src_frame(v, t) == src_before[t] for t in range(25, v.end))
    seq.trim_start(v.id, 5)  # de volta: o começo reaparece com a animação de antes
    assert curve(seq, v, "opacidade") == {t: before[t] for t in range(5, v.end)}
    seq.trim_end(v.id, 100)  # aparar o fim não mexe na animação
    assert curve(seq, v, "opacidade") == {t: before[t] for t in range(5, 100)}


def test_split_keeps_both_halves_exact():
    seq, v = video_seq()
    animated(seq, v)
    animated(seq, next(c for c in seq.clips if c.kind == tl.AUDIO), "volume",
             ((0, 0.0, "linear"), (60, -20.0, "suavizar")))
    before = {c.kind: curve(seq, c, "opacidade" if c.kind == tl.VIDEO else "volume") for c in seq.clips}
    new_ids = seq.split(37)
    assert len(new_ids) == 2
    for kind in (tl.VIDEO, tl.AUDIO):
        key = "opacidade" if kind == tl.VIDEO else "volume"
        merged = {}
        for c in seq.clips:
            if c.kind == kind:
                merged.update(curve(seq, c, key))
        assert merged == before[kind]
    right = seq.find(new_ids[0])
    assert right.key_off == 37 and right.start == 37
    # dividir de novo a metade da direita continua exato
    seq.split(70)
    merged = {}
    for c in seq.clips:
        if c.kind == tl.VIDEO:
            merged.update(curve(seq, c, "opacidade"))
    assert merged == before[tl.VIDEO]


def test_overwrite_cuts_keep_the_animation_of_what_remains():
    seq, v = video_seq()
    animated(seq, v)
    before = curve(seq, v, "opacidade")
    other = tl.Source("C:/v/b.png", W, H, is_image=True)
    seq.insert_media(other, at=0)        # cobre o começo: corte da cabeça (`_clear_range`)
    head_cut = next(c for c in seq.clips if c.id == v.id)
    assert head_cut.start > 0 and head_cut.key_off == head_cut.start
    after = curve(seq, head_cut, "opacidade")
    assert after == {t: before[t] for t in after}
    seq.insert_media(other, at=150)      # no meio: o resto vira dois clipes
    merged = {}
    for c in seq.clips:
        if c.kind == tl.VIDEO and c.src == v.src:
            merged.update(curve(seq, c, "opacidade"))
    assert merged and merged == {t: before[t] for t in merged}


def test_speed_change_keeps_the_animation_on_the_picture():
    seq, v = video_seq()
    animated(seq, v)
    seq.trim_start(v.id, 8)  # com deslocamento: a velocidade reescala a partir do começo atual
    before = curve(seq, v, "opacidade")
    pic_before = {t: seq.src_time(v, t) for t in before}
    seq.set_speed(v.id, 2.0)
    assert v.key_off == 0
    for t, x in before.items():
        if (t - 8) % 2 == 0 and 8 + (t - 8) // 2 < v.end:
            t2 = 8 + (t - 8) // 2
            assert seq.src_time(v, t2) == pytest.approx(pic_before[t])
            assert seq.values_at(v, t2)["opacidade"] == pytest.approx(x)
    seq.set_speed(v.id, 1.0)
    back = curve(seq, v, "opacidade")
    for t in back:
        assert back[t] == pytest.approx(before[t])


def test_delete_and_ripple_keep_the_other_clips_animation():
    seq, v = video_seq(48)
    b = seq.insert_media(tl.Source("C:/v/b.mp4", W, H, 24.0, "24/1", 96, 4.0))[0]
    animated(seq, b)
    before = curve(seq, b, "opacidade")
    seq.delete([v.id], ripple=True)
    assert b.start == 0
    assert curve(seq, b, "opacidade") == {t - 48: x for t, x in before.items()}


def test_cutting_tools_keep_the_animation_on_the_picture_and_the_sound():
    """Ferramentas de corte da 1.5 (Q/W, corte J/L e a velocidade de um par com corte J/L): cada chave continua
    no mesmo instante do arquivo."""
    seq = tl.Sequence(W, H, "24/1")
    for n in "AB":
        seq.insert_media(tl.Source(f"C:/v/{n}.mp4", W, H, 24.0, "24/1", 200, 200 / 24, has_audio=True))
    for c in [c for c in seq.clips if c.kind == tl.VIDEO]:
        seq.trim_start(c.id, c.start + 50)
        seq.trim_end(c.id, c.start + 100)
    seq.close_gaps(tl.VIDEO, 0)
    seq.close_gaps(tl.AUDIO, 0)
    bv = next(c for c in seq.clips if c.kind == tl.VIDEO and c.src.endswith("B.mp4"))
    ba = next(c for c in seq.clips if c.kind == tl.AUDIO and c.src.endswith("B.mp4"))
    animated(seq, bv, keys=((20, 0.0, "linear"), (60, 1.0, "suavizar")))
    animated(seq, ba, "volume", ((30, 0.0, "linear"), (80, -20.0, "suavizar")))

    def anchors():
        def at(c, t):
            return round(c.src_in + (t - c.start) / seq.fps * c.speed, 6)
        return ([(at(bv, t), v) for t, v, _e in seq.keys_of(bv, "opacidade")],
                [(at(ba, t), v) for t, v, _e in seq.keys_of(ba, "volume")])

    first = anchors()
    assert seq.split_edit(bv.id, True, -24) == -24  # corte J: o som de B entra antes da imagem
    assert anchors() == first
    seq.set_speed(bv.id, 2.0)                       # par com corte J: as diferenças acompanham
    assert ba.start != bv.start and bv.speed == ba.speed == 2.0
    assert anchors() == first
    seq.set_speed(bv.id, 1.0)
    assert anchors() == first
    assert seq.ripple_trim_start(bv.id, bv.start + 10) > 0  # Q
    assert seq.ripple_trim_end(bv.id, bv.end - 10) > 0      # W
    assert anchors() == first


def test_relink_keeps_the_keys():
    seq, v = video_seq()
    animated(seq, v)
    keys = dict(v.keys)
    seq.relink("C:/v/a.mp4", "D:/novo/a.mp4")
    assert seq.find(v.id).keys == keys and seq.find(v.id).src == "D:/novo/a.mp4"


def test_local_keys_and_paste_keep_the_animation_relative_to_the_clip_start():
    seq, v = video_seq()
    animated(seq, v, "exposicao", ((0, -1.0, "linear"), (40, 1.0, "suavizar")))
    animated(seq, v, "pos_x", ((0, 0.0, "linear"), (40, 0.5, "linear")))
    seq.trim_start(v.id, 10)
    b = seq.insert_media(tl.Source("C:/v/b.mp4", W, H, 24.0, "24/1", 96, 4.0), at=300)[0]
    seq.trim_start(b.id, 320)
    local = seq.local_keys(v, editparams.color_keys())
    assert set(local) == {"exposicao"}
    assert seq.paste_keys(b.id, local, editparams.color_keys())
    for k in range(0, 40):
        assert seq.values_at(b, b.start + k)["exposicao"] == seq.values_at(v, v.start + k)["exposicao"]
    assert "pos_x" not in b.keys
    assert seq.paste_keys(b.id, {}, editparams.color_keys())  # colar sem animação tira a da cor
    assert not b.keys


def test_set_key_uses_the_current_value_and_respects_locks():
    seq, v = video_seq()
    seq.set_values(v.id, {**v.values, "exposicao": 0.75})
    assert seq.set_key(v.id, "exposicao", 20)
    assert seq.keys_of(v, "exposicao") == [(20.0, 0.75, "linear")]
    assert not seq.set_key(v.id, "exposicao", 20)  # mesma chave: nada muda
    assert seq.move_key(v.id, "exposicao", 20, 30) and seq.keys_of(v, "exposicao")[0][0] == 30.0
    assert not seq.move_key(v.id, "exposicao", 99, 31)
    with pytest.raises(KeyError):
        seq.set_key(v.id, "velocidade", 0, 2.0)
    seq.kind_tracks(tl.VIDEO)[0].locked = True
    assert not seq.set_key(v.id, "exposicao", 40, 1.0)
    seq.kind_tracks(tl.VIDEO)[0].locked = False
    assert seq.remove_key(v.id, "exposicao", 30) and not v.keys


# ------------------------------------------------------------------ avaliação: camadas e uniforms
def test_layer_values_feed_the_uniforms():
    seq, v = video_seq(image=True)
    animated(seq, v, "pos_x", ((0, -0.5, "linear"), (20, 0.5, "linear")))
    animated(seq, v, "opacidade", ((0, 0.0, "linear"), (20, 1.0, "linear")))
    layer = seq.layers_at(10)[0]
    assert layer.values["pos_x"] == 0.0 and layer.values["opacidade"] == 0.5
    U, _mip = compositor.clip_uniforms(seq, layer, W, H, W, H, False)
    static, sv = video_seq(image=True)
    static.set_values(sv.id, {**sv.values, "pos_x": 0.0, "opacidade": 0.5})
    U2, _mip2 = compositor.clip_uniforms(static, static.layers_at(10)[0], W, H, W, H, False)
    assert U == U2


def test_constant_keys_give_the_same_uniforms_as_no_keys():
    seq, v = video_seq()
    seq.set_values(v.id, {**v.values, "exposicao": 0.5, "escala": 1.3})
    plain = [compositor.clip_uniforms(seq, layer, W, H, W, H, False) for layer in seq.layers_at(12)]
    seq.set_key(v.id, "exposicao", 0)
    seq.set_key(v.id, "escala", 100)
    keyed = [compositor.clip_uniforms(seq, layer, W, H, W, H, False) for layer in seq.layers_at(12)]
    assert plain == keyed


def test_decode_size_uses_the_largest_animated_scale():
    s = tl.Source("C:/v/grande.mp4", 1920, 1080, 24.0, "24/1", 96, 4.0)
    seq = tl.Sequence(width=640, height=360, fps_str="24/1")
    v = seq.insert_media(s, 0)[0]
    assert sequence.decode_size(seq, v, 640, 360) == (640, 360)
    seq.set_key(v.id, "escala", 0, 1.0)
    seq.set_key(v.id, "escala", 48, 2.0, "suavizar")
    seq.set_key(v.id, "escala", 90, 1.2)
    assert sequence.decode_size(seq, v, 640, 360) == (1280, 720)  # o mesmo tamanho no clipe inteiro


# ------------------------------------------------------------------ som
def _segments_without_keys(seq):
    clone = tl.Sequence.from_json(seq.to_json())
    for c in clone.clips:
        c.keys, c.key_off = {}, 0
    return clone


def test_audio_graph_without_keys_is_unchanged(tmp_path):
    a = tmp_path / "a.mp4"
    a.write_bytes(b"x")
    seq = tl.Sequence()
    seq.insert_media(tl.Source(str(a), 320, 180, 24.0, "24/1", 48, 2.0, has_audio=True))
    aud = next(c for c in seq.clips if c.kind == tl.AUDIO)
    seq.set_values(aud.id, {**aud.values, "volume": -6.0})
    inputs, graph = audiomix.build_graph(seq)
    assert "volume=-6dB" in graph and "eval=frame" not in graph
    seq.set_key(aud.id, "volume", 0, -6.0)
    seq.set_key(aud.id, "volume", 24, -30.0, "suavizar")
    _i, keyed = audiomix.build_graph(seq)
    assert "volume='pow(10," in keyed and ":eval=frame" in keyed and "volume=-6dB" not in keyed
    assert audiomix.build_graph(_segments_without_keys(seq))[1] == graph
    assert audiomix.mix_key(seq) != audiomix.mix_key(_segments_without_keys(seq))


def _tone(ffmpeg, path, seconds=3):
    cmd = [ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", f"color=c=gray:s=64x36:r=24:d={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=500:sample_rate=48000:duration={seconds}",
           "-map", "0:v", "-map", "1:a", "-c:v", "ffv1", "-c:a", "pcm_s16le", "-shortest", str(path)]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        pytest.skip("não foi possível gerar o tom: " + res.stderr.decode("utf-8", "replace"))
    return str(path)


def _db_windows(samples, rate, times, win=0.04):
    out = []
    for t in times:
        a, b = int((t - win / 2) * rate), int((t + win / 2) * rate)
        rms = float(np.sqrt(np.mean(samples[a:b, 0] ** 2)))
        out.append(20 * math.log10(max(rms, 1e-9)))
    return np.array(out)


@pytest.mark.ffmpeg
def test_volume_envelope_on_a_tone(ffmpeg_ok, tmp_path):
    from pelicula import media
    from test_audiomix import _wav
    src = media.probe_source(_tone(ffmpeg_ok, tmp_path / "tom.mkv"))
    seq = tl.Sequence.for_source(src)
    aud = next(c for c in seq.clips if c.kind == tl.AUDIO)
    times = [0.3, 0.6, 1.0, 1.2, 1.5, 1.8, 2.2, 2.7]
    ref_out = tmp_path / "ref.wav"
    assert audiomix.render_mix(seq, str(ref_out))
    rate, _ch, _w, ref = _wav(ref_out)
    ref_db = _db_windows(ref, rate, times)
    # 0 dB até 0,5 s, desce até −30 dB em 2 s (suavizar) e fica
    seq.set_key(aud.id, "volume", 12, 0.0, "suavizar")
    seq.set_key(aud.id, "volume", 48, -30.0)
    out = tmp_path / "env.wav"
    assert audiomix.render_mix(seq, str(out))
    _r, _c, _w, s = _wav(out)
    got = _db_windows(s, rate, times) - ref_db
    want = np.array([seq.values_at(aud, t * seq.fps)["volume"] for t in times])
    assert np.abs(got - want).max() < 0.8, (got, want)
    # aparar o começo não escorrega o volume em relação ao som (mesmo tempo da sequência, mesmo ganho)
    seq.trim_start(aud.id, 12)
    assert audiomix.render_mix(seq, str(out))
    _r, _c, _w, s = _wav(out)
    later = [t for t in times if t > 0.6]
    got2 = _db_windows(s, rate, later) - _db_windows(ref, rate, later)
    assert np.abs(got2 - want[-len(later):]).max() < 0.8, (got2, want)


# ------------------------------------------------------------------ look
def test_look_values_follow_the_look_keys():
    v = params.defaults()
    r = frame.Recipe.for_source(v, 24.0, 8, legal=True,
                                keys={"exposicao": [[0, -1.0], [10, 1.0]], "bitola": [[0, "8mm"]]})
    assert set(r.keys) == {"exposicao"}  # escolhas não animam
    assert r.look_values(5)["exposicao"] == pytest.approx(0.0)
    assert r.look_values(-3)["exposicao"] == -1.0 and r.look_values(99)["exposicao"] == 1.0
    assert r.look_values(5)["bitola"] == v["bitola"]
    assert frame.Recipe.for_source(v, 24.0, 8, legal=True).look_values(5) is v
    # saída a 48 quadros/s de um arquivo a 24: o quadro 10 da saída é o 5 do arquivo
    r48 = r.with_(fps=48.0, src_fps=24.0)
    assert r48.look_values(10)["exposicao"] == r.look_values(5)["exposicao"]


def test_project_and_job_keep_the_look_keys(make_info):
    name = "exposicao"
    keys = {name: [[0, -1.0], [24, 2.0, "suavizar"]]}
    p = project.Project(media_path="C:/v/a.mp4", look_keys=keys)
    d = p.to_json()
    assert d["chaves"] == keys and d["formato"] == project.FORMAT_15 and d["recursos"] == ["chaves_look"]
    assert project.from_json(json.loads(json.dumps(d))).look_keys == keys
    plain = project.Project(media_path="C:/v/a.mp4").to_json()
    assert "chaves" not in plain and plain["formato"] == project.FORMAT_SIMPLE
    job = export.ExportJob(info=make_info(), values=params.defaults(), settings=export.ExportSettings(),
                           out_path="C:/o.mp4", look_keys=keys)
    back = export.ExportJob.from_dict(json.loads(json.dumps(job.to_dict())))
    assert back.look_keys == keys
    assert "chaves" not in export.ExportJob(info=make_info(), values={}, settings=export.ExportSettings(),
                                            out_path="C:/o.mp4").to_dict()


def test_cli_look_keys_follow_preset_and_set():
    from pelicula import cli
    name = "exposicao"
    p = project.Project(look_keys={name: [[0, 0.1]], "outro": [[0, 1]]})
    assert cli.look_keys(p, None, []) == p.look_keys
    assert cli.look_keys(p, "vision3_500t", []) == {}
    assert name not in cli.look_keys(p, None, [f"{name}=0.3"])
    assert cli.look_keys(None, None, []) == {}


@pytest.mark.gpu
def test_animated_clip_frame_equals_the_static_clip(gl_engine, test_rgb):
    seq, v = video_seq(image=True)
    animated(seq, v, "opacidade", ((0, 0.0, "linear"), (20, 1.0, "linear")))
    animated(seq, v, "exposicao", ((0, -1.0, "linear"), (20, 1.0, "linear")))
    animated(seq, v, "escala", ((0, 1.0, "linear"), (20, 1.5, "linear")))
    static, sv = video_seq(image=True)
    static.set_values(sv.id, {**sv.values, "opacidade": 0.5, "exposicao": 0.0, "escala": 1.25})
    fl = sequence.FrameLayers(10, [sequence.LayerImage(layer, test_rgb) for layer in seq.layers_at(10)])
    fs = sequence.FrameLayers(10, [sequence.LayerImage(layer, test_rgb) for layer in static.layers_at(10)])
    a = gl_engine.compose(fl, seq, W, H, 8)
    assert np.array_equal(a, gl_engine.compose(fs, static, W, H, 8))
    first = sequence.FrameLayers(0, [sequence.LayerImage(layer, test_rgb) for layer in seq.layers_at(0)])
    assert gl_engine.compose(first, seq, W, H, 8).max() == 0  # opacidade 0 no começo: só o fundo


@pytest.mark.gpu
def test_animated_look_frame_equals_the_static_look(gl_engine, test_rgb):
    name = "exposicao"
    v = params.defaults()
    r = frame.Recipe.for_source(v, 24.0, 8, legal=True, keys={name: [[0, 0.0], [10, 1.0, "suavizar_saida"]]})
    static = frame.Recipe.for_source({**v, name: r.look_values(5)[name]}, 24.0, 8, legal=True)
    a = r.render(gl_engine, test_rgb, 5)
    assert np.array_equal(a, static.render(gl_engine, test_rgb, 5))
    assert not np.array_equal(a, r.render(gl_engine, test_rgb, 10))
