"""Edição das legendas como aparecem na montagem (`subedit`): itens, mudanças e cortes."""

from __future__ import annotations

import pytest

from pelicula import subedit as se, subtitles as sb, timeline as tl
from pelicula.subtitles import Cue, Word

PATH = "C:/v/fala.mp4"


def W(a, b, t):
    return Word(a, b, t)


def sentence(a: float, text: str, step: float = 0.5) -> Cue:
    toks = text.split()
    words = tuple(W(a + i * step, a + (i + 1) * step, t) for i, t in enumerate(toks))
    return Cue(a, a + len(toks) * step, text, words)


def make_seq(seconds: float = 20.0, path: str = PATH) -> tl.Sequence:
    seq = tl.Sequence(1920, 1080, "24/1")
    seq.insert_media(tl.Source(path=path, width=1920, height=1080, fps=24.0, fps_str="24/1",
                               frames=int(seconds * 24), duration=seconds, has_video=True, has_audio=True))
    return seq


def by_kind(seq, kind):
    return sorted((c for c in seq.clips if c.kind == kind), key=lambda c: c.start)


def doc(*cues, seq_cues=()) -> sb.Subtitles:
    return sb.Subtitles(sources={PATH: list(cues)}, cues=list(seq_cues))


def times(items):
    return [(it.cue.text, round(it.cue.start, 6), round(it.cue.end, 6)) for it in items]


def same_as_timeline(seq, subs):
    """Os itens são exatamente o que a renderização e o .srt usam."""
    assert [it.cue for it in se.items(seq, subs)] == subs.timeline_cues(seq)


# ------------------------------------------------------------------ itens
def test_items_match_timeline_cues_and_know_where_they_came_from():
    seq = make_seq()
    subs = doc(Cue(1, 2, "do arquivo"), Cue(8, 9, "outra"), seq_cues=[Cue(0.5, 1.5, "da sequência")])
    items = se.items(seq, subs)
    same_as_timeline(seq, subs)
    assert [it.ref for it in items] == [se.Ref(None, 0), se.Ref(PATH, 0), se.Ref(PATH, 1)]
    assert items[0].fixed and items[0].mapping is None
    assert not items[1].fixed and items[1].mapping.to_seq(1.0) == 1.0
    assert se.items(seq, None) == []


def test_items_follow_cuts_and_dedup_two_tracks():
    seq = make_seq()
    seq.split(24 * 5)
    right = by_kind(seq, tl.AUDIO)[1]
    seq.move(right.id, 24 * 8)                    # a parte da direita do som vai 3 s para a frente
    subs = doc(Cue(2, 3, "antes"), Cue(6, 7, "depois"))
    items = se.items(seq, subs)
    same_as_timeline(seq, subs)
    assert times(items) == [("antes", 2.0, 3.0), ("depois", 9.0, 10.0)]   # vídeo e som juntos: uma vez só
    seq.unlink(right.id)
    seq.move(right.id, 24 * 12)                   # só o som anda: a fala vai com o som
    assert times(se.items(seq, subs))[1:] == [("depois", 13.0, 14.0)]
    same_as_timeline(seq, subs)
    seq2 = make_seq()                             # som e vídeo juntos: uma vez só
    assert len(se.items(seq2, doc(Cue(2, 3, "uma")))) == 1


# ------------------------------------------------------------------ texto e estilo
def test_set_text_keeps_word_times_when_count_matches():
    subs = doc(sentence(1.0, "um dois três"))
    ref = se.Ref(PATH, 0)
    new = se.set_text(subs, ref, "Um dois Três")
    assert [w.text for w in new.words] == ["Um", "dois", "Três"] and new.words[2].start == 2.0
    new = se.set_text(subs, ref, "outra frase")
    assert new.text == "outra frase" and new.words == ()
    assert se.set_text(subs, ref, "   ") is None and PATH not in subs.sources   # vazio apaga


def test_set_style_flags():
    subs = doc(Cue(1, 2, "x"))
    new = se.set_style(subs, se.Ref(PATH, 0), italic=True)
    assert new.italic and not new.bold
    new = se.set_style(subs, se.Ref(PATH, 0), bold=True)
    assert new.italic and new.bold


