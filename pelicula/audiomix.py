"""Mixagem do som da sequência do modo Edição com o ffmpeg (prévia e exportação usam a mesma função).

Cada clipe de som vira uma entrada do ffmpeg (`-ss`/`-t` no trecho usado do arquivo) e uma cadeia
de filtros: velocidade (`atempo`), volume do clipe + da faixa, equalização (graves, médios,
agudos), realce de voz, redução de ruído, normalização, balanço, fades, recorte para o trecho
pedido e atraso até a posição na sequência. Tudo é somado (`amix` sem normalizar) sobre um silêncio
com a duração exata do trecho, e o resultado é um WAV de 48 kHz estéreo em 24 bits.

Emendas: com `Sequence.micro_fade` ligado, cada borda de clipe que corta o arquivo no meio ganha um
fade de `timeline.MICRO_FADE` (5 ms), menos onde o fade do clipe já é maior, onde há transição de som e
onde o clipe vizinho continua o mesmo arquivo do ponto exato (corte não mexido). A transição de som
(`values["transicao"]` no clipe que entra, tempo de `Sequence.audio_crossfade`) estende os dois
clipes além do corte com o arquivo que sobra e cruza as curvas seno/cosseno (`afade curve=qsin`): a
soma das potências fica constante. Projeto sem nada disso gera exatamente o mesmo grafo de antes.
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


def crossfades(seq: timeline.Sequence) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """Transições de som da sequência: ({id do que entra: (antes, depois)}, {id do que sai: (antes, depois)}),
    em segundos antes e depois do corte (só as que têm alguma duração)."""
    heads: dict[str, tuple[float, float]] = {}
    tails: dict[str, tuple[float, float]] = {}
    for c in seq.clips:
        if c.kind != timeline.AUDIO:
            continue
        prev, before, after = seq.audio_crossfade(c)
        if prev is not None and before + after > 1e-6:
            heads[c.id] = tails[prev.id] = (before, after)
    return heads, tails


def segments(seq: timeline.Sequence, start: int = 0, end: int = -1) -> list[dict]:
    """Clipes de som que tocam no trecho [start, end) (quadros), com os tempos já calculados."""
    a, b = _range(seq, start, end)
    fps = seq.fps
    heads, tails = crossfades(seq)
    micro = timeline.MICRO_FADE if seq.micro_fade else 0.0
    playing = seq.audio_clips()
    audible = {c.id for c in playing}
    out = []
    for c in playing:
        src = seq.sources.get(c.src)
        if src is None or not src.is_file or not src.has_audio or not os.path.exists(c.src):
            continue  # clipes sem arquivo (geradores) não têm som
        head, tail = heads.get(c.id), tails.get(c.id)
        pre = head[0] if head else 0.0    # o clipe começa antes (transição com o anterior)
        post = tail[1] if tail else 0.0   # e termina depois (transição com o próximo)
        if head or tail:
            t0 = c.start / fps - pre      # tempo da sequência no começo da cadeia do clipe
            v0, v1 = max(t0, a / fps), min(c.end / fps + post, b / fps)
            if v1 - v0 <= 1e-9:
                continue
            trim_start, trim_len, delay = v0 - t0, v1 - v0, v0 - a / fps
        else:
            s0, s1 = max(c.start, a), min(c.end, b)
            if s1 <= s0:
                continue
            trim_start, trim_len, delay = (s0 - c.start) / fps, (s1 - s0) / fps, (s0 - a) / fps
        micro_in = micro_out = False
        if micro:
            v = c.values
            prev, nxt = seq.previous_on_track(c), seq.next_on_track(c)
            micro_in = (head is None and float(v["fade_in"]) < micro and c.src_in > 1e-4
                        and not (prev is not None and prev.id in audible and seq.continues(prev, c)))
            micro_out = (tail is None and float(v["fade_out"]) < micro and c.dur < seq.max_dur(c)
                         and not (nxt is not None and nxt.id in audible and seq.continues(c, nxt)))
        tr = seq.track(timeline.AUDIO, c.track)
        out.append({
            "clip": c,
            "src_in": max(0.0, c.src_in - pre * c.speed),        # segundos no arquivo (início da cadeia)
            "src_len": (c.dur / fps + pre + post) * c.speed,     # segundos do arquivo usados
            "clip_len": c.dur / fps,                             # duração do clipe na sequência (s)
            "trim_start": trim_start,                            # quanto da cadeia fica antes do trecho
            "trim_len": trim_len,
            "delay": delay,                                      # posição no trecho
            "gain_db": float(c.values["volume"]) + (tr.volume if tr else 0.0),
            "track_db": tr.volume if tr else 0.0,
            # Volume animado: as chaves do clipe no tempo dele (τ = segundos do clipe × fps + key_off).
            "vol_keys": c.keys.get("volume") or [],
            "key_off": c.key_off,
            "fps": fps,
            "pre": pre,                                          # s antes do início do clipe (transição)
            "xf_in": sum(head) if head else 0.0,                 # transição de entrada (começa em 0)
            "xf_out": sum(tail) if tail else 0.0,                # transição de saída...
            "xf_out_st": pre + c.dur / fps - tail[0] if tail else 0.0,  # ...a partir daqui
            "micro": micro if (micro_in or micro_out) else 0.0,
            "micro_in": micro_in,
            "micro_out": micro_out,
        })
    return out


def has_audio(seq: timeline.Sequence, start: int = 0, end: int = -1) -> bool:
    return bool(segments(seq, start, end))


def _chain(seg: dict, k: int) -> str:
    c: timeline.Clip = seg["clip"]
    v = c.values
    f = [f"[{k + 1}:a:0]aresample={RATE}", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
    f += _atempo(c.speed)
    vk = seg.get("vol_keys")
    if vk:
        f.append(volume_envelope(vk, seg["pre"], seg["fps"], seg["key_off"], seg["track_db"]))
    elif abs(seg["gain_db"]) > 1e-6:
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
    # Fades do clipe; numa borda com transição de som vale só a transição (o fade silenciaria a sobra).
    pre = seg["pre"]
    fi = 0.0 if seg["xf_in"] else min(float(v["fade_in"]), seg["clip_len"])
    fo = 0.0 if seg["xf_out"] else min(float(v["fade_out"]), seg["clip_len"])
    if fi > 0:
        f.append(f"afade=t=in:st={_fmt(pre)}:d={_fmt(fi)}")
    if fo > 0:
        f.append(f"afade=t=out:st={_fmt(pre + max(0.0, seg['clip_len'] - fo))}:d={_fmt(fo)}")
    if seg["xf_in"]:  # potência constante: sen² + cos² = 1 com a saída do clipe anterior
        f.append(f"afade=t=in:st=0:d={_fmt(seg['xf_in'])}:curve=qsin")
    if seg["xf_out"]:
        f.append(f"afade=t=out:st={_fmt(seg['xf_out_st'])}:d={_fmt(seg['xf_out'])}:curve=qsin")
    m = seg["micro"]
    if seg["micro_in"]:
        f.append(f"afade=t=in:st={_fmt(pre)}:d={_fmt(m)}")
    if seg["micro_out"]:
        f.append(f"afade=t=out:st={_fmt(pre + max(0.0, seg['clip_len'] - m))}:d={_fmt(m)}")
    f.append(f"atrim=start={_fmt(seg['trim_start'])}:duration={_fmt(seg['trim_len'])}")
    f.append("asetpts=PTS-STARTPTS")
    ms = int(round(seg["delay"] * 1000))
    if ms > 0:
        f.append(f"adelay={ms}|{ms}")
    return ",".join(f) + f"[a{k}]"


def volume_envelope(keys, pre: float, fps: float, key_off: int, track_db: float = 0.0) -> str:
    """Filtro `volume` do ffmpeg com o volume animado (chaves em dB, `keyframes.ffmpeg_expr`: a mesma conta da
    imagem), avaliado a cada bloco de som (`eval=frame`). `t` é o tempo da cadeia, que começa `pre` segundos
    antes do clipe (transição de som); o tempo das chaves é τ = (t − pre) × fps + key_off."""
    from . import keyframes
    tau = f"((t-{_fmt(pre)})*{_fmt(fps)}+{int(key_off)})"
    db = keyframes.ffmpeg_expr(keys, tau)
    if abs(track_db) > 1e-9:
        db = f"({db})+{_fmt(track_db)}"
    return f"volume='pow(10,({db})/20)':eval=frame"


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
    if seq.micro_fade:
        data["micro_fades"] = True
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


# ------------------------------------------------------------------ som para o medidor
def decode_wav(path: str, out_path: str, cancel: threading.Event | None = None) -> bool:
    """O som do arquivo inteiro num WAV estéreo de 16 bits em 48 kHz, para o medidor de som do modo
    Película ler junto com a reprodução. False se não deu (sem som, erro do ffmpeg ou cancelado)."""
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-nostdin", "-hide_banner", "-i", path, "-map", "0:a:0", "-vn",
           "-ac", "2", "-ar", str(RATE), "-c:a", "pcm_s16le", "-f", "wav", out_path]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **media.Perf(priority="baixa").popen_kwargs())
    except OSError:
        return False
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            _remove(out_path)
            return False
        time.sleep(0.05)
    if proc.returncode != 0:
        _remove(out_path)
        return False
    return True


class WavReader:
    """Lê trechos de um WAV PCM (inteiros de 16, 24 ou 32 bits, ou float de 32 bits) sem carregar o
    arquivo inteiro: cada leitura abre, lê e fecha (o arquivo pode ser apagado entre uma e outra)."""

    def __init__(self, path: str):
        import struct
        self.path = path
        fmt = None
        with open(path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                raise ValueError(f"não é um WAV: {path}")
            while True:
                hdr = fh.read(8)
                if len(hdr) < 8:
                    raise ValueError(f"WAV sem dados: {path}")
                cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
                if cid == b"fmt ":
                    body = fh.read(size + (size & 1))
                    tag, ch, rate, _rate_bytes, align, bits = struct.unpack("<HHIIHH", body[:16])
                    if tag == 0xFFFE and len(body) >= 26:  # WAVE_FORMAT_EXTENSIBLE: o tipo vem no GUID
                        tag = struct.unpack("<H", body[24:26])[0]
                    fmt = (tag, ch, rate, align, bits)
                elif cid == b"data":
                    self.offset = fh.tell()
                    break
                else:
                    fh.seek(size + (size & 1), 1)
        if fmt is None:
            raise ValueError(f"WAV sem formato: {path}")
        tag, self.channels, self.rate, self.align, self.bits = fmt
        if (tag, self.bits) not in ((1, 16), (1, 24), (1, 32), (3, 32)) or self.align != self.channels * self.bits // 8:
            raise ValueError(f"WAV num formato que o medidor não lê ({tag}, {self.bits} bits): {path}")
        self.float = tag == 3
        avail = os.path.getsize(path) - self.offset
        self.frames = max(0, (min(size, avail) if size not in (0, 0xFFFFFFFF) else avail) // self.align)

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def read(self, start: int, count: int) -> np.ndarray:
        """Amostras [start, start + count) em float32 (n, canais), de −1 a 1; menos no fim do arquivo."""
        start = max(0, int(start))
        count = max(0, min(int(count), self.frames - start))
        if count == 0:
            return np.zeros((0, self.channels), np.float32)
        with open(self.path, "rb") as fh:
            fh.seek(self.offset + start * self.align)
            raw = fh.read(count * self.align)
        n = len(raw) // self.align
        raw = raw[:n * self.align]
        if self.float:
            x = np.frombuffer(raw, dtype="<f4")
        elif self.bits == 16:
            x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif self.bits == 32:
            x = (np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0).astype(np.float32)
        else:
            b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            v = np.where(v >= 1 << 23, v - (1 << 24), v)
            x = v.astype(np.float32) / 8388608.0
        return x.reshape(n, self.channels)
