"""1.8, aviso do som de película com "Copiar original" (ARQUITETURA §45.8).

Com o som de película ligado, o som do arquivo nunca é copiado (`export._film_sound`): sai do WAV processado no formato
que `_audio_mode` dá para um WAV de 24 bits. O aviso só informa (a exportação não muda): a janela mostra ao lado do áudio
(caso em `export_ui_cases.py`), o terminal no começo (`cli._export_notes`) e a fila/barra de status/terminal no fim
(`job.note`).
"""

from __future__ import annotations

import subprocess

import pytest

from pelicula import cli, export, media, params
from pelicula.export import ExportJob, ExportSettings

ON = params.sanitize({"somf_on": True})


def test_mode_and_note_follow_the_container(make_info):
    info = make_info()
    cases = {"mp4": ("aac320", "AAC 320 kb/s"), "mov": ("copy", "PCM 24 bits (sem perdas)"),
             "mkv": ("copy", "PCM 24 bits (sem perdas)"), "webm": ("opus", "Opus 192 kb/s"),
             "avi": ("mp3", "MP3 320 kb/s")}
    for container, (mode, label) in cases.items():
        s = ExportSettings(codec="x264", container=container, audio="copy")
        assert export.audio_reencoded_for_film(s, info, ON) == mode, container
        assert export.film_sound_note(s, info, ON) == (
            f"O som de película está ligado: o som será recodificado em {label}.")
        assert export.film_sound_note(s, info, ON, done=True) == (
            f"O som de película estava ligado: o som foi recodificado em {label}.")


def test_no_note_when_it_does_not_apply(make_info):
    info = make_info()
    s = ExportSettings(codec="x264", container="mp4", audio="copy")
    assert export.film_sound_note(s, info, params.defaults()) == ""            # som de película desligado
    assert export.film_sound_note(s, info, None) == ""
    assert export.film_sound_note(ExportSettings(codec="x264", container="mp4", audio="copy", no_effects=True),
                                  info, ON) == ""                             # "Desligar todos os efeitos"
    assert export.film_sound_note(ExportSettings(codec="x264", container="mp4", audio="aac192"), info, ON) == ""
    assert export.film_sound_note(ExportSettings(codec="x264", container="mp4", audio="none"), info, ON) == ""
    assert export.film_sound_note(s, make_info(has_audio=False, audio_codec=""), ON) == ""
    assert export.film_sound_note(ExportSettings(codec="png", container="png", audio="copy"), info, ON) == ""
    assert export.film_sound_note(s, info, ON, sequence=object()) == ""     # a montagem já é a mixagem


def test_cli_prints_the_note_at_the_start(make_info):
    info = make_info()
    s = ExportSettings(codec="x264", container="mp4", audio="copy")
    lines = cli._export_notes(None, s, info, 10.0, ON, None)
    assert "O som de película está ligado: o som será recodificado em AAC 320 kb/s." in lines
    assert not any("película" in t for t in cli._export_notes(None, s, info, 10.0, params.defaults(), None))
    assert not any("película" in t for t in cli._export_notes(None, s, info, 10.0))


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_finished_job_says_it_was_reencoded(gl_engine, ffmpeg_ok, tmp_path):
    src = tmp_path / "ruido.mp4"
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=1",
           "-f", "lavfi", "-i", "anoisesrc=color=white:amplitude=0.05:sample_rate=48000:seed=3", "-t", "1",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        pytest.skip("não foi possível gerar o vídeo de teste")
    info = media.probe(str(src))
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=24, preset="ultrafast", audio="copy")
    job = ExportJob(info=info, values=params.defaults(), settings=s, out_path=str(tmp_path / "desligado.mp4"))
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert job.note == ""
    job = ExportJob(info=info, values=ON, settings=s, out_path=str(tmp_path / "ligado.mp4"))
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert job.note == "O som de película estava ligado: o som foi recodificado em AAC 320 kb/s."
    assert job.settings.audio == "copy"
    assert media.probe(str(tmp_path / "ligado.mp4")).audio_codec == "aac"