# ------------------------------------------------------------------ tempo
def test_set_times_through_the_clip_mapping():
    seq = make_seq()
    a = by_kind(seq, tl.AUDIO)[0]
    v = by_kind(seq, tl.VIDEO)[0]
    seq.unlink(a.id)
    seq.delete([v.id])
    seq.trim_start(a.id, 24 * 2)                  # o som começa 2 s depois...
    seq.move(a.id, 0)                             # ...no começo da sequência: sequência = arquivo − 2 s
    subs = doc(sentence(4.0, "a b"))              # 4–5 s do arquivo = 2–3 s na sequência
    it = se.items(seq, subs)[0]
    assert (it.cue.start, it.cue.end) == (2.0, 3.0)
    new = se.set_times(subs, it, end=3.5)
    assert (new.start, new.end) == (4.0, 5.5)     # guardado no tempo do arquivo
    it = se.items(seq, subs)[0]
    new = se.set_times(subs, it, start=1.0)
    assert (new.start, new.end) == (3.0, 5.5)
    assert new.words == sentence(4.0, "a b").words  # aparar não mexe nas palavras que ficam dentro
    same_as_timeline(seq, subs)


def test_reverse_and_ramp_keep_the_subtitles_on_the_speech():
    """Rampa e reverso (frente de tempo): cada legenda continua no instante em que o arquivo passa por ela."""
    from pelicula import timemap
    seq = make_seq()
    v = by_kind(seq, tl.VIDEO)[0]
    subs = doc(sentence(4.0, "a b"))                            # 4–5 s do arquivo
    assert seq.retime(v.id, reverse=True)
    tm = seq.time_map(v)
    it = se.items(seq, subs)[0]
    assert it.cue.start == pytest.approx(tm.out_at(5.0)) and it.cue.end == pytest.approx(tm.out_at(4.0))
    assert it.cue.start < it.cue.end and [w.text for w in it.cue.words] == ["b", "a"]
    same_as_timeline(seq, subs)
    new = se.set_times(subs, it, start=it.cue.start - 0.5)      # o começo na tela é o fim no arquivo
    assert (new.start, new.end) == (4.0, pytest.approx(5.5))
    new = se.move(subs, se.items(seq, subs)[0], 1.0)            # para a frente na tela = para trás no arquivo
    assert (new.start, new.end) == (pytest.approx(3.0), pytest.approx(4.5))
    assert seq.retime(v.id, ramp=timemap.preset_anchors("impacto", 0.0, 20.0, reverse=True), reverse=True)
    tm = seq.time_map(v)
    it = se.items(seq, subs)[0]
    assert it.cue.start == pytest.approx(tm.out_at(4.5)) and it.cue.end == pytest.approx(tm.out_at(3.0))
    assert seq.retime(v.id, ramp=timemap.preset_anchors("impacto", 0.0, 20.0), reverse=False)
    tm = seq.time_map(v)
    it = se.items(seq, subs)[0]
    assert it.cue.start == pytest.approx(tm.out_at(3.0)) and it.cue.end == pytest.approx(tm.out_at(4.5))
    assert it.cue.end - it.cue.start != pytest.approx(1.5)      # a rampa estica a fala (não é o tempo constante)
    same_as_timeline(seq, subs)


def test_set_times_clamps_words_and_keeps_minimum():
    subs = doc(sentence(1.0, "um dois três"))     # 1.0–2.5
    seq = make_seq()
    it = se.items(seq, subs)[0]
    new = se.set_times(subs, it, end=1.7)
    assert new.end == pytest.approx(1.7)
    assert all(w.end <= 1.7 + 1e-9 for w in new.words)
    it = se.items(seq, subs)[0]
    new = se.set_times(subs, it, start=5.0)       # passou do fim: fica com a duração mínima
    assert new.end - new.start == pytest.approx(se.MIN_DUR)


def test_set_times_of_a_cut_cue_moves_only_the_edge_that_changed():
    seq = make_seq()
    seq.split(24 * 5)
    seq.delete([c.id for c in seq.clips if c.start >= 24 * 5], ripple=True)   # sobra 0–5 s
    subs = doc(Cue(4.0, 7.0, "cortada"))
    it = se.items(seq, subs)[0]
    assert (it.cue.start, it.cue.end) == (4.0, 5.0)
    new = se.set_times(subs, it, start=3.0)
    assert (new.start, new.end) == (3.0, 7.0)     # o pedaço que não aparece continua guardado


