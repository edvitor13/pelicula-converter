"""Leitura e gravação de vídeo com o ffmpeg (processos externos via pipe)."""

from __future__ import annotations

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
    global _ENCODERS, _HWACCELS
    _ENCODERS = None
    _HWACCELS = None
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
        raise RuntimeError(_("ffmpeg não encontrado. Use Configurações > Dependências e atualizações para baixar."))
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

    @property
    def ext(self) -> str:
        return Path(self.path).suffix.lower()

    def summary(self) -> str:
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


def probe(path: str) -> MediaInfo:
    return _info_from(path, _probe_json(path))


def probe_source(path: str):
    """Arquivo para o modo Edição: vídeo, imagem parada ou só áudio (música, narração).

    Devolve um `timeline.Source`; arquivos só de som têm `has_video=False`.
    """
    from . import timeline
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
    return MediaInfo(
        path=path, width=w, height=h, fps=float(fr), fps_str=f"{fr.numerator}/{fr.denominator}",
        frames=max(frames, 1), duration=dur, pix_fmt=pix, bit_depth=_depth(pix, vs.get("bits_per_raw_sample")),
        codec=vs.get("codec_name", "?"), profile=vs.get("profile", "") or "",
        bitrate=int(vs.get("bit_rate") or fmt.get("bit_rate") or 0),
        color_space=vs.get("color_space", "") or "", color_range=vs.get("color_range", "") or "",
        color_transfer=vs.get("color_transfer", "") or "", color_primaries=vs.get("color_primaries", "") or "",
        has_audio=aus is not None, audio_codec=(aus or {}).get("codec_name", ""),
        container=fmt.get("format_name", ""), is_image=is_image,
    )


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
                if getattr(exc, "winerror", 0) != 535:
                    errs.append(exc)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        t0 = time.time()
        while not done.wait(0.05):
            if proc.poll() is not None or time.time() - t0 > timeout:
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
    """Decodifica quadros RGB (8 ou 16 bits) já na resolução pedida."""

    def __init__(self, info: MediaInfo, width: int, height: int, depth: int = 8, start_frame: int = 0,
                 max_frames: int | None = None, fps_out: str | None = None, hq: bool = False,
                 perf: Perf | None = None):
        perf = perf or Perf()
        self.w, self.h, self.depth = width, height, depth
        self.pix = "rgb24" if depth == 8 else "rgb48le"
        self.dtype = np.uint8 if depth == 8 else np.uint16
        self.frame_bytes = width * height * 3 * (1 if depth == 8 else 2)
        args = [ffmpeg(), "-v", "error", "-nostdin", "-hide_banner"]
        if perf.hwaccel and perf.hwaccel != "none" and not info.is_image:
            args += ["-hwaccel", perf.hwaccel]
        if perf.threads > 0:
            args += ["-threads", str(perf.threads)]
        if not info.is_image and start_frame > 0:
            args += ["-ss", f"{max(0.0, (start_frame - 0.45) / info.fps):.6f}"]
        args += ["-i", info.path, "-map", "0:v:0", "-an", "-sn", "-dn"]
        flags = "lanczos+accurate_rnd+full_chroma_int" if hq else "bicubic+full_chroma_int"
        vf = []
        if fps_out:
            vf.append(f"fps={fps_out}")
        vf.append(f"scale={width}:{height}:flags={flags}:in_color_matrix={_in_matrix(info)}"
                  f":in_range={_in_range(info)}:threads={max(0, perf.threads)}")
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
        return np.frombuffer(buf, dtype=self.dtype).reshape(self.h, self.w, 3)

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


def grab_frame(info: MediaInfo, frame: int, width: int, height: int, depth: int = 8, hq: bool = False):
    r = FrameReader(info, width, height, depth, frame, 1, hq=hq)
    try:
        img = r.read()
        if img is None and frame > 0:
            r.close()
            r = FrameReader(info, width, height, depth, max(0, frame - 2), 1, hq=hq)
            img = r.read()
        if img is None:
            raise RuntimeError(r.error or _("Falha ao ler o quadro."))
        return img.copy()
    finally:
        r.close()


_ENCODERS: set[str] | None = None
_WORKING: dict[str, bool] = {}


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
