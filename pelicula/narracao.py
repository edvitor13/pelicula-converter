"""Gravar narração (1.8, ARQUITETURA §48): o gravador e as contas da gravação, sem Qt.

O microfone entrega blocos de PCM crus (8/16/32 bits inteiros ou float, qualquer taxa e número de canais que o
dispositivo escolher); aqui eles viram um WAV de 48 kHz em 24 bits (`somcache.WavWriter`), o formato de todo o som da
montagem. A gravação é um arquivo comum da Mídia: nenhum tipo de clipe novo e nenhum campo novo no projeto.

**Canais**: 1 canal vira estéreo centrado (L = R, a voz fica no meio do balanço da faixa); 2 canais ficam como estão; mais
de 2, só os dois primeiros. (Média dos canais não: uma interface com o microfone só na entrada 1 perderia 6 dB.)

**Taxa**: igual a 48 kHz passa direto, sem conta nenhuma; as outras por `Resampler`, um sinc com janela de Kaiser (24
pontos de cada lado, corte logo abaixo do Nyquist menor, ganho 1 em DC), em fluxo: a saída não depende de como os blocos
chegaram. A posição de cada amostra de saída sai de uma conta inteira (`n × entrada / saída`): nada de erro acumulado.

**Atraso do microfone**: o som capturado chega alguns milissegundos depois de acontecer; `skip_s` descarta esse começo do
arquivo (à amostra), o que equivale a adiantar o clipe sem depender do fps nem esbarrar no quadro 0.

**Arquivo seguro**: grava num parcial ao lado (`system.partial_path`) e só troca de nome em `finish`; `cancel` (ou uma
gravação vazia) não deixa nada. `BackgroundRecorder` faz a conversão e a escrita numa thread: a interface só põe os bytes
numa fila e lê o nível.
"""

from __future__ import annotations

import math
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import somcache, system
from .audiomix import RATE
from .i18n import _

PREFIX = "narracao_"     # narracao_001.wav, narracao_002.wav…
HALF_TAPS = 24           # pontos do sinc de cada lado
KAISER_BETA = 8.6        # ~ −90 dB fora da faixa
CUTOFF = 0.96            # corte em fração do Nyquist menor
BLOCK = 8192             # amostras de saída por rodada do `Resampler`
FORMATS = {              # nome → (dtype do PCM, zero, escala)
    "uint8": (np.uint8, 128.0, 128.0),
    "int16": (np.int16, 0.0, 32768.0),
    "int32": (np.int32, 0.0, 2147483648.0),
    "float32": (np.float32, 0.0, 1.0),
}


@dataclass(frozen=True)
class Level:
    """Pico e RMS (lineares, 0 a 1) do último bloco que chegou."""
    peak: float = 0.0
    rms: float = 0.0

    @property
    def peak_db(self) -> float:
        return db(self.peak)

    @property
    def rms_db(self) -> float:
        return db(self.rms)


def db(x: float) -> float:
    """dBFS de um valor linear (−120 no silêncio)."""
    return 20.0 * math.log10(x) if x > 1e-6 else -120.0


@dataclass(frozen=True)
class Take:
    """Uma gravação pronta."""
    path: str
    frames: int          # amostras a 48 kHz
    peak: float          # pico linear do arquivo

    @property
    def seconds(self) -> float:
        return self.frames / RATE