def test_move_with_speed():
    seq = make_seq()
    a = by_kind(seq, tl.AUDIO)[0]
    v = by_kind(seq, tl.VIDEO)[0]
    seq.unlink(a.id)
    seq.delete([v.id])
    seq.set_speed(a.id, 2.0)
    subs = doc(sentence(4.0, "rápido demais"))    # 4–5 s do arquivo = 2–2,5 s na sequência
    it = se.items(seq, subs)[0]
    assert (it.cue.start, it.cue.end) == (2.0, 2.5)
    se.move(subs, it, 0.5)                        # meio segundo na tela = um segundo no arquivo
    assert subs.sources[PATH][0].start == pytest.approx(5.0)
    assert subs.sources[PATH][0].words[0].start == pytest.approx(5.0)
    it = se.items(seq, subs)[0]
    assert it.cue.start == pytest.approx(2.5)
    se.move(subs, it, -100)                       # não passa do começo
    assert subs.sources[PATH][0].start == 0.0


def test_sequence_cue_times_are_sequence_times():
    seq = make_seq()
    seq.split(24 * 5)
    seq.delete([c.id for c in seq.clips if c.start < 24 * 5], ripple=True)    # tira os 5 primeiros segundos
    subs = doc(seq_cues=[Cue(1, 2, "fixa")])
    it = se.items(seq, subs)[0]
    assert it.fixed
    se.set_times(subs, it, end=3.0)
    assert (subs.cues[0].start, subs.cues[0].end) == (1.0, 3.0)


# ------------------------------------------------------------------ criar, apagar, dividir, juntar
def test_anchor_and_add_follow_the_clip():
    seq = make_seq()
    seq.split(24 * 5)
    right = by_kind(seq, tl.AUDIO)[1]
    v_right = by_kind(seq, tl.VIDEO)[1]
    seq.move(right.id, 24 * 8)
    seq.move(v_right.id, 24 * 8)
    path, m = se.anchor_at(seq, 24 * 9)           # 9 s da sequência = 6 s do arquivo
    assert path == PATH and m.to_file(9.0) == pytest.approx(6.0)
    subs = sb.Subtitles()
    cue = se.add(subs, 9.0, 10.0, "nova", m, path)
    assert (cue.start, cue.end) == (6.0, 7.0) and subs.sources[PATH] == [cue]
    assert se.anchor_at(seq, 24 * 6) == (None, None)   # no vão: nada de arquivo
    cue = se.add(subs, 6.0, 7.0, "no vão")
    assert subs.cues == [cue]
    assert se.add(subs, 1.0, 1.0, "x") is None and se.add(subs, 1.0, 2.0, "  ") is None
    same_as_timeline(seq, subs)


def test_anchor_skips_images_generators_and_frozen():
    seq = tl.Sequence(1920, 1080, "24/1")
    seq.insert_media(tl.Source(path="C:/v/foto.png", width=100, height=100, fps=24.0, fps_str="24/1", frames=1,
                               duration=5.0, is_image=True, has_audio=False))
    assert se.anchor_at(seq, 10) == (None, None)


def test_delete_split_merge():
    seq = make_seq()
    subs = doc(sentence(1.0, "um dois três quatro"), Cue(5, 6, "seguinte"), Cue(8, 9, "outra"))
    items = se.items(seq, subs)
    left, right = se.split(subs, items[0], 2.0)
    assert left.text == "um dois" and right.text == "três quatro"
    assert (left.end, right.start) == (2.0, 2.0)
    assert [w.text for w in left.words] == ["um", "dois"] and [w.text for w in right.words] == ["três", "quatro"]
    items = se.items(seq, subs)
    assert se.split(subs, items[0], 0.5) is None  # fora da legenda
    left, right = se.split(subs, items[2], 5.5)   # sem palavras: o texto se divide pela proporção
    assert left.text == right.text == "seguinte"  # uma palavra só: as duas partes ficam com ela
    refs = [it.ref for it in se.items(seq, subs)[:2]]
    merged = se.merge(subs, refs)
    assert merged.text == "um dois três quatro" and len(merged.words) == 4
    assert (merged.start, merged.end) == (1.0, 3.0)
    n = se.delete(subs, [it.ref for it in se.items(seq, subs) if it.cue.text == "outra"])
    assert n == 1 and [c.text for c in subs.sources[PATH]] == ["um dois três quatro", "seguinte", "seguinte"]
    assert se.merge(subs, [se.Ref(PATH, 0), se.Ref(None, 0)]) is None   # listas diferentes não juntam


