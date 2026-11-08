"""Limpeza do som do clipe (1.8, ARQUITETURA §44): ruído aprendido, zumbido da rede elétrica, filtros de corte e
nivelamento da voz (sem Qt).

Ruído aprendido
---------------
O clipe guarda só o **trecho** do arquivo que tem o ruído (`ruido_ini`/`ruido_fim`, segundos da fonte), nunca o
espectro: o JSON fica pequeno e o perfil é refeito do arquivo na hora de mixar (`profile_for`, em memória pelo
carimbo do arquivo + trecho). O perfil é a magnitude média (e o desvio) de cada faixa de frequência de uma STFT
(Hann de 2048 amostras, salto de 512, a 48 kHz) do trecho, com os dois canais juntos: um perfil só, aplicado igual
aos dois canais (a imagem estéreo não muda).

A redução é uma subtração espectral com sobra (`BETA`), suavizada no tempo e na frequência antes e depois do
ganho (sem "ruído musical"), com piso de `ruido_perfil × MAX_REDUCTION_DB`: 0% não muda nada, 100% tira até 30 dB
do que é só ruído. A reconstrução é exata (Hann periódica com salto de N/4: a soma dos quadrados é 1,5 em toda
amostra) e o ganho de cada quadro depende só de quadros vizinhos (filtros simétricos, sem estado), então processar
em blocos dá o mesmo que processar de uma vez (`denoise(..., block=)`): memória limitada a um bloco.

Na mixagem, como o WAV de uma sequência aninhada (§41.5), a **entrada** do clipe vira um WAV limpo do trecho usado
do arquivo, com sobras para transições, rampas e reverso (`clean_input`, chamado por `audiomix.segments`); a cadeia
do clipe (velocidade, volume, equalização…) vem depois, como um plugin de redução de ruído posto em primeiro lugar.
O WAV limpo fica num cache no temporário do sistema (`clean_dir`), com o nome tirado de (carimbo do arquivo, trecho
usado, trecho do ruído, força, `VERSION`), e é gravado por `render_inputs` antes da mixagem, na mesma thread de
trabalho (`audiomix._render_nested`).

Zumbido, filtros e voz
----------------------
Filtros do ffmpeg na cadeia do clipe (`audiomix._chain_tail`): `hum_filters` (entalhes `bandreject` em f, 2f, …,
antes da equalização), `after_eq_filters` (`highpass`/`lowpass` de 2 polos e `speechnorm`, depois da equalização e
antes do `loudnorm`). Tudo no padrão = nenhum filtro: o grafo de antes, byte a byte.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import media
from .i18n import _

RATE = 48000
N_FFT = 2048
HOP = 512
VERSION = 1                 # muda com o algoritmo: os WAVs limpos de antes deixam de valer
MIN_PROFILE_S = 0.25        # trecho de ruído mais curto que dá um perfil
MAX_PROFILE_S = 30.0        # o perfil lê no máximo isto do trecho
SILENT_DB = -70.0           # RMS abaixo disto = trecho sem som
MAX_REDUCTION_DB = 30.0     # o que 100% tira do que é só ruído
BETA = 2.0                  # sobra da subtração espectral
MARGIN_S = 1.0              # s do arquivo além do trecho usado (transições, rampas, reverso)
GRID_S = 0.5                # as pontas do WAV limpo caem nesta grade (mais reaproveitamento do cache)
BLOCK = 1 << 18             # amostras por bloco do processamento (~5,5 s)
CLEAN_DIR = "pelicula_som_limpo"
CLEAN_MAX_BYTES = 2 * 1024 ** 3
CLEAN_KEEP_S = 600.0

_W = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(N_FFT) / N_FFT)   # Hann periódica
_OLA = float(np.sum(_W.reshape(N_FFT // HOP, HOP) ** 2, axis=0)[0])  # 1,5: soma dos quadrados em cada amostra
_K5 = np.array([1.0, 2.0, 3.0, 2.0, 1.0]) / 9.0
_K3 = np.array([1.0, 2.0, 1.0]) / 4.0
_CTX = 3                    # quadros de contexto de cada lado (_K5 = 2, _K3 = 1)


class CleanError(RuntimeError):
    """Falha com mensagem para o usuário (PT-BR)."""


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


# ------------------------------------------------------------------ perfil do ruído
@dataclass(frozen=True)
class NoiseProfile:
    """Magnitude média e desvio de cada faixa (N_FFT // 2 + 1) no trecho do ruído."""
    mean: np.ndarray
    spread: np.ndarray

    @property
    def power(self) -> np.ndarray:
        """Potência média por faixa (= média² + desvio²)."""
        return self.mean ** 2 + self.spread ** 2


def learn_profile(x: np.ndarray, rate: int = RATE) -> NoiseProfile:
    """O perfil do ruído de `x` ((n, canais) ou (n,), float, −1 a 1). CleanError se o trecho é curto ou mudo."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[0] < max(N_FFT, int(round(MIN_PROFILE_S * rate))):
        raise CleanError(_("O trecho do ruído é curto demais: escolha pelo menos {s} s só com o ruído.").format(
            s=str(MIN_PROFILE_S).replace(".", ",")))
    rms = float(np.sqrt(np.mean(x ** 2)))
    if rms <= 0 or 20.0 * math.log10(rms) < SILENT_DB:
        raise CleanError(_("O trecho escolhido não tem som: escolha um trecho em que só o ruído toca (sem fala nem "
                           "música)."))
    frames = np.lib.stride_tricks.sliding_window_view(x, N_FFT, axis=0)[::HOP]   # (quadros, canais, N)
    mag = np.abs(np.fft.rfft(frames * _W, axis=-1)).reshape(-1, N_FFT // 2 + 1)
    return NoiseProfile(mag.mean(axis=0), mag.std(axis=0))


# ------------------------------------------------------------------ redução (STFT em blocos)
def _smooth(a: np.ndarray, k: np.ndarray, axis: int) -> np.ndarray:
    """Convolução simétrica: no eixo 1 (frequência) com as pontas repetidas; no eixo 0 (tempo) só a parte válida
    (o resultado perde len(k) // 2 quadros de cada lado). Soma em ordem fixa: o mesmo em qualquer bloco."""
    h = len(k) // 2
    if axis == 1:
        p = np.pad(a, ((0, 0), (h, h)), mode="edge")
        return sum(k[i] * p[:, i:i + a.shape[1]] for i in range(len(k)))
    n = a.shape[0] - 2 * h
    return sum(k[i] * a[i:i + n] for i in range(len(k)))


def _gains(power: np.ndarray, noise: np.ndarray, floor: float) -> np.ndarray:
    """Ganho por quadro e faixa: (quadros − 2·_CTX, faixas)."""
    ps = _smooth(_smooth(power, _K5, 1), _K5, 0)
    g = np.sqrt(np.clip(1.0 - BETA * noise / np.maximum(ps, 1e-30), 0.0, 1.0))
    g = np.maximum(g, floor)
    return _smooth(_smooth(g, _K3, 1), _K3, 0)


def _padded(read, total: int, start: int, count: int) -> np.ndarray:
    """`read(start, count)` com zeros fora de [0, total)."""
    a, b = max(0, start), min(total, start + count)
    got = read(a, b - a) if b > a else None
    ch = got.shape[1] if got is not None and got.ndim == 2 else 2
    out = np.zeros((count, ch), np.float64)
    if got is not None and len(got):
        out[a - start:a - start + len(got)] = got
    return out


def _block(read, total: int, o0: int, o1: int, noise: np.ndarray, floor: float) -> np.ndarray:
    """Saída limpa das amostras [o0, o1) (o0 múltiplo de HOP). O quadro k cobre [(k − 3)·HOP, (k + 1)·HOP); a
    amostra i recebe os quadros i // HOP … i // HOP + 3, e o ganho de cada um usa ±_CTX quadros vizinhos."""
    j0, j1 = o0 // HOP, -(-o1 // HOP) + 3                     # quadros que somam na saída
    seg = _padded(read, total, (j0 - 3 - _CTX) * HOP, (j1 - j0 + 3 + 2 * _CTX) * HOP)
    frames = np.lib.stride_tricks.sliding_window_view(seg, N_FFT, axis=0)[::HOP]   # (j1−j0+2·CTX, canais, N)
    spec = np.fft.rfft(frames * _W, axis=-1)
    power = np.mean(spec.real ** 2 + spec.imag ** 2, axis=1)
    g = _gains(power, noise, floor)                            # (j1 − j0, faixas)
    y = np.fft.irfft(spec[_CTX:-_CTX] * g[:, None, :], n=N_FFT, axis=-1) * _W   # (quadros, canais, N)
    nj, ch = y.shape[0], y.shape[1]
    parts = y.reshape(nj, ch, N_FFT // HOP, HOP)
    out = np.zeros((nj + 3, ch, HOP))
    for q in range(N_FFT // HOP):
        out[q:q + nj] += parts[:, :, q]
    out = out.transpose(0, 2, 1).reshape(-1, ch) / _OLA      # começa na amostra (j0 − 3)·HOP
    a = o0 - (j0 - 3) * HOP
    return out[a:a + (o1 - o0)]


def floor_for(amount: float) -> float:
    """Ganho mínimo (o que sobra do que é só ruído) para a força 0–1."""
    return 10.0 ** (-max(0.0, min(1.0, float(amount))) * MAX_REDUCTION_DB / 20.0)


def denoise_stream(read, total: int, write, profile: NoiseProfile, amount: float, block: int = BLOCK,
                   cancel: threading.Event | None = None) -> bool:
    """Limpa `total` amostras lidas por `read(start, count)` e entrega a saída em ordem a `write(array)`, um bloco
    de cada vez. False se foi cancelado."""
    block = max(HOP, (int(block) // HOP) * HOP)
    noise, floor = profile.power, floor_for(amount)
    for o0 in range(0, total, block):
        if cancel is not None and cancel.is_set():
            return False
        write(_block(read, total, o0, min(total, o0 + block), noise, floor))
    return True


def denoise(x: np.ndarray, profile: NoiseProfile, amount: float, block: int = BLOCK) -> np.ndarray:
    """`x` (n, canais) limpo, do mesmo tamanho (referência em memória de `denoise_stream`)."""
    x = np.asarray(x, dtype=np.float64)
    mono = x.ndim == 1
    if mono:
        x = x[:, None]
    parts: list[np.ndarray] = []
    denoise_stream(lambda s, n: x[s:s + n], len(x), parts.append, profile, amount, block)
    out = np.concatenate(parts) if parts else np.zeros_like(x)
    return out[:, 0] if mono else out


# ------------------------------------------------------------------ ffmpeg: ler trechos
def _stamp(path: str) -> list:
    """Carimbo do arquivo: caminho, data e tamanho. Um WAV de sequência aninhada já tem o conteúdo no nome (e a
    data muda a cada uso, `audiomix._render_nested`): só o caminho."""
    from . import audiomix
    try:
        if Path(path).parent == audiomix.nested_dir():
            return [path]
        st = os.stat(path)
        return [path, st.st_mtime, st.st_size]
    except OSError:
        return [path, 0, 0]


def _run(cmd: list[str], cancel: threading.Event | None = None, perf: media.Perf | None = None,
         stdout=subprocess.DEVNULL) -> tuple[int, bytes, bytes]:
    kw = (perf or media.Perf(priority="baixa")).popen_kwargs()
    if "creationflags" not in kw:
        kw["creationflags"] = media.NO_WINDOW
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.PIPE, **kw)
    out, err = bytearray(), bytearray()

    def drain(pipe, buf, cap):
        for chunk in iter(lambda: pipe.read(65536), b""):
            if cap is None or len(buf) < cap:
                buf.extend(chunk)

    ths = [threading.Thread(target=drain, args=(proc.stderr, err, 20000), daemon=True)]
    if stdout is subprocess.PIPE:
        ths.append(threading.Thread(target=drain, args=(proc.stdout, out, None), daemon=True))
    for th in ths:
        th.start()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            for th in ths:
                th.join(timeout=2)
            return -1, b"", b""
        time.sleep(0.02)
    for th in ths:
        th.join(timeout=5)
    return proc.returncode, bytes(out), bytes(err)


def read_range(path: str, t0: float, dur: float, rate: int = RATE, channels: int = 2,
               cancel: threading.Event | None = None) -> np.ndarray:
    """O som de [t0, t0 + dur) do arquivo em float32 (n, canais). Vazio se o arquivo não tem som ali; cancelado
    também devolve vazio."""
    cmd = [media.ffmpeg(), "-v", "error", "-nostdin", "-hide_banner", "-ss", _fmt(max(0.0, t0)), "-t",
           _fmt(max(1e-3, dur)), "-i", path, "-map", "0:a:0", "-vn", "-ac", str(channels), "-ar", str(rate),
           "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1"]
    code, out, _err = _run(cmd, cancel, stdout=subprocess.PIPE)
    if code != 0 or not out:
        return np.zeros((0, channels), np.float32)
    x = np.frombuffer(out[:len(out) // (4 * channels) * 4 * channels], dtype="<f4")
    return x.reshape(-1, channels)


_PROFILES: OrderedDict = OrderedDict()
_PROFILES_LOCK = threading.Lock()


def profile_for(path: str, t0: float, t1: float, cancel: threading.Event | None = None) -> NoiseProfile:
    """O perfil do trecho [t0, t1] do arquivo, guardado em memória pelo carimbo do arquivo + trecho.
    CleanError se o trecho é curto ou mudo."""
    a, b = sorted((float(t0), float(t1)))
    key = json.dumps([_stamp(path), round(a, 6), round(b, 6)])
    with _PROFILES_LOCK:
        hit = _PROFILES.get(key)
        if hit is not None:
            _PROFILES.move_to_end(key)
            return hit
    if b - a < MIN_PROFILE_S - 1e-9:
        raise CleanError(_("O trecho do ruído é curto demais: escolha pelo menos {s} s só com o ruído.").format(
            s=str(MIN_PROFILE_S).replace(".", ",")))
    prof = learn_profile(read_range(path, a, min(b - a, MAX_PROFILE_S), cancel=cancel))
    with _PROFILES_LOCK:
        _PROFILES[key] = prof
        while len(_PROFILES) > 16:
            _PROFILES.popitem(last=False)
    return prof


# ------------------------------------------------------------------ a entrada limpa do clipe na mixagem
def wants_clean(values: dict) -> bool:
    """O clipe pede a limpeza pelo ruído aprendido (força > 0 e um trecho aprendido)."""
    return (float(values.get("ruido_perfil", 0.0)) > 0.0
            and float(values.get("ruido_fim", 0.0)) - float(values.get("ruido_ini", 0.0)) > 1e-9)


def clean_dir() -> Path:
    """Pasta dos WAVs limpos, no temporário do sistema (como os das sequências aninhadas)."""
    return Path(tempfile.gettempdir()) / CLEAN_DIR


def clean_path(source: str, lo: float, hi: float, ini: float, fim: float, amount: float) -> str:
    """O WAV limpo de [lo, hi] do arquivo `source` (pode ainda não existir)."""
    name = hashlib.sha1(json.dumps([VERSION, _stamp(source), round(lo, 6), round(hi, 6), round(ini, 6),
                                    round(fim, 6), round(float(amount), 6)]).encode("utf-8")).hexdigest()
    return str(clean_dir() / f"{name}.wav")


def clean_input(seg: dict, length: float = 0.0) -> None:
    """Gancho de `audiomix.segments`: com o ruído aprendido ligado, troca a entrada do clipe (`seg["path"]`) pelo
    WAV limpo do trecho usado do arquivo (com `MARGIN_S` de sobra, pontas na grade de `GRID_S`) e ajusta os tempos
    do arquivo para o começo dele (`src_in`; numa rampa/reverso, os pedaços e o tamanho). `seg["clean"]` leva o que
    `render_inputs` precisa para gravá-lo. Sem a limpeza, não mexe em nada."""
    v = seg["clip"].values
    if not wants_clean(v):
        return
    if seg.get("pieces"):
        ext = [t for p in seg["pieces"] for t in (p[2], p[3])]
        a, b = min(ext), max(ext)
    else:
        a, b = seg["src_in"], seg["src_in"] + seg["src_len"]
    lo = max(0.0, math.floor((a - MARGIN_S) / GRID_S) * GRID_S)
    hi = math.ceil((b + MARGIN_S) / GRID_S) * GRID_S
    if length > 0:
        hi = min(hi, math.ceil(length / GRID_S) * GRID_S)
    hi = max(hi, lo + GRID_S)
    ini, fim, amount = float(v["ruido_ini"]), float(v["ruido_fim"]), float(v["ruido_perfil"])
    source = seg["path"]
    seg["clean"] = {"source": source, "lo": lo, "hi": hi, "ini": ini, "fim": fim, "amount": amount}
    seg["path"] = clean_path(source, lo, hi, ini, fim, amount)
    seg["src_in"] = max(0.0, seg["src_in"] - lo)
    if seg.get("pieces"):
        seg["pieces"] = [(xa, xb, sa - lo, sb - lo) for xa, xb, sa, sb in seg["pieces"]]
        seg["length"] = hi - lo


class _WavOut:
    """WAV float32 estéreo de 48 kHz gravado em ordem (o cabeçalho é refeito no fim com o tamanho certo)."""

    def __init__(self, path: str, channels: int = 2):
        self.fh = open(path, "wb")
        self.channels = channels
        self.frames = 0
        self._header()

    def _header(self) -> None:
        data = self.frames * 4 * self.channels
        self.fh.write(b"RIFF" + struct.pack("<I", 36 + data) + b"WAVE")
        self.fh.write(b"fmt " + struct.pack("<IHHIIHH", 16, 3, self.channels, RATE, RATE * 4 * self.channels,
                                            4 * self.channels, 32))
        self.fh.write(b"data" + struct.pack("<I", data))

    def write(self, x: np.ndarray) -> None:
        self.fh.write(np.ascontiguousarray(x, dtype="<f4").tobytes())
        self.frames += len(x)

    def close(self) -> None:
        self.fh.seek(0)
        self._header()
        self.fh.close()


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def render_clean(job: dict, out_path: str, cancel: threading.Event | None = None,
                 perf: media.Perf | None = None) -> bool:
    """Grava o WAV limpo de `job` (o `seg["clean"]` de `clean_input`). False se cancelado; erro do ffmpeg vira
    RuntimeError. Um trecho do ruído que ficou mudo ou curto (o arquivo mudou) não limpa: o WAV sai igual ao arquivo."""
    from .audiomix import WavReader
    src = f"{out_path[:-4]}.fonte.wav"
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-nostdin", "-hide_banner", "-ss", _fmt(job["lo"]), "-t",
           _fmt(job["hi"] - job["lo"]), "-i", job["source"], "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(RATE),
           "-c:a", "pcm_f32le", "-f", "wav", src]
    try:
        code, _out, err = _run(cmd, cancel, perf)
        if code < 0:
            return False
        if code != 0:
            raise RuntimeError(_("Falha ao limpar o som do clipe:\n{erro}").format(
                erro=err.decode("utf-8", "replace").strip()[-1500:]))
        try:
            prof = profile_for(job["source"], job["ini"], job["fim"], cancel)
        except CleanError:
            prof = None
        if cancel is not None and cancel.is_set():
            return False
        reader = WavReader(src)
        out = _WavOut(out_path, reader.channels)
        try:
            if prof is None:
                for s in range(0, reader.frames, BLOCK):
                    out.write(reader.read(s, BLOCK))
                ok = True
            else:
                ok = denoise_stream(reader.read, reader.frames, out.write, prof, job["amount"], cancel=cancel)
        finally:
            out.close()
        if not ok:
            _remove(out_path)
        return ok
    finally:
        _remove(src)


def _prune(keep: set[str]) -> None:
    """Tira os WAVs limpos mais antigos até caber em `CLEAN_MAX_BYTES` (menos os de `keep` e os usados há pouco)."""
    now = time.time()
    found = []
    try:
        for e in os.scandir(clean_dir()):
            if e.is_file() and e.name.endswith(".wav"):
                st = e.stat()
                found.append((st.st_mtime, st.st_size, e.path))
    except OSError:
        return
    total = sum(f[1] for f in found)
    for mtime, size, path in sorted(found):
        if total <= CLEAN_MAX_BYTES:
            break
        if path in keep or now - mtime < CLEAN_KEEP_S:
            continue
        _remove(path)
        if not os.path.exists(path):
            total -= size


def render_inputs(segs: list[dict], cancel: threading.Event | None = None, perf: media.Perf | None = None) -> bool:
    """Deixa prontos os WAVs limpos dos segmentos (`audiomix.segments`) que pedem limpeza. Grava num parcial e troca
    no fim. False se foi cancelado; erro do ffmpeg vira RuntimeError."""
    wanted = {seg["path"]: seg["clean"] for seg in segs if seg.get("clean")}
    if not wanted:
        return True
    clean_dir().mkdir(parents=True, exist_ok=True)
    _prune(set(wanted))
    for path, job in wanted.items():
        if cancel is not None and cancel.is_set():
            return False
        if os.path.exists(path):
            try:
                os.utime(path)
            except OSError:
                pass
            continue
        part = f"{path[:-4]}.{os.getpid()}_{threading.get_ident()}.wav"
        try:
            if not render_clean(job, part, cancel, perf):
                return False
            os.replace(part, path)
        finally:
            _remove(part)
    return True


# ------------------------------------------------------------------ "Aprender o ruído" (o trecho)
def learn_range(seq, clip, playhead: int, inp: int | None = None, outp: int | None = None) -> tuple[float, float]:
    """O trecho do arquivo (segundos, em ordem) para aprender o ruído: a entrada/saída da linha do tempo se as duas
    caem dentro do clipe; senão 1 s a partir do cursor dentro do clipe (recuado se o clipe acaba antes). CleanError
    com a explicação se o cursor está fora do clipe ou o trecho fica curto demais."""
    fps = seq.fps
    if inp is not None and outp is not None and clip.start <= inp < outp <= clip.end:
        f0, f1 = int(inp), int(outp)
    else:
        if not clip.start <= int(playhead) < clip.end:
            raise CleanError(_("Ponha o cursor sobre um trecho deste clipe em que só o ruído toca (ou marque a entrada "
                               "e a saída dentro dele)."))
        n = max(1, int(round(fps)))
        f1 = min(clip.end, int(playhead) + n)
        f0 = max(clip.start, f1 - n)
    t0, t1 = sorted((seq.src_time(clip, f0), seq.src_time(clip, f1)))
    if t1 - t0 < MIN_PROFILE_S - 1e-9:
        raise CleanError(_("O trecho do ruído é curto demais: escolha pelo menos {s} s só com o ruído.").format(
            s=str(MIN_PROFILE_S).replace(".", ",")))
    return t0, t1


def source_path(seq, clip) -> str | None:
    """O que a mixagem lê para o clipe: o arquivo ou, de um clipe de sequência, o WAV da mixagem dela (None se não
    tem som de arquivo)."""
    from . import audiomix
    inner = seq.nested(clip)
    if inner is not None:
        return audiomix.nested_mix_path(inner)
    src = seq.sources.get(clip.src)
    if src is None or not src.is_file or not src.has_audio:
        return None
    return clip.src


# ------------------------------------------------------------------ zumbido da rede elétrica
HUM_Q = 15.0                # entalhe: ≥ 30 dB no centro e ±0,5 dB a ±10% da frequência
HUM_SEARCH = (50, 60)
HUM_MIN_DB = 10.0           # o zumbido precisa sobressair isto da vizinhança do espectro
HUM_MARGIN_DB = 6.0         # e isto da outra rede
HUM_RATE = 4000
HUM_MAX_S = 20.0


def hum_filters(v: dict) -> list[str]:
    """Entalhes do ffmpeg em f, 2f, … (`zumbido_harmonicos` deles); [] sem zumbido escolhido."""
    z = v.get("zumbido", "nao")
    if z == "nao":
        return []
    f0 = float(z)
    n = max(1, int(v.get("zumbido_harmonicos", 6)))
    return [f"bandreject=f={_fmt(f0 * k)}:width_type=q:width={_fmt(HUM_Q)}" for k in range(1, n + 1)]


def hum_scores(x: np.ndarray, rate: int = HUM_RATE) -> dict[str, float]:
    """Quanto (dB) as três primeiras harmônicas de 50 e de 60 Hz sobressaem da vizinhança do espectro (média das
    três). `x` mono."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    seg = 4 * rate                                        # 0,25 Hz por faixa
    if len(x) < seg:
        x = np.pad(x, (0, seg - len(x)))
    win = np.hanning(seg)
    starts = range(0, len(x) - seg + 1, seg // 2)
    spec = np.mean([np.abs(np.fft.rfft(x[s:s + seg] * win)) ** 2 for s in starts], axis=0)
    hz = np.fft.rfftfreq(seg, 1.0 / rate)
    out = {}
    for base in HUM_SEARCH:
        vals = []
        for h in (1, 2, 3):
            f = base * h
            peak = spec[(hz >= f - 1.0) & (hz <= f + 1.0)].max()
            near = spec[((hz >= f - 12) & (hz <= f - 4)) | ((hz >= f + 4) & (hz <= f + 12))]
            vals.append(10.0 * math.log10((peak + 1e-30) / (float(np.median(near)) + 1e-30)))
        out[str(base)] = float(np.mean(vals))
    return out


def detect_hum(x: np.ndarray, rate: int = HUM_RATE) -> str | None:
    """"50", "60" ou None (nenhum sobressai, ou os dois parecidos)."""
    s = hum_scores(x, rate)
    best = max(s, key=s.get)
    other = min(s, key=s.get)
    if s[best] >= HUM_MIN_DB and s[best] - s[other] >= HUM_MARGIN_DB:
        return best
    return None


def detect_hum_file(path: str, t0: float, t1: float, cancel: threading.Event | None = None) -> str | None:
    """`detect_hum` no som do arquivo entre t0 e t1 (no máximo `HUM_MAX_S`, em mono a 4 kHz)."""
    a, b = sorted((float(t0), float(t1)))
    x = read_range(path, a, min(max(b - a, 0.5), HUM_MAX_S), rate=HUM_RATE, channels=1, cancel=cancel)
    if len(x) < HUM_RATE // 2 or float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) < 10 ** (SILENT_DB / 20):
        return None
    return detect_hum(x[:, 0], HUM_RATE)


# ------------------------------------------------------------------ cortes e voz
SPEECH_MAX_EXPANSION = 10.0   # 100%: o trecho baixo sobe até 20 dB
SPEECH_MAX_COMPRESSION = 2.0  # 100%: o pico alto desce até 6 dB


def speechnorm_filter(amount: float) -> str:
    """`speechnorm` do ffmpeg pela força 0–1: expansão 1 + 9·a (até +20 dB), compressão 1 + a (até −6 dB), pico
    alvo 0,9 e subida/descida 0,0005 + 0,0045·a por meio ciclo (mais força, alcança o alvo mais depressa); canais
    ligados (a imagem estéreo não muda)."""
    a = max(0.0, min(1.0, float(amount)))
    e = 1.0 + (SPEECH_MAX_EXPANSION - 1.0) * a
    c = 1.0 + (SPEECH_MAX_COMPRESSION - 1.0) * a
    r = 0.0005 + 0.0045 * a
    return f"speechnorm=p=0.9:e={_fmt(e)}:c={_fmt(c)}:r={_fmt(r)}:f={_fmt(r)}:l=1"


def after_eq_filters(v: dict) -> list[str]:
    """Depois da equalização e antes do `loudnorm`: cortar graves/agudos (2 polos) e nivelar a voz."""
    f: list[str] = []
    hp, lp = float(v.get("passa_alta", 0.0)), float(v.get("passa_baixa", 0.0))
    if hp > 0:
        f.append(f"highpass=f={_fmt(hp)}:poles=2")
    if lp > 0:
        f.append(f"lowpass=f={_fmt(lp)}:poles=2")
    a = float(v.get("nivelar_voz", 0.0))
    if a > 0:
        f.append(speechnorm_filter(a))
    return f


__all__ = ["NoiseProfile", "CleanError", "learn_profile", "denoise", "denoise_stream", "profile_for", "clean_input",
           "render_inputs", "learn_range", "source_path", "hum_filters", "detect_hum", "detect_hum_file",
           "after_eq_filters", "speechnorm_filter"]
