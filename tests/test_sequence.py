"""Decodificação de sequências (sequence.py) e exportação de uma edição de ponta a ponta."""

from __future__ import annotations

import subprocess
import threading

import numpy as np
import pytest

from helpers import SAMPLE_FPS, SAMPLE_H, SAMPLE_W, read_all
from pelicula import export, look, media, presets, sequence
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings


# ------------------------------------------------------------------ tamanhos (sem ffmpeg)
def test_canvas_size():
    seq = tl.Sequence(width=1920, height=1080)
    assert sequence.canvas_size(seq) == (1920, 1080)
    assert sequence.canvas_size(seq, 2160) == (1920, 1080)
    assert sequence.canvas_size(seq, 720) == (1280, 720)
    w, h = sequence.canvas_size(tl.Sequence(width=1080, height=1350), 541)
    assert w % 2 == 0 and h % 2 == 0 and h == 540


def test_decode_size_fits_box_and_never_upscales():
    seq = tl.Sequence(width=1920, height=1080)
    big, = seq.insert_media(tl.Source("4k.png", 3840, 2160, is_image=True))
    assert sequence.decode_size(seq, big, 1920, 1080) == (1920, 1080)
    assert sequence.decode_size(seq, big, 960, 540) == (960, 540)
    seq.set_values(big.id, {**big.values, "escala": 1.5})
    assert sequence.decode_size(seq, big, 1920, 1080) == (2880, 1620)
    small, = seq.insert_media(tl.Source("sd.png", 640, 480, is_image=True))
    assert sequence.decode_size(seq, small, 1920, 1080) == (640, 480)


def test_media_info_of_a_sequence(make_info):
    seq = tl.Sequence(width=1280, height=720, fps_str="25/1", name="")
    s = tl.Source.from_info(make_info(path="C:/v/filme.mov", width=1280, height=720, fps=25.0, fps_str="25/1",
                                      frames=50, codec="prores", profile="HQ", pix_fmt="yuv422p10le", bit_depth=10))
    seq.insert_media(s)
    info = sequence.media_info(seq)
    assert info.path.replace("\\", "/").endswith("/v/filme_edicao.mov")
    assert (info.width, info.height, info.fps, info.frames, info.codec, info.bit_depth) == (1280, 720, 25.0, 50,
                                                                                            "prores", 10)
    assert info.has_audio and info.audio_codec == "pcm_s24le" and not info.is_image
    assert export.quality_presets(info)[0][0] == "original"
    assert export.job_frames(info, ExportSettings(), 0, -1) == 50


# ------------------------------------------------------------------ com ffmpeg
@pytest.fixture(scope="module")
def second_video(ffmpeg_ok, tmp_path_factory) -> str:
    """1 s, 320x180, 24 fps, barras de cor + seno de 880 Hz (diferente da amostra)."""
    out = tmp_path_factory.mktemp("video2") / "barras.mp4"
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-nostdin",
           "-f", "lavfi", "-i", f"smptebars=size={SAMPLE_W}x{SAMPLE_H}:rate={SAMPLE_FPS}:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", str(out)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        pytest.skip("não foi possível gerar o segundo vídeo")
    return str(out)


