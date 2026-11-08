"""1.8, som de película na exportação e na prévia (`somfilme.export_sound`, `export._film_sound`; ARQUITETURA §45).

Um trecho exportado tem as mesmas amostras que a prévia (que processa o som inteiro a partir do quadro 0) nos mesmos
instantes, na montagem e no arquivo direto; o estalo cai no quadro do corte com "A montagem na película"; a trilha
corta os agudos; com o som de película ligado o som do arquivo é recodificado a partir do WAV processado, nunca
copiado; desligado, nada muda. Os arquivos de teste têm 2 s, gerados pelo ffmpeg (lavfi).
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from pelicula import audiomix, export, media, params, sequence, somfilme as S
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings

RATE = S.RATE


def _make(ffmpeg, path, audio):
    cmd = [ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=2",
           "-f", "lavfi", "-i", audio, "-map", "0:v", "-map", "1:a", "-t", "2", "-c:v", "libx264", "-preset",
           "veryfast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(path)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        pytest.skip("não foi possível gerar o vídeo de teste")
    return str(path)


@pytest.fixture(scope="module")
def noise_video(ffmpeg_ok, tmp_path_factory):
    return _make(ffmpeg_ok, tmp_path_factory.mktemp("somf") / "ruido.mov",
                 "anoisesrc=color=white:amplitude=0.05:sample_rate=48000:seed=3")


@pytest.fixture(scope="module")
def silent_video(ffmpeg_ok, tmp_path_factory):
    return _make(ffmpeg_ok, tmp_path_factory.mktemp("somf") / "mudo.mov", "anullsrc=r=48000:cl=stereo")


def _two(path):
    """O mesmo arquivo duas vezes: um corte seco da V1 no quadro 48 (2 s)."""
    src = media.probe_source(path)
    seq = tl.Sequence.for_source(src)
    seq.insert_media(src, at=48)
    return seq


def _vals(**kw):
    return params.sanitize({"somf_on": True, "somf_projetor": 0.4, "somf_sala": 0.5, "somf_estalos": 1.0,
                            "somf_poeira": 0.8, "somf_wow": 0.8, "mfilme_on": True, "mfilme_emenda": 1.0, **kw})


def _read(path):
    r = audiomix.WavReader(path)
    return r.read(0, r.frames).astype(np.float64)


def _preview_seq(seq, v, tmp_path):
    raw = str(tmp_path / "mix.wav")
    assert audiomix.render_mix(seq, raw)
    info = sequence.media_info(seq)
    out = str(tmp_path / "previa.wav")
    assert S.process_wav(raw, out, v, info.fps, 0, S.events_for(v, info.fps, info.frames, seq))
    return _read(out)


@pytest.mark.ffmpeg
def test_montage_range_equals_the_preview(noise_video, tmp_path):
    seq = _two(noise_video)
    v = _vals()
    prev = _preview_seq(seq, v, tmp_path)
    info = sequence.media_info(seq)
    start, end = 30, 80
    part = str(tmp_path / "trecho.wav")
    assert audiomix.render_mix(seq, part, start, end)
    out = S.export_sound(v, info, seq, start, end, part)
    try:
        got = _read(out)
    finally:
        audiomix._remove(out)
    a = round(start / 24 * RATE)
    assert abs(len(got) - (end - start) / 24 * RATE) <= 2
    ref = prev[a:a + len(got)]
    assert np.abs(got[:len(ref)] - ref).max() < 1e-6


@pytest.mark.ffmpeg
def test_file_range_equals_the_preview(noise_video, tmp_path):
    info = media.probe(noise_video)
    v = _vals(mfilme_on=False, desg_on=True, emenda_on=True, emenda=1.0)
    dec = str(tmp_path / "arquivo.wav")
    assert audiomix.decode_wav(noise_video, dec)
    pv = str(tmp_path / "previa.wav")
    assert S.process_wav(dec, pv, v, info.fps, 0, S.events_for(v, info.fps, info.frames))
    prev = _read(pv)
    start, end = 30, 44
    out = S.export_sound(v, info, None, start, end, None)
    try:
        got = _read(out)
    finally:
        audiomix._remove(out)
    a = round(start / 24 * RATE)
    n = min(len(got), len(prev) - a)
    assert n > 0.5 * RATE
    assert np.abs(got[:n] - prev[a:a + n]).max() < 1e-4  # o arquivo da prévia é de 16 bits


@pytest.mark.ffmpeg
def test_pop_lands_on_the_cut_and_track_cuts_the_highs(silent_video, noise_video, tmp_path):
    seq = _two(silent_video)
    v = _vals(somf_trilha_forca=0.0, somf_poeira=0.0, somf_wow=0.0, somf_projetor=0.0, somf_sala=0.0)
    info = sequence.media_info(seq)
    start, end = 10, 90
    part = str(tmp_path / "mudo.wav")
    assert audiomix.render_mix(seq, part, start, end)
    out = S.export_sound(v, info, seq, start, end, part)
    got = _read(out)
    audiomix._remove(out)
    first = int(np.flatnonzero(np.abs(got[:, 0]) > 0)[0])
    assert first == round(48 / 24 * RATE) - round(start / 24 * RATE)

    seq = _two(noise_video)
    v = _vals(somf_trilha="otica_16", somf_estalos=0.0, somf_poeira=0.0, somf_wow=0.0, somf_projetor=0.0,
              somf_sala=0.0)
    part = str(tmp_path / "ruido.wav")
    assert audiomix.render_mix(seq, part, 0, 96)
    out = S.export_sound(v, info, seq, 0, 96, part)
    got = _read(out).mean(axis=1)
    audiomix._remove(out)
    raw = _read(part).mean(axis=1)

    def high(x):
        p = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / RATE)
        return p[f > 9000].sum() / p.sum()

    assert high(raw) > 0.4
    assert high(got) < 0.01


def test_film_sound_is_none_when_off(make_info):
    info = make_info()
    s = ExportSettings(audio="copy", container="mov", codec="prores")
    job = ExportJob(info=info, values=params.defaults(), settings=s, out_path="x.mov")
    assert export._film_sound(job, info, None, 0, 10, None, s.perf()) is None
    job.values = _vals()
    job.settings = ExportSettings(audio="copy", container="mov", codec="prores", no_effects=True)
    assert export._film_sound(job, info, None, 0, 10, None, s.perf()) is None
    job.settings = ExportSettings(audio="none", container="mov", codec="prores")
    assert export._film_sound(job, info, None, 0, 10, None, s.perf()) is None


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_reencodes_the_file_sound_and_off_copies(gl_engine, noise_video, tmp_path):
    info = media.probe(noise_video)
    s = ExportSettings(codec="x264", container="mov", pix="yuv420p", quality=24, preset="ultrafast", audio="copy")
    off = tmp_path / "desligado.mov"
    job = ExportJob(info=info, values=params.defaults(), settings=s, out_path=str(off), start_frame=6, end_frame=40)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert media.probe(str(off)).audio_codec == "pcm_s16le", "desligado: o som é copiado como sempre"
    on = tmp_path / "ligado.mov"
    job = ExportJob(info=info, values=_vals(mfilme_on=False), settings=s, out_path=str(on), start_frame=6,
                    end_frame=40)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    i = media.probe(str(on))
    assert i.audio_codec == "pcm_s24le", "ligado: o som vem do WAV processado"
    assert i.duration == pytest.approx(35 / 24, abs=0.05)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_of_a_montage_has_the_pop_at_the_cut(gl_engine, silent_video, tmp_path):
    seq = _two(silent_video)
    v = _vals(somf_trilha_forca=0.0, somf_poeira=0.0, somf_wow=0.0, somf_projetor=0.0, somf_sala=0.0)
    s = ExportSettings(codec="ffv1", container="mkv", pix="yuv420p", audio="pcm24")
    out = tmp_path / "montagem.mkv"
    job = ExportJob(info=sequence.media_info(seq), values=v, settings=s, out_path=str(out), start_frame=24,
                    end_frame=71, sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    wav = str(tmp_path / "saida.wav")
    assert audiomix.decode_wav(str(out), wav)
    got = _read(wav)
    first = int(np.flatnonzero(np.abs(got[:, 0]) > 1e-3)[0])
    assert abs(first - (round(48 / 24 * RATE) - round(24 / 24 * RATE))) <= 2
