"""Legendas automáticas da montagem (`subauto`): o que ouvir, o trabalho na fila (whisper-cli falso,
tests/whisper_falso.py, sem rede nem modelo) e a junção no projeto, presa aos arquivos."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pelicula import jobs, subauto, subtitles as sb, timeline as tl, transcribe as tc
from pelicula.subtitles import Cue

FAKE = Path(__file__).with_name("whisper_falso.py")
A, B = "C:/v/a.mp4", "C:/v/b.mp4"


def source(path, seconds=20.0, audio=True, image=False):
    return tl.Source(path=path, width=1920, height=1080, fps=24.0, fps_str="24/1", frames=int(seconds * 24),
                     duration=seconds, has_video=True, has_audio=audio, is_image=image)


def seq_with(*sources) -> tl.Sequence:
    seq = tl.Sequence(1920, 1080, "24/1")
    for s in sources:
        seq.insert_media(s)
    return seq


def by_kind(seq, kind, path=None):
    return sorted((c for c in seq.clips if c.kind == kind and (path is None or c.src == path)),
                  key=lambda c: c.start)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """O motor falso no lugar do whisper-cli e um som de mentira no lugar do ffmpeg."""
    model, vad = tmp_path / "modelo.bin", tmp_path / "vad.bin"
    model.write_bytes(b"modelo")
    vad.write_bytes(b"vad")
    log = tmp_path / "chamadas.txt"
    monkeypatch.setenv("PCTEST_WHISPER_LOG", str(log))
    monkeypatch.delenv("PCTEST_WHISPER_MODO", raising=False)
    monkeypatch.setattr(tc, "temp_dir", lambda: tmp_path / "cache")
    eng = tc.Engine((sys.executable, str(FAKE)), model, vad)
    monkeypatch.setattr(tc, "engine", lambda model="small", root=None: eng)
    monkeypatch.setattr(tc, "vulkan_available", lambda: True)
    extracted = []

    def fake_extract(path, out, start=0.0, duration=0.0, *a, **k):
        extracted.append((path, start, duration))
        Path(out).write_bytes(b"RIFF")

    monkeypatch.setattr(tc, "extract_audio", fake_extract)
    return extracted


# ------------------------------------------------------------------ o que ouvir
def test_spans_cover_what_the_montage_shows():
    seq = seq_with(source(A), source(B, 10.0))
    assert subauto.spans_for(seq) == [subauto.Span(A, 0.0, 20.0), subauto.Span(B, 0.0, 10.0)]
    a_audio = by_kind(seq, tl.AUDIO, A)[0]
    seq.split(24 * 5, [a_audio.id, *[c.id for c in seq.group(a_audio)]])
    right = by_kind(seq, tl.AUDIO, A)[1]
    seq.delete([right.id, *[c.id for c in seq.group(right)]], ripple=True)   # sobram 0–5 s de A
    assert subauto.spans_for(seq) == [subauto.Span(A, 0.0, 5.0), subauto.Span(B, 0.0, 10.0)]


def test_spans_merge_close_pieces_and_keep_far_ones_apart():
    seq = seq_with(source(A, 200.0))
    a = by_kind(seq, tl.AUDIO)[0]
    seq.split(24 * 10, [c.id for c in seq.group(a)])
    seq.split(24 * 20, None)
    seq.split(24 * 100, None)
    mid = [c for c in seq.clips if c.start == 24 * 10]
    seq.delete([c.id for c in mid], ripple=True)                 # tira 10–20 s: perto, vira um trecho só
    assert subauto.spans_for(seq) == [subauto.Span(A, 0.0, 200.0)]
    assert subauto.spans_for(seq, gap=5.0) == [subauto.Span(A, 0.0, 10.0), subauto.Span(A, 20.0, 200.0)]
    far = [c for c in seq.clips if c.start == 24 * 90]           # 100–200 s do arquivo (depois do corte)
    seq.delete([c.id for c in far], ripple=True)
    assert subauto.spans_for(seq) == [subauto.Span(A, 0.0, 100.0)]


def test_spans_follow_speed_selection_mute_and_skip_what_has_no_speech():
    seq = seq_with(source(A), source(B, 10.0), source("C:/v/mudo.mp4", audio=False),
                   source("C:/v/foto.png", 4.0, audio=False, image=True))
    seq.insert_media(tl.Source.virtual("texto", 1920, 1080, seconds=3.0))
    a = by_kind(seq, tl.AUDIO, A)[0]
    for c in seq.group(a):
        seq.set_speed(c.id, 2.0)                                  # 2x: 20 s do arquivo em 10 s
    assert subauto.spans_for(seq)[0] == subauto.Span(A, 0.0, 20.0)
    b = by_kind(seq, tl.VIDEO, B)[0]
    assert subauto.spans_for(seq, [b.id]) == [subauto.Span(B, 0.0, 10.0)]   # o vídeo escolhido leva o som ligado
    assert subauto.spans_for(seq, []) == []
    seq.track(tl.AUDIO, 0).muted = True                           # faixa muda: não há fala para ouvir
    assert subauto.spans_for(seq) == []


def test_spans_without_audio_clips_use_the_picture():
    seq = seq_with(source(A))
    a = by_kind(seq, tl.AUDIO)[0]
    seq.unlink(a.id)
    seq.delete([a.id])                                            # o arquivo tem som, mas a montagem só usa a imagem
    assert subauto.spans_for(seq) == [subauto.Span(A, 0.0, 20.0)]


def test_languages_start_with_detection():
    langs = subauto.languages()
    assert next(iter(langs)) == "auto" and {"pt", "en", "es", "fr"} <= set(langs)


# ------------------------------------------------------------------ na fila
def test_one_span_is_the_transcribe_job(installed):
    q = jobs.JobQueue()
    try:
        job = q.submit(subauto.make_job(tc.Options(language="pt"), "Legendas: a.mp4", [subauto.Span(A, 2.0, 8.0)]))
        assert job.kind == jobs.GPU and job.key == tc.JOB_KEY
        assert job.wait(30) and job.state == jobs.CONCLUIDO, job.error
        (res,) = job.result
        assert res.path == A and (res.start, res.end) == (2.0, 8.0) and res.device == "gpu"
        assert res.words[0].start == pytest.approx(2.5)           # 2 s do trecho + 0,5 s no som
        assert installed == [(A, 2.0, 6.0)]
    finally:
        q.shutdown()


def test_many_spans_run_in_one_job_and_fall_back_to_the_cpu(installed, monkeypatch):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", "falha_gpu")      # a placa falha: o mesmo trabalho vai no processador
    spans = [subauto.Span(A, 0.0, 5.0), subauto.Span(B, 1.0, 9.0)]
    q = jobs.JobQueue()
    stages = []
    q.add_listener(lambda ev, j: stages.append(j.stage) if ev == jobs.PROGRESS else None)
    try:
        job = q.submit(subauto.make_job(tc.Options(gpu=True), "Legendas: 2 arquivos", spans))
        assert job.wait(60) and job.state == jobs.CONCLUIDO, job.error
        assert [(r.path, r.start, r.end, r.device) for r in job.result] == [(A, 0.0, 5.0, "cpu"),
                                                                            (B, 1.0, 9.0, "cpu")]
        assert any(s.startswith("Trecho 2 de 2") for s in stages)
        doc = sb.Subtitles(sources={A: [Cue(0.2, 0.4, "velha"), Cue(6, 7, "fica")]})
        assert subauto.apply(doc, job.result) == 2
        assert [c.text for c in doc.sources[A]] == ["Olá, pessoal. Tudo bem?", "fica"]
        assert doc.sources[B][0].start == pytest.approx(1.5)
    finally:
        q.shutdown()


def test_cancel_stops_every_span(installed, monkeypatch):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", "lento")
    q = jobs.JobQueue()
    try:
        job = q.submit(subauto.make_job(tc.Options(), "x", [subauto.Span(A, 0, 5), subauto.Span(B, 0, 5)]))
        for _ in range(200):
            if job.stage:
                break
            job.wait(0.05)
        job.cancel()
        assert job.wait(30) and job.state == jobs.CANCELADO
        assert [p for p, *_ in installed] == [A]                 # o segundo trecho nem começou
    finally:
        q.shutdown()


def test_missing_components_fail_with_a_message(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "WHISPER_CMD", None)
    monkeypatch.setattr(tc, "vulkan_available", lambda: False)
    q = jobs.JobQueue()
    try:
        job = q.submit(subauto.make_job(tc.Options(), "x", [subauto.Span(A)], root=tmp_path))
        assert job.wait(30) and job.state == jobs.ERRO and "Componentes" in job.error
    finally:
        q.shutdown()
