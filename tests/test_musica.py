"""Música na montagem (`musica.py`, 1.8, ARQUITETURA §46): batidas no tempo da sequência (aparar, velocidade, rampa,
reverso), ímã nas batidas, o plano de encaixar a música numa duração e o de abaixá-la sob a voz."""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import batidas, musica
from pelicula import timeline as tl

FPS = 24


def grid_beats(bpm: float = 120.0, secs: float = 60.0, first: float = 0.0, phase: int = 0) -> batidas.Beats:
    """Batidas exatas a `bpm` desde `first`; o compasso começa na batida `phase`."""
    per = 60.0 / bpm
    times = tuple(first + i * per for i in range(int((secs - first) / per) + 1))
    return batidas.Beats(times, bpm, times[phase::4], 1.0, (bpm / 2, bpm * 2), 1.0, secs)


def music_seq(secs: float = 60.0, start: int = 0, src_in: float = 0.0, dur: int | None = None,
              speed: float = 1.0) -> tuple[tl.Sequence, tl.Clip]:
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(tl.Source("musica.wav", fps=float(FPS), frames=int(secs * FPS), duration=secs, has_video=False,
                             has_audio=True))
    c = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, start, dur or int((secs - src_in) * FPS), src_in,
                values={"velocidade": speed})
    seq.clips.append(c)
    return seq, c


# ------------------------------------------------------------------ batidas no tempo da sequência
def test_beat_frames_follow_trim_and_speed():
    b = grid_beats(120)
    seq, c = music_seq(start=48, src_in=2.0, dur=120)       # começa no quadro 48 com 2 s do arquivo: 5 s de clipe
    fr = musica.beat_frames(seq, c, b)
    assert [f for f, _d in fr] == pytest.approx([48 + 12 * k for k in range(10)])
    assert [d for _f, d in fr] == [k % 4 == 0 for k in range(10)]   # 2,0 s é começo de compasso (batida 4)
    seq.set_speed(c.id, 2.0)                                   # 2×: uma batida a cada 6 quadros, no mesmo começo
    c = seq.find(c.id)
    fr = musica.beat_frames(seq, c, b)
    assert fr[0][0] == pytest.approx(48) and np.allclose(np.diff([f for f, _d in fr]), 6)
    assert all(48 <= f < c.end for f, _d in fr)
    # rampa e reverso: o mapa exato do clipe (o quadro em que o arquivo passa pela batida)
    seq, c = music_seq(start=0, src_in=10.0, dur=96)
    seq.retime(c.id, reverse=True)
    c = seq.find(c.id)
    rev = musica.beat_frames(seq, c, b)
    assert len(rev) == 8 and rev[0][0] == pytest.approx(0)    # de 10 s para trás: 10; 9,5; … 6,5
    for f, _d in rev:
        s = seq.time_map(c).src_at((f - c.start) / FPS)
        assert abs(s * 2 - round(s * 2)) < 1e-6
    seq, c = music_seq(start=0, src_in=0.0, dur=240)
    seq.retime(c.id, ramp=[[0.0, 1.0], [10.0, 2.0]])
    c = seq.find(c.id)
    m = seq.time_map(c)
    for f, _d in musica.beat_frames(seq, c, b):
        s = m.src_at((f - c.start) / FPS)
        assert abs(s * 2 - round(s * 2)) < 1e-6           # cada marca cai exatamente numa batida do arquivo


def test_snap_frames_skip_the_dragged_clip():
    b = grid_beats(120)
    seq, c = music_seq(start=7, dur=48)
    pts = musica.snap_frames(seq, lambda p: b if p == "musica.wav" else None)
    assert {7, 19, 31, 43} <= pts and 55 not in pts          # só dentro do clipe
    assert musica.snap_frames(seq, lambda p: b, exclude=[c.id]) == set()
    assert musica.snap_frames(seq, lambda p: None) == set()


