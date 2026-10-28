"""Tirar trechos de tempo da montagem (`rangecut`): "Remover silêncios…" e "Cortar pelo texto".

Sem Qt; os silêncios de verdade (ffmpeg) usam um som sintético: tom, silêncio, tom.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from pelicula import media, rangecut as rc, silences, subedit as se, subtitles as sb, timeline as tl
from pelicula.subtitles import Cue, Word
from pelicula.timeline import AUDIO, VIDEO

PATH = "C:/v/fala.mp4"


def source(path=PATH, seconds=20.0, audio=True):
    return tl.Source(path=path, width=1920, height=1080, fps=24.0, fps_str="24/1", frames=int(seconds * 24),
                     duration=seconds, has_video=True, has_audio=audio)


def make_seq(seconds=20.0) -> tl.Sequence:
    seq = tl.Sequence(1920, 1080, "24/1")
    seq.insert_media(source(seconds=seconds))
    return seq


def layout(seq, kind):
    return [(c.start, c.end, round(c.src_in, 6)) for c in sorted((c for c in seq.clips if c.kind == kind),
                                                                  key=lambda c: c.start)]


def in_sync(seq):
    """Cada vídeo tem o som ligado no mesmo lugar e mostrando o mesmo tempo do arquivo."""
    for v in (c for c in seq.clips if c.kind == VIDEO):
        partners = [g for g in seq.group(v) if g.kind == AUDIO]
        assert len(partners) == 1, v
        a = partners[0]
        assert (a.start, a.dur, a.src_in) == (v.start, v.dur, v.src_in)
    return True


# ------------------------------------------------------------------ trechos
def test_seconds_become_whole_frames_inside_the_range():
    seq = make_seq(10.0)
    assert rc.to_frames(seq, [(1.01, 2.0), (1.5, 3.0), (9.5, 99.0)]) == [(25, 72), (228, 240)]
    assert rc.to_frames(seq, [(1.0, 1.02)]) == []                    # menos de um quadro: nada sai
    assert rc.merge([(3, 4), (0, 1), (1, 2)]) == [(0, 2), (3, 4)] and rc.total([(0, 1), (0.5, 2)]) == 2.0


def test_remove_ranges_cuts_every_track_and_keeps_sync():
    seq = make_seq()
    n = rc.remove_ranges(seq, [(24 * 12, 24 * 14), (24 * 2, 24 * 5)])
    assert n == 24 * 5 and seq.duration == 24 * 15
    assert layout(seq, VIDEO) == [(0, 48, 0.0), (48, 216, 5.0), (216, 360, 14.0)]
    assert layout(seq, VIDEO) == layout(seq, AUDIO) and in_sync(seq)
    # o corte vira emenda seca (a transição de saída fica com a última parte)
    parts = sorted((c for c in seq.clips if c.kind == VIDEO), key=lambda c: c.start)
    assert parts[0].values.get("saida_tipo") == "corte" and parts[1].values.get("entrada_tipo") == "corte"


def test_overlapping_and_out_of_range_pieces_are_merged_and_clamped():
    seq = make_seq(10.0)
    assert rc.remove_ranges(seq, [(24, 72), (48, 96), (230, 999), (300, 400)]) == 72 + 10
    assert seq.duration == 240 - 82 and in_sync(seq)
    assert rc.remove_ranges(seq, [(5, 5), (10, 3)]) == 0


def test_locked_tracks_stay_and_head_trims_keep_the_image():
    seq = make_seq()
    seq.insert_media(source("C:/v/musica.mp3", 30.0, audio=True), at=0, vtrack=1, atrack=1, with_audio=True)
    music_v = [c for c in seq.clips if c.src == "C:/v/musica.mp3" and c.kind == VIDEO][0]
    seq.delete([music_v.id])                                          # só o som da música, na A2
    seq.track(AUDIO, 1).locked = True
    before = layout(seq, AUDIO)
    rc.remove_ranges(seq, [(0, 24)])                                 # o começo: a fala perde 1 s
    music = [c for c in seq.clips if c.src == "C:/v/musica.mp3"]
    assert [(c.start, c.end, c.src_in) for c in music] == [b for b in before if b[1] == 720]   # travada: igual
    speech = [c for c in seq.clips if c.src == PATH]
    assert all(c.start == 0 and c.src_in == pytest.approx(1.0) for c in speech) and in_sync(seq)


def test_keys_markers_and_subtitles_follow():
    seq = make_seq()
    v = [c for c in seq.clips if c.kind == VIDEO][0]
    seq.set_key(v.id, "opacidade", 24 * 3, 0.2)
    seq.set_key(v.id, "opacidade", 24 * 8, 1.0)
    want = seq.values_at(v, 24 * 7)["opacidade"]                      # o quadro de 7 s do arquivo
    seq.add_marker(24 * 1, "antes")
    seq.add_marker(24 * 5, "dentro")
    seq.add_marker(24 * 10, "depois")
    seq.subtitles = sb.Subtitles(sources={PATH: [Cue(1, 2, "fica"), Cue(4.5, 5.5, "some"), Cue(9, 10, "anda")]},
                                 cues=[Cue(0.5, 1, "seq antes"), Cue(4, 7, "seq cruza"), Cue(12, 13, "seq depois")])
    rc.remove_ranges(seq, [(24 * 4, 24 * 6)])
    right = [c for c in seq.clips if c.kind == VIDEO and c.start == 24 * 4][0]
    assert seq.values_at(right, 24 * 5)["opacidade"] == pytest.approx(want)   # a chave fica com a imagem
    assert sorted((m.name, m.frame) for m in seq.markers) == [("antes", 24), ("dentro", 24 * 4), ("depois", 24 * 8)]
    got = [(c.text, round(c.start, 6), round(c.end, 6)) for c in seq.subtitles.timeline_cues(seq)]
    assert ("fica", 1.0, 2.0) in got and ("anda", 7.0, 8.0) in got and not any(t == "some" for t, *_ in got)
    assert [(c.text, c.start, c.end) for c in seq.subtitles.cues] == [
        ("seq antes", 0.5, 1.0), ("seq cruza", 4.0, 5.0), ("seq depois", 10.0, 11.0)]


def test_j_cut_partner_goes_with_the_right_part():
    seq = make_seq()
    v = [c for c in seq.clips if c.kind == VIDEO][0]
    a = [c for c in seq.clips if c.kind == AUDIO][0]
    seq.trim_start_only(a.id, 24 * 10)                                # o som do par começa só aos 10 s (corte L)
    rc.remove_ranges(seq, [(24 * 2, 24 * 4)])
    left, right = sorted((c for c in seq.clips if c.kind == VIDEO), key=lambda c: c.start)
    sound = [c for c in seq.clips if c.kind == AUDIO][0]
    assert sound.start == 24 * 8 and sound.link and sound.link == right.link and left.link != sound.link


def test_text_ranges_from_the_words_on_screen():
    seq = make_seq()
    words = [Word(1.0, 1.4, "um"), Word(1.5, 1.9, "éé"), Word(2.0, 2.4, "dois")]
    seq.subtitles = sb.Subtitles(sources={PATH: [Cue(1.0, 2.4, "um éé dois", tuple(words))]})
    on_screen = se.words(se.items(seq, seq.subtitles))
    cut = rc.text_ranges(on_screen, [1])
    assert cut == [(1.43, 1.97)]
    frames = rc.to_frames(seq, cut)
    rc.remove_ranges(seq, frames)
    left = [w.text for w in se.words(se.items(seq, seq.subtitles))]
    assert left == ["um", "dois"]


# ------------------------------------------------------------------ silêncios no som da montagem
@pytest.fixture
def tone_gap_tone(tmp_path, ffmpeg_ok):
    """Vídeo de 6 s (MOV com PCM) com som: tom 0–2 s, silêncio 2–4 s, tom 4–6 s."""
    rate = 48000
    t = np.arange(rate * 6) / rate
    wave = 0.3 * np.sin(2 * np.pi * 440 * t)
    wave[(t >= 2.0) & (t < 4.0)] = 0.0
    raw = tmp_path / "som.f32"
    raw.write_bytes(wave.astype("<f4").tobytes())
    cmd = [media.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=24:d=6",
           "-f", "f32le", "-ar", str(rate), "-ac", "1", "-i", str(raw), "-shortest", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(tmp_path / "tom.mov")]
    subprocess.run(cmd, check=True, timeout=60)
    out = tmp_path / "tom.mov"
    return media.probe(str(out))


@pytest.mark.ffmpeg
def test_find_silences_in_the_mix_and_remove_them(tone_gap_tone):
    info = tone_gap_tone
    seq = tl.Sequence.for_source(tl.Source.from_info(info))
    found = rc.find_silences(seq, threshold=-30.0, min_duration=0.5, padding=0.1)
    assert len(found) == 1
    s = found[0]
    assert s.start == pytest.approx(2.1, abs=0.03) and s.end == pytest.approx(3.9, abs=0.03)
    removed = rc.remove_ranges(seq, rc.to_frames(seq, silences.ranges(found)))
    assert removed == pytest.approx(24 * 1.8, abs=2) and in_sync(seq)
    assert rc.find_silences(seq, min_duration=0.5) == []             # depois do corte, nada mais


@pytest.mark.ffmpeg
def test_find_silences_only_in_the_chosen_clips(tone_gap_tone):
    info = tone_gap_tone
    seq = tl.Sequence.for_source(tl.Source.from_info(info))
    seq.split(24 * 3)
    first = sorted((c for c in seq.clips if c.kind == AUDIO), key=lambda c: c.start)[0]
    found = rc.find_silences(seq, [first.id], min_duration=0.5, padding=0.1)
    assert len(found) == 1 and found[0].end == pytest.approx(3.0, abs=1e-6)   # para no fim do clipe escolhido
    v = [c for c in seq.clips if c.kind == VIDEO][0]
    seq.unlink(v.id)
    with pytest.raises(silences.SilenceError):
        rc.find_silences(seq, [v.id])                                 # só imagem: não há som para medir
    seq.track(AUDIO, 0).muted = True
    with pytest.raises(silences.SilenceError):
        rc.find_silences(seq)                                         # tudo mudo: não propõe cortar tudo
