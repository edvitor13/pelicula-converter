"""Exportação: qualidades prontas, montagem do comando do ffmpeg e fila de trabalhos."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import look, media, system
from .engine import Engine, lut_info
from .i18n import _

X26_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
NV_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]

# ------------------------------------------------------------------ codecs
CODECS: dict[str, dict[str, Any]] = {
    "x264": dict(label="H.264 (CPU, x264)", enc="libx264", exts=["mp4", "mov", "mkv"],
                 pix=["yuv420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le", "yuv444p10le"],
                 rc="crf", qrange=(0, 51), presets=X26_PRESETS, grain=True),
    "x265": dict(label="H.265 / HEVC (CPU, x265)", enc="libx265", exts=["mp4", "mov", "mkv"],
                 pix=["yuv420p", "yuv420p10le", "yuv422p10le", "yuv444p10le", "yuv420p12le"],
                 rc="crf", qrange=(0, 51), presets=X26_PRESETS, grain=True),
    "h264_nvenc": dict(label="H.264 (GPU NVIDIA)", enc="h264_nvenc", exts=["mp4", "mov", "mkv"],
                       pix=["yuv420p", "yuv444p"], rc="cq", qrange=(0, 51), presets=NV_PRESETS, gpu=True),
    "hevc_nvenc": dict(label="H.265 / HEVC (GPU NVIDIA)", enc="hevc_nvenc", exts=["mp4", "mov", "mkv"],
                       pix=["yuv420p", "p010le", "yuv444p", "yuv444p16le"], rc="cq", qrange=(0, 51),
                       presets=NV_PRESETS, gpu=True),
    "h264_qsv": dict(label="H.264 (GPU Intel)", enc="h264_qsv", exts=["mp4", "mov", "mkv"], pix=["nv12"],
                     rc="gq", qrange=(1, 51), presets=["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]),
    "hevc_qsv": dict(label="H.265 (GPU Intel)", enc="hevc_qsv", exts=["mp4", "mov", "mkv"], pix=["nv12", "p010le"],
                     rc="gq", qrange=(1, 51), presets=["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]),
    "h264_amf": dict(label="H.264 (GPU AMD)", enc="h264_amf", exts=["mp4", "mov", "mkv"], pix=["yuv420p", "nv12"],
                     rc="qp", qrange=(0, 51), presets=["speed", "balanced", "quality"]),
    "hevc_amf": dict(label="H.265 (GPU AMD)", enc="hevc_amf", exts=["mp4", "mov", "mkv"], pix=["yuv420p", "nv12"],
                     rc="qp", qrange=(0, 51), presets=["speed", "balanced", "quality"]),
    "av1": dict(label="AV1 (CPU, SVT-AV1)", enc="libsvtav1", exts=["mp4", "mkv", "webm"], pix=["yuv420p", "yuv420p10le"],
                rc="crf", qrange=(0, 63), presets=[str(i) for i in range(13, -1, -1)]),
    "vp9": dict(label="VP9 (WebM)", enc="libvpx-vp9", exts=["webm", "mkv"], pix=["yuv420p", "yuv420p10le"],
                rc="crf", qrange=(0, 63), presets=[str(i) for i in range(8, -1, -1)]),
    "xvid": dict(label="MPEG-4 Xvid (AVI)", enc="libxvid", exts=["avi"], pix=["yuv420p"], rc="qscale", qrange=(1, 31)),
    "prores": dict(label="Apple ProRes", enc="prores_ks", exts=["mov"], pix=["yuv422p10le", "yuv444p10le"], rc="profile",
                   profiles=[("0", "Proxy"), ("1", "LT"), ("2", "422"), ("3", "422 HQ"), ("4", "4444"), ("5", "4444 XQ")]),
    "dnxhr": dict(label="Avid DNxHR", enc="dnxhd", exts=["mov", "mxf"], pix=["yuv422p", "yuv422p10le", "yuv444p10le"],
                  rc="profile", profiles=[("dnxhr_lb", "LB"), ("dnxhr_sq", "SQ"), ("dnxhr_hq", "HQ"),
                                          ("dnxhr_hqx", "HQX (10 bits)"), ("dnxhr_444", "444 (10 bits)")]),
    "ffv1": dict(label="FFV1 (sem perdas)", enc="ffv1", exts=["mkv"], pix=["rgb48le", "yuv444p16le", "yuv444p10le", "yuv420p"],
                 rc="none"),
    "gif": dict(label="GIF animado", enc="gif", exts=["gif"], pix=["pal8"], rc="none"),
    "png_seq": dict(label="Sequência PNG", enc="png", exts=["png"], pix=["rgb48be", "rgb24"], rc="none"),
    "tiff_seq": dict(label="Sequência TIFF", enc="tiff", exts=["tif"], pix=["rgb48le", "rgb24"], rc="none"),
    "png": dict(label="Imagem PNG", enc="png", exts=["png"], pix=["rgb48be", "rgb24"], rc="none", image=True),
    "tiff": dict(label="Imagem TIFF", enc="tiff", exts=["tif"], pix=["rgb48le", "rgb24"], rc="none", image=True),
    "jpg": dict(label="Imagem JPEG", enc="mjpeg", exts=["jpg"], pix=["yuvj444p"], rc="jpgq", qrange=(1, 31), image=True),
    "webp": dict(label="Imagem WebP", enc="libwebp", exts=["webp"], pix=["yuv420p"], rc="webpq", qrange=(0, 100), image=True),
}

# Os rótulos destas tabelas ficam em português e são traduzidos com _() onde aparecem
# (ui/export_dialog.py); tools/i18n_extract.py lê as tabelas para montar os catálogos.
AUDIO = [("copy", "Copiar original (sem recodificar)"), ("aac320", "AAC 320 kb/s"), ("aac192", "AAC 192 kb/s"),
         ("mp3", "MP3 320 kb/s"), ("opus", "Opus 192 kb/s"), ("pcm24", "PCM 24 bits (sem perdas)"),
         ("none", "Sem áudio")]

RESOLUTIONS = [("original", "Original"), ("4320", "8K (4320p)"), ("2160", "4K (2160p)"), ("1440", "1440p"),
               ("1080", "1080p"), ("720", "720p"), ("540", "540p"), ("480", "480p"), ("360", "360p")]

FPS = [("original", "Original"), ("12", "12"), ("15", "15"), ("24000/1001", "23,976"), ("24", "24"), ("25", "25"),
       ("30000/1001", "29,97"), ("30", "30"), ("50", "50"), ("60000/1001", "59,94"), ("60", "60")]

PRIORITIES = [("normal", "Normal"), ("baixa", "Baixa (dá para usar o PC enquanto exporta)"),
              ("alta", "Acima do normal (mais rápido)")]

HWACCEL_LABELS = {"none": "Desligada (processador)", "auto": "Automática", "cuda": "NVIDIA (CUDA)",
                  "d3d11va": "DirectX 11", "dxva2": "DirectX (DXVA2)", "qsv": "Intel Quick Sync"}


@dataclass
class ExportSettings:
    codec: str = "x264"
    container: str = "mp4"
    pix: str = "yuv420p"
    quality: float = 16
    preset: str = "slow"
    profile: str = ""
    bitrate: float = 0.0  # Mb/s; 0 = usar qualidade constante
    resolution: str = "original"
    fps: str = "original"
    audio: str = "copy"
    tune_grain: bool = True
    dither: bool = True
    threads: int = 0
    priority: str = "normal"
    hwaccel: str = "none"
    gpu: int = 0
    buffer: int = 4

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExportSettings":
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    def perf(self) -> media.Perf:
        return media.Perf(int(self.threads), self.priority, self.hwaccel, int(self.gpu), int(self.buffer))


pix_depth = media.pix_depth


def high_depth(s: ExportSettings) -> bool:
    return pix_depth(s.pix) > 8 or s.codec in ("prores", "ffv1")


def available(key: str) -> bool:
    c = CODECS[key]
    enc = c["enc"]
    if enc == "libxvid" and enc not in media.encoders():
        c["enc"] = enc = "mpeg4"
    if enc not in media.encoders():
        return False
    if any(t in enc for t in ("nvenc", "qsv", "amf")):
        return media.encoder_works(enc)
    return True


# ------------------------------------------------------------------ qualidades prontas
def _S(codec, container, pix, quality=0, preset="", profile="", bitrate=0.0, resolution="original", fps="original",
       audio="copy", tune_grain=False, dither=True) -> ExportSettings:
    return ExportSettings(codec, container, pix, quality, preset, profile, bitrate, resolution, fps, audio,
                          tune_grain, dither)


def _original(info: media.MediaInfo) -> ExportSettings:
    ext = info.ext.lstrip(".")
    deep = info.bit_depth > 8
    chroma = "444" if "444" in info.pix_fmt else "422" if "422" in info.pix_fmt else "420"
    if info.codec == "prores":
        prof = {"Proxy": "0", "LT": "1", "Standard": "2", "HQ": "3", "4444": "4", "4444 XQ": "5", "XQ": "5"}.get(info.profile, "3")
        return _S("prores", "mov", "yuv444p10le" if prof in ("4", "5") else "yuv422p10le", profile=prof)
    if info.codec == "dnxhd":
        return _S("dnxhr", "mov", "yuv422p10le" if deep else "yuv422p", profile="dnxhr_hqx" if deep else "dnxhr_hq")
    if info.codec == "vp9" and ext == "webm":
        return _S("vp9", "webm", "yuv420p10le" if deep else "yuv420p", 20, "2", audio="opus")
    if info.codec == "hevc" or deep:
        pix = {"420": "yuv420p10le", "422": "yuv422p10le", "444": "yuv444p10le"}[chroma] if deep else "yuv420p"
        return _S("x265", ext if ext in ("mp4", "mov", "mkv") else "mp4", pix, 14, "slow", tune_grain=True)
    pix = {"420": "yuv420p", "422": "yuv422p", "444": "yuv444p"}[chroma]
    return _S("x264", ext if ext in ("mp4", "mov", "mkv") else "mp4", pix, 13, "slow", tune_grain=True)


def quality_presets(info: media.MediaInfo | None) -> list[tuple[str, str, ExportSettings]]:
    if info is not None and info.is_image:
        out = [
            ("img_png", _("PNG 16 bits (sem perdas)"), _S("png", "png", "rgb48be", audio="none", dither=False)),
            ("img_tiff", _("TIFF 16 bits (sem perdas)"), _S("tiff", "tif", "rgb48le", audio="none", dither=False)),
            ("img_jpg", _("JPEG alta qualidade"), _S("jpg", "jpg", "yuvj444p", 2, audio="none")),
        ]
        if available("webp"):
            out.append(("img_webp", _("WebP (para sites)"), _S("webp", "webp", "yuv420p", 90, audio="none")))
        return out
    out = []
    if info is not None:
        out.append(("original", _("Original — mesmo formato, sem perda visível"), _original(info)))
    out += [
        ("mp4", _("MP4 H.264 — o formato mais comum, abre em tudo"), _S("x264", "mp4", "yuv420p", 18, "medium", audio="aac320", tune_grain=True)),
        ("mov", _("MOV H.264 — Apple, Final Cut, iPhone"), _S("x264", "mov", "yuv420p", 17, "slow", audio="aac320", tune_grain=True)),
        ("mkv", _("MKV H.265 — arquivo menor com boa qualidade"), _S("x265", "mkv", "yuv420p10le", 20, "medium", audio="aac192", tune_grain=True)),
        ("yt4k_hevc", _("YouTube 4K — H.265 10 bits"), _S("x265", "mp4", "yuv420p10le", 16, "slow", resolution="2160", audio="aac320", tune_grain=True)),
        ("yt4k_h264", _("YouTube 4K — H.264"), _S("x264", "mp4", "yuv420p", 15, "slow", resolution="2160", audio="aac320", tune_grain=True)),
        ("fhd", _("Full HD 1080p — H.264 alta qualidade"), _S("x264", "mp4", "yuv420p", 17, "slow", resolution="1080", audio="aac320", tune_grain=True)),
        ("social", _("Redes sociais 1080p — Instagram, TikTok, WhatsApp"), _S("x264", "mp4", "yuv420p", 20, "medium", resolution="1080", audio="aac192", tune_grain=True)),
        ("leve", _("Leve 720p — H.264"), _S("x264", "mp4", "yuv420p", 23, "medium", resolution="720", audio="aac192")),
    ]
    if available("vp9"):
        out.append(("webm", _("WebM VP9 — para sites e navegadores"), _S("vp9", "webm", "yuv420p", 30, "2", audio="opus")))
    if available("xvid"):
        out.append(("avi", _("AVI Xvid — aparelhos e players antigos"), _S("xvid", "avi", "yuv420p", 3, audio="mp3")))
    if available("gif"):
        out.append(("gif", _("GIF animado (480p, 15 quadros/s)"), _S("gif", "gif", "pal8", resolution="480", fps="15", audio="none", dither=False)))
    out += [
        ("prores_hq", _("Master — ProRes 422 HQ (10 bits)"), _S("prores", "mov", "yuv422p10le", profile="3", audio="pcm24")),
        ("prores_xq", _("Master máximo — ProRes 4444 XQ"), _S("prores", "mov", "yuv444p10le", profile="5", audio="pcm24")),
        ("dnxhr_hqx", _("Master — DNxHR HQX (10 bits)"), _S("dnxhr", "mov", "yuv422p10le", profile="dnxhr_hqx", audio="pcm24")),
        ("ffv1", _("Sem perdas — FFV1 16 bits RGB (.mkv)"), _S("ffv1", "mkv", "rgb48le", audio="pcm24", dither=False)),
    ]
    if available("hevc_nvenc"):
        out.append(("gpu", _("Rápido na GPU NVIDIA — H.265 10 bits"), _S("hevc_nvenc", "mp4", "p010le", 17, "p6", audio="aac320")))
    if available("hevc_qsv"):
        out.append(("gpu_intel", _("Rápido na GPU Intel — H.265"), _S("hevc_qsv", "mp4", "p010le", 20, "medium", audio="aac320")))
    if available("hevc_amf"):
        out.append(("gpu_amd", _("Rápido na GPU AMD — H.265"), _S("hevc_amf", "mp4", "yuv420p", 20, "quality", audio="aac320")))
    out.append(("png_seq", _("Sequência PNG 16 bits (para efeitos visuais)"), _S("png_seq", "png", "rgb48be", audio="none", dither=False)))
    return out


def output_size(info: media.MediaInfo, s: ExportSettings) -> tuple[int, int]:
    """Largura e altura da saída.

    A resolução escolhida ("2160", "1080", "720"…) vale para o **lado menor** do quadro, como no YouTube
    e nos celulares: em 1080p, um vídeo deitado sai 1920 × 1080 e um vertical sai 1080 × 1920 (antes a
    altura mandava e o vertical encolhia para 608 × 1080). Codecs de vídeo recebem dimensões pares.
    """
    w, h = max(1, int(info.width)), max(1, int(info.height))
    if s.resolution != "original":
        short = int(s.resolution)
        if w >= h:
            w, h = round(w * short / h), short
        else:
            w, h = short, round(h * short / w)
    if not CODECS[s.codec].get("image") and s.codec not in ("png_seq", "tiff_seq", "ffv1", "gif"):
        w -= w % 2
        h -= h % 2
    return max(w, 2), max(h, 2)


def _audio_args(s: ExportSettings, info: media.MediaInfo, start_time: float = 0.0) -> list[str]:
    if (s.audio == "none" or not info.has_audio or CODECS[s.codec].get("image") or s.codec.endswith("_seq")
            or s.codec == "gif"):
        return ["-an"]
    mode = s.audio
    ac = info.audio_codec
    if mode == "copy":
        ok = {"mp4": ("aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"), "webm": ("opus", "vorbis"),
              "avi": ("mp3", "ac3", "pcm_s16le"), "mov": ("aac", "mp3", "ac3", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le")}
        allowed = ok.get(s.container)
        # Ao copiar a partir do meio do arquivo, o ffmpeg leva pacotes de antes do corte. O MP4/MOV
        # esconde isso com edit list; MKV, WebM e AVI deslocariam o vídeo. Nesses, recodifica.
        trim = start_time > 0 and s.container in ("mkv", "webm", "avi")
        if (allowed is None or ac in allowed) and not trim:
            return ["-c:a", "copy"]
        if trim and s.container == "mkv":
            return ["-c:a", "flac"]
        mode = {"webm": "opus", "avi": "mp3", "mov": "pcm24"}.get(s.container, "aac320")
    if s.container == "webm":
        mode = "opus"
    elif s.container == "avi" and mode not in ("mp3", "pcm24"):
        mode = "mp3"
    elif s.container == "mp4" and mode == "pcm24":
        mode = "aac320"
    return {"aac320": ["-c:a", "aac", "-b:a", "320k"], "aac192": ["-c:a", "aac", "-b:a", "192k"],
            "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"], "opus": ["-c:a", "libopus", "-b:a", "192k"],
            "pcm24": ["-c:a", "pcm_s24le"]}[mode]


def build_encoder_cmd(out_path: str, info: media.MediaInfo, s: ExportSettings, w: int, h: int, fps_str: str,
                      depth: int, start_time: float, duration: float, input_path: str = "pipe:0",
                      audio_path: str | None = None) -> list[str]:
    """Comando do codificador. `audio_path` (modo Edição) é um WAV já recortado no trecho: entra sem -ss."""
    c = CODECS[s.codec]
    in_pix = "rgb24" if depth == 8 else "rgb48le"
    th = int(s.threads)
    args = [media.ffmpeg(), "-y", "-v", "error", "-hide_banner", "-progress", "pipe:2", "-stats_period", "0.5",
            "-f", "rawvideo", "-pix_fmt", in_pix,
            "-s", f"{w}x{h}", "-framerate", fps_str, "-i", input_path]
    audio = _audio_args(s, info, 0.0 if audio_path else start_time)
    if audio != ["-an"]:
        if start_time > 0 and not audio_path:
            args += ["-ss", f"{start_time:.6f}"]
        args += ["-t", f"{duration:.6f}", "-i", audio_path or info.path, "-map", "0:v:0", "-map", "1:a:0?"]
    else:
        args += ["-map", "0:v:0"]
    rgb_out = s.pix.startswith(("rgb", "gbr", "pal"))
    if s.codec == "gif":
        args += ["-vf", "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a"]
    elif not rgb_out:
        matrix = "bt601" if s.codec in ("jpg", "webp") else "bt709"
        rng = "full" if s.pix.startswith("yuvj") else "limited"
        args += ["-vf", f"scale=out_color_matrix={matrix}:out_range={rng}"
                        f":flags=accurate_rnd+full_chroma_int:threads={max(0, th)},format={s.pix}"]
    args += ["-c:v", c["enc"], "-pix_fmt", s.pix]
    if th > 0 and s.codec not in ("x265",) and not any(t in c["enc"] for t in ("nvenc", "qsv", "amf")):
        args += ["-threads", str(th)]
    if s.codec in ("x264", "x265"):
        args += ["-preset", s.preset or "slow"]
        if s.bitrate > 0:
            args += ["-b:v", f"{s.bitrate}M", "-maxrate", f"{s.bitrate * 1.5}M", "-bufsize", f"{s.bitrate * 2}M"]
        else:
            args += ["-crf", f"{s.quality:g}"]
        if s.tune_grain:
            args += ["-tune", "grain"]
        if s.codec == "x265":
            args += ["-x265-params", "log-level=error" + (f":pools={th}" if th > 0 else "")]
            if s.container in ("mp4", "mov"):
                args += ["-tag:v", "hvc1"]
    elif s.codec in ("h264_nvenc", "hevc_nvenc"):
        args += ["-gpu", str(int(s.gpu)), "-preset", s.preset or "p6", "-tune", "hq", "-rc", "vbr",
                 "-spatial-aq", "1", "-temporal-aq", "1"]
        if s.bitrate > 0:
            args += ["-b:v", f"{s.bitrate}M", "-maxrate", f"{s.bitrate * 1.5}M"]
        else:
            args += ["-cq", f"{s.quality:g}", "-b:v", "0"]
        if s.codec == "hevc_nvenc" and s.container in ("mp4", "mov"):
            args += ["-tag:v", "hvc1"]
    elif s.codec in ("h264_qsv", "hevc_qsv"):
        args += ["-preset", s.preset or "medium"]
        args += ["-b:v", f"{s.bitrate}M"] if s.bitrate > 0 else ["-global_quality", f"{int(s.quality)}"]
        if s.codec == "hevc_qsv" and s.container in ("mp4", "mov"):
            args += ["-tag:v", "hvc1"]
    elif s.codec in ("h264_amf", "hevc_amf"):
        args += ["-quality", s.preset or "quality"]
        if s.bitrate > 0:
            args += ["-rc", "vbr_peak", "-b:v", f"{s.bitrate}M"]
        else:
            q = str(int(s.quality))
            args += ["-rc", "cqp", "-qp_i", q, "-qp_p", q] + (["-qp_b", q] if s.codec == "h264_amf" else [])
        if s.codec == "hevc_amf" and s.container in ("mp4", "mov"):
            args += ["-tag:v", "hvc1"]
    elif s.codec == "av1":
        args += ["-preset", s.preset or "5"]
        args += ["-b:v", f"{s.bitrate}M"] if s.bitrate > 0 else ["-crf", f"{s.quality:g}"]
    elif s.codec == "vp9":
        args += ["-deadline", "good", "-cpu-used", s.preset or "2", "-row-mt", "1"]
        args += ["-b:v", f"{s.bitrate}M"] if s.bitrate > 0 else ["-crf", f"{s.quality:g}", "-b:v", "0"]
    elif s.codec == "xvid":
        args += ["-q:v", f"{int(s.quality or 3)}", "-vtag", "XVID"]
    elif s.codec == "prores":
        args += ["-profile:v", s.profile or "3", "-vendor", "apl0"]
    elif s.codec == "dnxhr":
        args += ["-profile:v", s.profile or "dnxhr_hq"]
    elif s.codec == "ffv1":
        args += ["-level", "3", "-g", "1", "-slices", "16", "-slicecrc", "1"]
    elif s.codec == "gif":
        args += ["-loop", "0"]
    elif s.codec == "jpg":
        args += ["-q:v", f"{int(s.quality or 2)}"]
    elif s.codec == "webp":
        args += ["-quality", f"{int(s.quality or 90)}"]
    elif s.codec in ("tiff", "tiff_seq"):
        args += ["-compression_algo", "deflate"]
    if not rgb_out and not s.pix.startswith("yuvj") and s.codec not in ("gif", "webp"):
        args += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    if s.container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args += audio
    if c.get("image"):
        args += ["-frames:v", "1", "-update", "1"]
    args += [out_path]
    return args


SEQUENCE_CODECS = ("png_seq", "tiff_seq")


def is_sequence(s: ExportSettings) -> bool:
    return s.codec in SEQUENCE_CODECS


def sequence_dir(path: str) -> Path:
    """Pasta dos quadros de uma sequência: `saida/quadros.png` → `saida/quadros/`."""
    return Path(path).with_suffix("")


def _frame_name(path: str) -> str:
    p = Path(path)
    return f"{p.stem}_%06d{p.suffix}"


def sequence_path(path: str) -> str:
    """Padrão dos quadros dentro da pasta da sequência (`quadros/quadros_%06d.png`); cria a pasta."""
    folder = sequence_dir(path)
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / _frame_name(path))


def _partial_sequence_dir(path: str) -> Path:
    """Pasta parcial da sequência, ao lado da final: `quadros.parcial-pelicula/`."""
    p = Path(path)
    return p.with_name(f"{p.stem}.{system.PARTIAL}")


def _frames(folder: Path, path: str) -> list[str]:
    """Nomes dos quadros desta sequência (`quadros_000001.png`…) que existem em `folder`."""
    p = Path(path)
    pattern = re.compile(re.escape(p.stem) + r"_\d{6,}" + re.escape(p.suffix))
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n for n in names if pattern.fullmatch(n))


def output_target(path: str, s: ExportSettings) -> str:
    """O que a exportação cria no fim: o arquivo ou, nas sequências de imagens, a pasta dos quadros."""
    return str(sequence_dir(path)) if is_sequence(s) else path


def output_exists(path: str, s: ExportSettings) -> bool:
    """O destino já existe? Nas sequências, se a pasta já tem quadros com este nome."""
    if is_sequence(s):
        return bool(_frames(sequence_dir(path), path))
    return os.path.exists(path)


# ------------------------------------------------------------------ gravação segura
# O ffmpeg nunca grava direto no destino: grava num parcial ao lado (`video.parcial-pelicula.mp4`; nas
# sequências, a pasta `quadros.parcial-pelicula/`) e o resultado só troca de nome quando a exportação termina
# bem. Cancelar, dar erro ou o app fechar no meio nunca deixa um arquivo quebrado com o nome final, e
# o arquivo antigo com o mesmo nome continua intacto até o último instante.
def partial_output(path: str, s: ExportSettings) -> str:
    """O parcial desta exportação: `video.parcial-pelicula.mp4` ou, nas sequências, a pasta
    `quadros.parcial-pelicula`."""
    return str(_partial_sequence_dir(path)) if is_sequence(s) else system.partial_path(path)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def job_inputs(info: media.MediaInfo, sequence=None) -> list[str]:
    """Arquivos lidos pela exportação: o vídeo ou, no modo Edição, todos os arquivos da montagem."""
    if sequence is not None:
        return [str(p) for p in sequence.sources]
    return [info.path]


def partial_clash(path: str, s: ExportSettings, inputs: list[str]) -> str:
    """Arquivo de entrada que tem o nome do parcial desta exportação ("" se nenhum).

    O parcial que sobra de uma exportação interrompida é apagado antes de começar; se a pessoa abriu
    justamente esse arquivo (`video.parcial-pelicula.mp4`) e exporta para `video.mp4`, ele não pode ser apagado.
    """
    part = _norm(partial_output(path, s))
    for src in inputs:
        if src and (_norm(src) == part or (is_sequence(s) and _norm(os.path.dirname(src)) == part)):
            return src
    return ""


def partial_clash_message(src: str) -> str:
    return _("O arquivo de entrada {caminho} tem o nome que esta exportação usa enquanto grava. Escolha outro nome "
             "para a saída.").format(caminho=src)


def _discard_output(path: str, s: ExportSettings) -> None:
    """Apaga o parcial (desta exportação ou o que sobrou de uma interrompida)."""
    if not is_sequence(s):
        system.remove_file(system.partial_path(path))
        return
    folder = _partial_sequence_dir(path)
    for name in _frames(folder, path):
        system.remove_file(folder / name)
    try:
        folder.rmdir()  # só se ficou vazia: o que não é quadro desta sequência nunca é apagado
    except OSError:
        pass


def _prepare_output(path: str, s: ExportSettings) -> str:
    """Limpa o parcial antigo e devolve onde o codificador grava."""
    _discard_output(path, s)
    if is_sequence(s):
        folder = _partial_sequence_dir(path)
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / _frame_name(path))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return system.partial_path(path)


def _commit_output(path: str, s: ExportSettings) -> None:
    """Troca o destino pelo resultado (o antigo é substituído só agora, já com o novo completo)."""
    if not is_sequence(s):
        system.replace_file(system.partial_path(path), path)
        return
    part, final = _partial_sequence_dir(path), sequence_dir(path)
    new = _frames(part, path)
    if not final.exists() and len(new) == len(os.listdir(part)):
        try:
            os.replace(part, final)  # pasta nova: troca o nome da pasta inteira de uma vez
            return
        except OSError:
            pass
    final.mkdir(parents=True, exist_ok=True)
    for name in new:
        system.replace_file(part / name, final / name)
    keep = set(new)
    for name in _frames(final, path):
        if name not in keep:
            system.remove_file(final / name)  # sobra de uma exportação anterior mais longa
    try:
        part.rmdir()
    except OSError:
        pass


# ------------------------------------------------------------------ trabalhos
@dataclass
class ExportJob:
    info: media.MediaInfo
    values: dict
    settings: ExportSettings
    out_path: str
    start_frame: int = 0
    end_frame: int = -1  # inclusivo; -1 = até o fim
    name: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "aguardando"  # aguardando | exportando | concluido | erro | cancelado
    done: int = 0
    total: int = 0
    fps_rate: float = 0.0
    eta: float = 0.0
    error: str = ""
    started: float = 0.0
    finished: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event)
    warmup: int = 8          # quadros ignorados na medição de velocidade
    t_warm: float = 0.0      # momento em que o quadro `warmup` foi gravado
    rendered: int = 0        # quadros processados pela GPU
    encoded: int = 0         # quadros já gravados pelo codificador (progresso do ffmpeg)
    sequence: Any = None     # timeline.Sequence do modo Edição (None = o arquivo de `info`)

    @property
    def progress(self) -> float:
        return self.done / self.total if self.total else 0.0


class ExportQueue:
    """Executa os trabalhos um de cada vez numa thread com seu próprio contexto de GPU."""

    def __init__(self):
        self.jobs: list[ExportJob] = []
        self._q: queue.Queue[ExportJob] = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="exportacao")
        self._engine: Engine | None = None
        self._thread.start()

    def add(self, job: ExportJob) -> None:
        with self._lock:
            self.jobs.append(job)
        self._q.put(job)

    def remove_finished(self) -> None:
        with self._lock:
            self.jobs = [j for j in self.jobs if j.status in ("aguardando", "exportando")]

    @property
    def busy(self) -> bool:
        return any(j.status in ("aguardando", "exportando") for j in self.jobs)

    def _loop(self) -> None:
        while True:
            job = self._q.get()
            if job.cancel.is_set():
                job.status = "cancelado"
                continue
            try:
                if self._engine is None:
                    self._engine = Engine()
                run_job(job, self._engine)
            except Exception as exc:  # noqa: BLE001
                job.status = "erro"
                job.error = str(exc)
            job.finished = time.time()


def run_job(job: ExportJob, engine: Engine) -> None:
    """Exporta um trabalho. O ffmpeg grava num parcial ao lado do destino e o resultado só vai para o
    lugar do destino quando tudo deu certo; cancelado ou com erro, o parcial é apagado e o arquivo
    antigo (se havia) fica como estava."""
    info, s = job.info, job.settings
    perf = s.perf()
    job.status = "exportando"
    job.started = time.time()
    seq = job.sequence
    w, h = output_size(info, s)
    fps_str = info.fps_str if s.fps == "original" else s.fps
    fps_out = None if s.fps == "original" else s.fps
    fps_val = float(eval_fraction(fps_str))
    depth = 16 if high_depth(s) else 8
    start = max(0, job.start_frame)
    end = info.frames - 1 if job.end_frame < 0 else min(job.end_frame, info.frames - 1)
    src_count = max(1, end - start + 1)
    start_time = start / info.fps
    duration = src_count / info.fps
    total = 1 if info.is_image else max(1, round(duration * fps_val))
    job.total = total
    if job.cancel.is_set():
        job.status = "cancelado"
        return
    clash = partial_clash(job.out_path, s, job_inputs(info, seq))
    if clash:
        job.status = "erro"
        job.error = partial_clash_message(clash)
        return
    target = _prepare_output(job.out_path, s)
    mix_path = None
    keep_partial = False
    try:
        if seq is not None:
            # Modo Edição: o som da sequência é mixado antes, já no trecho exportado.
            from . import audiomix
            if _audio_args(s, info, 0.0) != ["-an"] and audiomix.has_audio(seq, start, end + 1):
                import tempfile
                fd, mix_path = tempfile.mkstemp(prefix="pelicula_som_", suffix=".wav")
                os.close(fd)
                try:
                    ok = audiomix.render_mix(seq, mix_path, start, end + 1, job.cancel, perf)
                except RuntimeError as exc:
                    job.status = "erro"
                    job.error = str(exc)[-1500:]
                    return
                if job.cancel.is_set():
                    job.status = "cancelado"
                    return
                if not ok:
                    system.remove_file(mix_path)
                    mix_path = None
            has = mix_path is not None
            info = media.MediaInfo(**{**info.__dict__, "has_audio": has, "audio_codec": "pcm_s24le" if has else ""})
        if _encode(job, engine, info, s, perf, w, h, fps_str, fps_out, fps_val, depth, start, total, start_time,
                   duration, target, seq, mix_path):
            try:
                _commit_output(job.out_path, s)
            except OSError as exc:
                # O resultado está completo: não joga fora o trabalho; diz onde ele ficou.
                keep_partial = True
                job.status = "erro"
                job.error = _("A exportação terminou, mas não foi possível substituir {destino} (ele pode estar "
                              "aberto em outro programa): {erro}\nO resultado ficou em: {parcial}").format(
                    destino=output_target(job.out_path, s), erro=exc, parcial=partial_output(job.out_path, s))
            else:
                job.status = "concluido"
    finally:
        if job.status != "concluido" and not keep_partial:
            _discard_output(job.out_path, s)
        if mix_path:
            system.remove_file(mix_path)


def _encode(job: ExportJob, engine: Engine, info: media.MediaInfo, s: ExportSettings, perf: media.Perf, w: int,
            h: int, fps_str: str, fps_out: str | None, fps_val: float, depth: int, start: int, total: int,
            start_time: float, duration: float, target: str, seq, mix_path: str | None) -> bool:
    """Lê, aplica o look e codifica em `target` (o parcial). True quando todos os quadros foram gravados;
    senão marca o trabalho como cancelado ou com erro e devolve False."""
    pipe = media.NamedPipe(False) if media.use_named_pipes() else None
    cmd = build_encoder_cmd(target, info, s, w, h, fps_str, depth, start_time, duration,
                            pipe.name if pipe else "pipe:0", audio_path=mix_path)
    if seq is not None:
        from .sequence import SequenceReader
        reader = SequenceReader(seq, w, h, depth, start, total, hq=True, perf=perf, fps_out=fps_out)
        skip = 0
    elif fps_out:
        # Com troca de fps a decodificação começa no tempo e não no quadro.
        reader = media.FrameReader(info, w, h, depth, 0, None, fps_out, hq=True, perf=perf)
        skip = round(start_time * fps_val)
    else:
        reader = media.FrameReader(info, w, h, depth, start, total, None, hq=True, perf=perf)
        skip = 0
    enc = subprocess.Popen(cmd, stdin=None if pipe else subprocess.PIPE, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, **perf.popen_kwargs())
    err_buf = bytearray()
    t0 = time.time()

    def update() -> None:
        d = job.encoded if job.encoded > 0 else job.rendered
        job.done = min(d, total)
        if not job.t_warm and d >= job.warmup:
            job.t_warm = time.time()
        el = time.time() - t0
        job.fps_rate = d / el if el > 0 else 0.0
        job.eta = (total - d) / job.fps_rate if job.fps_rate > 0 else 0.0

    progress_keys = (b"fps=", b"stream_", b"bitrate=", b"total_size=", b"out_time", b"dup_frames=",
                     b"drop_frames=", b"speed=", b"progress=")

    def drain():
        for line in enc.stderr:
            if line.startswith(b"frame="):
                try:
                    job.encoded = int(line[6:].strip() or b"0")
                    update()
                except ValueError:
                    pass
                continue
            if line.startswith(progress_keys):
                continue
            if len(err_buf) < 20000:
                err_buf.extend(line)

    threading.Thread(target=drain, daemon=True).start()
    try:
        sink = pipe.connect(enc) if pipe else enc.stdin
    except (RuntimeError, OSError) as exc:
        reader.close()
        enc.wait()
        job.status = "erro"
        job.error = (err_buf.decode("utf-8", "replace").strip() or str(exc))[-1500:]
        return False
    nbuf = max(2, int(perf.buffer))
    frames_q: queue.Queue = queue.Queue(maxsize=nbuf)
    out_q: queue.Queue = queue.Queue(maxsize=nbuf)

    def read_loop():
        try:
            for _n in range(skip):
                if reader.read() is None:
                    break
            for _n in range(total):
                if job.cancel.is_set():
                    break
                img = reader.read()
                if img is None:
                    break
                frames_q.put(img)
        finally:
            frames_q.put(None)

    write_err: list[str] = []

    def write_loop():
        while True:
            data = out_q.get()
            if data is None:
                break
            if write_err or job.cancel.is_set():
                continue
            try:
                mv = memoryview(data)
                while len(mv):
                    n = sink.write(mv)
                    if n is None:
                        break
                    mv = mv[n:]
            except (BrokenPipeError, OSError, ValueError) as exc:
                write_err.append(str(exc))

    rt = threading.Thread(target=read_loop, daemon=True)
    wt = threading.Thread(target=write_loop, daemon=True)
    rt.start()
    wt.start()
    info_lut = lut_info(job.values.get("lut_arquivo", "")) if job.values.get("lut_on") else None
    first_index = round(start * fps_val / info.fps) if fps_out else start
    i = 0
    try:
        while True:
            img = frames_q.get()
            if img is None:
                break
            if job.cancel.is_set() or write_err:
                break
            if seq is not None:
                img = engine.compose(img, seq, w, h, depth)
            engine.set_input(img)
            plan = look.build_plan(job.values, w, h, first_index + i, fps_val, info_lut, dither=s.dither and depth == 8)
            out = engine.render(plan, depth)
            out_q.put(out.tobytes())
            i += 1
            job.rendered = i
            update()
    finally:
        out_q.put(None)
        if job.cancel.is_set():
            enc.kill()
        wt.join()
        try:
            sink.close()
        except OSError:
            pass
        if pipe:
            pipe.close()
        while enc.poll() is None:
            if job.cancel.is_set():
                enc.kill()
            time.sleep(0.05)
        rc = enc.wait()
        reader.close()
        while True:
            try:
                frames_q.get_nowait()
            except queue.Empty:
                break
        rt.join(timeout=5)
    if job.cancel.is_set():
        job.status = "cancelado"
        return False
    if rc != 0 or write_err:
        job.status = "erro"
        job.error = (err_buf.decode("utf-8", "replace").strip() or "; ".join(write_err) or reader.error)[-1500:]
        return False
    if i == 0:
        job.status = "erro"
        job.error = reader.error or _("Nenhum quadro foi lido do arquivo.")
        return False
    job.done = job.total = i
    return True


def job_frames(info: media.MediaInfo, s: ExportSettings, start: int = 0, end: int = -1) -> int:
    end = info.frames - 1 if end < 0 else min(end, info.frames - 1)
    fps = info.fps if s.fps == "original" else eval_fraction(s.fps)
    return 1 if info.is_image else max(1, round((end - max(0, start) + 1) / info.fps * fps))


def measure_speed(info: media.MediaInfo, values: dict, settings: ExportSettings, cancel: threading.Event,
                  frames: int = 60, limit: float = 15.0, sequence=None) -> float:
    """Exporta um trecho num arquivo temporário e devolve a velocidade real (quadros/s).

    Os primeiros quadros (abertura do ffmpeg e do codificador) ficam de fora da conta, e a
    medição para sozinha depois de `limit` segundos.
    """
    import shutil
    import tempfile
    s = ExportSettings.from_dict(settings.to_dict())
    s.audio = "none"
    tmp = tempfile.mkdtemp(prefix="pelicula_medida_")
    start = 0 if info.frames <= frames * 2 else info.frames // 3
    out = os.path.join(tmp, "teste." + s.container)
    job = ExportJob(info=info, values=values, settings=s, out_path=out, start_frame=start,
                    end_frame=min(info.frames - 1, start + frames - 1), sequence=sequence)
    stop = threading.Event()

    def watch():
        t_end = time.time() + limit
        while not stop.is_set():
            if cancel.is_set() or time.time() > t_end:
                job.cancel.set()
                return
            time.sleep(0.05)

    threading.Thread(target=watch, daemon=True).start()
    engine = Engine()
    t0 = time.time()
    try:
        run_job(job, engine)
    finally:
        stop.set()
        engine.release()
        shutil.rmtree(tmp, ignore_errors=True)
    t_end = time.time()
    if cancel.is_set() or job.done == 0 or job.status == "erro":
        return 0.0
    if job.t_warm and job.done > job.warmup + 2:
        return (job.done - job.warmup) / max(t_end - job.t_warm, 1e-3)
    return job.done / max(t_end - t0, 1e-3)


# "Salvar quadro" (janela e `pelicula-cli quadro`): formato de pixel e opções por extensão.
STILL_ARGS = {".png": ["-pix_fmt", "rgb48be"], ".tif": ["-pix_fmt", "rgb48le", "-compression_algo", "deflate"],
              ".tiff": ["-pix_fmt", "rgb48le"], ".jpg": ["-pix_fmt", "yuvj444p", "-q:v", "2"],
              ".jpeg": ["-pix_fmt", "yuvj444p", "-q:v", "2"]}


def save_still(img, path: str) -> None:
    """Grava um quadro RGB de 16 bits (array h × w × 3) em PNG, TIFF ou JPEG, conforme a extensão.

    Grava num parcial ao lado e só então troca o destino; se o ffmpeg falhar, levanta RuntimeError e o
    arquivo antigo com o mesmo nome fica intacto.
    """
    h, w = img.shape[:2]
    part = system.partial_path(path)
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{w}x{h}",
           "-i", "pipe:0", *STILL_ARGS.get(Path(path).suffix.lower(), []), "-frames:v", "1", "-update", "1", part]
    res = subprocess.run(cmd, input=img.tobytes(), capture_output=True, creationflags=media.NO_WINDOW)
    if res.returncode != 0 or not os.path.isfile(part):
        system.remove_file(part)
        raise RuntimeError(res.stderr.decode("utf-8", "replace").strip() or _("O ffmpeg não gravou o quadro."))
    try:
        system.replace_file(part, path)
    except OSError:
        system.remove_file(part)
        raise


def eval_fraction(txt: str) -> float:
    if "/" in txt:
        a, b = txt.split("/", 1)
        return float(a) / float(b)
    return float(txt)
