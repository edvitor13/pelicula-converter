"""Exportação de ponta a ponta (GPU + ffmpeg): run_job, fila, cancelamento e medição de velocidade."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from helpers import SAMPLE_FRAMES, SAMPLE_H, SAMPLE_W, read_all
from pelicula import export, look, media, presets
from pelicula.export import ExportJob, ExportSettings

pytestmark = [pytest.mark.gpu, pytest.mark.ffmpeg]


@pytest.fixture
def film():
    return presets.builtin_values("vision3_500t")  # grão, halação, bloom, cópia


def x264(**over) -> ExportSettings:
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=18, preset="ultrafast",
                       audio="aac192", tune_grain=True)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def ffv1(**over) -> ExportSettings:
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="pcm24", dither=False)
    for k, v in over.items():
        setattr(s, k, v)
    return s


class CancelAfter:
    """Engine que pede o cancelamento do trabalho depois de N quadros renderizados."""

    def __init__(self, engine, job, n):
        self.engine, self.job, self.n, self.count = engine, job, n, 0

    def set_input(self, img):
        self.engine.set_input(img)

    def render(self, plan, depth=8):
        out = self.engine.render(plan, depth)
        self.count += 1
        if self.count >= self.n:
            self.job.cancel.set()
        return out


def test_export_x264_mp4_with_audio(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "saida.mp4"
    s = x264()
    job = ExportJob(info=sample_info, values=film, settings=s, out_path=str(out), start_frame=0, end_frame=11)
    assert export.job_frames(sample_info, s, 0, 11) == 12
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert job.done == job.total == 12 and job.progress == 1.0
    assert job.started > 0 and job.fps_rate > 0
    i = media.probe(str(out))
    assert i.codec == "h264" and i.pix_fmt == "yuv420p"
    assert (i.width, i.height) == (SAMPLE_W, SAMPLE_H)
    assert i.frames == 12
    assert i.has_audio and i.audio_codec == "aac"
    assert i.color_space == "bt709"
    assert i.duration == pytest.approx(0.5, abs=0.08)


def test_export_whole_clip_with_resize_and_fps_change(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "metade.mkv"
    s = x264(container="mkv", resolution="90", fps="12", audio="none")
    job = ExportJob(info=sample_info, values=film, settings=s, out_path=str(out))
    expected = export.job_frames(sample_info, s)
    assert expected == SAMPLE_FRAMES // 2
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    i = media.probe(str(out))
    assert (i.width, i.height) == (160, 90)
    assert i.fps == pytest.approx(12.0)
    assert i.frames == expected == job.done
    assert not i.has_audio


def test_export_ffv1_is_bit_exact_with_direct_render(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    """O FFV1 16 bits guarda exatamente o que o motor renderiza (sem dither)."""
    out = tmp_path / "mestre.mkv"
    start, end = 4, 15
    job = ExportJob(info=sample_info, values=film, settings=ffv1(), out_path=str(out), start_frame=start,
                    end_frame=end)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    n = end - start + 1
    assert job.done == n

    i = media.probe(str(out))
    assert i.codec == "ffv1" and i.has_audio and i.audio_codec == "pcm_s24le"
    decoded = read_all(media.FrameReader(i, SAMPLE_W, SAMPLE_H, 16))
    assert len(decoded) == n

    src = read_all(media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 16, start, n, hq=True))
    assert len(src) == n
    for k in range(n):
        gl_engine.set_input(src[k])
        plan = look.build_plan(film, SAMPLE_W, SAMPLE_H, start + k, sample_info.fps, None, dither=False)
        ref = gl_engine.render(plan, 16)
        assert decoded[k].dtype == np.uint16
        assert np.array_equal(decoded[k], ref), f"quadro {start + k} difere"
    # e o look de fato foi aplicado
    assert np.abs(decoded[0].astype(np.int64) - src[0].astype(np.int64)).mean() > 500


def test_export_png_sequence(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "quadros.png"
    s = ExportSettings(codec="png_seq", container="png", pix="rgb48be", audio="none", dither=False)
    job = ExportJob(info=sample_info, values=film, settings=s, out_path=str(out), start_frame=20, end_frame=-1)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    files = sorted((tmp_path / "quadros").glob("quadros_*.png"))
    assert [f.name for f in files] == [f"quadros_{k:06d}.png" for k in range(1, 5)]
    i = media.probe(str(files[0]))
    assert i.is_image and i.pix_fmt == "rgb48be"


def test_export_image_to_png_and_jpg(gl_engine, ffmpeg_ok, sample_image, tmp_path, film):
    info = media.probe(sample_image)
    for pid, _label, s in export.quality_presets(info):
        if pid not in ("img_png", "img_jpg"):
            continue
        out = tmp_path / f"foto.{s.container}"
        job = ExportJob(info=info, values=film, settings=s, out_path=str(out))
        export.run_job(job, gl_engine)
        assert job.status == "concluido", f"{pid}: {job.error}"
        assert job.total == job.done == 1
        o = media.probe(str(out))
        assert o.is_image and (o.width, o.height) == (SAMPLE_W, SAMPLE_H)


def test_cancel_leaves_no_partial_file(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "cancelado.mp4"
    job = ExportJob(info=sample_info, values=film, settings=x264(), out_path=str(out))
    export.run_job(job, CancelAfter(gl_engine, job, 3))
    assert job.status == "cancelado"
    assert job.done == 3 < job.total == SAMPLE_FRAMES
    assert not out.exists()
    assert [f for f in tmp_path.iterdir() if f.name != "appdata"] == []


def test_cancel_before_start(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "nunca.mkv"
    job = ExportJob(info=sample_info, values=film, settings=ffv1(audio="none"), out_path=str(out))
    job.cancel.set()
    export.run_job(job, gl_engine)
    assert job.status == "cancelado" and job.done == 0
    assert not out.exists()


def test_bad_encoder_settings_report_error(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "erro.mp4"
    s = x264(audio="none", preset="nao_existe")
    job = ExportJob(info=sample_info, values=film, settings=s, out_path=str(out), end_frame=5)
    export.run_job(job, gl_engine)
    assert job.status == "erro"
    assert job.error


def test_export_queue_runs_jobs_in_order(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    q = export.ExportQueue()
    skipped = ExportJob(info=sample_info, values=film, settings=x264(audio="none"), out_path=str(tmp_path / "a.mp4"))
    skipped.cancel.set()
    real = ExportJob(info=sample_info, values=film, settings=x264(audio="none"), out_path=str(tmp_path / "b.mp4"),
                     end_frame=5, name="b")
    q.add(skipped)
    q.add(real)
    assert q.busy
    t_end = time.time() + 60
    while real.status in ("aguardando", "exportando") and time.time() < t_end:
        time.sleep(0.05)
    assert skipped.status == "cancelado"
    assert real.status == "concluido", real.error
    assert real.finished >= real.started > 0
    assert not (tmp_path / "a.mp4").exists()
    assert media.probe(str(tmp_path / "b.mp4")).frames == 6
    assert not q.busy
    q.remove_finished()
    assert q.jobs == []


def test_measure_speed_in_worker_thread(gl_engine, ffmpeg_ok, sample_info, tmp_path, film, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    result = {}

    def work(cancel):
        result["fps"] = export.measure_speed(sample_info, film, x264(), cancel, frames=12)

    # Um contexto OpenGL por thread: a medição cria o seu próprio Engine numa thread separada.
    t = threading.Thread(target=work, args=(threading.Event(),))
    t.start()
    t.join(60)
    assert not t.is_alive()
    assert result["fps"] > 0
    assert not list(Path(tmp_path).glob("pelicula_medida_*"))

    cancelled = threading.Event()
    cancelled.set()
    t = threading.Thread(target=work, args=(cancelled,))
    t.start()
    t.join(60)
    assert result["fps"] == 0.0