# ------------------------------------------------------------------ resample
class Resampler:
    """Conversão de taxa em fluxo (n × canais, float): `process(bloco)` devolve o que já dá para calcular e `flush(total)` o
    resto. Saída total = `round(entrada × saída / entrada_taxa)` amostras."""

    def __init__(self, src: int, dst: int = RATE, channels: int = 2):
        self.src, self.dst, self.channels = int(src), int(dst), int(channels)
        self.cutoff = min(1.0, self.dst / self.src) * CUTOFF
        self.buf = np.zeros((HALF_TAPS, self.channels), np.float64)   # o silêncio antes do começo
        self.b0 = -HALF_TAPS                                          # índice (na entrada) da primeira linha de `buf`
        self.n_in = 0
        self.n_out = 0
        self.taps = np.arange(-HALF_TAPS + 1, HALF_TAPS + 1)

    def _weights(self, frac: np.ndarray) -> np.ndarray:
        d = self.taps[None, :] - frac[:, None]                        # distância de cada ponto à posição de saída
        arg = np.clip(1.0 - (d / HALF_TAPS) ** 2, 0.0, None)
        window = np.i0(KAISER_BETA * np.sqrt(arg)) / np.i0(KAISER_BETA)
        w = np.sinc(self.cutoff * d) * window
        return w / w.sum(axis=1, keepdims=True)

    def _run(self, upto: int) -> np.ndarray:
        """As amostras de saída de `n_out` até `upto` (exclusive), com a entrada que já está em `buf`."""
        parts = []
        while self.n_out < upto:
            n = np.arange(self.n_out, min(upto, self.n_out + BLOCK), dtype=np.int64)
            num = n * self.src
            i0, rest = num // self.dst, num % self.dst
            w = self._weights(rest / self.dst)
            idx = (i0[:, None] + self.taps[None, :]) - self.b0
            parts.append(np.einsum("mk,mkc->mc", w, self.buf[idx]))
            self.n_out = int(n[-1]) + 1
        out = np.concatenate(parts) if parts else np.zeros((0, self.channels))
        keep = max(self.n_out * self.src // self.dst - HALF_TAPS + 1, self.b0)   # o que ainda será lido
        self.buf = self.buf[keep - self.b0:]
        self.b0 = keep
        return out

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.float64).reshape(-1, self.channels)
        if not len(x):
            return np.zeros((0, self.channels), np.float32)
        self.buf = np.concatenate([self.buf, x])
        self.n_in += len(x)
        ready = self.n_in - HALF_TAPS    # a saída n precisa da entrada até floor(n × src / dst) + HALF_TAPS
        upto = -(-ready * self.dst // self.src) if ready > 0 else 0
        return self._run(upto).astype(np.float32)

    def flush(self) -> np.ndarray:
        """O fim: completa com silêncio e entrega o que falta até o total (`round(n_in × dst / src)`)."""
        total = int(math.floor(self.n_in * self.dst / self.src + 0.5))
        if self.n_out >= total:
            return np.zeros((0, self.channels), np.float32)
        self.buf = np.concatenate([self.buf, np.zeros((HALF_TAPS + 1, self.channels))])
        return self._run(total).astype(np.float32)


def to_float(data: bytes, fmt: str, channels: int) -> np.ndarray:
    """Bytes do dispositivo → float32 (n × canais) entre −1 e 1 (`len(data)` múltiplo de um quadro)."""
    dtype, zero, scale = FORMATS[fmt]
    x = np.frombuffer(data, dtype=np.dtype(dtype).newbyteorder("<"))
    return ((x.astype(np.float64) - zero) / scale).astype(np.float32).reshape(-1, channels)


def block_level(data: bytes, fmt: str, channels: int) -> Level:
    """Pico e RMS de um bloco cru (o medidor do painel enquanto não grava; um resto menos que um quadro é ignorado)."""
    width = np.dtype(FORMATS[fmt][0]).itemsize * channels
    data = bytes(data)[:len(data) - len(data) % width]
    if not data:
        return Level()
    x = to_stereo(to_float(data, fmt, channels))
    return Level(float(np.abs(x).max()), float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))))


def to_stereo(x: np.ndarray) -> np.ndarray:
    """1 canal → L = R; 2 ficam; mais de 2, os dois primeiros."""
    if x.shape[1] == 1:
        return np.repeat(x, 2, axis=1)
    return x[:, :2]


