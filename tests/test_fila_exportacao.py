"""Fila de exportação (#59): um trabalho novo não mexe no que está rodando; o mesmo destino é reconhecido."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from pelicula import export, media
from pelicula.export import ExportJob, ExportSettings


def info(path: str) -> media.MediaInfo:
    return media.MediaInfo(path=path, width=320, height=180, fps=24.0, fps_str="24/1", frames=24, duration=1.0,
                           pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="", bitrate=0, color_space="bt709",
                           color_range="tv", color_transfer="bt709", color_primaries="bt709", has_audio=False,
                           audio_codec="", container="mp4", is_image=False)


def job(out, status: str = "aguardando", settings: ExportSettings | None = None) -> ExportJob:
    j = ExportJob(info=info("fonte.mp4"), values={}, settings=settings or ExportSettings(), out_path=str(out))
    j.status = status
    return j


def test_new_job_waits_and_the_running_one_keeps_going(monkeypatch, tmp_path):
    """O que parecia "recomeçar": o 2º trabalho (mesmo destino sugerido) entra depois que o 1º termina. Pôr um trabalho
    na fila não cancela nem reinicia o que está rodando."""
    started, release = threading.Event(), threading.Event()
    order: list[str] = []

    def fake_run(j: ExportJob, _engine) -> None:
        j.status = "exportando"
        j.total = 100
        order.append(j.out_path)
        if len(order) == 1:
            j.done = 40
            started.set()
            assert release.wait(30)
            j.done += 60
        else:
            j.done = 100
        j.status = "concluido"

    monkeypatch.setattr(export, "Engine", lambda: object())
    monkeypatch.setattr(export, "run_job", fake_run)
    q = export.ExportQueue()
    first, second = job(tmp_path / "a.mp4"), job(tmp_path / "a.mp4")
    q.add(first)
    assert started.wait(30)
    progress = first.progress
    q.add(second)
    assert first.status == "exportando" and not first.cancel.is_set() and first.progress == progress
    assert second.status == "aguardando" and q.busy
    release.set()
    for _ in range(600):
        if not q.busy:
            break
        threading.Event().wait(0.05)
    assert not q.busy and first.progress == 1.0 and order == [first.out_path, second.out_path]


def test_queue_clash_only_with_jobs_that_will_still_write(tmp_path):
    out = tmp_path / "video.mp4"
    s = ExportSettings()
    assert not export.queue_clash(str(out), s, [])
    assert export.queue_clash(str(out), s, [job(out, "exportando")])
    assert export.queue_clash(str(out), s, [job(out, "aguardando")])
    for status in ("concluido", "erro", "cancelado"):
        assert not export.queue_clash(str(out), s, [job(out, status)])
    assert not export.queue_clash(str(tmp_path / "outro.mp4"), s, [job(out, "exportando")])
    assert export.queue_clash(str(tmp_path / "." / "video.mp4"), s, [job(out, "exportando")])  # o mesmo caminho


def test_queue_clash_on_image_sequences_is_the_folder(tmp_path):
    s = ExportSettings(codec="png_seq", container="png")
    assert export.is_sequence(s)
    folder = tmp_path / "quadros.png"
    running = job(folder, "exportando", s)
    assert export.queue_clash(str(folder), s, [running])
    assert not export.queue_clash(str(tmp_path / "outros.png"), s, [running])


def test_free_output_skips_the_queue_and_the_disk(tmp_path):
    out = tmp_path / "video.mp4"
    s = ExportSettings()
    assert Path(export.free_output(str(out), s, [])).name == "video_2.mp4"
    assert Path(export.free_output(str(out), s, [job(tmp_path / "video_2.mp4", "exportando")])).name == "video_3.mp4"
    (tmp_path / "video_2.mp4").write_bytes(b"x")
    (tmp_path / "video_3.mp4").write_bytes(b"x")
    assert Path(export.free_output(str(out), s, [])).name == "video_4.mp4"


@pytest.mark.parametrize("status", ["aguardando", "exportando"])
def test_busy_counts_the_jobs_that_are_not_finished(status, tmp_path):
    q = export.ExportQueue()
    q.jobs.append(job(tmp_path / "a.mp4", status))
    assert q.busy
    q.jobs[0].status = "concluido"
    assert not q.busy