# ------------------------------------------------------------------ encaixar a música numa duração
def played_downbeats(plan, b, speed=1.0, fps=FPS):
    """Quadros da sequência em que cada começo de compasso toca, pedaço por pedaço."""
    out = []
    for p in plan.pieces:
        u1 = p.src_in + p.dur / fps * speed
        out += [p.start + (d - p.src_in) / speed * fps for d in b.downbeats if p.src_in - 1e-9 <= d < u1 - 1e-9]
    return out


def check_joints(plan, b, speed=1.0, fps=FPS):
    downs = np.array(b.downbeats)
    for prev, p in zip(plan.pieces, plan.pieces[1:]):
        assert p.start == prev.start + prev.dur                       # sem buraco nem sobreposição
        assert np.min(np.abs(downs - p.src_in)) < speed / fps         # entra num começo de compasso
        out = prev.src_in + prev.dur / fps * speed
        assert np.min(np.abs(downs - out)) < speed / fps              # e sai noutro
        assert p.transition == pytest.approx(60.0 / b.bpm / speed, abs=1e-3)   # uma batida de transição


def test_fit_shortens_by_whole_bars_in_the_middle():
    b = grid_beats(120)                                     # compassos de 2 s
    seq, c = music_seq(60.0)
    plan = musica.fit_plan(b, c, 30 * FPS, FPS)
    assert plan.ok and plan.removed == 15 and plan.added == 0
    assert plan.pieces[0].start == 0 and plan.end == 30 * FPS
    assert len(plan.pieces) == 2 and plan.pieces[0].src_in == 0.0
    assert plan.pieces[1].src_in + plan.pieces[1].dur / FPS == pytest.approx(60.0)   # o final natural inteiro
    cut_at = plan.pieces[0].dur / FPS
    assert 10.0 <= cut_at <= 16.0 and 40.0 <= plan.pieces[1].src_in <= 46.0         # o corte é no meio
    check_joints(plan, b)
    assert plan.fade_out == 0.0                             # nada cortado do fim
    # duração que não é um número inteiro de compassos: o resto sai do fim, com a saída suave
    plan = musica.fit_plan(b, c, int(31.3 * FPS), FPS)
    assert plan.ok and plan.end == int(31.3 * FPS) and plan.fade_out == musica.FADE_S
    check_joints(plan, b)


def test_fit_lengthens_by_repeating_bars_and_keeps_the_tempo():
    b = grid_beats(128, secs=40.0, first=0.3)               # compasso de 1,875 s, a 25 qps: emendas fora da grade
    fps = 25
    seq = tl.Sequence(640, 360, f"{fps}/1")
    seq.add_source(tl.Source("musica.wav", fps=25.0, frames=1000, duration=40.0, has_video=False, has_audio=True))
    c = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 10, 950, 1.0)
    seq.clips.append(c)
    for target in (1200, 1650, 4000):                       # um bloco, o meio quase todo, o meio repetido várias vezes
        plan = musica.fit_plan(b, c, target, fps)
        assert plan.ok and plan.added > 0 and plan.end == 10 + target, target
        check_joints(plan, b, fps=fps)
        bar = 4 * 60.0 / 128 * fps
        played = np.array(played_downbeats(plan, b, fps=fps))
        phase = (played - played[0]) / bar
        assert np.allclose(phase, np.round(phase), atol=1e-6)   # os compassos continuam na mesma grade
        assert plan.pieces[0].src_in == 1.0 and plan.pieces[-1].src_in < 39.0
    # a velocidade do clipe entra na conta
    seq.set_speed(c.id, 2.0)
    c = seq.find(c.id)
    plan = musica.fit_plan(b, c, c.dur + 100, fps)
    assert plan.ok and plan.end == c.start + c.dur + 100
    check_joints(plan, b, speed=2.0, fps=fps)


