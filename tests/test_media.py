"""Leitura de mídia com o ffmpeg: probe, FrameReader, grab_frame, codificadores."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import helpers
from helpers import SAMPLE_FPS, SAMPLE_FRAMES, SAMPLE_H, SAMPLE_W, read_all
from pelicula import media


# ------------------------------------------------------------------ sem ffmpeg
@pytest.mark.parametrize("pix, raw, expected", [
    ("yuv420p", None, 8), ("yuv420p10le", None, 10), ("yuv422p10be", None, 10), ("p010le", None, 10),
    ("yuv444p12le", None, 12), ("gray16le", None, 16), ("yuv444p16le", None, 16), ("gbrp16le", None, 16),
    ("rgb24", None, 8), ("", "10", 10), ("", "abc", 8), ("", "4", 8), ("pal8", None, 8),
    ("rgb48le", None, 16),
    ("rgb48be", None, 16),
    ("rgba64le", None, 16),
])
def test_depth_from_pix_fmt(pix, raw, expected):
    assert media._depth(pix, raw) == expected


@pytest.mark.parametrize("over, matrix, rng", [
    (dict(color_space="bt709"), "bt709", "limited"),
    (dict(color_space="bt470bg"), "bt601", "limited"),
    (dict(color_space="smpte170m"), "bt601", "limited"),
    (dict(color_space="bt2020nc"), "bt2020", "limited"),
    (dict(color_space="smpte240m"), "smpte240m", "limited"),
    (dict(color_space="", height=1080), "bt709", "limited"),
    (dict(color_space="", height=480), "bt601", "limited"),
    (dict(color_range="pc"), "bt709", "full"),
    (dict(pix_fmt="yuvj420p", color_range=""), "bt709", "full"),
    (dict(pix_fmt="rgb24", color_range=""), "bt709", "auto"),
    (dict(pix_fmt="p010le", color_range=""), "bt709", "limited"),
])
def test_input_matrix_and_range(make_info, over, matrix, rng):
    info = make_info(**over)
    assert media._in_matrix(info) == matrix
    assert media._in_range(info) == rng


def test_mediainfo_summary_and_ext(make_info):
    v = make_info(path="C:/X/Clip.MOV", codec="prores", pix_fmt="yuv422p10le", bit_depth=10, bitrate=150_000_000)
    assert v.ext == ".mov"
    s = v.summary()
    assert "1920×1080" in s and "PRORES" in s and "10 bits" in s and "150 Mb/s" in s
    img = make_info(path="a.png", is_image=True, codec="png", bit_depth=8)
    assert "imagem PNG" in img.summary() and "8 bits" in img.summary()


@pytest.mark.skipif(sys.platform != "win32", reason="prioridade de processo do Windows")
def test_perf_flags_windows():
    assert media.Perf().flags() == media.NO_WINDOW
    assert media.Perf(priority="baixa").flags() == media.NO_WINDOW | 0x00004000
    assert media.Perf(priority="alta").flags() == media.NO_WINDOW | 0x00008000
    assert media.Perf(priority="xyz").flags() == media.NO_WINDOW
    assert media.Perf(priority="baixa").popen_kwargs() == {"creationflags": media.NO_WINDOW | 0x00004000}


# ------------------------------------------------------------------ cenários que já travaram
# Rodam em processos filhos, todos ao mesmo tempo, com prazo: se o código voltar a travar
# (por exemplo, o pipe nomeado esperando um ffmpeg que morreu), o filho é encerrado e o
# teste falha sem travar a suíte.


def _check_isolated(runs, name):
    finished, res, out = runs.result(name)
    assert finished, f"travou (encerrado depois de {helpers.HANG_DEADLINE:.0f} s): {out[-800:]}"
    assert res is not None, out[-800:]
    assert res["ok"], res["detail"]
    return res


@pytest.mark.skipif(sys.platform != "win32", reason="pipes nomeados só no Windows")
def test_named_pipe_name_and_double_close():
    p = media.NamedPipe(inbound=True)
    assert p.name.startswith("\\\\.\\pipe\\pelicula_")
    p.close()
    assert p.handle is None
    p.close()  # fechar de novo não quebra


@pytest.mark.skipif(sys.platform != "win32", reason="pipes nomeados só no Windows")
def test_named_pipe_keeps_the_data_when_the_writer_finished_before_connect():
    """Um quadro pequeno cabe no buffer do pipe: o ffmpeg pode abrir, gravar tudo e fechar antes de o app chamar
    ConnectNamedPipe (erro 232 do Windows). Os dados continuam no pipe e não podem virar "Falha ao ler o quadro"."""
    p = media.NamedPipe(inbound=True)
    code = f"f = open({p.name!r}, 'wb'); f.write(b'x' * 270000); f.close()"
    proc = subprocess.Popen([sys.executable, "-c", code])
    proc.wait(timeout=30)
    f = p.connect(proc, timeout=20)
    data = b""
    while chunk := f.read(65536):
        data += chunk
    p.close()
    assert len(data) == 270000


@pytest.mark.parametrize("name", ["pipe_in", "pipe_out"])
def test_named_pipe_connect_fails_fast_when_process_dies(hang_runs, name):
    _check_isolated(hang_runs, name)


def test_named_pipe_connect_timeout(hang_runs):
    _check_isolated(hang_runs, "pipe_timeout")


@pytest.mark.ffmpeg
def test_frame_reader_bad_file_reports_error(ffmpeg_ok, hang_runs):
    _check_isolated(hang_runs, "reader_bad")


@pytest.mark.ffmpeg
def test_grab_frame_unreadable_file_raises(ffmpeg_ok, hang_runs):
    _check_isolated(hang_runs, "grab_bad")


@pytest.mark.ffmpeg
def test_configure_with_empty_folder_still_finds_tools(ffmpeg_ok, tmp_path):
    assert media.configure(str(tmp_path)) is True
    assert Path(media.ffmpeg()).is_file() and Path(media.ffprobe()).is_file()


# ------------------------------------------------------------------ ffmpeg
@pytest.mark.ffmpeg
def test_configure_and_tool_dir(ffmpeg_ok):
    assert media.configure() is True
    d = media.tool_dir()
    assert d and Path(d).is_dir()
    assert media.configure(d) is True
    assert Path(media.ffmpeg()).parent == Path(d)
    assert Path(media.ffprobe()).is_file()


@pytest.mark.ffmpeg
def test_probe_sample_video(sample_video, sample_info):
    i = sample_info
    assert (i.width, i.height) == (SAMPLE_W, SAMPLE_H)
    assert i.fps == pytest.approx(SAMPLE_FPS) and i.fps_str == "24/1"
    assert i.frames == SAMPLE_FRAMES
    assert i.duration == pytest.approx(1.0, abs=0.05)
    assert i.codec == "h264" and i.pix_fmt == "yuv420p" and i.bit_depth == 8
    assert i.has_audio and i.audio_codec == "aac"
    assert "mp4" in i.container and not i.is_image
    assert i.ext == ".mp4" and i.path == sample_video
    assert f"{SAMPLE_W}×{SAMPLE_H}" in i.summary()


@pytest.mark.ffmpeg
def test_probe_image(ffmpeg_ok, sample_image):
    i = media.probe(sample_image)
    assert i.is_image
    assert (i.width, i.height) == (SAMPLE_W, SAMPLE_H)
    assert i.frames == 1 and i.duration == 0.0 and i.fps == 24.0
    assert i.codec == "png" and i.bit_depth == 8 and not i.has_audio
    assert "imagem" in i.summary()


@pytest.mark.ffmpeg
def test_probe_16bit_image_depth(ffmpeg_ok, sample_image16):
    i = media.probe(sample_image16)
    assert i.is_image and i.pix_fmt.startswith("rgb48")
    assert i.bit_depth == 16


@pytest.mark.ffmpeg
def test_probe_errors(ffmpeg_ok, tmp_path):
    with pytest.raises(RuntimeError):
        media.probe(str(tmp_path / "nao_existe.mp4"))
    txt = tmp_path / "texto.mp4"
    txt.write_text("não é vídeo", encoding="utf-8")
    with pytest.raises(RuntimeError):
        media.probe(str(txt))
    wav = tmp_path / "som.wav"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=0.2", str(wav)], check=True)
    with pytest.raises(RuntimeError, match="imagem de vídeo"):
        media.probe(str(wav))


@pytest.fixture(scope="module")
def all_frames8(sample_info):
    """Todos os quadros do vídeo de teste decodificados uma vez, em sequência."""
    return read_all(media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 8))


@pytest.mark.ffmpeg
def test_frame_reader_8bit_reads_every_frame(sample_info, all_frames8):
    r = media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 8)
    assert r.dtype == np.uint8 and r.frame_bytes == SAMPLE_W * SAMPLE_H * 3
    frames = read_all(r)
    assert len(frames) == SAMPLE_FRAMES
    assert all(np.array_equal(a, b) for a, b in zip(frames, all_frames8))  # decodificação determinística
    for f in frames:
        assert f.shape == (SAMPLE_H, SAMPLE_W, 3) and f.dtype == np.uint8
    # testsrc2 se move: quadros vizinhos são diferentes
    assert not np.array_equal(frames[0], frames[1])
    assert r.read() is None


@pytest.mark.ffmpeg
def test_frame_reader_16bit_matches_8bit(sample_info):
    f16 = read_all(media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 16, max_frames=3, hq=True))
    f8 = read_all(media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 8, max_frames=3, hq=True))
    assert len(f16) == len(f8) == 3
    assert f16[0].dtype == np.uint16 and f16[0].shape == (SAMPLE_H, SAMPLE_W, 3)
    assert f16[0].max() > 255
    diff = np.abs(f16[0].astype(np.float64) / 257.0 - f8[0])
    assert diff.max() <= 2.0 and diff.mean() < 0.5


@pytest.mark.ffmpeg
def test_frame_reader_start_and_count(sample_info, all_frames8):
    part = read_all(media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 8, start_frame=10, max_frames=5))
    assert len(part) == 5
    for k, f in enumerate(part):
        assert np.array_equal(f, all_frames8[10 + k]), f"quadro {10 + k}"


@pytest.mark.ffmpeg
def test_frame_reader_scales_and_changes_fps(sample_info):
    small = read_all(media.FrameReader(sample_info, 160, 90, 8, max_frames=2))
    assert len(small) == 2 and small[0].shape == (90, 160, 3)
    odd = read_all(media.FrameReader(sample_info, 161, 91, 16, max_frames=1))
    assert odd[0].shape == (91, 161, 3)
    half = read_all(media.FrameReader(sample_info, SAMPLE_W, SAMPLE_H, 8, fps_out="12"))
    assert len(half) == SAMPLE_FRAMES // 2


@pytest.mark.ffmpeg
def test_frame_reader_image(ffmpeg_ok, sample_image, test_rgb):
    info = media.probe(sample_image)
    frames = read_all(media.FrameReader(info, SAMPLE_W, SAMPLE_H, 8, start_frame=5))
    assert len(frames) == 1
    assert np.abs(frames[0].astype(int) - test_rgb).max() <= 1


@pytest.mark.ffmpeg
@pytest.mark.parametrize("frame", [0, 1, 12, SAMPLE_FRAMES - 1])
def test_grab_frame_matches_sequential_decode(sample_info, all_frames8, frame):
    g = media.grab_frame(sample_info, frame, SAMPLE_W, SAMPLE_H)
    assert g.shape == (SAMPLE_H, SAMPLE_W, 3) and g.flags.writeable
    assert np.array_equal(g, all_frames8[frame])


@pytest.mark.ffmpeg
def test_grab_frame_16bit_and_image(sample_info, sample_image):
    g = media.grab_frame(sample_info, 6, 160, 90, depth=16, hq=True)
    assert g.dtype == np.uint16 and g.shape == (90, 160, 3)
    img = media.grab_frame(media.probe(sample_image), 0, SAMPLE_W, SAMPLE_H)
    assert img.shape == (SAMPLE_H, SAMPLE_W, 3)


@pytest.mark.ffmpeg
def test_encoders_and_hwaccels(ffmpeg_ok):
    enc = media.encoders()
    assert {"libx264", "ffv1", "png", "aac"} <= enc
    assert media.encoders() is enc  # guardado em cache
    assert media.encoder_works("libx264") is True
    assert media.encoder_works("nao_existe_123") is False
    hw = media.hwaccels()
    assert isinstance(hw, list) and all(isinstance(h, str) and h and " " not in h for h in hw)


@pytest.mark.ffmpeg
def test_encoders_only_contains_names(ffmpeg_ok):
    assert all(n.replace("_", "").replace("-", "").isalnum() for n in media.encoders())


@pytest.mark.ffmpeg
def test_reset_cache(ffmpeg_ok):
    media.encoders()
    media.reset_cache()
    assert media._ENCODERS is None and media._WORKING == {}
    assert "libx264" in media.encoders()