# ------------------------------------------------------------------ gravador
class Recorder:
    """Recebe os blocos do microfone (`feed`) e grava o WAV. `skip_s`: começo a descartar (atraso do microfone);
    `max_s`: duração máxima do arquivo (a partir do que sobra depois de `skip_s`; passou disso, `full` fica verdadeiro e o
    resto é ignorado)."""

    def __init__(self, path: str, rate: int, channels: int, fmt: str = "int16", *, skip_s: float = 0.0,
                 max_s: float | None = None):
        if fmt not in FORMATS:
            raise ValueError(f"formato de amostra desconhecido: {fmt}")
        if rate <= 0 or channels <= 0:
            raise ValueError("taxa e canais precisam ser positivos")
        self.path = str(path)
        self.rate, self.channels, self.fmt = int(rate), int(channels), fmt
        self.partial = system.partial_path(self.path)
        self.resampler = None if self.rate == RATE else Resampler(self.rate, RATE, 2)
        self.skip = max(0, int(round(skip_s * RATE)))
        self.limit = None if max_s is None else max(0, int(round(max_s * RATE)))
        self.level = Level()
        self.peak = 0.0                 # maior pico gravado (linear)
        self.silent_run = 0             # quadros seguidos de zeros exatos que chegaram (microfone mudo no sistema?)
        self.frames = 0                 # amostras já gravadas
        self.full = False
        self.closed = False
        self._rest = b""
        self._skipped = 0
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.writer = somcache.WavWriter(self.partial)

    @property
    def seconds(self) -> float:
        return self.frames / RATE

    def feed(self, data: bytes) -> Level:
        """Um bloco do dispositivo (pode vir cortado no meio de um quadro). Devolve o nível dele."""
        if self.closed:
            return self.level
        width = np.dtype(FORMATS[self.fmt][0]).itemsize * self.channels
        data = self._rest + bytes(data)
        usable = len(data) - len(data) % width
        self._rest = data[usable:]
        if not usable:
            return self.level
        x = to_stereo(to_float(data[:usable], self.fmt, self.channels))
        absx = np.abs(x)
        self.level = Level(float(absx.max()), float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))))
        self.silent_run = self.silent_run + len(x) if not absx.any() else 0
        if self.full:
            return self.level
        y = x if self.resampler is None else self.resampler.process(x)
        self._write(y)
        return self.level

    def _write(self, y: np.ndarray) -> None:
        if self._skipped < self.skip:
            cut = min(len(y), self.skip - self._skipped)
            self._skipped += cut
            y = y[cut:]
        if self.limit is not None and self.frames + len(y) >= self.limit:
            y = y[:self.limit - self.frames]
            self.full = True
        if len(y):
            self.writer.write(y)
            self.frames += len(y)
            self.peak = max(self.peak, float(np.abs(y).max()))

    def finish(self) -> Take | None:
        """Fecha o arquivo e o põe no lugar de uma vez. None (e nada no disco) se não gravou nenhuma amostra."""
        if self.closed:
            return None
        if self.resampler is not None and not self.full:
            self._write(self.resampler.flush())
        self._close()
        if self.frames == 0:
            system.remove_file(self.partial)
            return None
        system.replace_file(self.partial, self.path)
        return Take(self.path, self.frames, self.peak)

    def cancel(self) -> None:
        """Descarta tudo: nem o parcial nem o arquivo ficam."""
        self._close()
        system.remove_file(self.partial)

    def _close(self) -> None:
        if not self.closed:
            self.closed = True
            self.writer.close()


