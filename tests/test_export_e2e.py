"""Exportação de ponta a ponta (GPU + ffmpeg): run_job, fila, cancelamento e medição de velocidade."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from helpers import SAMPLE_FRAMES, SAMPLE_H, SAMPLE_W, read_all
from pelicula import export, look, media, presets, system
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


class Watch:
    """Engine que chama `fn(n)` depois de cada quadro (para olhar o disco no meio da exportação);
    com `fail_at`, a GPU "falha" nesse quadro."""

    def __init__(self, engine, fn=None, fail_at=0):
        self.engine, self.fn, self.fail_at, self.count = engine, fn, fail_at, 0

    def set_input(self, img):
        self.engine.set_input(img)

    def render(self, plan, depth=8):
        self.count += 1
        if self.count == self.fail_at:
            raise RuntimeError("falha simulada na GPU")
        out = self.engine.render(plan, depth)
        if self.fn:
            self.fn(self.count)
        return out


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name != "appdata")


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
    assert names(tmp_path) == ["quadros"]  # a pasta parcial virou a pasta final


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


# ------------------------------------------------------------------ gravação segura
def test_success_replaces_the_old_file_only_at_the_end(gl_engine, ffmpeg_ok, sample_info, tmp_path, film,
                                                       monkeypatch):
    out = tmp_path / "saida.mp4"
    out.write_bytes(b"video antigo")
    part = tmp_path / "saida.parcial-pelicula.mp4"
    part.write_bytes(b"sobra de uma exportacao que o app fechou no meio")
    swaps, real = [], system.replace_file
    monkeypatch.setattr(system, "replace_file", lambda a, b, **k: (swaps.append((Path(a), Path(b))), real(a, b, **k)))
    during = []
    job = ExportJob(info=sample_info, values=film, settings=x264(audio="none"), out_path=str(out), end_frame=11)
    export.run_job(job, Watch(gl_engine, lambda n: during.append(out.read_bytes())))
    assert job.status == "concluido", job.error
    assert len(during) == 12 and set(during) == {b"video antigo"}  # o antigo ficou intacto o tempo todo
    assert swaps == [(part, out)]  # o ffmpeg gravou no parcial, que só no fim tomou o lugar do antigo
    assert media.probe(str(out)).frames == 12
    assert names(tmp_path) == ["saida.mp4"]


def test_cancel_keeps_the_old_file_and_removes_the_partial(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "cancelado.mp4"
    out.write_bytes(b"video antigo")
    (tmp_path / "cancelado.parcial-pelicula.mp4").write_bytes(b"sobra")
    job = ExportJob(info=sample_info, values=film, settings=x264(), out_path=str(out))
    export.run_job(job, CancelAfter(gl_engine, job, 3))
    assert job.status == "cancelado"
    assert out.read_bytes() == b"video antigo"
    assert names(tmp_path) == ["cancelado.mp4"]


def test_encoder_error_keeps_the_old_file_and_removes_the_partial(gl_engine, ffmpeg_ok, sample_info, tmp_path,
                                                                  film):
    out = tmp_path / "erro.mp4"
    out.write_bytes(b"video antigo")
    job = ExportJob(info=sample_info, values=film, settings=x264(audio="none", preset="nao_existe"),
                    out_path=str(out), end_frame=5)
    export.run_job(job, gl_engine)
    assert job.status == "erro" and job.error
    assert out.read_bytes() == b"video antigo"
    assert names(tmp_path) == ["erro.mp4"]


def test_failure_in_the_middle_never_leaves_a_broken_file(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    """Uma falha no meio (aqui, na GPU) não deixa vídeo pela metade com o nome final nem apaga o antigo."""
    out = tmp_path / "meio.mp4"
    out.write_bytes(b"video antigo")
    job = ExportJob(info=sample_info, values=film, settings=x264(audio="none"), out_path=str(out))
    with pytest.raises(RuntimeError, match="falha simulada"):
        export.run_job(job, Watch(gl_engine, fail_at=5))
    assert out.read_bytes() == b"video antigo"
    assert names(tmp_path) == ["meio.mp4"]
    # sem arquivo antigo: nada fica com o nome final
    new = tmp_path / "novo.mp4"
    job = ExportJob(info=sample_info, values=film, settings=x264(audio="none"), out_path=str(new))
    with pytest.raises(RuntimeError):
        export.run_job(job, Watch(gl_engine, fail_at=5))
    assert names(tmp_path) == ["meio.mp4"]


def test_finished_result_is_kept_when_the_old_file_cannot_be_replaced(gl_engine, ffmpeg_ok, sample_info, tmp_path,
                                                                      film, monkeypatch):
    """Arquivo antigo preso (aberto num player): a exportação vira erro, mas o resultado não se perde."""
    out = tmp_path / "preso.mp4"
    out.write_bytes(b"video antigo")

    def busy(a, b, **k):
        raise PermissionError(13, "o arquivo está aberto em outro programa")

    monkeypatch.setattr(system, "replace_file", busy)
    job = ExportJob(info=sample_info, values=film, settings=x264(audio="none"), out_path=str(out), end_frame=5)
    export.run_job(job, gl_engine)
    assert job.status == "erro"
    part = tmp_path / "preso.parcial-pelicula.mp4"
    assert str(part) in job.error and "outro programa" in job.error
    assert out.read_bytes() == b"video antigo"
    assert media.probe(str(part)).frames == 6  # o resultado completo ficou no parcial


def test_image_export_replaces_the_old_file(gl_engine, ffmpeg_ok, sample_image, tmp_path, film):
    info = media.probe(sample_image)
    s = {pid: st for pid, _label, st in export.quality_presets(info)}["img_jpg"]
    out = tmp_path / "foto.jpg"
    out.write_bytes(b"foto antiga")
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out))
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    assert media.probe(str(out)).is_image
    assert names(tmp_path) == ["foto.jpg"]


def png_seq(**over) -> ExportSettings:
    s = ExportSettings(codec="png_seq", container="png", pix="rgb24", audio="none", dither=False)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_sequence_replaces_old_frames_only_at_the_end(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "quadros.png"
    folder = tmp_path / "quadros"
    folder.mkdir()
    for k in range(1, 9):  # uma exportação anterior, mais longa
        (folder / f"quadros_{k:06d}.png").write_bytes(b"velho")
    (folder / "leia-me.txt").write_text("da pessoa")
    before = sorted((p.name, p.read_bytes()) for p in folder.iterdir())
    during = []
    job = ExportJob(info=sample_info, values=film, settings=png_seq(), out_path=str(out), start_frame=20)
    export.run_job(job, Watch(gl_engine, lambda n: during.append(sorted((p.name, p.read_bytes())
                                                                          for p in folder.iterdir()))))
    assert job.status == "concluido", job.error
    assert during and all(snap == before for snap in during)  # quadros antigos intactos até o fim
    assert names(folder) == ["leia-me.txt"] + [f"quadros_{k:06d}.png" for k in range(1, 5)]
    assert media.probe(str(folder / "quadros_000004.png")).is_image
    assert names(tmp_path) == ["quadros"]


def test_sequence_cancel_keeps_old_frames(gl_engine, ffmpeg_ok, sample_info, tmp_path, film):
    out = tmp_path / "quadros.png"
    folder = tmp_path / "quadros"
    folder.mkdir()
    for k in range(1, 4):
        (folder / f"quadros_{k:06d}.png").write_bytes(b"velho")
    job = ExportJob(info=sample_info, values=film, settings=png_seq(), out_path=str(out))
    export.run_job(job, CancelAfter(gl_engine, job, 2))
    assert job.status == "cancelado"
    assert [(folder / n).read_bytes() for n in names(folder)] == [b"velho"] * 3
    assert names(tmp_path) == ["quadros"]


# ------------------------------------------------------------------ vídeo vertical
def test_vertical_video_keeps_its_orientation(gl_engine, ffmpeg_ok, sample_vertical_video, tmp_path, film):
    """Regressão (issue #35): a resolução vale para o lado menor; vertical continua vertical."""
    info = media.probe(sample_vertical_video)
    assert (info.width, info.height) == (SAMPLE_H, SAMPLE_W)
    social = {pid: st for pid, _label, st in export.quality_presets(info)}["social"]
    social.preset, social.audio = "ultrafast", "none"
    for res, size in (("original", (180, 320)), ("90", (90, 160)), (social.resolution, (1080, 1920))):
        s = ExportSettings.from_dict({**social.to_dict(), "resolution": res})
        out = tmp_path / f"vertical_{res}.mp4"
        job = ExportJob(info=info, values=film, settings=s, out_path=str(out), end_frame=3)
        export.run_job(job, gl_engine)
        assert job.status == "concluido", job.error
        o = media.probe(str(out))
        assert (o.width, o.height) == size and o.frames == 4


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
