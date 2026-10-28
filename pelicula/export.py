"""Exportação: qualidades prontas, montagem do comando do ffmpeg e fila de trabalhos."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import media, system
from .engine import Engine
from .frame import Recipe, lut_of
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
         ("aac128", "AAC 128 kb/s"), ("mp3", "MP3 320 kb/s"), ("opus", "Opus 192 kb/s"),
         ("pcm24", "PCM 24 bits (sem perdas)"), ("none", "Sem áudio")]
AUDIO_ARGS = {"aac320": ["-c:a", "aac", "-b:a", "320k"], "aac192": ["-c:a", "aac", "-b:a", "192k"],
              "aac128": ["-c:a", "aac", "-b:a", "128k"], "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
              "opus": ["-c:a", "libopus", "-b:a", "192k"], "pcm24": ["-c:a", "pcm_s24le"], "flac": ["-c:a", "flac"]}
# kb/s de cada modo (estimativa de tamanho e tamanho alvo); FLAC ≈ metade do PCM estéreo de 48 kHz.
AUDIO_KBPS = {"aac320": 320, "aac192": 192, "aac128": 128, "mp3": 320, "opus": 192, "pcm24": 2304, "flac": 1100}

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
    # Exportação por plataforma (1.4). Todos com padrão neutro: um to_dict() antigo, sem estas chaves,
    # exporta exatamente como antes.
    platform: str = ""        # id de platforms.PLATFORMS que preencheu as opções ("" = nenhuma); só informativo
    frame: str = ""           # quadro fixo "LxA" (ex.: "1080x1920"); "" = segue `resolution` e a proporção do vídeo
    fit: str = "cortar"       # vídeo de outra proporção no quadro fixo: cortar | bordas | desfocado (fit.py)
    target_mb: float = 0.0    # tamanho alvo em MB (1 MB = 1.000.000 bytes), duas passadas no x264/x265; 0 = não
    maxrate: float = 0.0      # teto da taxa de bits (Mb/s) na qualidade constante do x264/x265; 0 = sem teto
    loudness: float = 0.0     # volume alvo em LUFS (−14, −16, −23…); 0 = o som não muda de volume
    true_peak: float = -1.0   # pico real máximo (dBTP) quando há volume alvo
    net_grain: bool = False   # "Grão para redes": grão com tamanho mínimo na saída (look.build_plan(net_grain=))

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


# ------------------------------------------------------------------ transparência (canal alfa)
# Codecs que guardam transparência e o formato de pixel com alfa de cada formato sem alfa: ProRes 4444 (perfis 4 e
# 5, yuva444p10le), WebM VP9 (yuva420p, o libvpx só tem alfa em 8 bits) e PNG/TIFF RGBA de 8 ou 16 bits. Os
# formatos com alfa entram no fim da lista `pix` de cada codec; quem pede é a janela ("Manter a transparência")
# ou `--pix` na linha de comando. Sem alfa no `pix`, a exportação é a de sempre (tela opaca).
ALPHA_PIX: dict[str, dict[str, str]] = {
    "prores": {"yuv422p10le": "yuva444p10le", "yuv444p10le": "yuva444p10le"},
    "vp9": {"yuv420p": "yuva420p", "yuv420p10le": "yuva420p"},
    "png_seq": {"rgb48be": "rgba64be", "rgb24": "rgba"},
    "tiff_seq": {"rgb48le": "rgba64le", "rgb24": "rgba"},
    "png": {"rgb48be": "rgba64be", "rgb24": "rgba"},
    "tiff": {"rgb48le": "rgba64le", "rgb24": "rgba"},
}
for _codec, _pairs in ALPHA_PIX.items():
    CODECS[_codec]["pix"] += [p for p in dict.fromkeys(_pairs.values()) if p not in CODECS[_codec]["pix"]]


def supports_alpha(codec: str) -> bool:
    """O codec guarda transparência?"""
    return codec in ALPHA_PIX


def alpha_pix(codec: str, pix: str) -> str:
    """O formato com alfa que corresponde a `pix` (o próprio, se já tem alfa); `pix` se o codec não tem alfa."""
    pairs = ALPHA_PIX.get(codec)
    if not pairs or media.pix_has_alpha(pix):
        return pix
    return pairs.get(pix) or next(iter(pairs.values()))


def opaque_pix(codec: str, pix: str) -> str:
    """O formato sem alfa que corresponde a `pix` (o primeiro da lista do codec que vira `pix`)."""
    if not media.pix_has_alpha(pix):
        return pix
    return next((k for k, v in ALPHA_PIX.get(codec, {}).items() if v == pix), pix)


def wants_alpha(s: ExportSettings) -> bool:
    """A exportação sai com transparência (formato de pixel com alfa num codec que guarda alfa)."""
    return supports_alpha(s.codec) and media.pix_has_alpha(s.pix)


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


def parse_frame(text: str) -> tuple[int, int] | None:
    """Quadro fixo "1080x1920" (também "1080×1920" ou "1080 x 1920") → (1080, 1920); vazio ou inválido → None."""
    m = re.fullmatch(r"\s*(\d{1,5})\s*[x×X:]\s*(\d{1,5})\s*", str(text or ""))
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if 2 <= w <= 16384 and 2 <= h <= 16384 else None


def output_size(info: media.MediaInfo, s: ExportSettings) -> tuple[int, int]:
    """Largura e altura da saída.

    A resolução escolhida ("2160", "1080", "720"…) vale para o **lado menor** do quadro, como no YouTube
    e nos celulares: em 1080p, um vídeo deitado sai 1920 × 1080 e um vertical sai 1080 × 1920 (antes a
    altura mandava e o vertical encolhia para 608 × 1080). Codecs de vídeo recebem dimensões pares.
    Com quadro fixo (`s.frame`, das plataformas) a saída é esse quadro e o vídeo entra nele conforme `s.fit`.
    """
    w, h = max(1, int(info.width)), max(1, int(info.height))
    fixed = parse_frame(s.frame)
    if fixed:
        w, h = fixed
    elif s.resolution != "original":
        short = int(s.resolution)
        if w >= h:
            w, h = round(w * short / h), short
        else:
            w, h = short, round(h * short / w)
    if not CODECS[s.codec].get("image") and s.codec not in ("png_seq", "tiff_seq", "ffv1", "gif"):
        w -= w % 2
        h -= h % 2
    return max(w, 2), max(h, 2)


TWO_PASS_CODECS = ("x264", "x265")


def uses_target(s: ExportSettings) -> bool:
    """Tamanho alvo ligado e possível com este codec (duas passadas do x264/x265)."""
    return float(s.target_mb or 0) > 0 and s.codec in TWO_PASS_CODECS


def wants_loudness(s: ExportSettings) -> bool:
    """Volume alvo ligado (LUFS negativos; 0 = desligado)."""
    return float(s.loudness or 0) < 0


def _audio_mode(s: ExportSettings, info: media.MediaInfo, start_time: float = 0.0) -> str:
    """Modo de áudio que a exportação usa de fato: "" (sem áudio), "copy", "flac" ou uma chave de `AUDIO_ARGS`.

    Com volume alvo ou tamanho alvo o som nunca é copiado: copiar não deixa mudar o volume nem saber quanto
    o som ocupa. Nesses casos "Copiar original" vira o formato do recipiente (AAC 128 kb/s no tamanho alvo).
    """
    if (s.audio == "none" or not info.has_audio or CODECS[s.codec].get("image") or s.codec.endswith("_seq")
            or s.codec == "gif"):
        return ""
    mode = s.audio
    ac = info.audio_codec
    fallback = {"webm": "opus", "avi": "mp3", "mov": "pcm24"}.get(s.container, "aac320")
    if mode == "copy" and (wants_loudness(s) or uses_target(s)):
        mode = "aac128" if uses_target(s) else fallback
    elif mode == "copy":
        ok = {"mp4": ("aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"), "webm": ("opus", "vorbis"),
              "avi": ("mp3", "ac3", "pcm_s16le"), "mov": ("aac", "mp3", "ac3", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le")}
        allowed = ok.get(s.container)
        # Ao copiar a partir do meio do arquivo, o ffmpeg leva pacotes de antes do corte. O MP4/MOV
        # esconde isso com edit list; MKV, WebM e AVI deslocariam o vídeo. Nesses, recodifica.
        trim = start_time > 0 and s.container in ("mkv", "webm", "avi")
        if (allowed is None or ac in allowed) and not trim:
            return "copy"
        if trim and s.container == "mkv":
            return "flac"
        mode = fallback
    if s.container == "webm":
        mode = "opus"
    elif s.container == "avi" and mode not in ("mp3", "pcm24"):
        mode = "mp3"
    elif s.container == "mp4" and mode == "pcm24":
        mode = "aac320"
    return mode


def _audio_args(s: ExportSettings, info: media.MediaInfo, start_time: float = 0.0) -> list[str]:
    mode = _audio_mode(s, info, start_time)
    if not mode:
        return ["-an"]
    if mode == "copy":
        return ["-c:a", "copy"]
    return list(AUDIO_ARGS[mode])


def audio_reencoded_for_volume(s: ExportSettings, info: media.MediaInfo) -> bool:
    """A escolha era "Copiar original", mas o volume alvo ou o tamanho alvo obrigam a recodificar (a janela avisa)."""
    return s.audio == "copy" and _audio_mode(s, info) not in ("", "copy") and (wants_loudness(s) or uses_target(s))


def audio_kbps(s: ExportSettings, info: media.MediaInfo, start_time: float = 0.0) -> float:
    """Taxa do som que sai (kb/s), para o tamanho alvo e a estimativa; copiar usa a taxa do vídeo de origem
    não conhecida (0) e sem som é 0."""
    return float(AUDIO_KBPS.get(_audio_mode(s, info, start_time), 0))


# ------------------------------------------------------------------ tamanho alvo (duas passadas)
# 1 MB = 1.000.000 bytes (o menor dos dois usos comuns: o limite de quem recebe nunca é ultrapassado).
# O orçamento desconta o som (5% acima da taxa nominal do AAC), o recipiente (índice do MP4 ≈ 1,5 kB por
# segundo + 48 kB de cabeçalho) e uma folga de 4% para o erro do controle de taxa do codificador.
TARGET_MARGIN = 0.04
TARGET_FIXED_BYTES = 48_000
TARGET_BYTES_PER_SECOND = 1_500
MIN_TARGET_RATE = 0.05  # Mb/s de vídeo: abaixo disso não dá para fazer um vídeo que se veja


def target_bytes(s: ExportSettings) -> int:
    return int(float(s.target_mb) * 1_000_000)


def target_bitrate(s: ExportSettings, info: media.MediaInfo, duration: float, start_time: float = 0.0) -> float:
    """Taxa de vídeo (Mb/s) que cabe no tamanho alvo com o som e o recipiente; pode dar ≤ 0 (não cabe)."""
    dur = max(float(duration), 0.04)
    budget = target_bytes(s) * (1.0 - TARGET_MARGIN) - TARGET_FIXED_BYTES - TARGET_BYTES_PER_SECOND * dur
    video_bps = budget * 8.0 / dur - audio_kbps(s, info, start_time) * 1000.0 * 1.05
    return video_bps / 1e6


def fmt_mb(mb: float) -> str:
    from .i18n import fmt_decimal
    return fmt_decimal(mb, 0 if float(mb).is_integer() else 1)


def target_too_small_message(s: ExportSettings, duration: float) -> str:
    return _("{mb} MB é pouco para {segundos} s de vídeo com som. Aumente o tamanho alvo, exporte um trecho menor "
             "ou tire o som.").format(mb=fmt_mb(float(s.target_mb)), segundos=f"{duration:.0f}")


def estimate_bytes(s: ExportSettings, info: media.MediaInfo, duration: float,
                   video_bytes_per_second: float = 0.0) -> int:
    """Tamanho provável do arquivo (bytes; 0 = não dá para saber).

    Tamanho alvo: o próprio alvo (nunca passa). Taxa de bits fixa: taxa × duração. Qualidade constante: a
    medida da estimativa de tempo (`measure_speed(stats=...)`, bytes de vídeo por segundo), quando houver.
    """
    if uses_target(s):
        return target_bytes(s)
    audio = audio_kbps(s, info) * 1000.0 / 8.0 * duration
    if s.bitrate > 0:
        return int(s.bitrate * 1e6 / 8.0 * duration + audio)
    if video_bytes_per_second > 0:
        return int(video_bytes_per_second * duration + audio)
    return 0


PASSLOG = "pelicula_2passadas"  # nome relativo: o codificador roda com cwd na pasta temporária das passadas


def build_encoder_cmd(out_path: str, info: media.MediaInfo, s: ExportSettings, w: int, h: int, fps_str: str,
                      depth: int, start_time: float, duration: float, input_path: str = "pipe:0",
                      audio_path: str | None = None, chapters_path: str | None = None, *, two_pass: int = 0,
                      loudness_measured: dict | None = None, subtitles: Any = None) -> list[str]:
    """Comando do codificador. `audio_path` (modo Edição) é um WAV já recortado no trecho: entra sem -ss.

    `chapters_path`: arquivo FFMETADATA com os capítulos do trecho (`chapters.export_file`); fica de fora da
    1ª passada do tamanho alvo, que não grava arquivo.
    `two_pass` (1 ou 2): uma das passadas do tamanho alvo (x264/x265, taxa em `s.bitrate`). O registro das
    passadas tem nome relativo (`PASSLOG`): rode o comando com `cwd` numa pasta temporária (os caminhos do
    destino, do som e dos capítulos viram absolutos). A 1ª passada não grava arquivo nem som (`-f null`).
    `loudness_measured`: valores medidos por `loudnorm.measure()` (volume alvo em `s.loudness`); o som recebe
    o `loudnorm` linear da segunda passada do volume.
    `subtitles`: faixa de legenda do trecho (`subtitles.Embed`, de `subtitles.export_file`): mov_text no
    MP4/MOV, SRT no MKV, WebVTT no WebM; fica de fora da 1ª passada do tamanho alvo, como os capítulos.
    Sem os opcionais o comando é o de sempre.
    """
    c = CODECS[s.codec]
    in_pix = "rgb24" if depth == 8 else "rgb48le"
    if wants_alpha(s):  # quadros RGBA de cor direta (`Recipe(alpha=True)`)
        in_pix = "rgba" if depth == 8 else "rgba64le"
    th = int(s.threads)
    args = [media.ffmpeg(), "-y", "-v", "error", "-hide_banner", "-progress", "pipe:2", "-stats_period", "0.5",
            "-f", "rawvideo", "-pix_fmt", in_pix,
            "-s", f"{w}x{h}", "-framerate", fps_str, "-i", input_path]
    audio = _audio_args(s, info, 0.0 if audio_path else start_time)
    if two_pass == 1:
        audio = ["-an"]
    if audio != ["-an"]:
        if start_time > 0 and not audio_path:
            args += ["-ss", f"{start_time:.6f}"]
        apath = audio_path or info.path
        args += ["-t", f"{duration:.6f}", "-i", os.path.abspath(apath) if two_pass else apath,
                 "-map", "0:v:0", "-map", "1:a:0?"]
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
            if s.maxrate > 0:  # qualidade constante com teto (plataformas que limitam a taxa de bits)
                args += ["-maxrate", f"{s.maxrate:g}M", "-bufsize", f"{s.maxrate * 2:g}M"]
        if s.tune_grain:
            args += ["-tune", "grain"]
        if two_pass and s.codec == "x264":
            args += ["-pass", str(two_pass), "-passlogfile", PASSLOG]
        if s.codec == "x265":
            xp = "log-level=error" + (f":pools={th}" if th > 0 else "")
            if two_pass:
                xp += f":pass={two_pass}:stats={PASSLOG}.log"
            args += ["-x265-params", xp]
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
        profile = s.profile or "3"
        if wants_alpha(s) and profile not in ("4", "5"):
            profile = "4"  # só o ProRes 4444 (e o XQ) guarda o alfa
        args += ["-profile:v", profile, "-vendor", "apl0"]
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
    if two_pass == 1:  # 1ª passada: só o registro do codificador, nenhum arquivo
        return args + audio + ["-f", "null", "-"]
    if s.container in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]
    args += audio
    if loudness_measured and audio not in (["-an"], ["-c:a", "copy"]):
        from . import loudnorm
        args += ["-af", loudnorm.filter_for(loudness_measured, float(s.loudness), float(s.true_peak))]
    if c.get("image"):
        args += ["-frames:v", "1", "-update", "1"]
    if chapters_path and two_pass != 1:
        # Capítulos: o FFMETADATA entra como a última entrada (antes do primeiro -map, que já é saída).
        n_inputs = args.count("-i")
        at = args.index("-map")
        args[at:at] = ["-f", "ffmetadata", "-i", os.path.abspath(chapters_path) if two_pass else chapters_path]
        args += ["-map_chapters", str(n_inputs)]
    if subtitles is not None and two_pass != 1:
        from . import subtitles as subs
        sub_in, sub_out = subs.encoder_args(subtitles, args.count("-i"), absolute=bool(two_pass))
        at = args.index("-map")
        args[at:at] = sub_in
        args += sub_out
    args += [os.path.abspath(out_path) if two_pass else out_path]
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
    """Arquivos lidos pela exportação: o vídeo ou, no modo Edição, todos os arquivos da montagem (clipes sem
    arquivo não contam)."""
    if sequence is not None:
        return [str(p) for p, s in sequence.sources.items() if s.is_file]
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


# ------------------------------------------------------------------ quadro a quadro (exportação e prévia)
# Do quadro decodificado ao quadro gravado: a receita única de `frame.py` (montagem, look e encaixe). O nome
# antigo continua valendo para quem já usava `export.FramePipeline`.
FramePipeline = Recipe


def frame_pipeline(info: media.MediaInfo, values: dict, s: ExportSettings, seq=None, scale: float = 1.0,
                   depth: int | None = None, keys: dict | None = None) -> Recipe:
    """A receita de um quadro desta exportação (`frame.Recipe`). `scale` < 1 reduz tudo (prévia): o quadro, o
    encaixe e o tamanho mínimo do "Grão para redes" (px@1080 já acompanha a altura). `keys`: as chaves de
    animação do look (`Project.look_keys`)."""
    from . import fit as fitmod
    ow, oh = output_size(info, s)
    if scale != 1.0:
        ow = max(2, int(round(ow * scale / 2)) * 2)
        oh = max(2, int(round(oh * scale / 2)) * 2)
    mode = ""
    if parse_frame(s.frame):  # quadro fixo: o vídeo nunca é esticado (modo desconhecido = cortar)
        mode = s.fit if s.fit in fitmod.MODE_IDS else fitmod.CORTAR
    geometry = fitmod.plan(info.width, info.height, ow, oh, mode, edit=seq is not None)
    depth = depth if depth is not None else (16 if high_depth(s) else 8)
    fps = float(eval_fraction(info.fps_str if s.fps == "original" else s.fps))
    if seq is not None:
        from .sequence import legal_range
        legal = legal_range(seq)
    else:
        legal = media.legal_range(info)
    return Recipe(values, fps, depth, dither=bool(s.dither) and depth == 8, legal=legal, lut=lut_of(values),
                  seq=seq, fit=geometry, net_grain=float(scale) if s.net_grain else 0.0, keys=dict(keys or {}),
                  src_fps=float(info.fps), alpha=wants_alpha(s))


def open_reader(info: media.MediaInfo, frames: Recipe, start: int, total: int, fps_out: str | None,
                perf: media.Perf, seq=None):
    """Leitor em ordem da exportação no tamanho do encaixe: (leitor, quadros a pular no começo)."""
    f = frames.fit
    if seq is not None:
        from .sequence import SequenceReader
        return SequenceReader(seq, f.dec_w, f.dec_h, frames.depth, start, total, hq=True, perf=perf,
                              fps_out=fps_out), 0
    if fps_out:
        # Com troca de fps a decodificação começa no tempo e não no quadro.
        reader = media.FrameReader(info, f.dec_w, f.dec_h, frames.depth, 0, None, fps_out, hq=True, perf=perf,
                                   crop=f.crop)
        return reader, round(start / info.fps * frames.fps)
    return media.FrameReader(info, f.dec_w, f.dec_h, frames.depth, start, total, None, hq=True, perf=perf,
                             crop=f.crop), 0


def preview_frame(engine: Engine, info: media.MediaInfo, values: dict, s: ExportSettings, frame: int, seq=None,
                  scale: float = 1.0, depth: int = 8, keys: dict | None = None):
    """Um quadro do resultado da exportação (o mesmo caminho de `_encode`), para a prévia da janela de
    exportação. Com `scale` = 1 e a profundidade da exportação, é exatamente o quadro gravado."""
    frames = frame_pipeline(info, values, s, seq, scale, depth, keys)
    f = frames.fit
    frame = max(0, min(int(frame), info.frames - 1))
    if seq is not None:
        from . import sequence
        img = sequence.grab(seq, frame, f.dec_w, f.dec_h, frames.depth, hq=True)
    else:
        img = media.grab_frame(info, frame, f.dec_w, f.dec_h, frames.depth, hq=True, crop=f.crop)
    index = round(frame * frames.fps / info.fps) if s.fps != "original" else frame
    return frames.render(engine, img, index)


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
    passes: int = 1          # passadas da GPU (2 no tamanho alvo; 3 se a 2ª passou do tamanho)
    pass_index: int = 0      # passada atual (0 = primeira); `done`/`total` contam os quadros dela
    stage: str = ""          # etapa atual para a fila ("Medindo o volume…", "Passada 1 de 2"); "" = exportando
    chapters: list = field(default_factory=list)  # [(quadro, título)] dos capítulos (`chapters.points`)
    look_keys: dict = field(default_factory=dict)  # chaves de animação do look (`Project.look_keys`)
    subtitles: dict = field(default_factory=dict)  # legendas em tempo da sequência (`subtitles.job_payload`)

    @property
    def progress(self) -> float:
        if not self.total:
            return 0.0
        passes = max(1, self.passes)
        return min(1.0, (min(self.pass_index, passes - 1) + self.done / self.total) / passes)

    def to_dict(self) -> dict:
        """O que é preciso para refazer este trabalho depois (fila guardada pela recuperação automática)."""
        out = {"id": self.id, "nome": self.name, "status": self.status, "saida": self.out_path,
               "inicio": self.start_frame, "fim": self.end_frame, "valores": self.values,
               "config": self.settings.to_dict(), "midia": asdict(self.info),
               "edicao": self.sequence.to_json() if self.sequence is not None else None,
               "capitulos": [[int(q), str(t)] for q, t in self.chapters],
               "legendas": self.subtitles}
        if self.look_keys:
            from . import keyframes, params
            out["chaves"] = keyframes.to_json(keyframes.clean_keys(params.FILM, self.look_keys))
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "ExportJob":
        """Trabalho novo (aguardando, do começo) a partir de `to_dict()`. ValueError se faltar algo."""
        names = {f.name for f in fields(media.MediaInfo)}
        # Campos novos do MediaInfo têm padrão (has_alpha, 1.5): uma fila guardada por uma versão anterior abre.
        needed = {f.name for f in fields(media.MediaInfo) if f.default is MISSING and f.default_factory is MISSING}
        raw = d.get("midia") if isinstance(d, dict) else None
        if not isinstance(raw, dict) or not needed <= set(raw) or not d.get("saida"):
            raise ValueError(_("Trabalho de exportação incompleto."))
        names &= set(raw)
        seq = None
        if isinstance(d.get("edicao"), dict):
            from . import timeline
            seq = timeline.Sequence.from_json(d["edicao"])
        from . import keyframes, params
        return cls(info=media.MediaInfo(**{k: raw[k] for k in names}), values=params.sanitize(d.get("valores") or {}),
                   settings=ExportSettings.from_dict(d.get("config") or {}), out_path=str(d["saida"]),
                   start_frame=int(d.get("inicio") or 0), end_frame=int(d.get("fim", -1)),
                   name=str(d.get("nome") or ""), sequence=seq,
                   chapters=[(int(q), str(t)) for q, t in d.get("capitulos") or []],
                   look_keys=keyframes.to_json(keyframes.clean_keys(params.FILM, d.get("chaves"))),
                   subtitles=d.get("legendas") if isinstance(d.get("legendas"), dict) else {})


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
    chapters_path = None
    subs_embed = None
    keep_partial = False
    try:
        if job.chapters:
            from . import chapters
            chapters_path = chapters.export_file(job.chapters, s.container, start, end + 1, info.fps)
        if job.subtitles:
            from . import subtitles
            subs_embed = subtitles.export_file(job.subtitles, s.container, start, end + 1, info.fps)
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
        run = _Run(info, perf, w, h, fps_str, fps_out, fps_val, depth, start, total, start_time, duration, target,
                   seq, mix_path, chapters_path, subs_embed)
        if wants_loudness(s) and not _measure_loudness(job, run, s):
            return
        if _encode_passes(job, engine, run, s):
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
        if chapters_path:
            system.remove_file(chapters_path)
        if subs_embed is not None:
            system.remove_file(subs_embed.path)


@dataclass
class _Run:
    """O que vale para todas as passadas de um trabalho (calculado uma vez em `run_job`)."""
    info: media.MediaInfo
    perf: media.Perf
    w: int
    h: int
    fps_str: str
    fps_out: str | None
    fps_val: float
    depth: int
    start: int
    total: int
    start_time: float
    duration: float
    target: str
    seq: Any
    mix_path: str | None
    chapters_path: str | None = None  # FFMETADATA dos capítulos (apagado no fim do run_job)
    subtitles: Any = None             # faixa de legenda (subtitles.Embed; o arquivo é apagado no fim do run_job)
    loud: dict | None = None  # volume medido (loudnorm.measure) para o loudnorm da gravação


def _measure_loudness(job: ExportJob, run: _Run, s: ExportSettings) -> bool:
    """1ª passada do volume alvo: mede o som que vai para o arquivo (o trecho do original ou a mixagem).
    False quando cancelou ou deu erro (o trabalho já fica marcado)."""
    from . import loudnorm
    run.loud = None
    if _audio_args(s, run.info, 0.0 if run.mix_path else run.start_time) == ["-an"]:
        return True
    path = run.mix_path or run.info.path
    start, dur = (0.0, 0.0) if run.mix_path else (run.start_time, run.duration)
    job.stage = _("Medindo o volume do som…")
    try:
        measured = loudnorm.measure(path, float(s.loudness), float(s.true_peak), start, dur, job.cancel, run.perf)
    except RuntimeError as exc:
        job.status = "erro"
        job.error = str(exc)[-1500:]
        return False
    if measured is None or job.cancel.is_set():
        job.status = "cancelado"
        return False
    run.loud = measured if loudnorm.audible(measured) else None  # silêncio: nada a ajustar
    job.stage = ""
    return True


def _encode_passes(job: ExportJob, engine: Engine, run: _Run, s: ExportSettings) -> bool:
    """Uma passada; no tamanho alvo, as duas do x264/x265 (a GPU renderiza o vídeo duas vezes). Se a 2ª passa
    do tamanho (raro: o controle de taxa erra por pouco), refaz só a 2ª com a taxa corrigida."""
    if not uses_target(s):
        return _encode(job, engine, run, s)
    import shutil
    import tempfile
    from dataclasses import replace
    rate = target_bitrate(s, run.info, run.duration, run.start_time if not run.mix_path else 0.0)
    if rate < MIN_TARGET_RATE:
        job.status = "erro"
        job.error = target_too_small_message(s, run.duration)
        return False
    limit = target_bytes(s)
    cur = replace(s, bitrate=round(rate, 4))
    tmp = tempfile.mkdtemp(prefix="pelicula_passadas_")
    job.passes = 2
    try:
        for p in range(3):
            n = 1 if p == 0 else 2
            job.pass_index = p
            job.stage = _("Passada {n} de {total}").format(n=p + 1, total=job.passes)
            if not _encode(job, engine, run, cur, two_pass=n, cwd=tmp):
                return False
            if n == 1:
                continue
            size = os.path.getsize(run.target)
            if size <= limit:
                job.stage = ""
                return True
            if p == 2:
                break
            job.passes = 3
            cur = replace(cur, bitrate=round(cur.bitrate * limit / size * 0.96, 4))
        job.status = "erro"
        job.error = _("O vídeo não coube em {mb} MB. Diminua a resolução ou o trecho, ou aumente o tamanho "
                      "alvo.").format(mb=fmt_mb(float(s.target_mb)))
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _encode(job: ExportJob, engine: Engine, run: _Run, s: ExportSettings, two_pass: int = 0,
            cwd: str | None = None) -> bool:
    """Lê, aplica o look e codifica em `run.target` (o parcial). True quando todos os quadros foram gravados;
    senão marca o trabalho como cancelado ou com erro e devolve False. `two_pass`: passada do tamanho alvo
    (o codificador roda em `cwd`, onde fica o registro das passadas)."""
    info, perf, total, depth = run.info, run.perf, run.total, run.depth
    job.encoded = job.rendered = job.done = 0
    pipe = media.NamedPipe(False) if media.use_named_pipes() else None
    cmd = build_encoder_cmd(run.target, info, s, run.w, run.h, run.fps_str, depth, run.start_time, run.duration,
                            pipe.name if pipe else "pipe:0", audio_path=run.mix_path, chapters_path=run.chapters_path,
                            two_pass=two_pass,
                            loudness_measured=run.loud, subtitles=run.subtitles)
    frames = frame_pipeline(info, job.values, s, run.seq, keys=job.look_keys)
    reader, skip = open_reader(info, frames, run.start, total, run.fps_out, perf, run.seq)
    enc = subprocess.Popen(cmd, stdin=None if pipe else subprocess.PIPE, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, cwd=cwd, **perf.popen_kwargs())
    err_buf = bytearray()
    t0 = time.time()

    def update() -> None:
        d = job.encoded if job.encoded > 0 else job.rendered
        job.done = min(d, total)
        if not job.t_warm and d >= job.warmup:
            job.t_warm = time.time()
        el = time.time() - t0
        job.fps_rate = d / el if el > 0 else 0.0
        later = max(0, job.passes - job.pass_index - 1) * total  # passadas que ainda vêm depois desta
        job.eta = (total - d + later) / job.fps_rate if job.fps_rate > 0 else 0.0

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
    first_index = round(run.start * run.fps_val / info.fps) if run.fps_out else run.start
    i = 0
    try:
        while True:
            img = frames_q.get()
            if img is None:
                break
            if job.cancel.is_set() or write_err:
                break
            out = frames.render(engine, img, first_index + i)
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
                  frames: int = 60, limit: float = 15.0, sequence=None, stats: dict | None = None,
                  keys: dict | None = None) -> float:
    """Exporta um trecho num arquivo temporário e devolve a velocidade real (quadros/s) de uma passada.

    Os primeiros quadros (abertura do ffmpeg e do codificador) ficam de fora da conta, e a
    medição para sozinha depois de `limit` segundos. Com `stats` (um dicionário), grava ali
    `"video_bytes_per_second"`: quanto o vídeo do trecho ocupou (estimativa do tamanho do arquivo).
    O tamanho alvo e o volume alvo ficam de fora (a janela conta as duas passadas).
    """
    import shutil
    import tempfile
    s = ExportSettings.from_dict(settings.to_dict())
    s.audio = "none"
    s.target_mb = 0.0
    s.loudness = 0.0
    tmp = tempfile.mkdtemp(prefix="pelicula_medida_")
    start = 0 if info.frames <= frames * 2 else info.frames // 3
    out = os.path.join(tmp, "teste." + s.container)
    job = ExportJob(info=info, values=values, settings=s, out_path=out, start_frame=start,
                    end_frame=min(info.frames - 1, start + frames - 1), sequence=sequence, look_keys=dict(keys or {}))
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
        if stats is not None and job.status == "concluido" and job.done > 0 and os.path.isfile(out):
            fps = info.fps if s.fps == "original" else eval_fraction(s.fps)
            stats["video_bytes_per_second"] = os.path.getsize(out) / (job.done / max(fps, 1e-3))
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
# Quadro com transparência (h × w × 4): só PNG e TIFF guardam o alfa.
STILL_ALPHA_ARGS = {".png": ["-pix_fmt", "rgba64be"], ".tif": ["-pix_fmt", "rgba64le", "-compression_algo", "deflate"],
                    ".tiff": ["-pix_fmt", "rgba64le"]}


def save_still(img, path: str) -> None:
    """Grava um quadro RGB de 16 bits (array h × w × 3) em PNG, TIFF ou JPEG, conforme a extensão. Com 4 canais
    (RGBA de cor direta), PNG e TIFF guardam a transparência; outro formato levanta ValueError.

    Grava num parcial ao lado e só então troca o destino; se o ffmpeg falhar, levanta RuntimeError e o
    arquivo antigo com o mesmo nome fica intacto.
    """
    h, w = img.shape[:2]
    ext = Path(path).suffix.lower()
    rgba = img.ndim == 3 and img.shape[2] == 4
    if rgba and ext not in STILL_ALPHA_ARGS:
        raise ValueError(_("Só PNG e TIFF guardam a transparência."))
    part = system.partial_path(path)
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba64le" if rgba else "rgb48le",
           "-s", f"{w}x{h}", "-i", "pipe:0", *(STILL_ALPHA_ARGS if rgba else STILL_ARGS).get(ext, []),
           "-frames:v", "1", "-update", "1", part]
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
