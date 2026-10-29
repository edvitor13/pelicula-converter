"""Leitura e gravação de vídeo com o ffmpeg (processos externos via pipe)."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from .i18n import _

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".dpx", ".exr"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".webm", ".m4v", ".mts", ".m2ts", ".wmv", ".mpg", ".mpeg",
             ".nev", ".r3d", ".braw", ".flv", ".3gp", ".ts"}
AUDIO_EXT = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".wma"}

_tools: dict[str, str | None] = {"ffmpeg": None, "ffprobe": None}


def _candidates() -> list[Path]:
    if sys.platform != "win32":
        return [Path(d) for d in ("/usr/local/bin", "/usr/bin", "/opt/homebrew/bin", "/snap/bin")]
    out = []
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    for d in (r"C:\FFMPEG\ffmpeg\bin", r"C:\FFMPEG\bin", r"C:\ffmpeg\bin", os.path.join(pf, "ffmpeg", "bin"),
              os.path.join(local, "Microsoft", "WinGet", "Links"), os.path.join(pf, "ShareX")):
        out.append(Path(d))
    return out


def reset_cache() -> None:
    """Esquece codificadores e acelerações detectados (depois de trocar o ffmpeg)."""
    global _ENCODERS, _HWACCELS, _DECODERS, _FILTERS
    _ENCODERS = None
    _HWACCELS = None
    _DECODERS = None
    _FILTERS = None
    _WORKING.clear()


def configure(folder: str | None = None) -> bool:
    """Procura ffmpeg e ffprobe (pasta escolhida, PATH ou locais comuns)."""
    from . import deps
    exe = ".exe" if sys.platform == "win32" else ""
    dirs = [Path(folder)] if folder else []
    dirs.append(deps.ffmpeg_dir())
    for name in ("ffmpeg", "ffprobe"):
        found = None
        for d in dirs:
            p = d / f"{name}{exe}"
            if p.is_file():
                found = str(p)
                break
        if not found:
            found = shutil.which(name)
        if not found:
            for d in _candidates():
                p = d / f"{name}{exe}"
                if p.is_file():
                    found = str(p)
                    break
        _tools[name] = found
    reset_cache()
    return bool(_tools["ffmpeg"] and _tools["ffprobe"])


def ffmpeg() -> str:
    if not _tools["ffmpeg"]:
        configure()
    if not _tools["ffmpeg"]:
        raise RuntimeError(_("ffmpeg não encontrado. Use Configurações > Componentes para baixar."))
    return _tools["ffmpeg"]


def ffprobe() -> str:
    if not _tools["ffprobe"]:
        configure()
    if not _tools["ffprobe"]:
        raise RuntimeError(_("ffprobe não encontrado."))
    return _tools["ffprobe"]


def tool_dir() -> str:
    return str(Path(_tools["ffmpeg"]).parent) if _tools["ffmpeg"] else ""


@dataclass
class MediaInfo:
    path: str
    width: int
    height: int
    fps: float
    fps_str: str
    frames: int
    duration: float
    pix_fmt: str
    bit_depth: int
    codec: str
    profile: str
    bitrate: int
    color_space: str
    color_range: str
    color_transfer: str
    color_primaries: str
    has_audio: bool
    audio_codec: str
    container: str
    is_image: bool
    has_alpha: bool = False  # imagem com transparência (`stream_has_alpha`; WebM com alpha_mode=1; PNG com paleta)
    # Sequência de imagens numeradas (`path` é o padrão do ffmpeg, plano_%04d.png): número do 1º quadro; -1 = não é.
    seq_start: int = -1

    @property
    def ext(self) -> str:
        return Path(self.path).suffix.lower()

    @property
    def is_sequence(self) -> bool:
        return self.seq_start >= 0

    def summary(self) -> str:
        if self.is_sequence:
            return _("{w}×{h} • {fps} fps • sequência de {n} imagens {codec} • {bits} bits").format(
                w=self.width, h=self.height, fps=f"{self.fps:.3f}", n=self.frames, codec=self.codec.upper(),
                bits=self.bit_depth)
        if self.is_image:
            return _("{w}×{h} • imagem {codec} • {bits} bits").format(
                w=self.width, h=self.height, codec=self.codec.upper(), bits=self.bit_depth)
        if self.bitrate >= 1_000_000:
            mb = f" • {self.bitrate / 1e6:.0f} Mb/s"
        elif self.bitrate:
            mb = f" • {self.bitrate / 1e3:.0f} kb/s"
        else:
            mb = ""
        return _("{w}×{h} • {fps} fps • {codec} {pix} • {bits} bits").format(
            w=self.width, h=self.height, fps=f"{self.fps:.3f}", codec=self.codec.upper(), pix=self.pix_fmt,
            bits=self.bit_depth) + mb


def pix_depth(pix: str) -> int:
    """Bits por canal de um formato de pixel do ffmpeg (yuv420p10le → 10, rgb48le → 16, nv12 → 8)."""
    pix = pix or ""
    if pix in ("p010le", "p010be"):
        return 10
    if pix in ("p016le", "p016be", "rgb48le", "rgb48be", "rgba64le", "rgba64be", "bgr48le", "bgr48be",
               "gray16le", "gray16be", "ya16le", "ya16be"):
        return 16
    m = re.search(r"(?:p|gray|gbrp|gbrap)(\d{1,2})(le|be)$", pix)
    return int(m.group(1)) if m else 8


# Formatos de pixel do ffmpeg com canal alfa (prefixos): yuva420p…/yuva444p10le (ProRes 4444), gbrap*, rgba/bgra/
# argb/abgr (e rgba64*), ya8/ya16 (cinza com alfa), ayuv/vuya. "pal8" (paleta) pode ter transparência, mas o
# formato sozinho não diz: só o ffprobe do arquivo (`probe`) decide. "rgb0"/"0rgb"/"bgr0" não têm alfa.
ALPHA_PIX_PREFIXES = ("yuva", "gbrap", "rgba", "bgra", "argb", "abgr", "ya8", "ya16", "ayuv", "vuya")


def pix_has_alpha(pix: str) -> bool:
    """O formato de pixel tem canal alfa? (yuva444p10le → True, yuv420p → False)"""
    return (pix or "").lower().startswith(ALPHA_PIX_PREFIXES)


def stream_has_alpha(vs: dict) -> bool:
    """O fluxo de vídeo do ffprobe tem transparência: formato de pixel com alfa, ou VP8/VP9 no WebM com a
    marca `alpha_mode=1` (o ffprobe mostra yuv420p porque o decodificador nativo descarta o alfa)."""
    if pix_has_alpha(vs.get("pix_fmt", "")):
        return True
    tags = {str(k).lower(): str(v).strip() for k, v in (vs.get("tags") or {}).items()}
    return vs.get("codec_name") in ("vp8", "vp9") and tags.get("alpha_mode") == "1"


ALPHA_DECODERS = {"vp9": "libvpx-vp9", "vp8": "libvpx"}


def alpha_decoder(codec: str) -> list[str]:
    """Decodificador que entrega o alfa, para pôr antes do `-i`: o VP8/VP9 nativo do ffmpeg descarta o alfa do
    WebM; o libvpx não. [] para os outros formatos (ou se esta compilação do ffmpeg não tem o libvpx)."""
    name = ALPHA_DECODERS.get(codec or "")
    return ["-c:v", name] if name and name in decoders() else []


def decodes_alpha(info: MediaInfo) -> bool:
    """A leitura entrega a transparência deste arquivo? (`has_alpha`; o VP8/VP9 só com o libvpx nesta compilação
    do ffmpeg — sem ele o clipe sai opaco, como antes)."""
    if not getattr(info, "has_alpha", False):
        return False
    return info.codec not in ALPHA_DECODERS or bool(alpha_decoder(info.codec))


def _palette_alpha(path: str) -> bool:
    """Imagem com paleta (pal8: PNG, GIF) tem transparência? O formato não diz: decodifica e olha o alfa."""
    try:
        res = subprocess.run([ffmpeg(), "-v", "error", "-nostdin", "-i", path, "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgba", "pipe:1"], capture_output=True, creationflags=NO_WINDOW,
                             timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    alpha = res.stdout[3::4]
    return res.returncode == 0 and bool(alpha) and min(alpha) < 255


def _depth(pix: str, raw: str | None) -> int:
    d = pix_depth(pix)
    if d > 8:
        return d
    try:
        return max(8, int(raw)) if raw else 8
    except ValueError:
        return 8


def _probe_json(path: str) -> dict:
    cmd = [ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]
    res = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", "replace").strip() or _("Não foi possível ler o arquivo."))
    return json.loads(res.stdout.decode("utf-8", "replace") or "{}")


def probe(path: str, fps_str: str = "") -> MediaInfo:
    """Metadados de um arquivo. Um padrão de sequência de imagens (plano_%04d.png) lê o primeiro trecho de
    números seguidos da pasta, a `fps_str` quadros por segundo (padrão 24)."""
    if is_sequence_pattern(path):
        found = sequence_from_pattern(path)
        if found is None:
            raise RuntimeError(_("Nenhum quadro da sequência foi encontrado: {caminho}").format(caminho=path))
        return probe_sequence(found, fps_str or "24/1")
    return _info_from(path, _probe_json(path))


def probe_source(path: str):
    """Arquivo para o modo Edição: vídeo, imagem parada ou só áudio (música, narração).

    Devolve um `timeline.Source`; arquivos só de som têm `has_video=False`.
    """
    from . import timeline
    if is_sequence_pattern(path):
        return timeline.Source.from_info(probe(path))
    data = _probe_json(path)
    streams = data.get("streams", [])
    has_video = any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
                    for s in streams)
    if has_video:
        return timeline.Source.from_info(_info_from(path, data))
    aus = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if aus is None:
        raise RuntimeError(_("O arquivo não tem imagem nem som."))
    fmt = data.get("format", {})
    try:
        dur = float(aus.get("duration") or fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    if dur <= 0:
        raise RuntimeError(_("Não foi possível saber a duração do som."))
    return timeline.Source(path=path, width=0, height=0, fps=24.0, fps_str="24/1", frames=1, duration=dur,
                           is_image=False, has_video=False, has_audio=True, codec="",
                           bitrate=int(aus.get("bit_rate") or fmt.get("bit_rate") or 0),
                           audio_codec=aus.get("codec_name", ""), container=fmt.get("format_name", ""))


def _info_from(path: str, data: dict) -> MediaInfo:
    streams = data.get("streams", [])
    vs = next((s for s in streams if s.get("codec_type") == "video"
               and not s.get("disposition", {}).get("attached_pic")), None)
    if vs is None:
        raise RuntimeError(_("O arquivo não tem imagem de vídeo."))
    aus = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    w, h = int(vs.get("width", 0)), int(vs.get("height", 0))
    rot = 0
    for sd in vs.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = int(vs.get("tags", {}).get("rotate", rot) or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    ext = Path(path).suffix.lower()
    is_image = ext in IMAGE_EXT or fmt.get("format_name", "").endswith("_pipe") or fmt.get("format_name") == "image2"
    rate = vs.get("r_frame_rate") or vs.get("avg_frame_rate") or "24/1"
    try:
        fr = Fraction(rate)
        if fr <= 0 or fr > 1000:
            raise ValueError
    except (ValueError, ZeroDivisionError):
        fr = Fraction(24, 1)
    if is_image:
        fr = Fraction(24, 1)
    dur = float(vs.get("duration") or fmt.get("duration") or 0.0)
    nb = vs.get("nb_frames")
    frames = int(nb) if nb and str(nb).isdigit() and int(nb) > 0 else int(round(dur * float(fr)))
    if is_image:
        frames, dur = 1, 0.0
    pix = vs.get("pix_fmt", "")
    alpha = stream_has_alpha(vs) or (is_image and pix == "pal8" and _palette_alpha(path))
    return MediaInfo(
        path=path, width=w, height=h, fps=float(fr), fps_str=f"{fr.numerator}/{fr.denominator}",
        frames=max(frames, 1), duration=dur, pix_fmt=pix, bit_depth=_depth(pix, vs.get("bits_per_raw_sample")),
        codec=vs.get("codec_name", "?"), profile=vs.get("profile", "") or "",
        bitrate=int(vs.get("bit_rate") or fmt.get("bit_rate") or 0),
        color_space=vs.get("color_space", "") or "", color_range=vs.get("color_range", "") or "",
        color_transfer=vs.get("color_transfer", "") or "", color_primaries=vs.get("color_primaries", "") or "",
        has_audio=aus is not None, audio_codec=(aus or {}).get("codec_name", ""),
        container=fmt.get("format_name", ""), is_image=is_image, has_alpha=bool(alpha),
    )


# ------------------------------------------------------------------ sequências de imagens numeradas
# plano_0001.png, plano_0002.png… viram uma fonte só: o caminho é o padrão do ffmpeg (plano_%04d.png) e
# `seq_start` é o número do primeiro quadro; a leitura usa `-f image2 -framerate -start_number` (`sequence_input`).
# O ffmpeg para de ler no primeiro número que falta, então a sequência é sempre o trecho de números seguidos que
# contém o arquivo escolhido (`ImageSequence.gaps` lista os buracos da pasta, para o aviso).
SEQUENCE_EXT = (".png", ".tif", ".tiff", ".jpg", ".jpeg", ".exr", ".dpx")
_SEQUENCE_DECODER = {".exr": "exr", ".dpx": "dpx"}  # só entram se o ffmpeg desta máquina decodifica
_NUMBERED = re.compile(r"^(.*?)(\d+)(\.[A-Za-z0-9]+)$")
_TOKEN = re.compile(r"(?<!%)%(0\d+)?d")


def sequence_exts() -> tuple[str, ...]:
    """Extensões que podem formar uma sequência de imagens nesta máquina (EXR e DPX só com o decodificador)."""
    try:
        dec = decoders()
    except Exception:  # noqa: BLE001 — sem ffmpeg: fica com as comuns
        dec = set()
    return tuple(e for e in SEQUENCE_EXT if e not in _SEQUENCE_DECODER or _SEQUENCE_DECODER[e] in dec)


@dataclass(frozen=True)
class ImageSequence:
    """Imagens numeradas de uma pasta (`find_sequence`)."""

    pattern: str              # caminho com o número trocado por %0Nd (ou %d, sem zeros à esquerda)
    first: int                # número do primeiro quadro do trecho de números seguidos
    count: int                # quadros seguidos a partir de `first` (o que entra na montagem)
    numbers: tuple[int, ...]  # todos os números achados na pasta, em ordem (com os buracos)

    @property
    def last(self) -> int:
        return self.first + self.count - 1

    def file(self, n: int) -> str:
        return sequence_file(self.pattern, n)

    @property
    def gaps(self) -> list[tuple[int, int]]:
        """Buracos da numeração: (primeiro, último número que falta), do menor ao maior número achado."""
        out, prev = [], None
        for n in self.numbers:
            if prev is not None and n > prev + 1:
                out.append((prev + 1, n - 1))
            prev = n
        return out

    @property
    def label(self) -> str:
        return sequence_label(self.pattern, self.first, self.count)


def is_sequence_pattern(path: str) -> bool:
    """O caminho é o padrão de uma sequência de imagens (plano_%04d.png)?"""
    return bool(path) and Path(path).suffix.lower() in SEQUENCE_EXT and bool(_TOKEN.search(os.path.basename(path)))


def sequence_file(pattern: str, n: int) -> str:
    """O arquivo do quadro número `n` de um padrão (plano_%04d.png, 12 → plano_0012.png)."""
    folder, name = os.path.split(pattern)
    return os.path.join(folder, name % int(n)) if folder else name % int(n)


def sequence_label(pattern: str, first: int, count: int) -> str:
    """Nome para mostrar: plano_[0001-0120].png."""
    name = os.path.basename(pattern)
    m = _TOKEN.search(name)
    if not m:
        return name
    width = int(m.group(1) or 0)
    tag = f"[{first:0{width}d}-{first + max(1, count) - 1:0{width}d}]"
    return (name[:m.start()] + tag + name[m.end():]).replace("%%", "%")


def sequence_stem(path: str) -> str:
    """Nome-base para arquivos derivados (exportação, quadro salvo): plano_%04d.png → plano."""
    stem = Path(path).stem
    if not is_sequence_pattern(path):
        return stem
    return _TOKEN.sub("", stem).replace("%%", "%").rstrip("_-. ") or "sequencia"


def path_exists(path: str, seq_start: int = -1) -> bool:
    """O arquivo existe? Numa sequência de imagens, o primeiro quadro dela (`seq_start`; -1 = qualquer um)."""
    if not is_sequence_pattern(path):
        return os.path.exists(path)
    if seq_start >= 0:
        return os.path.exists(sequence_file(path, seq_start))
    return sequence_from_pattern(path) is not None


def _numbers(folder: str, prefix: str, ext: str) -> list[str]:
    """Os números (texto, com os zeros) dos arquivos prefixo + número + extensão de uma pasta."""
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return []
    out = []
    for name in names:
        m = _NUMBERED.match(name)
        if m and m.group(1) == prefix and m.group(3) == ext:
            out.append(m.group(2))
    return out


def _sequence(folder: str, prefix: str, ext: str, digits: list[str], pick: str | None,
              width: int | None = None) -> ImageSequence | None:
    """Monta a sequência: com zeros à esquerda (%0Nd, só números de N dígitos) ou sem (%d)."""
    if width is None:
        w = len(pick) if pick else max((len(d) for d in digits), default=1)
        padded = len({len(d) for d in digits}) == 1 or any(len(d) == w and len(d) > 1 and d[0] == "0"
                                                            for d in digits)
        width = w if padded and w > 1 else 0
    if width:
        keep = sorted({int(d) for d in digits if len(d) == width})
        token = f"%0{width}d"
    else:
        keep = sorted({int(d) for d in digits if len(d) == 1 or d[0] != "0"})
        token = "%d"
    if not keep:
        return None
    have = set(keep)
    start = int(pick) if pick is not None and int(pick) in have else keep[0]
    while start - 1 in have:
        start -= 1
    count = 1
    while start + count in have:
        count += 1
    if count < 2:
        return None
    name = prefix.replace("%", "%%") + token + ext.replace("%", "%%")
    return ImageSequence(os.path.join(folder, name) if folder else name, start, count, tuple(keep))


def find_sequence(path: str, exts: tuple[str, ...] | None = None) -> ImageSequence | None:
    """Sequência de imagens numeradas a partir de um arquivo (plano_0001.png) ou de uma pasta (o maior grupo de
    imagens numeradas dela). None se não há pelo menos dois quadros seguidos."""
    exts = sequence_exts() if exts is None else exts
    if os.path.isdir(path):
        groups: dict[tuple[str, str], list[str]] = {}
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return None
        for name in names:
            m = _NUMBERED.match(name)
            if m and m.group(3).lower() in exts:
                groups.setdefault((m.group(1), m.group(3)), []).append(m.group(2))
        best = None
        for (prefix, ext), digits in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            found = _sequence(path, prefix, ext, digits, None)
            if found is not None and (best is None or found.count > best.count):
                best = found
        return best
    folder, name = os.path.split(path)
    m = _NUMBERED.match(name)
    if not m or m.group(3).lower() not in exts:
        return None
    prefix, pick, ext = m.groups()
    return _sequence(folder, prefix, ext, _numbers(folder, prefix, ext), pick)


def sequence_from_pattern(pattern: str, start: int = -1) -> ImageSequence | None:
    """A sequência de um padrão já gravado (projeto, relocalizar): o trecho seguido que começa em `start` (ou
    o primeiro da pasta)."""
    folder, name = os.path.split(pattern)
    m = _TOKEN.search(name)
    if not m:
        return None
    prefix, ext = name[:m.start()].replace("%%", "%"), name[m.end():].replace("%%", "%")
    digits = _numbers(folder, prefix, ext)
    width = int(m.group(1) or 0)
    found = _sequence(folder, prefix, ext, digits, None, width=width)
    if found is None or start < 0 or start == found.first:
        return found
    pick = f"{start:0{width}d}" if width else str(start)
    other = _sequence(folder, prefix, ext, digits, pick, width=width)
    return other if other is not None and other.first == start else found


def probe_sequence(found: ImageSequence, fps_str: str = "24/1") -> MediaInfo:
    """`MediaInfo` de uma sequência de imagens: o primeiro quadro diz o tamanho, a cor e a transparência;
    `fps_str` é a velocidade escolhida ao importar (padrão: a da montagem)."""
    first = found.file(found.first)
    info = _info_from(first, _probe_json(first))
    try:
        fr = Fraction(str(fps_str or "24/1"))
        if fr <= 0 or fr > 1000:
            raise ValueError
    except (ValueError, ZeroDivisionError):
        fr = Fraction(24, 1)
    return dataclasses.replace(info, path=found.pattern, fps=float(fr), fps_str=f"{fr.numerator}/{fr.denominator}",
                               frames=found.count, duration=found.count / float(fr), is_image=False, bitrate=0,
                               container="image2", seq_start=found.first)


def sequence_input(info: MediaInfo, start_frame: int = 0) -> list[str]:
    """Opções de entrada (antes do `-i`) para ler uma sequência de imagens a partir do quadro `start_frame`."""
    return ["-f", "image2", "-framerate", info.fps_str or "24/1",
            "-start_number", str(int(info.seq_start) + max(0, int(start_frame)))]


def _in_matrix(info: MediaInfo) -> str:
    cs = info.color_space
    if cs in ("bt709",):
        return "bt709"
    if cs in ("bt470bg", "smpte170m", "bt601"):
        return "bt601"
    if cs.startswith("bt2020"):
        return "bt2020"
    if cs == "smpte240m":
        return "smpte240m"
    return "bt709" if info.height >= 720 else "bt601"


def _in_range(info: MediaInfo) -> str:
    if info.color_range in ("pc", "jpeg") or info.pix_fmt.startswith("yuvj"):
        return "full"
    return "limited" if info.pix_fmt.startswith(("yuv", "nv", "p0")) else "auto"


def legal_range(info) -> bool:
    """O `FrameReader` expande este arquivo da faixa legal para 0–1? (`build_plan(..., legal=...)`)

    Vídeo YUV de faixa legal (o comum): sim, o shader recebe v = (código − 64)/876. Faixa cheia
    (`color_range` pc/jpeg, yuvj) e imagens/vídeo RGB: não, v = código/1023. Aceita `MediaInfo` ou
    qualquer objeto com `pix_fmt` e `color_range` (um `timeline.Source`, por exemplo).
    """
    return _in_range(info) == "limited"


# Perfis de entrada que não são log de câmera: a leitura deles continua em inteiros de 0 a 1 (8 ou 16 bits).
# Os outros (log) num vídeo de faixa legal são lidos em ponto flutuante (`float_input`).
DISPLAY_PROFILES = frozenset({"rec709", "linear", "hlg", "pq"})

# Matriz YUV → RGB do arquivo (`_in_matrix`) com o nome que o zscale (zimg) usa.
_ZSCALE_MATRIX = {"bt709": "709", "bt601": "470bg", "bt2020": "2020_ncl", "smpte240m": "240m"}


def float_input(info, profile: str | None) -> bool:
    """A leitura de `info` para o perfil de entrada `profile` vem em ponto flutuante (super-brancos)?

    Log de câmera num vídeo YUV de faixa legal: o decodificador expande a faixa (v = (código − 64)/876) sem
    cortar em 0–1 — o que a câmera gravou acima do código 940 (e abaixo do 64) chega ao shader, que volta ao
    domínio da curva como sempre (`look.INPUT_DOMAIN`). Precisa do filtro zscale no ffmpeg (`has_zscale`); sem
    ele, e em Rec.709, linear, HLG e PQ, imagens e arquivos de faixa cheia, a leitura de sempre (8 ou 16 bits).
    """
    if not profile or profile in DISPLAY_PROFILES or getattr(info, "is_image", False):
        return False
    return legal_range(info) and has_zscale()


def _exact_graph(info, width: int, height: int, flags: str, threads: int, pix: str) -> str:
    """Filtros da leitura em float de log num vídeo de faixa legal (`FrameReader.float`), saindo em `pix`
    (`gbrpf32le`).

    O swscale redimensiona como sempre, mas fica em YUV 4:4:4 de 16 bits sem mexer na faixa (o código de 10 bits
    vira código·64, exato, inclusive acima do 940); o zscale só aplica a matriz do arquivo e expande a faixa, sem
    cortar em 0–1. O swscale direto para RGB corta em 0–1. Redimensionar no zscale mudaria a reconstrução do croma
    nas bordas de cor (até 17% num padrão de teste): por isso ele não redimensiona."""
    return (f"scale={width}:{height}:flags={flags}:in_range=limited:out_range=limited:threads={threads},"
            f"format=yuv444p16le,zscale=matrixin={_ZSCALE_MATRIX[_in_matrix(info)]}:rangein=limited:range=full,"
            f"format={pix}")


# Transferências HDR do ffprobe (`color_transfer`) → perfil de entrada. O vídeo HDR do iPhone (Dolby
# Vision 8.4) é marcado como HLG (arib-std-b67).
HDR_TRANSFERS = {"arib-std-b67": "hlg", "smpte2084": "pq"}


def detect_profile(info) -> str | None:
    """Perfil de entrada sugerido pelos metadados do arquivo (só HDR: HLG ou PQ); None se não há."""
    return HDR_TRANSFERS.get(str(getattr(info, "color_transfer", "") or "").strip().lower())


def auto_profile(current: str, info, default: str = "rec709") -> str | None:
    """Novo perfil de entrada ao abrir `info`, ou None para manter `current`.

    Os perfis HDR seguem os metadados do arquivo: com o perfil no padrão (Rec.709) ou num perfil HDR,
    um vídeo HLG/PQ escolhe o seu e um arquivo sem HDR volta ao padrão. Perfis log (escolhidos à mão,
    porque câmeras não marcam a curva log nos metadados) nunca mudam.
    """
    if current != default and current not in HDR_TRANSFERS.values():
        return None
    want = detect_profile(info) or default
    return None if want == current else want


PRIORITY = {"baixa": 0x00004000, "normal": 0, "alta": 0x00008000}


@dataclass
class Perf:
    """Uso da máquina: núcleos, prioridade, decodificação por hardware e memória."""

    threads: int = 0          # 0 = todos os núcleos
    priority: str = "normal"  # baixa | normal | alta
    hwaccel: str = "none"     # none | auto | cuda | d3d11va | dxva2 | qsv
    gpu: int = 0              # placa NVIDIA usada pelo NVENC
    buffer: int = 4           # quadros guardados na memória entre as etapas

    def flags(self) -> int:
        return NO_WINDOW | PRIORITY.get(self.priority, 0) if sys.platform == "win32" else 0

    def popen_kwargs(self) -> dict:
        """Prioridade do processo do ffmpeg em cada sistema."""
        if sys.platform == "win32":
            return {"creationflags": self.flags()}
        nice = {"baixa": 10, "normal": 0, "alta": 0}.get(self.priority, 0)
        return {"preexec_fn": (lambda: os.nice(nice))} if nice else {}


class NamedPipe:
    """Pipe nomeado do Windows com buffer grande: bem mais rápido que stdin/stdout para quadros 4K."""

    def __init__(self, inbound: bool, size: int = 1 << 20):
        import _winapi
        import uuid
        self._w = _winapi
        self.inbound = inbound
        self.name = "\\\\.\\pipe\\pelicula_" + uuid.uuid4().hex
        access = 0x1 if inbound else 0x2  # PIPE_ACCESS_INBOUND / PIPE_ACCESS_OUTBOUND
        self.handle = _winapi.CreateNamedPipe(self.name, access, 0, 1, size, size, 0, _winapi.NULL)
        self.file = None

    def connect(self, proc: subprocess.Popen, timeout: float = 60.0):
        """Espera o ffmpeg abrir o pipe; se ele morrer antes, destrava e avisa."""
        import msvcrt
        import time
        done = threading.Event()
        errs: list[OSError] = []

        def run():
            try:
                self._w.ConnectNamedPipe(self.handle, self._w.NULL)
            except OSError as exc:
                # 535: o ffmpeg abriu o pipe antes desta chamada. 232: ele já gravou tudo e fechou (um quadro
                # pequeno cabe no buffer); os dados continuam no pipe para ler.
                if getattr(exc, "winerror", 0) not in (535, 232):
                    errs.append(exc)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        t0 = time.time()
        while not done.wait(0.05):
            # O ffmpeg pode ter terminado depois de gravar: dá tempo para a conexão acontecer antes de desistir.
            if (proc.poll() is not None and not done.wait(0.5)) or time.time() - t0 > timeout:
                try:
                    # O outro lado do pipe precisa do acesso oposto: quem lê (inbound) é destravado
                    # por alguém que escreve, e vice-versa.
                    access = 0x40000000 if self.inbound else 0x80000000  # GENERIC_WRITE / GENERIC_READ
                    h = self._w.CreateFile(self.name, access, 0, self._w.NULL, self._w.OPEN_EXISTING, 0, self._w.NULL)
                    self._w.CloseHandle(h)
                except OSError:
                    pass
                done.wait(2)
                self.close()
                raise RuntimeError(_("O ffmpeg terminou antes de começar a transferir os quadros."))
        if errs:
            self.close()
            raise errs[0]
        fd = msvcrt.open_osfhandle(self.handle, os.O_RDONLY if self.inbound else os.O_WRONLY)
        self.file = open(fd, "rb" if self.inbound else "wb", buffering=0)
        return self.file

    def close(self) -> None:
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None
        elif self.handle is not None:
            try:
                self._w.CloseHandle(self.handle)
            except OSError:
                pass
        self.handle = None


def use_named_pipes() -> bool:
    return sys.platform == "win32"


class FrameReader:
    """Decodifica quadros RGB (8 ou 16 bits) já na resolução pedida.

    `profile` (o perfil de entrada do look, `params` "entrada"): log de câmera num vídeo de faixa legal sai em
    float32 (h × w × 3) com o que passa do branco e do preto nominais (`float_input`), em qualquer `depth`.

    16 bits de um vídeo de faixa legal (`exact16`): o swscale expande a faixa para 0–65280 (o branco 0,4% abaixo,
    o branco de 8 bits · 256); `read` leva a cor a 0–65535 (`_legal16`). Vale também para a transparência de mais de
    8 bits (o alfa já sai em 0–65535).

    `crop` (x, y, largura, altura, em pixels do arquivo já girado) recorta antes de redimensionar: é o
    "cortar" da exportação num quadro de outra proporção (`fit.py`).

    `alpha` (pede a transparência; vale só se `decodes_alpha(info)`, senão saem os 3 canais de sempre): quadros
    RGBA **pré-multiplicados** (h × w × 4, uint8 ou uint16). O ffmpeg entrega o alfa direto (*straight*); a cor
    vira RGB com a matriz do arquivo no tamanho original, é multiplicada pelo alfa (`premultiply`) e só então
    redimensionada — assim a borda não puxa a cor dos pixels transparentes (sem franja escura). O WebM VP8/VP9
    usa o libvpx (`alpha_decoder`). Sem `alpha`, nada muda (3 canais, os mesmos bits). Veja `_alpha_graph`.
    """

    def __init__(self, info: MediaInfo, width: int, height: int, depth: int = 8, start_frame: int = 0,
                 max_frames: int | None = None, fps_out: str | None = None, hq: bool = False,
                 perf: Perf | None = None, crop: tuple[int, int, int, int] | None = None, alpha: bool = False,
                 profile: str | None = None):
        perf = perf or Perf()
        alpha = alpha and decodes_alpha(info)
        self.w, self.h, self.depth = width, height, depth
        self.channels = 4 if alpha else 3
        # Fonte com alfa de 8 bits: o ffmpeg trabalha e entrega em 8 bits; a 16 bits, `read` amplia (x257, exato).
        self._widen = bool(alpha and depth != 8 and info.bit_depth <= 8)
        self.float = not alpha and float_input(info, profile)
        self.exact16 = not self.float and depth != 8 and not self._widen and _in_range(info) == "limited"
        if alpha:
            self.pix = "rgba" if depth == 8 or self._widen else "rgba64le"
        elif self.float:
            self.pix = "gbrpf32le"  # planar (G, B, R); `read` entrega RGB intercalado
        else:
            self.pix = "rgb24" if depth == 8 else "rgb48le"
        self.dtype = np.float32 if self.float else np.uint8 if self.pix in ("rgba", "rgb24") else np.uint16
        self.frame_bytes = width * height * self.channels * np.dtype(self.dtype).itemsize
        args = [ffmpeg(), "-v", "error", "-nostdin", "-hide_banner"]
        numbered = getattr(info, "seq_start", -1) >= 0
        if perf.hwaccel and perf.hwaccel != "none" and not info.is_image and not alpha and not numbered:
            args += ["-hwaccel", perf.hwaccel]
        if perf.threads > 0:
            args += ["-threads", str(perf.threads)]
        if not info.is_image and start_frame > 0 and not numbered:
            args += ["-ss", f"{max(0.0, (start_frame - 0.45) / info.fps):.6f}"]
        if alpha:
            args += alpha_decoder(info.codec)
        if numbered:  # sequência de imagens: começa no número do quadro pedido (exato, sem procurar)
            args += sequence_input(info, start_frame)
        args += ["-i", info.path, "-map", "0:v:0", "-an", "-sn", "-dn"]
        flags = "lanczos+accurate_rnd+full_chroma_int" if hq else "bicubic+full_chroma_int"
        vf = []
        if crop:
            cx, cy, cw, ch = (int(c) for c in crop)
            vf.append(f"crop={cw}:{ch}:{cx}:{cy}:exact=1")
        if fps_out:
            vf.append(f"fps={fps_out}")
        th = max(0, perf.threads)
        if alpha:
            vf.append(_alpha_graph(info, width, height, flags, th, self.pix))
        elif self.float:
            vf.append(_exact_graph(info, width, height, flags, th, self.pix))
        else:
            vf.append(f"scale={width}:{height}:flags={flags}:in_color_matrix={_in_matrix(info)}"
                      f":in_range={_in_range(info)}:threads={th}")
            vf.append(f"format={self.pix}")
        args += ["-vf", ",".join(vf)]
        if perf.threads > 0:
            args += ["-filter_threads", str(perf.threads)]
        if max_frames:
            args += ["-frames:v", str(int(max_frames))]
        self.pipe = NamedPipe(True) if use_named_pipes() else None
        args += ["-f", "rawvideo", "-pix_fmt", self.pix, "-y", self.pipe.name if self.pipe else "pipe:1"]
        self.proc = subprocess.Popen(args, stdout=None if self.pipe else subprocess.PIPE, stderr=subprocess.PIPE,
                                     stdin=subprocess.DEVNULL, bufsize=0, **perf.popen_kwargs())
        self._err = bytearray()
        self._t = threading.Thread(target=self._drain, daemon=True)
        self._t.start()
        self.src = None
        if self.pipe:
            try:
                self.src = self.pipe.connect(self.proc)
            except (RuntimeError, OSError):
                self.src = None
        else:
            self.src = self.proc.stdout

    def _drain(self) -> None:
        try:
            for line in self.proc.stderr:
                if len(self._err) < 20000:
                    self._err.extend(line)
        except (OSError, ValueError):
            pass

    @property
    def error(self) -> str:
        try:
            self.proc.wait(timeout=0.5)
        except Exception:  # noqa: BLE001
            pass
        return self._err.decode("utf-8", "replace").strip()

    def read(self) -> np.ndarray | None:
        if self.src is None:
            return None
        buf = bytearray(self.frame_bytes)
        view = memoryview(buf)
        got = 0
        while got < self.frame_bytes:
            try:
                n = self.src.readinto(view[got:])
            except (OSError, ValueError):
                return None
            if not n:
                return None
            got += n
        if self.float:
            g, b, r = np.frombuffer(buf, dtype="<f4").reshape(3, self.h, self.w)
            return np.dstack([r, g, b])
        img = np.frombuffer(buf, dtype=self.dtype).reshape(self.h, self.w, self.channels)
        if self.exact16:
            return _legal16(img)
        return img.astype(np.uint16) * np.uint16(257) if self._widen else img

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        if self.pipe:
            self.pipe.close()
        for st in (self.proc.stdout, self.proc.stderr):
            try:
                if st:
                    st.close()
            except Exception:  # noqa: BLE001
                pass


def _legal16(img: np.ndarray) -> np.ndarray:
    """Cor de 16 bits do swscale para um vídeo de faixa legal (o branco em 65280 = 255·256, o que passa dele até
    65535) → branco em 65535: c·257/256 (o mesmo passo de 8 para 16 bits), com o que passa de 65280 no branco.
    Cada código sai a até 2 de 65535 do valor exato; preto 0 e branco 65535 exatos. O alfa não muda."""
    out = img if img.flags.writeable else img.copy()
    c = out[..., :3]
    np.minimum(c, 65280, out=c)
    c += c >> 8
    return out


def _alpha_graph(info: MediaInfo, width: int, height: int, flags: str, threads: int, pix: str) -> str:
    """Filtros da leitura com transparência: cor em RGB com a matriz do arquivo (no tamanho dele), alfa intacto,
    pré-multiplicação e só então o tamanho pedido; sai em `pix` (`rgba` ou `rgba64le`).

    Arquivo de 8 bits: a cor vai pelo mesmo caminho da leitura sem alfa (`rgb24`) e o alfa é copiado à parte
    (`alphaextract`/`alphamerge`) — o swscale converte yuva420p de 8 bits errado para formatos com alfa (cores
    trocadas no VP9 com alfa, conforme os filtros). Paleta (pal8) e cinza com alfa viram `rgba` antes (exato; o
    `alphaextract` direto na paleta derruba o ffmpeg). Mais de 8 bits (ProRes 4444, yuva…p10/12/16): direto em
    `gbrap16le`, que converte certo e guarda a precisão do arquivo."""
    color = f"scale=flags={flags}:in_color_matrix={_in_matrix(info)}:in_range={_in_range(info)}:threads={threads}"
    resize = f"scale={width}:{height}:flags={flags}:threads={threads}"
    if info.bit_depth > 8:
        return f"{color},format=gbrap16le,premultiply=inplace=1,{resize},format={pix}"
    decoded = "yuva420p" if info.codec in ALPHA_DECODERS else (info.pix_fmt or "")  # o libvpx entrega yuva420p
    pre = "" if decoded.startswith(("yuva", "gbrap", "rgba", "bgra", "argb", "abgr")) else "format=rgba,"
    return (f"{pre}split[c][a];[c]{color},format=rgb24,format=rgba[cc];[a]alphaextract,format=gray[aa];"
            f"[cc][aa]alphamerge,premultiply=inplace=1,{resize},format={pix}")


def grab_frame(info: MediaInfo, frame: int, width: int, height: int, depth: int = 8, hq: bool = False,
               crop: tuple[int, int, int, int] | None = None, alpha: bool = False, profile: str | None = None):
    """Um quadro (h × w × 3; com `alpha`, RGBA pré-multiplicado; com `profile` log, float32: veja `FrameReader`)."""
    r = FrameReader(info, width, height, depth, frame, 1, hq=hq, crop=crop, alpha=alpha, profile=profile)
    try:
        img = r.read()
        if img is None and frame > 0:
            r.close()
            r = FrameReader(info, width, height, depth, max(0, frame - 2), 1, hq=hq, crop=crop, alpha=alpha,
                            profile=profile)
            img = r.read()
        if img is None:
            raise RuntimeError(r.error or _("Falha ao ler o quadro."))
        return img.copy()
    finally:
        r.close()


_ENCODERS: set[str] | None = None
_WORKING: dict[str, bool] = {}
_DECODERS: set[str] | None = None
_FILTERS: set[str] | None = None


def filters() -> set[str]:
    """Filtros desta compilação do ffmpeg (nomes)."""
    global _FILTERS
    if _FILTERS is None:
        try:
            res = subprocess.run([ffmpeg(), "-hide_banner", "-filters"], capture_output=True, creationflags=NO_WINDOW)
            lines = res.stdout.decode("utf-8", "replace").splitlines()
        except OSError:
            lines = []
        _FILTERS = {parts[1] for parts in (ln.split() for ln in lines) if len(parts) >= 3 and "->" in parts[2]}
    return _FILTERS


def has_zscale() -> bool:
    """O ffmpeg tem o zscale (zimg)? É ele que lê log com super-brancos (veja `_exact_graph`)."""
    return "zscale" in filters()


def decoders() -> set[str]:
    """Decodificadores de vídeo desta compilação do ffmpeg (para o libvpx do WebM com alfa)."""
    global _DECODERS
    if _DECODERS is None:
        try:
            res = subprocess.run([ffmpeg(), "-hide_banner", "-decoders"], capture_output=True, creationflags=NO_WINDOW)
            lines = res.stdout.decode("utf-8", "replace").splitlines()
        except OSError:
            lines = []
        names = set()
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS" and parts[1] != "=":
                names.add(parts[1])
        _DECODERS = names
    return _DECODERS


def encoders() -> set[str]:
    global _ENCODERS
    if _ENCODERS is None:
        res = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, creationflags=NO_WINDOW)
        names = set()
        for line in res.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS" and parts[1] != "=":
                names.add(parts[1])
        _ENCODERS = names
    return _ENCODERS


def encoder_works(name: str) -> bool:
    """Testa de verdade (NVENC aparece na lista mesmo sem placa compatível)."""
    if name in _WORKING:
        return _WORKING[name]
    ok = False
    if name in encoders():
        if "nvenc" in name or "qsv" in name or "amf" in name:
            res = subprocess.run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1", "-c:v", name,
                                  "-f", "null", "-"], capture_output=True, creationflags=NO_WINDOW)
            ok = res.returncode == 0
        else:
            ok = True
    _WORKING[name] = ok
    return ok


_HWACCELS: list[str] | None = None


def hwaccels() -> list[str]:
    global _HWACCELS
    if _HWACCELS is None:
        res = subprocess.run([ffmpeg(), "-hide_banner", "-hwaccels"], capture_output=True, creationflags=NO_WINDOW)
        lines = res.stdout.decode("utf-8", "replace").splitlines()
        _HWACCELS = [ln.strip() for ln in lines[1:] if ln.strip()]
    return _HWACCELS
