"""Os comandos montados por build_encoder_cmd funcionam de verdade no ffmpeg (sem GPU).

Cada codec recebe 3 quadros RGB crus de um arquivo e o resultado é conferido com o ffprobe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from pelicula import export, media
from pelicula.export import CODECS, ExportSettings

from helpers import SAMPLE_H, SAMPLE_W

pytestmark = pytest.mark.ffmpeg

EXPECTED_CODEC = {
    "x264": "h264", "x265": "hevc", "h264_nvenc": "h264", "hevc_nvenc": "hevc", "h264_qsv": "h264",
    "hevc_qsv": "hevc", "h264_amf": "h264", "hevc_amf": "hevc", "av1": "av1", "vp9": "vp9", "xvid": "mpeg4",
    "prores": "prores", "dnxhr": "dnxhd", "ffv1": "ffv1", "gif": "gif", "png_seq": "png", "tiff_seq": "tiff",
    "png": "png", "tiff": "tiff", "jpg": "mjpeg", "webp": "webp",
}
NFRAMES = 3


def fast_settings(key: str, **over) -> ExportSettings:
    c = CODECS[key]
    lo, hi = c.get("qrange", (0, 0))
    s = ExportSettings(codec=key, container=c["exts"][0], pix=c["pix"][0], quality=(lo + hi) // 2 or lo,
                       preset=(c.get("presets") or [""])[0], profile=(c.get("profiles") or [("", "")])[0][0],
                       audio="none", tune_grain=bool(c.get("grain")))
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture(scope="module")
def raw_inputs(tmp_path_factory, test_rgb):
    d = tmp_path_factory.mktemp("raw")
    frames8 = [np.roll(test_rgb, 7 * i, axis=1) for i in range(NFRAMES)]
    p8 = d / "q8.rgb"
    p16 = d / "q16.rgb"
    p8.write_bytes(b"".join(f.tobytes() for f in frames8))
    p16.write_bytes(b"".join((f.astype("<u2") * 257).tobytes() for f in frames8))
    return {8: str(p8), 16: str(p16)}


def run_encode(key, raw_inputs, out_dir: Path, make_info, info=None, start=0.0, **over):
    if key not in CODECS:
        pytest.skip(f"codec {key} não existe mais")
    if not export.available(key):
        pytest.skip(f"{CODECS[key]['enc']} não funciona nesta máquina")
    s = fast_settings(key, **over)
    depth = 16 if export.high_depth(s) else 8
    info = info or make_info(width=SAMPLE_W, height=SAMPLE_H, has_audio=False)
    out = str(out_dir / f"saida.{s.container}")
    target = export.sequence_path(out) if key.endswith("_seq") else out
    dur = NFRAMES / 24.0
    cmd = export.build_encoder_cmd(target, info, s, SAMPLE_W, SAMPLE_H, "24/1", depth, start, dur,
                                   input_path=raw_inputs[depth])
    res = subprocess.run(cmd, capture_output=True, timeout=120)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")[-2000:]
    if key.endswith("_seq"):
        files = sorted(Path(out).with_suffix("").glob(f"*.{s.container}"))
        assert len(files) == NFRAMES
        return s, str(files[0])
    assert Path(out).is_file() and Path(out).stat().st_size > 0
    return s, out


@pytest.mark.parametrize("key", list(EXPECTED_CODEC))
def test_every_codec_command_really_encodes(ffmpeg_ok, raw_inputs, tmp_path, make_info, key):
    s, out = run_encode(key, raw_inputs, tmp_path, make_info)
    i = media.probe(out)
    assert i.codec == EXPECTED_CODEC[key]
    assert (i.width, i.height) == (SAMPLE_W, SAMPLE_H)
    assert not i.has_audio
    if CODECS[key].get("image") or key.endswith("_seq"):
        assert i.is_image
    elif key != "gif":
        assert i.frames == NFRAMES
    if not s.pix.startswith(("rgb", "pal", "yuvj")) and key not in ("gif", "webp", "xvid", "dnxhr", "prores"):
        assert i.color_space == "bt709", key


@pytest.mark.parametrize("key, pix", [
    ("x264", "yuv444p"), ("x264", "yuv420p10le"), ("x265", "yuv420p10le"), ("x265", "yuv444p10le"),
    ("ffv1", "yuv444p16le"), ("png", "rgb24"), ("tiff", "rgb24"), ("prores", "yuv444p10le"),
    ("dnxhr", "yuv422p10le"),
])
def test_other_pixel_formats_encode(ffmpeg_ok, raw_inputs, tmp_path, make_info, key, pix):
    over = {"pix": pix}
    if key == "dnxhr":
        over["profile"] = "dnxhr_444" if "444" in pix else ("dnxhr_hqx" if "10" in pix else "dnxhr_hq")
    if key == "prores":
        over["profile"] = "4" if "444" in pix else "3"
    _, out = run_encode(key, raw_inputs, tmp_path, make_info, **over)
    i = media.probe(out)
    if key not in ("prores", "dnxhr"):  # esses decodificadores podem anunciar outro pix_fmt equivalente
        assert i.pix_fmt == pix
    assert (i.bit_depth > 8) == any(t in pix for t in ("10", "12", "16"))


def stream_times(path: str) -> dict[str, tuple[float, float]]:
    """{tipo: (início, duração)} de cada fluxo, lendo também a tag DURATION do MKV."""
    import json
    res = subprocess.run([media.ffprobe(), "-v", "error", "-show_entries",
                          "stream=codec_type,start_time,duration:stream_tags=DURATION", "-of", "json", path],
                         capture_output=True)
    out = {}
    for st in json.loads(res.stdout.decode("utf-8", "replace")).get("streams", []):
        dur = st.get("duration") or st.get("tags", {}).get("DURATION", "0")
        if ":" in str(dur):
            h, m, sec = str(dur).split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(sec)
        out.setdefault(st["codec_type"], (float(st.get("start_time") or 0.0), float(dur)))
    return out


@pytest.mark.parametrize("key, container, audio, expected, start", [
    ("x264", "mp4", "aac320", "aac", 0.25),
    ("x264", "mp4", "pcm24", "aac", 0.25),
    ("x264", "mp4", "copy", "aac", 0.25),
    ("x264", "mov", "pcm24", "pcm_s24le", 0.25),
    ("x264", "mkv", "copy", "aac", 0.0),
    ("x264", "mkv", "copy", "flac", 0.25),
    ("x264", "mkv", "aac192", "aac", 0.25),
    ("vp9", "webm", "copy", "opus", 0.25),
    ("xvid", "avi", "aac192", "mp3", 0.25),
    ("ffv1", "mkv", "pcm24", "pcm_s24le", 0.25),
])
def test_audio_is_muxed_and_trimmed(ffmpeg_ok, raw_inputs, tmp_path, sample_info, key, container, audio, expected,
                                    start):
    _, out = run_encode(key, raw_inputs, tmp_path, None, info=sample_info, start=start, container=container,
                        audio=audio)
    i = media.probe(out)
    assert i.has_audio and i.audio_codec == expected
    want = NFRAMES / 24.0
    assert i.duration == pytest.approx(want, abs=0.06)
    t = stream_times(out)
    assert abs(t["video"][0] - t["audio"][0]) < 0.03, f"áudio e vídeo começam em tempos diferentes: {t}"
    assert t["audio"][1] == pytest.approx(want, abs=0.06), t


def test_x264_bitrate_mode_encodes(ffmpeg_ok, raw_inputs, tmp_path, make_info):
    _, out = run_encode("x264", raw_inputs, tmp_path, make_info, bitrate=2.5, threads=2, preset="ultrafast")
    assert media.probe(out).codec == "h264"
