"""Exportação por plataforma de ponta a ponta (GPU + ffmpeg): tamanho alvo em duas passadas e volume alvo.

- Tamanho alvo (Discord, WhatsApp): o arquivo nunca passa do alvo, o progresso cobre as duas passadas, uma 2ª
  passada grande demais é refeita com a taxa corrigida, e cancelar no meio da 2ª não deixa parcial nem apaga o
  arquivo antigo.
- Volume alvo: o som gravado fica a ±1 LU do alvo medido pelo `ebur128` do ffmpeg, nos modos Película (trecho
  do original) e Edição (mixagem), e "Copiar original" passa a recodificar.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

from pelicula import export, loudnorm, media, platforms, presets, sequence
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings

pytestmark = [pytest.mark.gpu, pytest.mark.ffmpeg]

W, H, FPS, SECONDS = 640, 360, 24, 4


@pytest.fixture(scope="module")
def noisy_video(ffmpeg_ok, tmp_path_factory) -> str:
    """4 s, 640x360, 24 fps, imagem com ruído forte (não cabe em pouco espaço sem a taxa certa) e som estéreo
    baixo (por volta de −30 LUFS) com volume variando."""
    out = tmp_path_factory.mktemp("ruido") / "ruido.mp4"
    audio = ("aevalsrc=0.05*sin(2*PI*440*t)*(0.6+0.4*sin(2*PI*0.5*t))|0.04*sin(2*PI*660*t)"
             f":s=48000:d={SECONDS}")
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-nostdin",
           "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration={SECONDS},noise=alls=40:allf=t+u",
           "-f", "lavfi", "-i", audio,
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not out.exists():
        pytest.skip("não foi possível gerar o vídeo com ruído: " + res.stderr.decode("utf-8", "replace"))
    return str(out)


@pytest.fixture(scope="module")
def noisy_info(noisy_video):
    return media.probe(noisy_video)


@pytest.fixture
def film():
    return presets.builtin_values("vision3_500t")


@pytest.fixture
def private_tmp(tmp_path, monkeypatch) -> Path:
    """Pasta temporária do sistema só deste teste (as passadas e a mixagem não podem deixar sobras)."""
    d = tmp_path / "temp_sistema"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


def target(mb: float, **over) -> ExportSettings:
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=18, preset="ultrafast", audio="aac128",
                       tune_grain=False, target_mb=mb)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name not in ("appdata", "temp_sistema"))


def ebur128(ffmpeg: str, path) -> tuple[float, float]:
    """(LUFS integrados, pico real em dBTP) do som de `path`, medidos pelo filtro ebur128 do ffmpeg."""
    res = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-i", str(path), "-map", "0:a:0",
                          "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True)
    text = res.stderr.decode("utf-8", "replace")
    summary = text[text.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    assert res.returncode == 0 and i and peak, text[-2000:]
    return float(i.group(1)), float(peak.group(1))


class Watch:
    """Engine que chama `fn(n)` depois de cada quadro renderizado (em todas as passadas)."""

    def __init__(self, engine, fn):
        self.engine, self.fn, self.count = engine, fn, 0

    def set_input(self, img):
        self.engine.set_input(img)

    def render(self, plan, depth=8):
        out = self.engine.render(plan, depth)
        self.count += 1
        self.fn(self.count)
        return out

    def render_fit(self, plan, depth, fit):
        out = self.engine.render_fit(plan, depth, fit)
        self.count += 1
        self.fn(self.count)
        return out


# ------------------------------------------------------------------ tamanho alvo
def test_target_size_never_passes_the_target_and_uses_it(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film,
                                                         private_tmp):
    out = tmp_path / "discord.mp4"
    s = target(1.0)
    seen = []
    job = ExportJob(info=noisy_info, values=film, settings=s, out_path=str(out))
    watch = Watch(gl_engine, lambda n: seen.append((job.pass_index, job.passes, job.stage, job.progress)))
    export.run_job(job, watch)
    assert job.status == "concluido", job.error
    size = out.stat().st_size
    assert size <= 1_000_000                    # nunca passa do alvo (1 MB = 1.000.000 bytes)
    assert size >= 600_000                      # e usa o espaço (a qualidade sai do alvo, não sobra metade)
    frames = SECONDS * FPS
    assert watch.count == 2 * frames            # a GPU renderiza o vídeo nas duas passadas
    i = media.probe(str(out))
    assert i.codec == "h264" and i.frames == frames and i.has_audio and i.audio_codec == "aac"
    # progresso: a 1ª passada vai até a metade, a 2ª da metade ao fim; a etapa aparece na fila
    first = [p for k, n, _st, p in seen if k == 0]
    second = [p for k, n, _st, p in seen if k == 1]
    assert len(first) == len(second) == frames
    assert max(first) <= 0.5 + 1e-9 and min(second) >= 0.5 - 1e-9
    assert {st for _k, _n, st, _p in seen} == {"Passada 1 de 2", "Passada 2 de 2"}
    assert job.progress == 1.0 and job.stage == ""
    # nada sobra: nem parcial, nem registro das passadas (na pasta temporária nem na pasta atual)
    assert names(tmp_path) == ["discord.mp4"]
    assert list(private_tmp.iterdir()) == []
    assert not [f for f in os.listdir(os.getcwd()) if f.startswith(export.PASSLOG)]


def test_target_size_in_a_trimmed_range_and_x265(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film, private_tmp):
    out = tmp_path / "trecho.mp4"
    s = target(0.4, codec="x265", pix="yuv420p", audio="copy")  # copiar o som vira AAC 128 no tamanho alvo
    job = ExportJob(info=noisy_info, values=film, settings=s, out_path=str(out), start_frame=24, end_frame=71)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert out.stat().st_size <= 400_000
    i = media.probe(str(out))
    assert i.codec == "hevc" and i.frames == 48 and i.audio_codec == "aac"
    assert i.duration == pytest.approx(2.0, abs=0.1)
    assert names(tmp_path) == ["trecho.mp4"] and list(private_tmp.iterdir()) == []


def test_second_pass_too_big_is_redone_with_a_corrected_rate(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film,
                                                             monkeypatch, private_tmp):
    real = export.target_bitrate
    monkeypatch.setattr(export, "target_bitrate", lambda *a, **k: real(*a, **k) * 3)  # o controle de taxa "erra"
    out = tmp_path / "refeito.mp4"
    job = ExportJob(info=noisy_info, values=film, settings=target(1.0), out_path=str(out))
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert job.passes == 3 and job.progress == 1.0
    assert out.stat().st_size <= 1_000_000
    assert names(tmp_path) == ["refeito.mp4"] and list(private_tmp.iterdir()) == []


def test_target_too_small_is_an_error_that_keeps_the_old_file(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film,
                                                              private_tmp):
    out = tmp_path / "pequeno.mp4"
    out.write_bytes(b"video antigo")
    job = ExportJob(info=noisy_info, values=film, settings=target(0.05), out_path=str(out))
    export.run_job(job, gl_engine)
    assert job.status == "erro" and "é pouco para 4 s de vídeo" in job.error
    assert out.read_bytes() == b"video antigo" and names(tmp_path) == ["pequeno.mp4"]


def test_cancel_in_the_second_pass_keeps_the_old_file(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film,
                                                      private_tmp):
    out = tmp_path / "cancelado.mp4"
    out.write_bytes(b"video antigo")
    job = ExportJob(info=noisy_info, values=film, settings=target(1.0), out_path=str(out))
    frames = SECONDS * FPS
    during = []

    def check(n):
        during.append(out.read_bytes())
        if n == frames + 10:  # já na 2ª passada
            job.cancel.set()

    export.run_job(job, Watch(gl_engine, check))
    assert job.status == "cancelado" and job.pass_index == 1
    assert set(during) == {b"video antigo"}
    assert out.read_bytes() == b"video antigo"
    assert names(tmp_path) == ["cancelado.mp4"] and list(private_tmp.iterdir()) == []


def test_platform_with_target_size_exports_end_to_end(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film,
                                                      private_tmp):
    """Discord (20 MB) com o alvo trocado pelo usuário: a plataforma inteira (quadro, fps, som, volume) funciona."""
    s = platforms.settings_for("discord", noisy_info, duration=noisy_info.duration)
    s.target_mb, s.preset = 0.8, "ultrafast"
    out = tmp_path / "discord.mp4"
    job = ExportJob(info=noisy_info, values=film, settings=s, out_path=str(out))
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert out.stat().st_size <= 800_000
    i = media.probe(str(out))
    assert (i.width, i.height) == (W, H)  # nunca aumenta o vídeo
    lufs, _peak = ebur128(ffmpeg_ok, out)
    assert lufs == pytest.approx(-14.0, abs=1.0)


# ------------------------------------------------------------------ volume alvo
def _measure_spy(monkeypatch) -> list[tuple]:
    calls, real = [], loudnorm.measure

    def spy(path, tgt, tp, start=0.0, duration=0.0, cancel=None, perf=None):
        calls.append((path, tgt, tp, start, duration))
        return real(path, tgt, tp, start, duration, cancel, perf)

    monkeypatch.setattr(loudnorm, "measure", spy)
    return calls


@pytest.mark.parametrize("lufs, tp, audio, container, codec", [
    (-14.0, -1.0, "aac192", "mp4", "aac"),        # redes
    (-16.0, -2.0, "copy", "mp4", "aac"),          # Spotify; copiar o som vira AAC (o volume precisa mudar)
    (-23.0, -1.0, "pcm24", "mov", "pcm_s24le"),   # festival (EBU R 128)
])
def test_loudness_target_in_film_mode(gl_engine, ffmpeg_ok, noisy_video, noisy_info, tmp_path, film, monkeypatch,
                                      lufs, tp, audio, container, codec):
    before, _ = ebur128(ffmpeg_ok, noisy_video)
    assert abs(before - lufs) > 4  # o som de origem está longe do alvo: o teste mede a mudança
    calls = _measure_spy(monkeypatch)
    s = ExportSettings(codec="x264", container=container, pix="yuv420p", quality=23, preset="ultrafast",
                       resolution="180", audio=audio, loudness=lufs, true_peak=tp)
    assert export.audio_reencoded_for_volume(s, noisy_info) == (audio == "copy")
    out = tmp_path / f"volume.{container}"
    job = ExportJob(info=noisy_info, values=film, settings=s, out_path=str(out), start_frame=24, end_frame=71)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    # mediu exatamente o trecho que foi gravado
    assert calls == [(noisy_video, lufs, tp, pytest.approx(1.0), pytest.approx(2.0))]
    i = media.probe(str(out))
    assert i.audio_codec == codec and i.duration == pytest.approx(2.0, abs=0.1)
    after, peak = ebur128(ffmpeg_ok, out)
    assert after == pytest.approx(lufs, abs=1.0)
    assert peak <= tp + 0.5


def test_loudness_target_in_edit_mode_measures_the_mix(gl_engine, ffmpeg_ok, noisy_video, tmp_path, film,
                                                       monkeypatch, private_tmp):
    src = media.probe_source(noisy_video)
    seq = tl.Sequence.for_source(src)
    a = [c for c in seq.clips if c.kind == tl.AUDIO][0]
    seq.set_values(a.id, {**a.values, "volume": -12.0})  # a mixagem é 12 dB mais baixa que o original
    v = [c for c in seq.clips if c.kind == tl.VIDEO][0]
    seq.trim_end(v.id, 72)
    seq.trim_end(a.id, 72)
    info = sequence.media_info(seq)
    calls = _measure_spy(monkeypatch)
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=23, preset="ultrafast",
                       resolution="180", audio="aac192", loudness=-14.0, true_peak=-1.0)
    out = tmp_path / "edicao.mp4"
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out), sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert len(calls) == 1
    path, tgt, tp, start, duration = calls[0]
    assert path.endswith(".wav") and (tgt, tp, start, duration) == (-14.0, -1.0, 0.0, 0.0)  # a mixagem pronta
    after, _peak = ebur128(ffmpeg_ok, out)
    assert after == pytest.approx(-14.0, abs=1.0)
    assert list(private_tmp.iterdir()) == []  # a mixagem temporária foi apagada


def test_silence_is_left_alone(gl_engine, ffmpeg_ok, tmp_path, film):
    out_src = tmp_path / "mudo.mp4"
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1",
           "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out_src)]
    assert subprocess.run(cmd, capture_output=True).returncode == 0
    info = media.probe(str(out_src))
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=23, preset="ultrafast", audio="aac128",
                       loudness=-14.0)
    out = tmp_path / "saida.mp4"
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out))
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error  # silêncio: nada a normalizar, sem erro nem ruído inventado
    assert media.probe(str(out)).has_audio


def test_cancel_while_measuring_the_volume(gl_engine, ffmpeg_ok, noisy_info, tmp_path, film, monkeypatch):
    out = tmp_path / "volume.mp4"
    out.write_bytes(b"video antigo")
    job = ExportJob(info=noisy_info, values=film, settings=ExportSettings(preset="ultrafast", audio="aac128",
                                                                          loudness=-14.0), out_path=str(out))
    real = loudnorm.measure

    def cancel_first(*a, **k):
        job.cancel.set()
        return real(*a, **k)

    monkeypatch.setattr(loudnorm, "measure", cancel_first)
    export.run_job(job, gl_engine)
    assert job.status == "cancelado" and job.done == 0
    assert out.read_bytes() == b"video antigo" and names(tmp_path) == ["volume.mp4"]


# ------------------------------------------------------------------ estimativa da janela
def test_measure_speed_reports_the_video_rate(gl_engine, ffmpeg_ok, noisy_info, film):
    # gl_engine só para pular sem OpenGL 3.3: measure_speed cria o próprio Engine na thread.
    stats: dict = {}
    out: list[float] = []
    s = target(0.5, loudness=-14.0)  # tamanho alvo e volume ficam de fora da medida (uma passada, sem som)

    def run():
        out.append(export.measure_speed(noisy_info, film, s, threading.Event(), frames=30, stats=stats))

    th = threading.Thread(target=run)
    th.start()
    th.join(120)
    assert out and out[0] > 0
    assert stats["video_bytes_per_second"] > 10_000
    assert s.target_mb == 0.5 and s.loudness == -14.0  # os ajustes do usuário não mudam
