"""Pôr efeitos sonoros sozinho (sfx_auto.py, 1.8, ARQUITETURA §47): o plano em montagens sintéticas (quadros exatos),
sem repetir ao rodar de novo, a faixa "Efeitos" sem cobrir clipes, e as teclas da máquina de escrever nos quadros em
que o título desenha cada letra."""

from __future__ import annotations

import json

import numpy as np

from pelicula import sequence, sfx, sfx_auto, titles
from pelicula import timeline as tl

FPS = "24/1"


def base() -> tl.Sequence:
    seq = tl.Sequence(320, 180, FPS)
    seq.add_track(tl.AUDIO)
    return seq


def video(seq, path, start, dur, track=0, image=False, **vals) -> tl.Clip:
    if path not in seq.sources:
        seq.add_source(tl.Source(path, width=320, height=180, fps=24.0, frames=2400, duration=100.0,
                                 is_image=image))
    c = tl.Clip(tl.new_id(), tl.VIDEO, path, track, start, dur, 0.0, values=vals)
    seq.clips.append(c)
    return c


def title_clip(seq, start, dur, **data) -> tl.Clip:
    src = titles.new_source(seq, "titulo_grande", "Película")
    src.data.update(data)
    seq.add_source(src)
    c = tl.Clip(tl.new_id(), tl.VIDEO, src.path, 1, start, dur, 0.0)
    seq.clips.append(c)
    return c


def by_tag(placements):
    return {p.tag: p for p in placements}


def no_glyphs(src):
    raise AssertionError("não devia contar letras")


# ------------------------------------------------------------------ cada regra
def test_whoosh_ends_at_the_end_of_an_entrance_transition_and_at_the_cut_of_an_exit():
    seq = base()
    a = video(seq, "a.mp4", 0, 48)
    b = video(seq, "b.mp4", 48, 48, entrada_tipo="dissolver", entrada_dur=0.5)       # 12 quadros
    c = video(seq, "c.mp4", 96, 72, saida_tipo="preto", saida_dur=1.0)               # 24 quadros
    got = by_tag(sfx_auto.plan(seq, glyphs=no_glyphs))
    w = got[f"transicao:{b.id}:entrada"]
    assert (w.effect, w.start, w.end) == ("whoosh", 48, 60)
    w = got[f"transicao:{c.id}:saida"]
    assert (w.effect, w.start, w.end) == ("whoosh", 144, 168)
    assert not any(t.startswith(f"transicao:{a.id}") for t in got)
    # transição curta: o whoosh tem no mínimo 0,4 s (10 quadros a 24 qps) e termina no mesmo ponto
    b.values = {**b.values, "entrada_dur": 0.12}
    w = by_tag(sfx_auto.plan(seq, glyphs=no_glyphs))[f"transicao:{b.id}:entrada"]
    n = seq.transition_frames(b, "entrada")
    assert w.end == 48 + n and w.dur == 10


def test_impact_only_when_asked_on_v1_cuts_between_different_sources():
    seq = base()
    video(seq, "a.mp4", 0, 48)
    b = video(seq, "b.mp4", 48, 48)
    c = video(seq, "b.mp4", 96, 48)   # mesma fonte: não é troca de imagem
    video(seq, "c.mp4", 200, 48)      # sem clipe colado antes
    video(seq, "d.mp4", 0, 48, track=1)
    video(seq, "e.mp4", 48, 48, track=1)  # V2: fora
    assert not [p for p in sfx_auto.plan(seq, glyphs=no_glyphs) if p.effect == "impacto"]
    got = [p for p in sfx_auto.plan(seq, sfx_auto.Options(impactos=True), glyphs=no_glyphs) if p.effect == "impacto"]
    assert [(p.tag, p.start, p.dur) for p in got] == [(f"corte:{b.id}", 48, 48)]
    assert c.id not in got[0].tag