@pytest.fixture(scope="module")
def tone_wav(ffmpeg_ok, tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("som") / "tom.wav"
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=2",
           "-c:a", "pcm_s16le", str(out)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        pytest.skip("não foi possível gerar o som")
    return str(out)


@pytest.mark.ffmpeg
def test_probe_source_video_image_audio(ffmpeg_ok, sample_video, sample_image, tone_wav):
    v = media.probe_source(sample_video)
    assert v.has_video and v.has_audio and v.frames == 24 and v.fps == 24.0
    i = media.probe_source(sample_image)
    assert i.is_image and i.has_video and not i.has_audio
    a = media.probe_source(tone_wav)
    assert not a.has_video and a.has_audio and a.duration == pytest.approx(2.0, abs=0.01)
    assert ".wav" in media.AUDIO_EXT and ".mp3" in media.AUDIO_EXT


def edit(sample_video, second_video, image=None) -> tl.Sequence:
    """Amostra (quadros 0–11), barras a 2× (12 quadros), amostra em câmera lenta 0,5× e uma imagem por cima."""
    a = media.probe_source(sample_video)
    b = media.probe_source(second_video)
    seq = tl.Sequence.for_source(a)
    v = [c for c in seq.clips if c.kind == tl.VIDEO][0]
    seq.trim_end(v.id, 12)
    vb = [c for c in seq.insert_media(b) if c.kind == tl.VIDEO][0]
    seq.set_speed(vb.id, 2.0)
    slow = [c for c in seq.insert_media(a) if c.kind == tl.VIDEO][0]
    seq.trim_start(slow.id, slow.start + 6)
    seq.move(slow.id, seq.duration - 0)
    seq.set_speed(slow.id, 0.5)
    seq.close_gaps(tl.VIDEO, 0)
    seq.close_gaps(tl.AUDIO, 0)
    if image:
        img = media.probe_source(image)
        top, = seq.insert_media(img, at=4, vtrack=1)
        seq.trim_end(top.id, 10)
        seq.set_values(top.id, {**top.values, "escala": 0.4, "pos_x": 0.25, "opacidade": 0.8,
                                "entrada_tipo": "dissolver", "entrada_dur": 0.1})
    return seq


@pytest.mark.ffmpeg
def test_reader_matches_random_access(ffmpeg_ok, sample_video, second_video, sample_image):
    seq = edit(sample_video, second_video, sample_image)
    assert seq.duration == 12 + 12 + 36
    w, h = sequence.canvas_size(seq, 120)
    sequence.clear_cache()
    reader = sequence.SequenceReader(seq, w, h, 8)
    got = []
    try:
        while True:
            fl = reader.read()
            if fl is None:
                break
            got.append(fl)
    finally:
        reader.close()
    assert [f.frame for f in got] == list(range(seq.duration))
    for fl in got:
        ref = sequence.grab(seq, fl.frame, w, h, 8)
        assert [l.layer.clip.id for l in fl.layers] == [l.layer.clip.id for l in ref.layers]
        for x, y in zip(fl.layers, ref.layers):
            assert x.layer.src_frame == y.layer.src_frame
            assert np.array_equal(x.image, y.image), f"quadro {fl.frame}, clipe {x.layer.clip.src}"
    # câmera lenta: cada quadro do arquivo aparece duas vezes
    slow = [c for c in seq.clips if c.kind == tl.VIDEO and c.speed == 0.5][0]
    frames = [seq.src_frame(slow, t) for t in range(slow.start, slow.end)]
    assert frames[:4] == [6, 6, 7, 7]


@pytest.mark.ffmpeg
def test_reader_with_fps_out_and_range(ffmpeg_ok, sample_video, second_video):
    seq = edit(sample_video, second_video)
    r = sequence.SequenceReader(seq, 160, 90, 8, start=6, count=10, fps_out="12")
    frames = []
    try:
        while (fl := r.read()) is not None:
            frames.append(fl.frame)
    finally:
        r.close()
    assert frames == [6 + 2 * i for i in range(10)]


@pytest.fixture
def film():
    return presets.builtin_values("vision3_500t")


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_edit_ffv1_is_bit_exact_with_preview(gl_engine, ffmpeg_ok, sample_video, second_video, sample_image,
                                                   tmp_path, film):
    seq = edit(sample_video, second_video, sample_image)
    c = [c for c in seq.clips if c.kind == tl.VIDEO and c.src == second_video][0]
    seq.set_values(c.id, {**c.values, "exposicao": 0.7, "saturacao": -0.4, "nitidez": 0.4})
    info = sequence.media_info(seq)
    out = tmp_path / "edicao.mkv"
    s = ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="pcm24", dither=False)
    start, end = 8, 30
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out), start_frame=start, end_frame=end,
                    sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    n = end - start + 1
    assert job.done == n
    i = media.probe(str(out))
    assert i.has_audio and i.audio_codec == "pcm_s24le"
    assert i.duration == pytest.approx(n / 24, abs=0.05)
    decoded = read_all(media.FrameReader(i, SAMPLE_W, SAMPLE_H, 16))
    assert len(decoded) == n
    for k in range(n):
        f = start + k
        img = gl_engine.compose(sequence.grab(seq, f, SAMPLE_W, SAMPLE_H, 16, hq=True), seq, SAMPLE_W, SAMPLE_H, 16)
        gl_engine.set_input(img)
        ref = gl_engine.render(look.build_plan(film, SAMPLE_W, SAMPLE_H, f, 24.0, None, dither=False), 16)
        assert np.array_equal(decoded[k], ref), f"quadro {f} difere"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_edit_mp4_with_fps_change_and_no_audio_track(gl_engine, ffmpeg_ok, sample_video, second_video,
                                                            tmp_path, film):
    seq = edit(sample_video, second_video)
    for t in seq.kind_tracks(tl.AUDIO):
        t.muted = True
    info = sequence.media_info(seq)
    assert not info.has_audio
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=20, preset="ultrafast", fps="12",
                       audio="aac192")
    out = tmp_path / "edicao12.mp4"
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out), sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    i = media.probe(str(out))
    assert i.frames == job.done == round(seq.duration / 24 * 12)
    assert not i.has_audio


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_edit_mixes_audio(gl_engine, ffmpeg_ok, sample_video, second_video, tone_wav, tmp_path, film):
    seq = edit(sample_video, second_video)
    seq.insert_media(media.probe_source(tone_wav), at=0, atrack=1)
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=20, preset="ultrafast", audio="aac192")
    out = tmp_path / "som.mp4"
    job = ExportJob(info=sequence.media_info(seq), values=film, settings=s, out_path=str(out), sequence=seq)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    i = media.probe(str(out))
    assert i.has_audio and i.audio_codec == "aac"
    assert i.duration == pytest.approx(seq.duration / 24, abs=0.1)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_measure_speed_with_sequence(ffmpeg_ok, sample_video, second_video, film):
    seq = edit(sample_video, second_video)
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", quality=23, preset="ultrafast")
    out: list[float] = []

    def run():
        out.append(export.measure_speed(sequence.media_info(seq), film, s, threading.Event(), frames=20,
                                        sequence=seq))

    th = threading.Thread(target=run)
    th.start()
    th.join(120)
    assert out and out[0] > 0