def test_split_cue_with_words_and_speed():
    seq = make_seq()
    a = by_kind(seq, tl.AUDIO)[0]
    seq.unlink(a.id)
    seq.delete([by_kind(seq, tl.VIDEO)[0].id])
    seq.set_speed(a.id, 2.0)
    subs = doc(sentence(4.0, "a b c d"))          # 4–6 s do arquivo = 2–3 s na sequência
    it = se.items(seq, subs)[0]
    left, right = se.split(subs, it, 2.5)         # 2,5 s na tela = 5 s do arquivo
    assert (left.end, right.start) == (5.0, 5.0)
    assert left.text == "a b" and right.text == "c d"


# ------------------------------------------------------------------ buscar e substituir
def test_find_and_replace_all():
    seq = make_seq()
    subs = doc(sentence(1.0, "Olá mundo"), Cue(5, 6, "outro mundo aqui"), seq_cues=[Cue(10, 11, "mundo")])
    items = se.items(seq, subs)
    assert len(se.matches(items, "MUNDO")) == 3 and len(se.matches(items, "MUNDO", case=True)) == 0
    assert se.matches(items, "") == items
    n = se.replace_all(subs, "mundo", "planeta")
    assert n == 3
    texts = [it.cue.text for it in se.items(seq, subs)]
    assert texts == ["Olá planeta", "outro planeta aqui", "planeta"]
    assert len(subs.sources[PATH][0].words) == 2 and subs.sources[PATH][0].words[1].text == "planeta"
    assert se.replace_all(subs, "planeta", "") == 3   # o que fica vazio some
    assert [it.cue.text for it in se.items(seq, subs)] == ["Olá", "outro aqui"]
    assert se.replace_all(subs, "", "x") == 0


# ------------------------------------------------------------------ importar e trechos removidos
def test_import_cues_appends_or_replaces():
    subs = doc(Cue(1, 2, "velha"))
    assert se.import_cues(subs, [Cue(0, 1, "nova")], PATH) == 1
    assert [c.text for c in subs.sources[PATH]] == ["nova", "velha"]
    se.import_cues(subs, [Cue(3, 4, "só esta")], PATH, replace_all_=True)
    assert [c.text for c in subs.sources[PATH]] == ["só esta"]
    se.import_cues(subs, [Cue(3, 4, "da sequência")])
    assert [c.text for c in subs.cues] == ["da sequência"]


def test_remove_time_shifts_and_cuts_sequence_cues():
    subs = sb.Subtitles(cues=[Cue(0, 1, "antes"), Cue(2, 3, "dentro"), Cue(1.5, 4.5, "cruza"),
                              Cue(5, 6, "depois"), sentence(1.0, "a b c d e f")])   # palavras 1.0 … 4.0
    se.remove_time(subs, 2.0, 4.0)
    got = {c.text: (round(c.start, 6), round(c.end, 6)) for c in subs.cues}
    assert got["antes"] == (0.0, 1.0) and got["depois"] == (3.0, 4.0) and got["cruza"] == (1.5, 2.5)
    assert "dentro" not in got
    words = next(c for c in subs.cues if c.words)
    assert [w.text for w in words.words] == ["a", "b"] and words.text == "a b"


def test_words_for_cut_by_text():
    seq = make_seq()
    subs = doc(sentence(1.0, "um dois"), sentence(4.0, "três"))
    assert [w.text for w in se.words(se.items(seq, subs))] == ["um", "dois", "três"]


def test_map_cues_after_edits_and_cuts_round_trip():
    """O que a interface muda continua preso ao arquivo: cortar depois mostra a legenda editada no lugar certo."""
    seq = make_seq()
    subs = doc(sentence(2.0, "primeira fala"), sentence(8.0, "segunda fala"))
    it = se.items(seq, subs)[1]
    se.set_text(subs, it.ref, "segunda fala!")
    se.move(subs, se.items(seq, subs)[1], 0.5)
    seq.split(24 * 5)
    seq.delete([c.id for c in seq.clips if c.start < 24 * 5], ripple=True)    # tira os 5 primeiros segundos
    out = subs.timeline_cues(seq)
    assert [(c.text, round(c.start, 6)) for c in out] == [("segunda fala!", 3.5)]
    same_as_timeline(seq, subs)