def test_swish_peaks_on_the_first_frame_of_a_title():
    seq = base()
    video(seq, "a.mp4", 0, 240)
    t = title_clip(seq, 48, 96, entrada="aparecer", dur_entrada=0.5)
    (p,) = [p for p in sfx_auto.plan(seq, glyphs=no_glyphs) if p.effect == "swish"]
    assert p.tag == f"titulo:{t.id}" and p.start == 48 - 4 and p.dur == 10   # 0,17 s e 0,4 s a 24 qps
    assert sfx_auto.plan(seq, sfx_auto.Options(titulos=False), glyphs=no_glyphs) == []


def test_typewriter_hits_one_key_per_letter_at_the_exact_frames():
    seq = base()
    t = title_clip(seq, 24, 96, entrada="maquina", dur_entrada=1.0)   # 8 letras em 1 s (24 quadros)
    (p,) = sfx_auto.plan(seq, glyphs=lambda src: (8, [5]))
    assert p.effect == "maquina" and p.start == 24 and p.tag == f"titulo:{t.id}"
    # a mesma conta de `titles.motion`: shown = floor(p × 8) com p = (quadro − começo) / 24
    want = [f for f in range(1, 96) if int(np.floor(min(f / 24, 1.0) * 8 + 1e-9)) >
            int(np.floor(min((f - 1) / 24, 1.0) * 8 + 1e-9))]
    assert [round(h * 24) for h in p.data["toques"]] == want == [3, 6, 9, 12, 15, 18, 21, 24]
    assert p.data["retornos"] == [round(p.data["toques"][4] + sfx_auto.RETURN_AFTER_S, 6)]
    assert p.dur == int(np.ceil((24 / 24 + sfx_auto.TYPE_TAIL_S) * 24))
    assert p.data["tecla"] == "maquina"
    q = sfx_auto.plan(seq, sfx_auto.Options(tecla="clique"), glyphs=lambda src: (8, []))[0]
    assert q.data["tecla"] == "clique" and q.data["retornos"] == []


def test_fast_typing_spreads_letters_inside_the_frame():
    seq = base()
    title_clip(seq, 0, 48, entrada="maquina", dur_entrada=0.25)   # 12 letras em 6 quadros: 2 por quadro
    (p,) = sfx_auto.plan(seq, glyphs=lambda src: (12, []))
    hits = p.data["toques"]
    assert len(hits) == 12 and hits == sorted(hits)
    frames = [int(np.floor(h * 24 + 1e-3)) for h in hits]
    assert frames == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6]


def test_shutter_on_freeze_frames_and_on_stills_after_a_cut():
    seq = base()
    video(seq, "a.mp4", 0, 48)
    fr = video(seq, "a.mp4", 48, 48, congelar=True)
    still = video(seq, "foto.png", 96, 48, image=True)
    lone = video(seq, "foto2.png", 300, 48, image=True)   # sem corte antes: não
    got = [p for p in sfx_auto.plan(seq, glyphs=no_glyphs) if p.effect == "obturador"]
    assert [(p.tag, p.start, p.dur) for p in got] == [(f"parado:{fr.id}", 48, 12), (f"parado:{still.id}", 96, 12)]
    assert lone.id not in "".join(p.tag for p in got)


def test_riser_ends_on_bang_markers_and_on_the_chosen_color():
    seq = base()
    video(seq, "a.mp4", 0, 480)
    seq.markers += [tl.Marker("m1", 200, "laranja", "Gol!"), tl.Marker("m2", 300, "azul", "nada"),
                    tl.Marker("m3", 30, "laranja", "cedo!"), tl.Marker("m4", 5, "laranja", "muito cedo!")]
    got = [p for p in sfx_auto.plan(seq, glyphs=no_glyphs) if p.effect == "riser"]
    assert [(p.tag, p.start, p.end) for p in got] == [("marcador:m3", 0, 30), ("marcador:m1", 128, 200)]
    got = [p for p in sfx_auto.plan(seq, sfx_auto.Options(cor_marcador="azul"), glyphs=no_glyphs)
           if p.effect == "riser"]
    assert ("marcador:m2", 228, 300) in [(p.tag, p.start, p.end) for p in got]