def test_fit_refusals_and_the_simple_fade():
    b = grid_beats(120)
    seq, c = music_seq(60.0)
    shaky = batidas.Beats(b.times, b.bpm, b.downbeats, 0.2)
    plan = musica.fit_plan(shaky, c, 30 * FPS, FPS)
    assert not plan.ok and "confiáveis" in plan.reason and plan.can_fade
    plan = musica.fit_plan(b, c, 6 * FPS, FPS)              # introdução (4 s) + final (4 s) não cabem em 6 s
    assert not plan.ok and plan.can_fade
    fade = musica.fade_plan(c, 6 * FPS, FPS)
    assert fade.ok and fade.end == 6 * FPS and fade.fade_out == musica.FADE_S
    assert not musica.fade_plan(c, 70 * FPS, FPS).ok       # a saída simples não alonga
    seq, short = music_seq(8.0)                             # 4 compassos: nada no meio
    assert not musica.fit_plan(b, short, 6 * FPS, FPS).ok
    seq, c = music_seq(60.0)
    seq.retime(c.id, reverse=True)
    assert not musica.fit_plan(b, seq.find(c.id), 30 * FPS, FPS).ok


def test_fit_target_and_blockers():
    seq, c = music_seq(60.0, start=24)
    assert musica.fit_target(seq, c) is None               # sem imagem e sem trecho
    seq.add_source(tl.Source("video.mp4", 640, 360, 24.0, "24/1", 2400, 100.0, has_video=True, has_audio=False))
    v = tl.Clip(tl.new_id(), tl.VIDEO, "video.mp4", 0, 0, 30 * FPS, 0.0)
    seq.clips.append(v)
    assert musica.fit_target(seq, c) == (24, 30 * FPS)
    assert musica.fit_target(seq, c, 48, 959) == (48, 960)
    assert musica.fit_blockers(seq, c, 24, 720) == ""
    other = tl.Clip(tl.new_id(), tl.AUDIO, "musica.wav", 0, 1500, 48, 0.0)
    seq.clips.append(other)
    assert musica.fit_blockers(seq, c, 24, 2000) != ""
    c.link = v.link = "x"
    assert "ligado" in musica.fit_blockers(seq, c, 24, 720)


def test_apply_fit_is_one_undo_step():
    from pelicula.ui.edit_model import TimelineModel
    b = grid_beats(120)
    seq, c = music_seq(60.0, start=24)
    c.values = {**c.values, "volume": -6.0, "fade_in": 1.0, "fade_out": 3.0}
    seq.set_key(c.id, "volume", 24 + 240, -3.0)
    m = TimelineModel(seq)
    plan = musica.fit_plan(b, m.seq.find(c.id), 30 * FPS, FPS)
    ids = []
    assert m.apply_edit(lambda s: ids.extend(musica.apply_fit(s, c.id, plan)))
    parts = [m.seq.find(i) for i in ids]
    assert ids[0] == c.id and len(parts) == 2
    assert [(p.start, p.dur) for p in parts] == [(q.start, q.dur) for q in plan.pieces]
    assert parts[0].values["fade_in"] == 1.0 and parts[0].values["fade_out"] == 0.0
    assert parts[1].values["fade_in"] == 0.0 and parts[1].values["fade_out"] == 3.0
    assert parts[1].values["transicao"] == pytest.approx(0.5) and parts[1].values["volume"] == -6.0
    prev, before, after = m.seq.audio_crossfade(parts[1])
    assert prev is parts[0] and before + after == pytest.approx(0.5)   # a emenda tem a transição de som
    assert m.seq.keys_of(parts[0], "volume")[0][0] == 264             # a chave fica presa à música
    m.undo()
    assert len(m.seq.clips) == 1 and m.seq.find(c.id).dur == 60 * FPS and not m.can_undo()
    assert not m.apply_edit(lambda s: None)                 # nada mudou: nenhum passo


# ------------------------------------------------------------------ abaixar a música sob a voz
VR = 48000


