"""Cache do som de cada clipe e a soma da mixagem (1.8, ARQUITETURA §43).

Antes cada edição refazia um grafo grande do ffmpeg com a montagem inteira. Agora o som de cada pedaço da montagem
(`Part`: um clipe de som com a cadeia de filtros de sempre, um tom de um clipe gerado, e o que a onda B acrescentar)
é renderizado **uma vez** pelo ffmpeg num WAV float32 de 48 kHz estéreo, guardado no temporário com o nome tirado de
tudo que muda aquelas amostras (`Part.key`). A mixagem (`mix`) só garante o cache (os que faltam, num grupo pequeno de
processos, cancelável) e soma em float64 com o numpy: cada pedaço na amostra dele, cortado no trecho pedido, com o
ganho e o balanço da faixa, e o resultado vira 24 bits como o `pcm_s24le` do ffmpeg faz. Prévia, exportação,
sequência aninhada, volume alvo, silêncios e transcrição passam por aqui (`audiomix.render_mix`).

O pedaço começa no começo da cadeia do clipe (com a sobra da transição de som) e cobre o clipe inteiro: mover o
clipe ou exportar outro trecho não renderiza nada de novo. O ganho da faixa só sai da cadeia (e vai para a soma, onde
mexer no fader não renderiza nada) quando a cadeia é linear (`chain_is_linear`); com um filtro não linear (voz,
normalizar, redução de ruído) ele fica onde sempre esteve, no `volume` do clipe, antes desses filtros.

Ganchos (seção 43.6):
- `LINEAR_KEYS`: ajustes de som do clipe cujos filtros, depois do volume, são lineares. Ajuste novo fora do padrão
  que não está aqui faz a cadeia contar como não linear (o seguro).
- `PROVIDERS`: fn(seq) -> [Part] com as fontes de som da montagem; uma fonte nova (música, efeitos, narração) entra
  com um provedor e a função que a renderiza (`Part.graph` para o ffmpeg ou `Part.synth` em numpy).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audiomix, editparams, media, timeline
from .i18n import _

RATE = audiomix.RATE
VERSION = 1                         # muda quando a forma de renderizar um pedaço muda (o cache antigo fica de fora)
CACHE_ENV = "PELICULA_SOM_CACHE"    # pasta do cache (os testes apontam para uma pasta deles)
CLIP_DIR = "pelicula_som_clipes"    # pasta dos pedaços no temporário do sistema, ao lado de `audiomix.NEST_DIR`
CLIP_MAX_BYTES = 2 * 1024 ** 3      # o mesmo limite e a mesma limpeza dos WAVs das sequências aninhadas
WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))  # processos do ffmpeg ao mesmo tempo
BATCH = 24                          # pedaços no máximo por processo (cada um é uma saída do mesmo ffmpeg)
CHUNK = RATE * 10                   # amostras somadas de cada vez (memória limitada em montagens longas)
PEAK_BLOCK = RATE // 100            # 10 ms: um pico por faixa a cada bloco (medidores do mixer)

# Ajustes de som do clipe que só geram filtros lineares depois do volume (ou nada depois dele): com todos os outros no
# padrão, o ganho da faixa pode ir para a soma sem mudar o som. Frentes novas acrescentam aqui o que for linear.
LINEAR_KEYS: set[str] = {"volume", "mudo", "balanco", "fade_in", "fade_out", "transicao", "graves", "medios",
                         "agudos", "velocidade",
                         # 1.8, limpeza do som (frente L, ARQUITETURA §44): filtros fixos (passa-altas/baixas e os
                         # entalhes do zumbido). O ruído aprendido e "nivelar a voz" não são lineares.
                         "passa_alta", "passa_baixa", "zumbido", "zumbido_harmonicos"}

# Pastas de WAVs derivados com o conteúdo no nome (a mixagem de uma aninhada, a entrada limpa de um clipe): a chave do
# pedaço usa o caminho, sem a data (que muda a cada uso, e o arquivo pode ainda não existir quando a chave é calculada).
CONTENT_NAMED_DIRS: list[Callable[[], Path]] = [audiomix.nested_dir]

# Etapas que preparam entradas derivadas antes de renderizar os pedaços: fn(segmentos, cancel, perf) -> bool (False =
# cancelado). Recebem as entradas de `audiomix.segments(seq)` da sequência INTEIRA (são elas que `clip_parts` lê) só dos
# clipes que tocam no trecho. Ex.: `somlimpo.render_inputs` (frente L) grava o WAV limpo que `segments` já pôs em
# `seg["path"]`.
PRERENDER: list[Callable] = []


def cache_dir() -> Path:
    """Pasta dos pedaços renderizados. Fica de uma sessão para a outra, como a das sequências aninhadas, e o tamanho é
    limitado por `prune`."""
    return Path(os.environ.get(CACHE_ENV) or tempfile.gettempdir()) / CLIP_DIR


@dataclass
class Part:
    """Um pedaço de som da montagem, renderizado uma vez e guardado.

    `offset` é a amostra da sequência (48 kHz, desde o quadro 0) em que a amostra 0 do pedaço toca. A renderização é
    `graph` (entradas do ffmpeg e um grafo cuja saída se chama `[out]`) ou `synth` (numpy: devolve (n, 2) float32).
    `kind`/`track` dizem a faixa (ganho, balanço e stem); `track_gain` diz se o ganho da faixa entra na soma (False
    quando a cadeia já o leva)."""

    key: str
    offset: int
    kind: str
    track: int
    clip: str = ""
    graph: tuple[list[str], str] | None = None
    synth: Callable[[], np.ndarray] | None = None
    track_gain: bool = True
    length: int = 0           # amostras previstas (para saber se toca no trecho antes de renderizar)
    source: str = ""          # "clipe" (toca no trecho se `audiomix.segments` do trecho o tem), "tom"…

    @property
    def path(self) -> str:
        return str(cache_dir() / f"{self.key}.wav")


# ------------------------------------------------------------------ os pedaços de uma montagem
def chain_is_linear(values: dict) -> bool:
    """A cadeia do clipe é linear depois do volume? Todo ajuste fora do padrão precisa estar em `LINEAR_KEYS`."""
    base = editparams.AUDIO.defaults()
    return all(k in LINEAR_KEYS or (k in base and v == base[k]) for k, v in values.items())


def _key(*data) -> str:
    return hashlib.sha1(json.dumps([VERSION, *data], sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _inputs_stamp(seq: timeline.Sequence, inputs: list[str]) -> list:
    """As entradas com a data e o tamanho de cada arquivo (o WAV de uma sequência aninhada já tem o conteúdo no nome, e
    a data dele muda a cada uso)."""
    out: list = []
    for i, a in enumerate(inputs):
        if i > 0 and inputs[i - 1] == "-i" and os.path.isabs(a) and not _is_nested_wav(a):
            out.append(audiomix._file_stamp(a))
        else:
            out.append(a)
    return out


def _is_nested_wav(path: str) -> bool:
    """WAV derivado com o conteúdo no nome (`CONTENT_NAMED_DIRS`)."""
    parent = Path(path).parent
    return any(parent == d() for d in CONTENT_NAMED_DIRS)


def clip_parts(seq: timeline.Sequence) -> list[Part]:
    """Um pedaço por clipe de som que toca (`audiomix.segments` da sequência inteira), com a cadeia de sempre do
    começo ao fim dela (sem recorte de trecho nem atraso)."""
    fps = seq.fps
    out = []
    for seg in audiomix.segments(seq):
        c: timeline.Clip = seg["clip"]
        total = seg["pre"] + seg["clip_len"] + seg["post"]  # a cadeia inteira, com as sobras da transição
        cs = dict(seg, trim_start=0.0, trim_len=total, delay=0.0)
        linear = chain_is_linear(c.values)
        if linear:  # o ganho da faixa vai para a soma (`mix`)
            cs["gain_db"] = seg["gain_db"] - seg["track_db"]
            cs["track_db"] = 0.0
        if cs.get("pieces"):
            inputs, graph = audiomix._retimed_chain(cs, 0, 0)
        else:
            inputs = ["-ss", audiomix._fmt(seg["src_in"]), "-t", audiomix._fmt(seg["src_len"]), "-i", seg["path"]]
            graph = audiomix._chain(cs, 0, 0)
        graph = graph[: graph.rindex("[a0]")] + "[out]"
        key = _key("clipe", _inputs_stamp(seq, inputs), graph, editparams.stored_values(c.kind, c.values),
                   c.keys, c.speed, c.ramp, c.reverse, seq.fps_str)
        t0 = c.start / fps - seg["pre"]
        out.append(Part(key, _at(t0), timeline.AUDIO, c.track, c.id, (inputs, graph), track_gain=linear,
                        length=_at(total), source="clipe"))
    return out


def tone_parts(seq: timeline.Sequence) -> list[Part]:
    """Os tons dos clipes gerados (`audiomix.tones`, o bipe da ponta), na faixa de vídeo do clipe."""
    out = []
    by_id = {c.id: c for c in seq.clips}
    for t in audiomix.tones(seq):
        c = by_id.get(t["clip"])
        whole = dict(t, onset=0)
        inputs = audiomix._tone_input(whole)
        graph = audiomix._tone_chain(whole, 0, 0)
        graph = graph[: graph.rindex("[t0]")] + "[out]"
        out.append(Part(_key("tom", inputs, graph), t["onset"], timeline.VIDEO, c.track if c else 0, t["clip"],
                        (inputs, graph), track_gain=False, length=t["samples"], source="tom"))
    return out


# Fontes de som da montagem. Uma fonte nova (onda B) acrescenta o provedor dela aqui.
PROVIDERS: list[Callable[[timeline.Sequence], list[Part]]] = [clip_parts, tone_parts]


def parts(seq: timeline.Sequence) -> list[Part]:
    return [p for fn in PROVIDERS for p in fn(seq)]


def _at(seconds: float) -> int:
    """Segundos → amostra a 48 kHz (arredonda como o ffmpeg: metade para longe do zero)."""
    return int(math.floor(seconds * RATE + 0.5))


def range_samples(seq: timeline.Sequence, start: int, end: int) -> tuple[int, int]:
    """(primeira amostra, quantas) do trecho [start, end) em quadros, como o grafo antigo media: a duração passa pelas
    6 casas de `_fmt` antes de virar amostras."""
    a, b = audiomix._range(seq, start, end)
    return _at(a / seq.fps), _at(float(audiomix._fmt((b - a) / seq.fps)))


# ------------------------------------------------------------------ renderizar o que falta
def _popen_kw(perf: media.Perf | None) -> dict:
    kw = (perf or media.Perf()).popen_kwargs()
    if "creationflags" not in kw:
        kw["creationflags"] = media.NO_WINDOW
    return kw


def _error(text: str) -> RuntimeError:
    return RuntimeError(_("Falha ao mixar o som da sequência:\n{erro}").format(erro=text.strip()[-1500:]))


_INPUT_REF = re.compile(r"\[(\d+):a(:\d+)?\]")
_LABEL = re.compile(r"\[([A-Za-z_]\w*)\]")


def _relabel(graph: str, base: int, tag: str) -> str:
    """O grafo de um pedaço dentro de um processo com outros: as entradas `[n:a…]` andam `base` e os rótulos `[nome]`
    ganham o prefixo `tag` (contrato de `Part.graph`)."""
    graph = _INPUT_REF.sub(lambda m: f"[{int(m.group(1)) + base}:a{m.group(2) or ''}]", graph)
    return _LABEL.sub(lambda m: f"[{tag}{m.group(1)}]", graph)


class _Job:
    """Um processo do ffmpeg renderizando alguns pedaços, cada um no seu parcial (uma saída do ffmpeg por pedaço:
    abrir um processo por clipe custava mais que o som de um clipe curto)."""

    def __init__(self, batch: list[Part], perf: media.Perf | None):
        self.batch = batch
        tag = f"{os.getpid()}_{threading.get_ident()}"
        self.partials = [f"{p.path[:-4]}.{tag}.wav" for p in batch]
        self.script = None
        inputs: list[str] = []
        chains: list[str] = []
        outs: list[str] = []
        for j, (p, partial) in enumerate(zip(batch, self.partials)):
            ins, graph = p.graph
            chains.append(_relabel(graph, inputs.count("-i"), f"p{j}_"))
            inputs += ins
            outs += ["-map", f"[p{j}_out]", "-c:a", "pcm_f32le", "-ar", str(RATE), "-ac", "2", "-f", "wav", partial]
        graph = ";".join(chains)
        ff = media.ffmpeg()
        cmd = [ff, "-y", "-v", "error", "-nostdin", "-hide_banner", *inputs]
        if len(graph) > audiomix.SCRIPT_LIMIT:
            fd, self.script = tempfile.mkstemp(prefix="pelicula_pedaco_", suffix=".txt")
            os.close(fd)
            Path(self.script).write_text(graph, encoding="utf-8")
            cmd += [audiomix.script_option(ff), self.script]
        else:
            cmd += ["-filter_complex", graph]
        cmd += outs
        self.err = bytearray()
        self.proc = audiomix.subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.PIPE, **_popen_kw(perf))
        self.drain = threading.Thread(target=self._drain, daemon=True)
        self.drain.start()

    def _drain(self) -> None:
        for line in self.proc.stderr:
            if len(self.err) < 20000:
                self.err.extend(line)

    def finish(self) -> None:
        """Os parciais viram os pedaços do cache (outra mixagem que gravou o mesmo pedaço antes também serve)."""
        try:
            for p, partial in zip(self.batch, self.partials):
                try:
                    os.replace(partial, p.path)
                except OSError:
                    if not os.path.exists(p.path):
                        raise
        finally:
            self.cleanup()

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.drain.join(timeout=2)
        self.cleanup()

    def cleanup(self) -> None:
        for partial in self.partials:
            audiomix._remove(partial)
        if self.script:
            audiomix._remove(self.script)
            self.script = None


def _write_synth(part: Part) -> None:
    x = np.asarray(part.synth(), dtype=np.float32).reshape(-1, 2)
    partial = f"{part.path[:-4]}.{os.getpid()}_{threading.get_ident()}.wav"
    try:
        with WavWriter(partial, float32=True) as w:
            w.write(x)
        os.replace(partial, part.path)
    finally:
        audiomix._remove(partial)


def _batches(todo: list[Part]) -> list[list[Part]]:
    """Os pedaços divididos entre `WORKERS` processos (no máximo `BATCH` em cada), os mais longos primeiro."""
    todo = sorted(todo, key=lambda p: -p.length)
    n = max(min(WORKERS, len(todo)), -(-len(todo) // BATCH))
    out: list[list[Part]] = [[] for _ in range(n)]
    load = [0] * n
    for p in todo:
        k = load.index(min(load))
        out[k].append(p)
        load[k] += max(1, p.length)
    return [b for b in out if b]


def ensure(items: list[Part], cancel: threading.Event | None = None, perf: media.Perf | None = None) -> bool:
    """Deixa no cache os pedaços que faltam (em até `WORKERS` processos do ffmpeg ao mesmo tempo). False se foi
    cancelado (nada pela metade fica); erro do ffmpeg vira RuntimeError. Os que já estão ganham a data de agora (a
    limpeza tira os mais antigos)."""
    todo, seen = [], set()
    for p in items:
        if p.key in seen:
            continue
        seen.add(p.key)
        if os.path.exists(p.path):
            try:
                os.utime(p.path)
            except OSError:
                pass
        else:
            todo.append(p)
    if not todo:
        return True
    if cancel is not None and cancel.is_set():
        return False
    cache_dir().mkdir(parents=True, exist_ok=True)
    prune({p.path for p in items})
    for p in [p for p in todo if p.synth is not None]:
        if cancel is not None and cancel.is_set():
            return False
        _write_synth(p)
    pending = _batches([p for p in todo if p.synth is None])
    running: list[_Job] = []
    try:
        while pending or running:
            while pending and len(running) < WORKERS:
                if cancel is not None and cancel.is_set():
                    return False
                running.append(_Job(pending.pop(0), perf))
            if cancel is not None and cancel.is_set():
                return False
            for job in list(running):
                if job.proc.poll() is None:
                    continue
                job.drain.join(timeout=2)
                running.remove(job)
                if job.proc.returncode != 0:
                    job.cleanup()
                    raise _error(job.err.decode("utf-8", "replace"))
                job.finish()
            if running:
                time.sleep(0.01)
        return True
    finally:
        for job in running:
            job.kill()


def prune(keep: set[str]) -> None:
    """Tira os pedaços mais antigos até caber em `CLIP_MAX_BYTES` (a regra de `audiomix._prune_nested`)."""
    audiomix._prune_dir(cache_dir(), keep, CLIP_MAX_BYTES)


# ------------------------------------------------------------------ a soma
@dataclass
class Mix:
    """O resultado de `mix`: o WAV do trecho e, se pedidos, os picos de cada faixa e os stems."""

    path: str
    samples: int
    tracks: list[tuple[str, int]] = field(default_factory=list)  # faixas com som no trecho (tipo, índice)
    peaks: np.ndarray | None = None   # (blocos de 10 ms, faixas de áudio) picos 0…1 depois do ganho e do balanço
    peak_tracks: list[int] = field(default_factory=list)  # índice da faixa de áudio de cada coluna de `peaks`
    master_peaks: np.ndarray | None = None  # (blocos de 10 ms,) picos da mixagem (tons e outras fontes incluídos)
    stems: dict[tuple[str, int], str] = field(default_factory=dict)


def track_gains(seq: timeline.Sequence, kind: str, idx: int) -> tuple[float, float, float]:
    """(ganho linear, esquerda, direita) da faixa na soma: o volume em dB e o balanço com a lei do `balanco` do clipe
    (`audiomix._chain_tail`): o lado para onde se puxa fica em 1 e o outro cai até 0."""
    tr = seq.track(kind, idx)
    if tr is None or kind != timeline.AUDIO:
        return 1.0, 1.0, 1.0
    pan = float(tr.pan)
    return 10.0 ** (tr.volume / 20.0), min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)


def to_s24(x: np.ndarray) -> np.ndarray:
    """Float → inteiros de 24 bits como o ffmpeg grava `pcm_s24le` (float → s32 com `llrintf` e corte; depois
    `>> 8`, que arredonda para baixo)."""
    v = np.rint(np.asarray(x, np.float32).astype(np.float64) * 2147483648.0)
    v = np.clip(v, -2147483648.0, 2147483647.0).astype(np.int64)
    return (v >> 8).astype(np.int32)


def mix(seq: timeline.Sequence, out_path: str, start: int = 0, end: int = -1,
        cancel: threading.Event | None = None, perf: media.Perf | None = None, *,
        with_peaks: bool = False, stems: Callable[[str, int], str] | None = None) -> Mix | None:
    """Grava o som do trecho [start, end) (quadros) num WAV de 24 bits, 48 kHz estéreo. None se o trecho não tem som
    ou se foi cancelado; erro do ffmpeg (ou de gravação) vira RuntimeError.

    `with_peaks`: guarda o pico de cada faixa de áudio a cada 10 ms (`Mix.peaks`, os medidores do mixer). `stems`:
    fn(tipo, índice) → caminho de um WAV com o som só daquela faixa (com o ganho e o balanço dela), do mesmo tamanho e
    no mesmo começo do trecho."""
    a0, n = range_samples(seq, start, end)
    a1 = a0 + n
    # O que toca no trecho: os clipes que `segments` do trecho tem (a mesma regra do grafo antigo) e as outras fontes
    # que caem nele.
    playing = {s["clip"].id for s in audiomix.segments(seq, start, end)}
    items = [p for p in parts(seq)
             if (p.clip in playing if p.source == "clipe" else p.offset < a1 and p.offset + p.length > a0)]
    if not items or n <= 0:
        return None
    if not audiomix._render_nested(seq, start, end, cancel, perf):
        return None
    if not _prerender(seq, playing, cancel, perf):
        return None
    try:
        if not ensure(items, cancel, perf):
            return None
    except OSError as exc:
        raise _error(str(exc)) from exc
    readers = []
    for p in items:
        try:
            r = audiomix.WavReader(p.path)
        except (OSError, ValueError) as exc:
            raise _error(str(exc)) from exc
        if p.offset < a1 and p.offset + r.frames > a0:
            readers.append((p, r))
    tracks = sorted({(p.kind, p.track) for p, _r in readers}, key=lambda t: (t[0] != timeline.AUDIO, t[1]))
    audio_cols = [t[1] for t in tracks if t[0] == timeline.AUDIO]
    peaks = np.zeros((-(-n // PEAK_BLOCK), len(audio_cols)), np.float32) if with_peaks else None
    result = Mix(out_path, n, tracks, peaks, audio_cols, np.zeros(len(peaks), np.float32) if with_peaks else None)
    writers: dict[tuple[str, int], WavWriter] = {}
    out = None
    done = False
    try:
        out = WavWriter(out_path, frames=n)
        if stems is not None:
            for t in tracks:
                result.stems[t] = stems(*t)
                writers[t] = WavWriter(result.stems[t], frames=n)
        for c0 in range(0, n, CHUNK):
            if cancel is not None and cancel.is_set():
                break
            m = min(CHUNK, n - c0)
            lo, hi = a0 + c0, a0 + c0 + m
            master = np.zeros((m, 2), np.float64)
            for t in tracks:
                g, gl, gr = track_gains(seq, *t)
                buf = np.zeros((m, 2), np.float64)
                for p, r in readers:
                    if (p.kind, p.track) != t or p.offset >= hi or p.offset + r.frames <= lo:
                        continue
                    s0, s1 = max(lo, p.offset), min(hi, p.offset + r.frames)
                    x = r.read(s0 - p.offset, s1 - s0).astype(np.float64)
                    # O ganho da faixa: na soma (cadeia linear) ou já dentro da cadeia do clipe (não linear).
                    buf[s0 - lo: s0 - lo + len(x)] += x * g if p.track_gain else x
                buf *= (gl, gr)
                master += buf
                if t in writers:
                    writers[t].write(buf)
                if peaks is not None and t[0] == timeline.AUDIO:
                    pk = _block_peaks(buf)
                    b0 = c0 // PEAK_BLOCK
                    peaks[b0: b0 + len(pk), audio_cols.index(t[1])] = pk
            out.write(master)
            if result.master_peaks is not None:
                pk = _block_peaks(master)
                result.master_peaks[c0 // PEAK_BLOCK: c0 // PEAK_BLOCK + len(pk)] = pk
        done = not (cancel is not None and cancel.is_set())
    except OSError as exc:
        raise _error(str(exc)) from exc
    finally:
        for w in [out, *writers.values()]:
            if w is not None:
                w.close()
        if not done:  # cancelado ou com erro: nada pela metade fica
            for path in [out_path, *result.stems.values()]:
                audiomix._remove(path)
    return result if done else None


def _prerender(seq: timeline.Sequence, playing: set[str], cancel, perf) -> bool:
    """O ponto das entradas derivadas (`PRERENDER`), depois das aninhadas e antes dos pedaços (`ensure`)."""
    if not PRERENDER:
        return True
    segs = [s for s in audiomix.segments(seq) if s["clip"].id in playing]
    return all(fn(segs, cancel, perf) for fn in PRERENDER)


def _block_peaks(buf: np.ndarray) -> np.ndarray:
    """Pico (os dois canais) de cada bloco de 10 ms do pedaço somado (CHUNK é múltiplo do bloco)."""
    n = len(buf)
    k = -(-n // PEAK_BLOCK)
    a = np.abs(buf).max(axis=1)
    if k * PEAK_BLOCK != n:
        a = np.concatenate([a, np.zeros(k * PEAK_BLOCK - n)])
    return np.minimum(a.reshape(k, PEAK_BLOCK).max(axis=1), 1.0).astype(np.float32)


# ------------------------------------------------------------------ picos das faixas ao lado do WAV da prévia
PEAKS_SUFFIX = ".faixas.npz"


def save_peaks(result: Mix) -> str:
    """Grava `Mix.peaks` ao lado do WAV (o medidor do mixer só indexa, sem decodificar nada). Devolve o caminho."""
    path = result.path + PEAKS_SUFFIX
    if result.peaks is None:
        return ""
    with open(path, "wb") as fh:
        np.savez(fh, picos=result.peaks, faixas=np.asarray(result.peak_tracks, np.int32), mestre=result.master_peaks)
    return path


def load_peaks(wav_path: str) -> tuple[list[int], np.ndarray, np.ndarray] | None:
    """(faixas de áudio, picos delas, picos da mixagem), por bloco de 10 ms, gravados por `save_peaks`; ou None."""
    try:
        with np.load(wav_path + PEAKS_SUFFIX, allow_pickle=False) as z:
            return ([int(i) for i in z["faixas"]], np.array(z["picos"], np.float32),
                    np.array(z["mestre"], np.float32))
    except (OSError, ValueError, KeyError):
        return None


# ------------------------------------------------------------------ WAV
_PCM = b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"  # fim do GUID KSDATAFORMAT_SUBTYPE_*


class WavWriter:
    """WAV estéreo de 48 kHz em 24 bits (`pcm_s24le`, como o do ffmpeg: WAVE_FORMAT_EXTENSIBLE) ou float32, gravado
    em blocos. Com `frames` o tamanho vai no cabeçalho desde o começo; sem, é corrigido no `close`."""

    def __init__(self, path: str, frames: int | None = None, float32: bool = False):
        self.path = path
        self.float32 = float32
        self.width = 4 if float32 else 3
        self.frames = 0
        self.fh = open(path, "wb")
        self._header(frames or 0)

    def _header(self, frames: int) -> None:
        align = 2 * self.width
        data = frames * align
        tag = 3 if self.float32 else 1
        fmt = struct.pack("<HHIIHHHHIH", 0xFFFE, 2, RATE, RATE * align, align, self.width * 8, 22,
                          self.width * 8, 3, tag) + _PCM
        self.fh.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + data) + b"WAVE")
        self.fh.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        self.fh.write(b"data" + struct.pack("<I", data))

    def write(self, x: np.ndarray) -> None:
        x = np.asarray(x).reshape(-1, 2)
        if self.float32:
            self.fh.write(x.astype("<f4").tobytes())
        else:
            v = to_s24(x).astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3]
            self.fh.write(np.ascontiguousarray(v).tobytes())
        self.frames += len(x)

    def close(self) -> None:
        if self.fh.closed:
            return
        self.fh.seek(0)
        self._header(self.frames)
        self.fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
