"""Legendas: modelo, tempo pela montagem, SRT/WebVTT, faixa na exportação e desenho no vídeo."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pelicula import export, media, subtitles as sb, textrender as tr, timeline as tl
from pelicula.export import ExportJob, ExportSettings
from pelicula.subtitles import Cue, Word


def W(a, b, t):
    return Word(a, b, t)


def sentence(a: float, text: str, step: float = 0.5) -> Cue:
    """Legenda com uma palavra a cada `step` segundos a partir de `a`."""
    ws = tuple(W(a + i * step, a + (i + 1) * step, t) for i, t in enumerate(text.split()))
    return Cue(ws[0].start, ws[-1].end, text, ws)


def make_seq(seconds: float = 20.0, fps: str = "24/1", path: str = "C:/v/fala.mp4") -> tl.Sequence:
    seq = tl.Sequence(1920, 1080, fps)
    f = float(tl.parse_fps(fps))
    src = tl.Source(path=path, width=1920, height=1080, fps=f, fps_str=fps, frames=int(seconds * f),
                    duration=seconds, has_video=True, has_audio=True)
    seq.insert_media(src)
    return seq


def by_kind(seq, kind):
    return sorted((c for c in seq.clips if c.kind == kind), key=lambda c: c.start)


# ------------------------------------------------------------------ modelo e JSON
def test_cue_json_roundtrip_and_sanitize():
    cue = Cue(1.0, 2.5, "Olá, mundo\nsegunda linha", (W(1.0, 1.4, "Olá,"), W(1.5, 2.0, "mundo")), italic=True)
    back = Cue.from_json(json.loads(json.dumps(cue.to_json())))
    assert back == cue
    assert all(k.isascii() for k in cue.to_json())
    assert Cue.from_json({"inicio": 2, "fim": 1, "texto": "x"}) is None          # fim antes do início
    assert Cue.from_json({"inicio": 0, "fim": 1, "texto": "  \n "}) is None       # sem texto
    assert Cue.from_json({"inicio": "nan", "fim": 1, "texto": "x"}) is None
    odd = Cue.from_json({"inicio": 0, "fim": 1, "texto": "a\x00b\r\n\r\n  c  ", "palavras": [[0, 1], "x", [0, .5, "a"]]})
    assert odd.text == "ab\nc" and odd.words == (W(0, .5, "a"),)
    assert sb.clean_text("e\u0301") == "é"                                         # NFC


def test_subtitles_document_json():
    doc = sb.Subtitles(sources={"C:/v/a.mp4": [Cue(0, 1, "um")]}, cues=[Cue(5, 6, "dois")], language="pt",
                       style=sb.style("reels"), burn="copia", embed=False)
    d = json.loads(json.dumps(doc.to_json()))
    assert set(d) == {"versao", "idioma", "estilo", "gravar", "faixa", "fontes", "sequencia"}
    back = sb.Subtitles.from_json(d)
    assert back.sources == doc.sources and back.cues == doc.cues and back.language == "pt"
    assert back.style == sb.style("reels") and back.burn == "copia" and back.embed is False
    junk = sb.Subtitles.from_json({"fontes": {"": [], "x\x00": [{"inicio": 0, "fim": 1, "texto": "a"}], 3: []},
                                   "gravar": "sim", "idioma": "português", "estilo": {"id": "??", "largura": 9}})
    assert junk.sources == {} and junk.burn == "nao" and junk.language == "" and junk.embed is True
    assert junk.style.id == sb.DEFAULT_STYLE and junk.style.width == 1.0
    assert sb.Subtitles.from_json(None).is_empty()
    doc.relink("C:/v/a.mp4", "D:/novo/a.mp4")
    assert list(doc.sources) == ["D:/novo/a.mp4"]
    assert sb.FEATURE_ID == "legendas"


def test_styles_are_complete_and_overridable():
    assert set(sb.STYLES) == {"youtube", "reels", "cinema"}
    for st in sb.STYLES.values():
        assert st.id.isascii() and st.name and st.position in sb.POSITIONS
        assert sb.SubStyle.from_json(st.to_json()) == st
    yt, reels, cinema = sb.style("youtube"), sb.style("reels"), sb.style("cinema")
    assert yt.position == "baixo" and yt.text.box > 0
    assert reels.position == "meio" and reels.text.weight >= 700 and reels.highlight and reels.max_words > 0
    assert reels.text.size > yt.text.size > cinema.text.size
    assert cinema.text.box == 0 and cinema.text.shadow > 0 and cinema.position == "baixo"
    custom = sb.SubStyle.from_json({"id": "youtube", "texto": {"cor": "#ffff00"}, "margem": 100,
                                    "destaque": {"cor": "#00ff00", "escala": 1.2}})
    assert custom.text.color == (1.0, 1.0, 0.0) and custom.text.box == yt.text.box and custom.margin == 100
    assert custom.highlight.color == (0.0, 1.0, 0.0) and custom.highlight.scale == 1.2
    assert sb.SubStyle.from_json({"id": "reels", "destaque": None}).highlight is None


def test_cues_from_words_breaks_on_pauses_sentences_and_length():
    words = [W(0.0, 0.3, "Olá"), W(0.35, 0.6, "pessoal."), W(0.7, 1.0, "Hoje"), W(1.0, 1.3, "vamos"),
             W(1.3, 1.6, "falar"), W(1.6, 1.9, "de"), W(1.9, 2.2, "cinema."),
             W(5.0, 5.3, "Depois"), W(5.3, 5.6, "da"), W(5.6, 5.9, "pausa")]
    cues = sb.cues_from_words(words)
    assert [c.text for c in cues] == ["Olá pessoal. Hoje vamos falar de cinema.", "Depois da pausa"]
    assert cues[0].words == tuple(words[:7]) and cues[1].start == 5.0
    many = [W(i * 0.3, i * 0.3 + 0.25, f"palavra{i}") for i in range(40)]
    long_cues = sb.cues_from_words(many, max_chars=42)
    assert all(len(c.text.replace("\n", " ")) <= 84 for c in long_cues)
    assert all(len(line) <= 42 + 10 for c in long_cues for line in c.text.split("\n"))
    assert sum(len(c.words) for c in long_cues) == 40
    short = sb.cues_from_words([W(0, 0.1, "Sim."), W(3, 3.2, "Não.")])
    assert short[0].end == pytest.approx(0.8) and short[1].start == 3
    assert sb.balance_lines("uma frase que precisa de duas linhas bem certinhas", 30) == \
        "uma frase que precisa de\nduas linhas bem certinhas"


# ------------------------------------------------------------------ tempo pela montagem
def test_untouched_sequence_keeps_source_times():
    seq = make_seq()
    cues = [sentence(1.0, "primeira fala aqui"), Cue(10.0, 12.0, "sem palavras")]
    out = sb.map_cues(seq, "C:/v/fala.mp4", cues)
    assert out == cues                                       # som e vídeo ligados: uma cópia só


def test_split_and_move_follow_the_clips():
    seq = make_seq()
    path = "C:/v/fala.mp4"
    seq.split(24 * 5)                                        # corta em 5 s (vídeo e som)
    right_audio = by_kind(seq, tl.AUDIO)[1]
    seq.move(right_audio.id, 24 * 8)                         # a parte da direita vai 3 s para frente
    cues = [Cue(2.0, 3.0, "antes"), Cue(6.0, 7.0, "depois")]
    out = sb.map_cues(seq, path, cues)
    assert [(c.text, round(c.start, 6), round(c.end, 6)) for c in out] == [("antes", 2.0, 3.0), ("depois", 9.0, 10.0)]


def test_cut_removes_words_and_short_leftovers():
    seq = make_seq()
    path = "C:/v/fala.mp4"
    cue = sentence(4.0, "um dois três quatro")             # palavras em 4.0, 4.5, 5.0, 5.5 (fim 6.0)
    seq.split(24 * 5)
    gone = by_kind(seq, tl.AUDIO)[1]
    seq.delete([gone.id], ripple=True)                       # tira tudo depois de 5 s
    out = sb.map_cues(seq, path, [cue])
    assert len(out) == 1 and out[0].text == "um dois" and (out[0].start, out[0].end) == (4.0, 5.0)
    assert [w.text for w in out[0].words] == ["um", "dois"]
    # pedaço que sobra curto demais para ler some; a legenda inteira curta continua
    seq2 = make_seq()
    seq2.split(24 * 5 + 2)                                   # sobra 2 quadros (0,083 s) depois do corte
    seq2.delete([by_kind(seq2, tl.AUDIO)[0].id])
    out2 = sb.map_cues(seq2, path, [Cue(4.0, 5.08, "corte quase no fim"), Cue(6.0, 6.1, "curta")])
    assert [c.text for c in out2] == ["curta"]


def test_trim_and_speed():
    seq = make_seq()
    path = "C:/v/fala.mp4"
    a = by_kind(seq, tl.AUDIO)[0]
    seq.trim_start(a.id, 24 * 2)                             # começa 2 s depois (o clipe também anda)
    out = sb.map_cues(seq, path, [Cue(1.0, 3.0, "metade fora"), Cue(5.0, 6.0, "inteira")])
    assert [(c.text, round(c.start, 6), round(c.end, 6)) for c in out] == \
        [("metade fora", 2.0, 3.0), ("inteira", 5.0, 6.0)]
    seq.move(a.id, 0)                                        # e volta para o começo da sequência
    seq.set_speed(a.id, 2.0)                                 # o dobro da velocidade
    out = sb.map_cues(seq, path, [sentence(4.0, "rápido demais")])
    assert [(round(c.start, 6), round(c.end, 6)) for c in out] == [(1.0, 1.5)]
    assert [(round(w.start, 6), round(w.end, 6)) for w in out[0].words] == [(1.0, 1.25), (1.25, 1.5)]


def test_two_clips_of_the_same_take_show_it_twice_and_frozen_shows_nothing():
    seq = make_seq()
    path = "C:/v/fala.mp4"
    src = seq.sources[path]
    seq.insert_media(src)                                    # o mesmo arquivo de novo, depois do primeiro
    out = sb.map_cues(seq, path, [Cue(1.0, 2.0, "bis")])
    assert [round(c.start, 6) for c in out] == [1.0, 21.0]
    # só vídeo (sem o som na sequência): congelado não mostra fala nova
    seq2 = tl.Sequence(1920, 1080, "24/1")
    seq2.insert_media(tl.Source(path=path, fps=24.0, fps_str="24/1", frames=480, duration=20.0, has_audio=True),
                      with_audio=False)
    v = by_kind(seq2, tl.VIDEO)[0]
    assert len(sb.map_cues(seq2, path, [Cue(1.0, 2.0, "vídeo")])) == 1
    v.values["congelar"] = True
    assert sb.map_cues(seq2, path, [Cue(1.0, 2.0, "vídeo")]) == []


def test_timeline_cues_joins_sources_and_sequence_cues():
    seq = make_seq()
    doc = sb.Subtitles(sources={"C:/v/fala.mp4": [Cue(1, 2, "do arquivo")], "C:/v/outro.mp4": [Cue(0, 1, "fora")]},
                       cues=[Cue(0.5, 1.5, "da sequência")])
    assert [c.text for c in doc.timeline_cues(seq)] == ["da sequência", "do arquivo"]
    assert [c.text for c in doc.timeline_cues(None, "C:/v/outro.mp4")] == ["fora", "da sequência"]


# ------------------------------------------------------------------ SRT e WebVTT
SRT = ("\ufeff1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>Olá, mundo!</i>\r\n\r\n"
       "7\r\n00:00:02,000 --> 00:00:04,000\r\n{\\an8}Linha <b>um</b>\r\n<font color=\"#ff0\">linha dois</font>\r\n"
       "8\r\n00:00:05,5 --> 00:00:06,000\r\nsem linha em branco antes\r\n\r\n"
       "9\r\n00:00:09,000 --> 00:00:08,000\r\ninvertida (some)\r\n\r\n"
       "10\r\n01:00:00,000 --> 01:00:01,000\r\n<b>Tudo negrito</b>\r\n")


def test_parse_srt():
    cues = sb.parse(SRT)
    assert [c.text for c in cues] == ["Olá, mundo!", "Linha um\nlinha dois", "sem linha em branco antes", "Tudo negrito"]
    assert cues[0].italic and not cues[0].bold and not cues[1].italic and cues[3].bold
    assert (cues[1].start, cues[1].end) == (2.0, 4.0)                    # sobreposição mantida
    assert cues[2].start == 5.5 and cues[3].start == 3600.0
    assert sb.parse("") == [] and sb.parse("só texto\nsem tempos") == []


def test_srt_roundtrip_and_encoding_fallback(tmp_path):
    cues = sb.parse(SRT)
    text = sb.to_srt(cues)
    assert text.startswith("1\n00:00:01,000 --> 00:00:02,500\n<i>Olá, mundo!</i>\n")
    assert sb.parse(text) == [Cue(c.start, c.end, c.text, (), c.italic, c.bold) for c in cues]
    p = tmp_path / "x.srt"
    sb.save(p, cues)
    assert p.read_bytes()[:3] != b"\xef\xbb\xbf" and b"\r\n" not in p.read_bytes()
    assert sb.load(p) == sb.parse(text)
    latin = tmp_path / "antiga.srt"
    latin.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nAção é ótima\n".encode("cp1252"))
    assert sb.load(latin)[0].text == "Ação é ótima"
    utf16 = tmp_path / "u16.srt"
    utf16.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nçã\n".encode("utf-16"))
    assert sb.load(utf16)[0].text == "çã"
    bad = tmp_path / "nada.srt"
    bad.write_text("isto não é legenda", encoding="utf-8")
    with pytest.raises(ValueError, match="Nenhuma legenda"):
        sb.load(bad)


VTT = """WEBVTT - legendas de teste
Kind: captions
Language: pt

