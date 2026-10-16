"""Funções auxiliares usadas pelos testes (importáveis com ``from helpers import ...``)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

# Vídeo de teste gerado pelo fixture sample_video.
SAMPLE_W, SAMPLE_H, SAMPLE_FPS, SAMPLE_FRAMES = 320, 180, 24, 24


def write_png(path: Path, arr: np.ndarray) -> Path:
    """PNG RGB 8 ou 16 bits sem dependências (zlib + struct)."""
    arr = np.ascontiguousarray(arr)
    h, w, c = arr.shape
    assert c == 3
    if arr.dtype == np.uint16:
        depth = 16
        rows = arr.astype(">u2")
    else:
        depth = 8
        rows = arr.astype(np.uint8)
    raw = b"".join(b"\x00" + rows[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, depth, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6))
                     + chunk(b"IEND", b""))
    return path


def read_all(reader) -> list[np.ndarray]:
    out = []
    try:
        while True:
            f = reader.read()
            if f is None:
                break
            out.append(f.copy())
    finally:
        reader.close()
    return out


# ------------------------------------------------------------------ cenários que podem travar
ROOT = Path(__file__).resolve().parents[1]

_PRELUDE = r'''
import json, os, sys, subprocess, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ["PELICULA_ROOT"])
from pelicula import media
def report(ok, detail=""):
    print("RESULT " + json.dumps({"ok": bool(ok), "detail": str(detail)[:500]}), flush=True)
'''


HANG_DEADLINE = 8.0

# Cenários que travam o processo enquanto o bug do NamedPipe.connect() existir.
HANG_SCENARIOS = {
    "pipe_in": r'''
p = media.NamedPipe(inbound=True)
proc = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    p.connect(proc, timeout=20)
    report(False, "connect voltou sem erro")
except RuntimeError as exc:
    report(p.handle is None, exc)
''',
    "pipe_out": r'''
p = media.NamedPipe(inbound=False)
proc = subprocess.Popen([sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    p.connect(proc, timeout=20)
    report(False, "connect voltou sem erro")
except RuntimeError as exc:
    report(p.handle is None, exc)
''',
    "pipe_timeout": r'''
p = media.NamedPipe(inbound=True)
proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
t0 = time.time()
try:
    p.connect(proc, timeout=1.0)
    report(False, "connect voltou sem erro")
except RuntimeError as exc:
    report(time.time() - t0 < 6, exc)
finally:
    proc.kill()
''',
    "reader_bad": r'''
if not media.configure():
    report(True, "SEM_FFMPEG")
else:
    bad = os.path.join(os.environ["PELICULA_TMP"], "ruim.mp4")
    open(bad, "wb").write(b"\x00" * 1000)
    info = media.MediaInfo(path=bad, width=64, height=36, fps=24.0, fps_str="24/1", frames=24, duration=1.0,
                           pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="", bitrate=0, color_space="",
                           color_range="", color_transfer="", color_primaries="", has_audio=False, audio_codec="",
                           container="mp4", is_image=False)
    r = media.FrameReader(info, 64, 36, 8)
    img = r.read()
    err = r.error
    r.close()
    report(img is None and bool(err), err)
''',
    "grab_bad": r'''
if not media.configure():
    report(True, "SEM_FFMPEG")
else:
    bad = os.path.join(os.environ["PELICULA_TMP"], "vazio.mp4")
    open(bad, "wb").close()
    info = media.MediaInfo(path=bad, width=64, height=36, fps=24.0, fps_str="24/1", frames=24, duration=1.0,
                           pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="", bitrate=0, color_space="",
                           color_range="", color_transfer="", color_primaries="", has_audio=False, audio_codec="",
                           container="mp4", is_image=False)
    try:
        media.grab_frame(info, 3, 64, 36)
        report(False, "grab_frame não levantou erro")
    except RuntimeError as exc:
        report(True, exc)
''',
}


class Isolated:
    """Roda trechos de código em processos filhos ao mesmo tempo e espera cada um até um prazo.

    Usado para comportamentos que, com bug, travam o processo para sempre (o filho é encerrado
    no prazo e o teste falha em vez de travar a suíte).
    """

    def __init__(self, scenarios: dict[str, str], env: dict[str, str], deadline: float):
        import subprocess
        import sys
        import time
        self._t0 = time.time()
        self._deadline = deadline
        self._procs = {}
        self._results: dict[str, tuple[bool, dict | None, str]] = {}
        full_env = dict(env)
        full_env["PELICULA_ROOT"] = str(ROOT)
        for name, code in scenarios.items():
            self._procs[name] = subprocess.Popen([sys.executable, "-c", _PRELUDE + code], env=full_env,
                                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def result(self, name: str) -> tuple[bool, dict | None, str]:
        """(terminou_no_prazo, resultado, saída)."""
        import json
        import subprocess
        import time
        if name in self._results:
            return self._results[name]
        proc = self._procs[name]
        left = max(0.1, self._deadline - (time.time() - self._t0))
        try:
            out, _ = proc.communicate(timeout=left)
            finished = True
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            finished = False
        text = out.decode("utf-8", "replace")
        res = None
        for line in text.splitlines():
            if line.startswith("RESULT "):
                res = json.loads(line[7:])
        self._results[name] = (finished, res, text)
        return self._results[name]

    def close(self) -> None:
        for name in self._procs:
            self.result(name)