# ------------------------------------------------------------------ na montagem
def test_apply_uses_an_effects_track_never_covers_clips_and_does_not_repeat():
    seq = base()
    a = video(seq, "a.mp4", 0, 48)
    video(seq, "b.mp4", 48, 48, entrada_tipo="preto", entrada_dur=0.5)
    video(seq, "c.mp4", 96, 48, entrada_tipo="dissolver", entrada_dur=2.0)
    seq.markers.append(tl.Marker("m1", 100, "laranja", "Agora!"))
    music = tl.Source("musica.wav", fps=24.0, frames=1, duration=60.0, has_video=False, has_audio=True)
    seq.add_source(music)
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, music.path, 0, 0, 400, 0.0))
    first = sfx_auto.plan(seq, glyphs=no_glyphs)
    assert len(first) == 3
    made = sfx_auto.apply(seq, first)
    assert len(made) == 3
    tracks = seq.kind_tracks(tl.AUDIO)
    used = {c.track for c in made}
    assert all(tracks[t].name == "Efeitos" for t in used) and 0 not in used  # a música fica onde está
    for t in used:  # nada se sobrepõe na faixa
        clips = sorted(seq.clips_on(tl.AUDIO, t), key=lambda c: c.start)
        assert all(x.end <= y.start for x, y in zip(clips, clips[1:]))
    assert len(used) == 2   # o whoosh de 2 s e o riser de 3 s se cruzam: o segundo vai para outra faixa "Efeitos"
    for c in made:
        src = seq.sources[c.src]
        assert src.kind == sfx.KIND and src.data["auto"] and c.dur == next(p.dur for p in first
                                                                          if p.tag == src.data["auto"])
    # rodar de novo não repete, nem depois de salvar e abrir
    assert sfx_auto.plan(seq, glyphs=no_glyphs) == []
    back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    assert sfx_auto.plan(back, glyphs=no_glyphs) == []
    # apagado o clipe de um efeito, ele volta; um efeito novo reaproveita a faixa "Efeitos" livre
    seq.clips = [c for c in seq.clips if c.id != made[0].id]
    again = sfx_auto.plan(seq, glyphs=no_glyphs)
    assert [p.tag for p in again] == [seq.sources[made[0].src].data["auto"]]
    n_tracks = len(seq.kind_tracks(tl.AUDIO))
    sfx_auto.apply(seq, again)
    assert len(seq.kind_tracks(tl.AUDIO)) == n_tracks
    assert a.id  # o clipe de imagem continua


def test_typewriter_keys_fall_on_the_frames_where_the_title_draws_a_new_letter(qapp):
    """Com o `textrender` de verdade: uma tecla em cada quadro em que o desenho do título muda (e só neles)."""
    seq = tl.Sequence(320, 180, FPS)
    src = titles.new_source(seq, "titulo_grande", "Pé de\nmoleque")
    src.data.update(entrada="maquina", dur_entrada=1.0, saida="nenhuma")
    seq.add_source(src)
    clip = tl.Clip(tl.new_id(), tl.VIDEO, src.path, 0, 10, 48, 0.0)
    seq.clips.append(clip)
    n, lines = sfx_auto.title_glyphs(src, seq.height)
    assert n == len("Pédemoleque") and lines == [len("Péde")]
    (p,) = sfx_auto.plan(seq)
    hit_frames = sorted({clip.start + int(np.floor(h * 24 + 1e-3)) for h in p.data["toques"]})
    drawn = []
    prev = None
    for f in range(clip.start, clip.end):
        img = sequence.render_source(seq, clip, seq.src_frame(clip, f), 320, 180, 8)
        a = int(img[..., 3].astype(np.int64).sum())
        if prev is not None and a != prev or (prev is None and a > 0):
            drawn.append(f)
        prev = a
    assert hit_frames == drawn
    assert len(p.data["toques"]) == n and len(p.data["retornos"]) == 1
