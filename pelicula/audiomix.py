"""Mixagem do som da sequência do modo Edição com o ffmpeg (prévia e exportação usam a mesma função).

Cada clipe de som vira uma entrada do ffmpeg (`-ss`/`-t` no trecho usado do arquivo) e uma cadeia
de filtros: velocidade (`atempo`), volume do clipe + da faixa, equalização (graves, médios,
agudos), realce de voz, redução de ruído, normalização, balanço, fades, recorte para o trecho
pedido e atraso até a posição na sequência. Tudo é somado (`amix` sem normalizar) sobre um silêncio
com a duração exata do trecho, e o resultado é um WAV de 48 kHz estéreo em 24 bits.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from . import media, timeline
from .i18n import _

RATE = 48000
SCRIPT_LIMIT = 6000  # acima disso o grafo vai para um arquivo (-filter_complex_script)


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


def _atempo(speed: float) -> list[str]:
    """`atempo` aceita de 0,5 a 2 por filtro: encadeia para velocidades fora disso."""
    out = []
    s = float(speed)
    while s > 2.0 + 1e-9:
        out.append("atempo=2")
        s /= 2.0
    while s < 0.5 - 1e-9:
        out.append("atempo=0.5")
        s /= 0.5
    if abs(s - 1.0) > 1e-6:
        out.append(f"atempo={_fmt(s)}")
    return out


def _range(seq: timeline.Sequence, start: int, end: int) -> tuple[int, int]:
    total = seq.duration
    a = max(0, int(start))
    b = total if end is None or end < 0 else min(int(end), total)
    return a, b


def segments(seq: timeline.Sequence, start: int = 0, end: int = -1) -> list[dict]:
    """Clipes de som que tocam no trecho [start, end) (quadros), com os tempos já calculados."""
    a, b = _range(seq, start, end)
    fps = seq.fps
    out = []
    for c in seq.audio_clips():
        src = seq.sources.get(c.src)
        if src is None or not src.has_audio or not os.path.exists(c.src):
            continue
        s0, s1 = max(c.start, a), min(c.end, b)
        if s1 <= s0:
            continue
        tr = seq.track(timeline.AUDIO, c.track)
        out.append({
            "clip": c,
            "src_in": c.src_in,                                  # segundos no arquivo (início do clipe)
            "src_len": c.dur / fps * c.speed,                    # segundos do arquivo usados pelo clipe
            "clip_len": c.dur / fps,                             # duração do clipe na sequência (s)
            "trim_start": (s0 - c.start) / fps,                  # quanto do clipe fica antes do trecho
            "trim_len": (s1 - s0) / fps,
            "delay": (s0 - a) / fps,                             # posição no trecho
            "gain_db": float(c.values["volume"]) + (tr.volume if tr else 0.0),
        })
    return out


def has_audio(seq: timeline.Sequence, start: int = 0, end: int = -1) -> bool:
    return bool(segments(seq, start, end))


def _chain(seg: dict, k: int) -> str:
    c: timeline.Clip = seg["clip"]
    v = c.values
    f = [f"[{k + 1}:a:0]aresample={RATE}", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
    f += _atempo(c.speed)
    if abs(seg["gain_db"]) > 1e-6:
        f.append(f"volume={_fmt(seg['gain_db'])}dB")
    if v["voz"]:
        f += ["highpass=f=90", "acompressor=threshold=-18dB:ratio=3:attack=5:release=120:makeup=2"]
    if abs(v["graves"]) > 1e-6:
        f.append(f"bass=g={_fmt(v['graves'])}:f=110")
    if abs(v["medios"]) > 1e-6:
        f.append(f"equalizer=f=1200:width_type=o:width=2:g={_fmt(v['medios'])}")
    if abs(v["agudos"]) > 1e-6:
        f.append(f"treble=g={_fmt(v['agudos'])}:f=5000")
    if v["reducao_ruido"] > 0:
        f.append(f"afftdn=nr={_fmt(6 + 30 * v['reducao_ruido'])}:nf=-40")
    if v["normalizar"]:
        f += ["loudnorm=I=-16:TP=-1.5:LRA=11", f"aresample={RATE}"]
    bal = float(v["balanco"])
    if abs(bal) > 1e-6:
        gl, gr = min(1.0, 1.0 - bal), min(1.0, 1.0 + bal)
        f.append(f"pan=stereo|c0={_fmt(gl)}*c0|c1={_fmt(gr)}*c1")
    fi = min(float(v["fade_in"]), seg["clip_len"])
    fo = min(float(v["fade_out"]), seg["clip_len"])
    if fi > 0:
        f.append(f"afade=t=in:st=0:d={_fmt(fi)}")
    if fo > 0:
        f.append(f"afade=t=out:st={_fmt(max(0.0, seg['clip_len'] - fo))}:d={_fmt(fo)}")
    f.append(f"atrim=start={_fmt(seg['trim_start'])}:duration={_fmt(seg['trim_len'])}")
    f.append("asetpts=PTS-STARTPTS")
    ms = int(round(seg["delay"] * 1000))
    if ms > 0:
        f.append(f"adelay={ms}|{ms}")
    return ",".join(f) + f"[a{k}]"


def build_graph(seq: timeline.Sequence, start: int = 0, end: int = -1) -> tuple[list[str], str] | None:
    """(entradas do ffmpeg, grafo de filtros) do trecho, ou None se não há som nele."""
    segs = segments(seq, start, end)
    if not segs:
        return None
    a, b = _range(seq, start, end)
    total = (b - a) / seq.fps
    inputs = ["-f", "lavfi", "-t", _fmt(total), "-i", f"anullsrc=r={RATE}:cl=stereo"]
    chains = []
    for k, seg in enumerate(segs):
        inputs += ["-ss", _fmt(seg["src_in"]), "-t", _fmt(seg["src_len"]), "-i", seg["clip"].src]
        chains.append(_chain(seg, k))
    labels = "[0:a]" + "".join(f"[a{k}]" for k in range(len(segs)))
    mix = (f"{labels}amix=inputs={len(segs) + 1}:duration=first:dropout_transition=0:normalize=0,"
           f"atrim=duration={_fmt(total)}[out]")
    return inputs, ";".join(chains + [mix])


def build_mix_cmd(seq: timeline.Sequence, out_path: str, start: int = 0, end: int = -1,
                  script_path: str | None = None) -> list[str] | None:
    """Comando do ffmpeg que grava o som do trecho [start, end) num WAV (None se não há som).

    Com `script_path`, o grafo é gravado nesse arquivo e passado por `-filter_complex_script`
    (grafos longos passam do limite da linha de comando do Windows).
    """
    g = build_graph(seq, start, end)
    if g is None:
        return None
    inputs, graph = g
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-nostdin", "-hide_banner", *inputs]
    if script_path:
        Path(script_path).write_text(graph, encoding="utf-8")
        cmd += ["-filter_complex_script", script_path]
    else:
        cmd += ["-filter_complex", graph]
    cmd += ["-map", "[out]", "-c:a", "pcm_s24le", "-ar", str(RATE), "-ac", "2", out_path]
    return cmd


def render_mix(seq: timeline.Sequence, out_path: str, start: int = 0, end: int = -1,
               cancel: threading.Event | None = None, perf: media.Perf | None = None) -> bool:
    """Grava o som do trecho num WAV. False se o trecho não tem som; erro do ffmpeg vira RuntimeError."""
    g = build_graph(seq, start, end)
    if g is None:
        return False
    script = None
    if len(g[1]) > SCRIPT_LIMIT:
        fd, script = tempfile.mkstemp(prefix="pelicula_mix_", suffix=".txt")
        os.close(fd)
    try:
        cmd = build_mix_cmd(seq, out_path, start, end, script)
        kw = (perf or media.Perf()).popen_kwargs()
        if "creationflags" not in kw:
            kw["creationflags"] = media.NO_WINDOW
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                **kw)
        err = bytearray()

        def drain():
            for line in proc.stderr:
                if len(err) < 20000:
                    err.extend(line)

        th = threading.Thread(target=drain, daemon=True)
        th.start()
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                th.join(timeout=2)
                _remove(out_path)
                return False
            time.sleep(0.03)
        th.join(timeout=2)
        if proc.returncode != 0:
            _remove(out_path)
            raise RuntimeError(_("Falha ao mixar o som da sequência:\n{erro}").format(
                erro=err.decode("utf-8", "replace").strip()[-1500:]))
        return True
    finally:
        if script:
            _remove(script)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def mix_key(seq: timeline.Sequence) -> str:
    """Impressão digital de tudo que muda o som (para saber quando refazer o WAV da prévia)."""
    data = {
        "fps": seq.fps_str,
        "faixas": [t.to_json() for t in seq.kind_tracks(timeline.AUDIO)],
        "clipes": [c.to_json() for c in seq.clips if c.kind == timeline.AUDIO],
        "fontes": sorted((p, round(s.duration, 6)) for p, s in seq.sources.items() if s.has_audio),
    }
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ forma de onda
_PEAKS: dict[str, tuple[float, np.ndarray]] = {}
_PEAKS_LOCK = threading.Lock()


def peaks(path: str, rate: int = 100) -> np.ndarray | None:
    """Picos do som (0 a 1) com `rate` valores por segundo, para desenhar a forma de onda.

    Decodifica o arquivo inteiro em mono numa taxa baixa (pode demorar em arquivos longos: chame de
    uma thread de trabalho). Fica em memória enquanto o arquivo não mudar.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = f"{path}|{rate}"
    with _PEAKS_LOCK:
        hit = _PEAKS.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    per = 40
    cmd = [media.ffmpeg(), "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-ac", "1",
           "-ar", str(rate * per), "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"]
    try:
        res = subprocess.run(cmd, capture_output=True, creationflags=media.NO_WINDOW)
    except OSError:
        return None
    if res.returncode != 0 or not res.stdout:
        return None
    raw = np.frombuffer(res.stdout, dtype="<i2")
    n = len(raw) // per
    if n == 0:
        return None
    blocks = np.abs(raw[: n * per].astype(np.int32)).reshape(n, per).max(axis=1)
    out = (blocks / 32768.0).astype(np.float32)
    with _PEAKS_LOCK:
        _PEAKS[key] = (mtime, out)
    return out