class BackgroundRecorder:
    """O `Recorder` numa thread: `feed` só põe os bytes numa fila (chamado pela interface, a cada `readyRead`); a conversão, o
    resample e a escrita ficam por conta da thread. `level`, `frames`, `full` e `error` podem ser lidos a qualquer hora."""

    def __init__(self, *args, **kwargs):
        self.rec = Recorder(*args, **kwargs)
        self.error = ""
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="narracao", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            data = self._q.get()
            if data is None:
                return
            if self.error:
                continue          # disco cheio ou parecido: descarta o resto, o erro sai em `finish`
            try:
                self.rec.feed(data)
            except OSError as exc:
                self.error = str(exc)

    @property
    def level(self) -> Level:
        return self.rec.level

    @property
    def frames(self) -> int:
        return self.rec.frames

    @property
    def seconds(self) -> float:
        return self.rec.seconds

    @property
    def full(self) -> bool:
        return self.rec.full

    @property
    def silent_run(self) -> int:
        return self.rec.silent_run

    def feed(self, data: bytes) -> None:
        self._q.put(bytes(data))

    def _stop_thread(self) -> None:
        self._q.put(None)
        self._thread.join()

    def finish(self) -> Take | None:
        """Espera a fila esvaziar e fecha o arquivo. OSError se a escrita falhou (nada fica no disco)."""
        self._stop_thread()
        if self.error:
            self.rec.cancel()
            raise OSError(self.error)
        try:
            return self.rec.finish()
        except OSError:
            self.rec.cancel()
            raise

    def cancel(self) -> None:
        self._stop_thread()
        self.rec.cancel()


# ------------------------------------------------------------------ onde fica e onde entra
def take_folder(project_path: str | None) -> tuple[Path, bool]:
    """(pasta, ao lado do projeto?): `<projeto>_narracao/` ao lado do `.plc` salvo; sem projeto salvo, `narracao/` na pasta do
    app (os arquivos não mudam de lugar quando o projeto é salvo depois: o projeto passa a apontar para eles)."""
    if project_path:
        p = Path(project_path)
        return p.with_name(p.stem + "_narracao"), True
    from . import deps
    return deps.app_data_dir() / "narracao", False


def next_take_path(folder: Path) -> Path:
    """`narracao_001.wav`, o primeiro número depois do maior que já existe na pasta (nunca sobrescreve)."""
    top = 0
    if folder.is_dir():
        for f in folder.iterdir():
            m = re.fullmatch(re.escape(PREFIX) + r"(\d+)\.wav", f.name, re.IGNORECASE)
            if m:
                top = max(top, int(m.group(1)))
    return folder / f"{PREFIX}{top + 1:03d}.wav"


def plan_span(frame: int, inp: int | None, outp: int | None, fps: float) -> tuple[int, float | None]:
    """(quadro onde a gravação começa, duração máxima em segundos ou None). Com a entrada marcada, começa nela; senão no
    cursor. Para sozinha na saída, se ela vier depois do começo."""
    start = max(0, int(inp if inp is not None else frame))
    if outp is not None and outp > start and fps > 0:
        return start, (outp - start) / fps
    return start, None


def free_track(seq, start: int, dur: int) -> tuple[int, bool]:
    """(faixa de áudio onde a gravação cabe, é nova?): uma faixa "Narração" livre em [start, start + dur) tem a preferência
    (as gravações seguintes ficam juntas); senão a primeira destravada e livre ali; senão uma nova depois das outras."""
    from .timeline import AUDIO
    n = len(seq.kind_tracks(AUDIO))
    free = [t for t in range(n)
            if not seq.track(AUDIO, t).locked
            and all(c.end <= start or c.start >= start + dur for c in seq.clips_on(AUDIO, t))]
    named = [t for t in free if seq.track(AUDIO, t).name == track_name()]
    if named or free:
        return (named or free)[0], False
    return n, True


def track_name() -> str:
    return _("Narração")


def place_take(seq, src, start: int) -> tuple[int, bool]:
    """Prepara a faixa para a gravação `src` entrar em `start` (cria e nomeia a "Narração" se não há livre) e devolve (faixa,
    nova?). Não insere o clipe: `TimelineModel.insert_media` faz, no mesmo passo do desfazer."""
    from .timeline import AUDIO
    track, new = free_track(seq, start, seq.default_dur(src))
    if new:
        seq.ensure_track(AUDIO, track)
        seq.track(AUDIO, track).name = track_name()
    return track, new