def voice(secs: float, bursts, seed: int = 3, noise=()) -> np.ndarray:
    """Fala sintética: vogais (harmônicos de 140 Hz com vibrato, sílabas a 4 Hz) nos trechos `bursts`, um chiado
    fraco por baixo e rajadas de ruído branco forte (que não são fala) em `noise`."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs * VR)) / VR
    x = 0.002 * rng.standard_normal(len(t))
    f0 = 140 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))
    ph = 2 * np.pi * np.cumsum(f0) / VR
    vowel = sum(np.sin(k * ph) / k for k in range(1, 12))
    syll = 0.55 + 0.45 * np.sin(2 * np.pi * 4 * t) ** 2
    for a, b in bursts:
        m = (t >= a) & (t < b)
        x[m] += 0.25 * vowel[m] * syll[m]
    for a, b in noise:
        m = (t >= a) & (t < b)
        x[m] += 0.3 * rng.standard_normal(m.sum())
    return x


def test_speech_regions_find_voice_and_skip_noise():
    x = voice(12.0, [(1.0, 3.0), (3.5, 4.5), (8.0, 9.2)], noise=[(6.0, 6.8)])
    regions = musica.speech_regions(x, VR)
    assert len(regions) == 2, regions                        # 3,0 → 3,5: menos de 1 s, viram uma; o ruído não conta
    (a0, b0), (a1, b1) = regions
    assert abs(a0 - 1.0) < 0.05 and 4.5 <= b0 <= 4.5 + musica.VOICE_HANG_S + 0.05
    assert abs(a1 - 8.0) < 0.05 and 9.2 <= b1 <= 9.2 + musica.VOICE_HANG_S + 0.05
    stereo = np.repeat(x[:, None], 2, axis=1).astype(np.float32)
    assert musica.speech_regions(stereo, VR) == pytest.approx(regions, abs=0.02)
    assert musica.speech_regions(np.zeros(VR), VR) == []
    assert musica.speech_regions(voice(4.0, []), VR) == []  # só o chiado de fundo


def test_duck_keys_frames_and_depth():
    seq, c = music_seq(60.0, start=24, dur=480)            # quadros 24 a 503
    c.values = {**c.values, "volume": -4.0}
    ducks = musica.duck_spans(c, [(5.0, 8.0), (8.5, 9.0), (30.0, 40.0)], FPS, attack=0.5, release=1.0)
    assert ducks == [musica.Duck(108, 120, 216, 240)]      # 8,5 s: a subida tocaria a descida seguinte; 30 s: fora
    assert musica.apply_duck(seq, c.id, ducks, -12.0) == 4
    assert [(f, v) for f, v, _e in seq.keys_of(c, "volume")] == [(108, -4.0), (120, -16.0), (216, -16.0), (240, -4.0)]
    assert seq.values_at(c, 168)["volume"] == pytest.approx(-16.0)
    assert seq.values_at(c, 300)["volume"] == pytest.approx(-4.0)
    # descida que passa do começo do clipe: o clipe já começa embaixo
    seq, c = music_seq(60.0, start=24, dur=480)
    ducks = musica.duck_spans(c, [(0.5, 2.0)], FPS)
    assert ducks[0].k0 is None and ducks[0].fa == 24
    musica.apply_duck(seq, c.id, ducks, 12.0)               # o sinal da profundidade não importa
    assert seq.keys_of(c, "volume")[0][:2] == (24, -12.0)


def test_duck_existing_keys_are_conflicts_and_get_replaced():
    seq, c = music_seq(60.0, start=0, dur=480)
    seq.set_key(c.id, "volume", 10, -2.0)
    seq.set_key(c.id, "volume", 130, -8.0)                 # dentro da descida
    seq.set_key(c.id, "volume", 400, -2.0)
    ducks = musica.duck_spans(c, [(5.0, 6.0)], FPS)
    assert musica.duck_conflicts(seq, c, ducks) == [130]
    musica.apply_duck(seq, c.id, ducks, -12.0)
    frames = [f for f, _v, _e in seq.keys_of(c, "volume")]
    assert 130 not in frames and 10 in frames and 400 in frames
    lvl = seq.values_at(c, 113)["volume"]                  # o volume de fora volta a valer nas pontas
    assert lvl == pytest.approx(-2.0) and seq.values_at(c, 132)["volume"] == pytest.approx(-14.0)


def test_voice_tracks_and_voice_mix():
    seq, music = music_seq(60.0, start=0, dur=480)
    seq.add_source(tl.Source("voz.wav", fps=24.0, frames=240, duration=10.0, has_video=False, has_audio=True))
    seq.ensure_track(tl.AUDIO, 2)
    v = tl.Clip(tl.new_id(), tl.AUDIO, "voz.wav", 1, 100, 100, 0.0)
    far = tl.Clip(tl.new_id(), tl.AUDIO, "voz.wav", 2, 600, 100, 0.0)
    seq.clips += [v, far]
    seq.track(tl.AUDIO, 1).solo = True
    assert musica.voice_tracks_for(seq, [music]) == [1]
    mix = musica.voice_mix(seq, [1], skip=[music.id])
    assert [c.id for c in mix.clips] == [v.id] and not any(t.solo for t in mix.kind_tracks(tl.AUDIO))
    assert seq.track(tl.AUDIO, 1).solo                      # a original não muda


def test_ducked_mix_is_lower_under_the_voice(ffmpeg_ok, tmp_path):
    import wave

    from pelicula import audiomix

    def wav(path, x):
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(VR)
            w.writeframes(np.repeat((np.clip(x, -1, 1) * 32767).astype("<i2")[:, None], 2, axis=1).tobytes())
        return str(path)

    t = np.arange(3 * VR) / VR
    song = wav(tmp_path / "musica.wav", 0.3 * np.sin(2 * np.pi * 440 * t))
    speech = wav(tmp_path / "voz.wav", voice(3.0, [(1.0, 2.0)]))
    seq = tl.Sequence(640, 360, f"{FPS}/1")
    seq.add_source(tl.Source(song, fps=24.0, frames=72, duration=3.0, has_video=False, has_audio=True))
    seq.add_source(tl.Source(speech, fps=24.0, frames=72, duration=3.0, has_video=False, has_audio=True))
    seq.ensure_track(tl.AUDIO, 1)
    music = tl.Clip(tl.new_id(), tl.AUDIO, song, 0, 0, 72, 0.0)
    talk = tl.Clip(tl.new_id(), tl.AUDIO, speech, 1, 0, 72, 0.0)
    seq.clips += [music, talk]
    out = str(tmp_path / "voz_mix.wav")
    assert audiomix.render_mix(musica.voice_mix(seq, [1], [music.id]), out)
    regions = musica.speech_regions(audiomix.WavReader(out).read(0, 3 * VR), VR)
    assert len(regions) == 1 and abs(regions[0][0] - 1.0) < 0.06
    ducks = musica.duck_spans(music, regions, FPS, 0.3, 0.4)
    musica.apply_duck(seq, music.id, ducks, -12.0)
    seq.track(tl.AUDIO, 1).muted = True                     # ouvir só a música
    out = str(tmp_path / "mix.wav")
    assert audiomix.render_mix(seq, out)
    y = audiomix.WavReader(out).read(0, 3 * VR)[:, 0]

    def rms(a, b):
        return 20 * np.log10(np.sqrt(np.mean(y[int(a * VR):int(b * VR)] ** 2)))

    assert rms(1.2, 1.8) - rms(0.1, 0.6) == pytest.approx(-12.0, abs=1.0)
    assert rms(2.6, 2.9) - rms(0.1, 0.6) == pytest.approx(0.0, abs=1.0)