STYLE
::cue { color: yellow }

NOTE isto é um comentário
que ocupa duas linhas

intro
00:01.000 --> 00:03.000 align:start position:10% line:0
Tom &amp; Jerry &lt;3

00:00:04.000 --> 00:00:06.000
<v Ana>Eu <i>acho</i> que sim</v>

00:00:07.000 --> 00:00:09.000
<00:00:07.000><c> palavra</c><00:00:07.500><c> por</c><00:00:08.000><c> palavra</c>
"""


def test_parse_vtt():
    cues = sb.parse(VTT)
    assert [c.text for c in cues] == ["Tom & Jerry <3", "Eu acho que sim", "palavra por palavra"]
    assert (cues[0].start, cues[0].end) == (1.0, 3.0) and not cues[1].italic
    assert [(w.text, w.start, w.end) for w in cues[2].words] == \
        [("palavra", 7.0, 7.5), ("por", 7.5, 8.0), ("palavra", 8.0, 9.0)]
    out = sb.to_vtt(cues)
    assert out.startswith("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nTom &amp; Jerry &lt;3\n")
    assert [c.text for c in sb.parse(out)] == [c.text for c in cues]


def test_relative_to_export_range():
    cues = [Cue(0.5, 1.5, "corta no começo"), sentence(2.0, "dentro do trecho"), Cue(9.0, 12.0, "corta no fim"),
            Cue(20, 21, "fora")]
    rel = sb.relative(cues, 1.0, 10.0)
    assert [(c.text, c.start, c.end) for c in rel] == [("corta no começo", 0.0, 0.5), ("dentro do trecho", 1.0, 2.5),
                                                       ("corta no fim", 8.0, 9.0)]
    assert rel[1].words[0] == W(1.0, 1.5, "dentro")


# ------------------------------------------------------------------ exportação
@pytest.fixture
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    return "ffmpeg"


def test_export_file_by_container():
    payload = sb.job_payload([Cue(1.0, 2.0, "um"), Cue(30.0, 31.0, "longe")], "pt")
    assert payload["idioma"] == "pt" and sb.job_payload([]) == {}
    for container, codec in (("mp4", "mov_text"), ("mov", "mov_text"), ("mkv", "srt"), ("webm", "webvtt")):
        emb = sb.export_file(payload, container, 12, 240, 24.0)
        try:
            assert emb.codec == codec and emb.path.endswith(".vtt") and emb.language == "por"
            text = Path(emb.path).read_text(encoding="utf-8")
            assert "00:00:00.500 --> 00:00:01.500" in text.replace(",", ".") and "longe" not in text
        finally:
            os.remove(emb.path)
    assert sb.export_file(payload, "avi", 0, 240, 24.0) is None
    assert sb.export_file(payload, "mp4", 100, 200, 24.0) is None            # nada no trecho
    assert sb.export_file({}, "mp4", 0, 240, 24.0) is None
    assert sb.iso639_2("en") == "eng" and sb.iso639_2("") == "" and sb.iso639_2("xx") == "und"


def test_encoder_cmd_adds_the_subtitle_track(fake_ffmpeg, make_info):
    info = make_info(path="C:/v/entrada.mp4")
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="aac192")
    plain = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 1.0, 2.0)
    emb = sb.Embed("leg.vtt", "mov_text", "por")
    cmd = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 1.0, 2.0, subtitles=emb)
    j = plain.index("-map")
    assert cmd == plain[:j] + ["-f", "webvtt", "-i", "leg.vtt"] + plain[j:-1] + \
        ["-map", "2:s:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=por", "o.mp4"]
    both = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 1.0, 2.0, chapters_path="cap.txt",
                                    subtitles=emb)
    assert both[both.index("-map_chapters") + 1] == "2" and both[both.index("-c:s") - 1] == "3:s:0"
    s2 = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="aac192", bitrate=4.0)
    first = export.build_encoder_cmd("o.mp4", info, s2, 320, 180, "24/1", 8, 0.0, 2.0, subtitles=emb, two_pass=1)
    assert "-c:s" not in first
    second = export.build_encoder_cmd("o.mp4", info, s2, 320, 180, "24/1", 8, 0.0, 2.0, subtitles=emb, two_pass=2)
    assert os.path.abspath("leg.vtt") in second


def test_run_job_writes_the_track_and_removes_the_file(make_info, tmp_path, monkeypatch):
    seen = {}

    def fake_encode(job, engine, run, s, **kw):
        emb = run.subtitles
        seen["emb"] = emb
        seen["text"] = Path(emb.path).read_text(encoding="utf-8") if emb else ""
        return False

    monkeypatch.setattr(export, "_encode", fake_encode)
    info = make_info(path=str(tmp_path / "entrada.mp4"), frames=480, duration=20.0, has_audio=False)
    s = ExportSettings(codec="x264", container="mkv", pix="yuv420p", audio="none")
    job = ExportJob(info=info, values={}, settings=s, out_path=str(tmp_path / "saida.mkv"), start_frame=48,
                    end_frame=239, subtitles=sb.job_payload([Cue(3.0, 4.0, "dentro"), Cue(15, 16, "fora")], "es"))
    export.run_job(job, None)
    assert seen["emb"].codec == "srt" and seen["emb"].language == "spa"
    assert "00:00:01.000 --> 00:00:02.000\ndentro" in seen["text"] and "fora" not in seen["text"]
    assert not os.path.exists(seen["emb"].path)
    again = ExportJob.from_dict(json.loads(json.dumps(job.to_dict())))
    assert again.subtitles == job.subtitles
    assert ExportJob.from_dict({**job.to_dict(), "legendas": "x"}).subtitles == {}


@pytest.mark.ffmpeg
@pytest.mark.parametrize("container,codec", [("mp4", "mov_text"), ("mov", "mov_text"), ("mkv", "subrip"),
                                             ("webm", "webvtt")])
def test_exported_file_has_the_subtitle_track(ffmpeg_ok, sample_video, tmp_path, container, codec):
    info = media.probe(sample_video)
    # O SRT (MKV) não tem escape e o ffmpeg grava o WebVTT (WebM) sem escapar: lá "<fim>" seria lido como tag.
    last = "<fim> & tal" if container in ("mp4", "mov") else "fim & tal"
    payload = sb.job_payload([Cue(0.1, 0.6, "Olá, ação!"), Cue(0.6, 0.9, last)], "pt")
    emb = sb.export_file(payload, container, 0, 24, 24.0)
    if container == "webm":
        s = ExportSettings(codec="vp9", container="webm", pix="yuv420p", quality=40, preset="8", audio="opus")
    else:
        s = ExportSettings(codec="x264", container=container, pix="yuv420p", quality=30, preset="ultrafast",
                           audio="aac192")
    out = tmp_path / f"saida.{container}"
    try:
        cmd = export.build_encoder_cmd(str(out), info, s, 320, 180, "24/1", 8, 0.0, 1.0, subtitles=emb)
        frames = np.zeros((24, 180, 320, 3), np.uint8).tobytes()
        res = subprocess.run(cmd, input=frames, capture_output=True, timeout=180)
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")[-2000:]
    finally:
        os.remove(emb.path)
    probe = subprocess.run([media.ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(out)],
                           capture_output=True, timeout=60)
    streams = json.loads(probe.stdout.decode("utf-8"))["streams"]
    subs = [st for st in streams if st["codec_type"] == "subtitle"]
    assert len(subs) == 1 and subs[0]["codec_name"] == codec
    assert subs[0].get("tags", {}).get("language") in ("por", None if container == "webm" else "por")
    back = tmp_path / "volta.srt"   # o SRT do ffmpeg sai sem mexer no texto (e o "<fim>" não é tag de SRT)
    res = subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-i", str(out), "-map", "0:s:0", str(back)],
                         capture_output=True, timeout=60)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert [c.text for c in sb.load(back)] == ["Olá, ação!", last]
    assert {st["codec_type"] for st in streams} >= {"video", "audio"}


# ------------------------------------------------------------------ gravada no vídeo
def test_visible_text_pages_and_spoken_word():
    reels = sb.style("reels")
    cue = sentence(10.0, "um dois três quatro cinco")
    assert sb.visible_text(cue, 9.99 + 0.02, sb.style("youtube")) == ("um dois três quatro cinco", 0)
    assert sb.visible_text(cue, 10.0, reels) == ("um dois três", 0)
    assert sb.visible_text(cue, 11.2, reels) == ("um dois três", 2)     # 4ª palavra (11.5) ainda não: 3ª
    assert sb.visible_text(cue, 11.0, reels) == ("um dois três", 2)
    assert sb.visible_text(cue, 11.6, reels) == ("quatro cinco", 0)
    edited = Cue(cue.start, cue.end, "texto mudado à mão", cue.words)
    assert sb.visible_text(edited, 11.0, reels) == ("texto mudado à mão", None)  # palavras não batem: sem destaque


def test_overlay_places_and_highlights(qapp):
    cues = [sentence(1.0, "legenda de teste com destaque"), Cue(5.0, 6.0, "outra")]
    assert sb.overlay(cues, 0, 24.0, sb.style("youtube"), 1920, 1080) is None
    yt = sb.overlay(cues, 24, 24.0, sb.style("youtube"), 1920, 1080)
    lay = yt.image.layout
    assert yt.y + lay.height == pytest.approx(1080 - 64, abs=1)              # embaixo, com a margem
    assert yt.x == pytest.approx((1920 - lay.width) / 2, abs=1)
    frame = np.zeros((1080, 1920, 4), np.uint8)
    yt.paste(frame)
    ys = np.nonzero(frame[..., 3])[0]
    assert ys.min() > 900 and ys.max() < 1080
    # 4K: tudo dobra (px@1080)
    yt4 = sb.overlay(cues, 24, 24.0, sb.style("youtube"), 3840, 2160, depth=16)
    assert yt4.image.rgba.dtype == np.uint16 and yt4.image.layout.height == pytest.approx(lay.height * 2)
    # vertical com destaque: a palavra falada sai amarela, as outras brancas
    reels = sb.style("reels")
    ov = sb.overlay(cues, int(1.6 * 24), 24.0, reels, 1080, 1920)           # 2ª palavra ("de")
    assert ov.image.layout.words[1].text == "DE" and len(ov.image.layout.words) == 3  # estilo em maiúsculas
    rgba = ov.image.rgba.astype(int)
    yellow = (rgba[..., 0] > 230) & (rgba[..., 1] > 190) & (rgba[..., 2] < 60) & (rgba[..., 3] > 200)
    assert yellow.sum() > 200
    assert abs((ov.y + ov.image.layout.height / 2) - (1920 / 2 + 120 * 1920 / 1080)) < 2   # no meio, um pouco abaixo
    again = sb.overlay(cues, int(1.6 * 24), 24.0, reels, 1080, 1920)
    assert np.array_equal(again.image.rgba, ov.image.rgba)                  # determinístico (e em cache)
    italic = sb.overlay([Cue(0, 1, "itálico", italic=True)], 0, 24.0, sb.style("cinema"), 1920, 1080)
    assert italic.image.layout.face.italic


def test_overlay_stacks_overlapping_cues(qapp):
    cues = [Cue(0, 2, "primeira"), Cue(1, 3, "segunda")]
    ov = sb.overlay(cues, 30, 24.0, sb.style("cinema"), 1920, 1080)
    assert [w.text for w in ov.image.layout.words] == ["primeira", "segunda"]
    assert len(ov.image.layout.lines) == 2
