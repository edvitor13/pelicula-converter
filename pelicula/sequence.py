"""Decodificação dos quadros de uma sequência do modo Edição (sem GPU e sem Qt).

O resultado de cada quadro é um `FrameLayers`: as imagens dos clipes ativos, de baixo para cima,
já no tamanho certo para a tela. A montagem (cor, enquadramento, mesclagem) é feita depois na GPU
por `Engine.compose()`, na thread dona do contexto OpenGL.

- `grab()` decodifica um quadro qualquer (arrastar a linha do tempo, "Salvar quadro").
- `SequenceReader` lê em sequência (reprodução e exportação): um `media.FrameReader` por clipe,
  aberto antes do clipe começar (sem engasgo nos cortes), andando para a frente e repetindo o último
  quadro em câmera lenta. O quadro do arquivo mostrado vem sempre de `Sequence.src_frame()`, então
  o quadro N lido em sequência é igual ao quadro N buscado direto.
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import media, timeline


@dataclass
class LayerImage:
    """Imagem de uma camada: h × w × 3 (RGB) ou, de fontes com transparência, h × w × 4 com o RGB
    **pré-multiplicado** pelo alfa (`media.FrameReader(alpha=True)`), uint8 ou uint16. `editshaders.CLIP`
    desfaz a multiplicação depois de amostrar e usa o alfa como cobertura."""
    layer: timeline.Layer
    image: np.ndarray


@dataclass
class FrameLayers:
    frame: int
    layers: list[LayerImage]


# ------------------------------------------------------------------ tamanhos
def canvas_size(seq: timeline.Sequence, height: int | None = None) -> tuple[int, int]:
    """Tamanho da tela: a resolução da sequência (None) ou reduzida para a prévia (altura ≤ a da sequência)."""
    if height is None or height >= seq.height:
        return seq.width, seq.height
    h = max(2, int(height))
    w = max(2, int(round(seq.width * h / seq.height)))
    return w - w % 2, h - h % 2


def decode_size(seq: timeline.Sequence, clip: timeline.Clip, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    """Tamanho em que o clipe é decodificado: a caixa do encaixe na tela (× escala, se ampliado),
    sem passar da resolução do arquivo. Com a escala animada, a maior escala do clipe (decodifica uma vez só,
    no tamanho em que ele mais aparece)."""
    from . import compositor, keyframes
    src = seq.sources[clip.src]
    sw, sh = (src.width or canvas_w), (src.height or canvas_h)
    bw, bh = compositor.fit_box(seq, clip, canvas_w, canvas_h)
    k = max(1.0, keyframes.max_value(clip.keys.get("escala"), float(clip.values.get("escala", 1.0))))
    w = min(int(round(bw * k)), sw)
    h = min(int(round(bh * k)), sh)
    return max(2, w), max(2, h)


def _blank(w: int, h: int, depth: int) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8 if depth == 8 else np.uint16)


# ------------------------------------------------------------------ acesso direto
_CACHE: OrderedDict = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 16


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _cached_grab(src: timeline.Source, frame: int, w: int, h: int, depth: int, hq: bool) -> np.ndarray:
    try:
        mtime = os.path.getmtime(src.path)
    except OSError:
        mtime = 0.0
    key = (src.path, mtime, 0 if src.is_image else frame, w, h, depth, hq, src.has_alpha)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    img = media.grab_frame(src.to_info(), 0 if src.is_image else frame, w, h, depth, hq=hq, alpha=src.has_alpha)
    img.setflags(write=False)
    with _CACHE_LOCK:
        _CACHE[key] = img
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return img


def grab(seq: timeline.Sequence, frame: int, canvas_w: int, canvas_h: int, depth: int = 8,
         hq: bool = False) -> FrameLayers:
    """Imagens das camadas do quadro `frame` (pode ser chamado de qualquer thread)."""
    out = []
    for layer in seq.layers_at(frame):
        src = seq.sources.get(layer.clip.src)
        if src is None or not src.has_video or not os.path.exists(src.path):
            continue
        w, h = decode_size(seq, layer.clip, canvas_w, canvas_h)
        out.append(LayerImage(layer, _cached_grab(src, layer.src_frame, w, h, depth, hq)))
    return FrameLayers(int(frame), out)


# ------------------------------------------------------------------ leitura em sequência
class _ClipStream:
    """Um FrameReader de um clipe, andando para a frente no arquivo."""

    def __init__(self, src: timeline.Source, start: int, w: int, h: int, depth: int, hq: bool, perf):
        self.src, self.w, self.h, self.depth, self.hq, self.perf = src, w, h, depth, hq, perf
        self.reader: media.FrameReader | None = None
        self.next = 0
        self.last: np.ndarray | None = None
        self.last_idx = -1
        self.error = ""
        self._open(start)

    def _open(self, f: int) -> None:
        self.close()
        self.reader = media.FrameReader(self.src.to_info(), self.w, self.h, self.depth, max(0, f), None,
                                        hq=self.hq, perf=self.perf, alpha=self.src.has_alpha)
        self.next = max(0, f)

    def get(self, f: int, jump: int) -> np.ndarray:
        if f == self.last_idx and self.last is not None:
            return self.last
        if self.reader is None or f < self.next or f - self.next > jump:
            self._open(f)
        while self.next <= f:
            img = self.reader.read() if self.reader is not None else None
            if img is None:
                if self.reader is not None and not self.error:
                    self.error = self.reader.error
                break
            self.last, self.last_idx = img, self.next
            self.next += 1
        if self.last is None:
            self.last = _blank(self.w, self.h, self.depth)
            self.last_idx = f
        return self.last

    def close(self) -> None:
        if self.reader is not None:
            self.reader.close()
            self.reader = None


class SequenceReader:
    """Lê os quadros da sequência em ordem: `read()` devolve um `FrameLayers` ou None no fim.

    `start`/`count` em quadros da sequência; com `fps_out` (texto "30000/1001", "25"...) o quadro i
    da saída mostra o quadro `start + floor(i·fps_seq/fps_out)` da sequência.
    """

    def __init__(self, seq: timeline.Sequence, canvas_w: int, canvas_h: int, depth: int = 8, start: int = 0,
                 count: int | None = None, hq: bool = False, perf: media.Perf | None = None,
                 fps_out: str | None = None, lookahead: float = 1.5):
        self.seq = seq.copy()
        self.w, self.h, self.depth, self.hq = int(canvas_w), int(canvas_h), depth, hq
        self.perf = perf or media.Perf()
        self.start = max(0, int(start))
        self.count = count
        self.ratio = (self.seq.fps / float(timeline.parse_fps(fps_out))) if fps_out else 1.0
        self.i = 0
        self.lookahead = max(1, int(round(lookahead * self.seq.fps)))
        self.jump = max(8, int(round(2 * self.seq.fps)))
        self._streams: dict[str, _ClipStream] = {}
        self._pending: dict[str, Future] = {}
        self._images: dict[tuple, np.ndarray] = {}
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="seq-prefetch")
        self._closed = False
        self._errors: list[str] = []

    @property
    def error(self) -> str:
        msgs = [e for e in self._errors if e]
        msgs += [s.error for s in self._streams.values() if s.error]
        return "\n".join(dict.fromkeys(msgs))

    def frame_at(self, i: int) -> int:
        if self.ratio == 1.0:
            return self.start + i
        return self.start + int(math.floor(i * self.ratio + 1e-6))

    def _size(self, clip: timeline.Clip) -> tuple[int, int]:
        return decode_size(self.seq, clip, self.w, self.h)

    def _new_stream(self, clip: timeline.Clip, first: int) -> _ClipStream:
        w, h = self._size(clip)
        return _ClipStream(self.seq.sources[clip.src], first, w, h, self.depth, self.hq, self.perf)

    def _stream(self, clip: timeline.Clip, f: int) -> _ClipStream:
        st = self._streams.get(clip.id)
        if st is None:
            fut = self._pending.pop(clip.id, None)
            if fut is not None:
                try:
                    st = fut.result()
                except Exception as exc:  # noqa: BLE001
                    self._errors.append(str(exc))
                    st = None
            if st is None:
                st = self._new_stream(clip, f)
            self._streams[clip.id] = st
        return st

    def _image(self, clip: timeline.Clip) -> np.ndarray:
        src = self.seq.sources[clip.src]
        w, h = self._size(clip)
        key = (src.path, w, h)
        img = self._images.get(key)
        if img is None:
            try:
                img = media.grab_frame(src.to_info(), 0, w, h, self.depth, hq=self.hq, alpha=src.has_alpha)
            except Exception as exc:  # noqa: BLE001
                self._errors.append(str(exc))
                img = _blank(w, h, self.depth)
            self._images[key] = img
        return img

    def _prefetch(self, t: int) -> None:
        """Abre antes da hora os leitores dos clipes que começam nos próximos quadros."""
        horizon = t + self.lookahead
        for c in self.seq.clips:
            if (c.kind != timeline.VIDEO or c.id in self._streams or c.id in self._pending
                    or not (t < c.start <= horizon)):
                continue
            src = self.seq.sources.get(c.src)
            if src is None or src.is_image or not src.has_video or not os.path.exists(src.path):
                continue
            self._pending[c.id] = self._pool.submit(self._new_stream, c, self.seq.src_frame(c, c.start))

    def read(self) -> FrameLayers | None:
        if self._closed:
            return None
        if self.count is not None and self.i >= self.count:
            return None
        t = self.frame_at(self.i)
        if t >= self.seq.duration:
            return None
        self.i += 1
        out: list[LayerImage] = []
        active: set[str] = set()
        for layer in self.seq.layers_at(t):
            c = layer.clip
            src = self.seq.sources.get(c.src)
            if src is None or not src.has_video or not os.path.exists(src.path):
                continue
            if src.is_image:
                img = self._image(c)
            else:
                active.add(c.id)
                img = self._stream(c, layer.src_frame).get(layer.src_frame, self.jump)
            out.append(LayerImage(layer, img))
        for cid in [k for k in self._streams if k not in active]:
            c = self.seq.find(cid)
            # Fecha quem já passou (o "dissolver" mantém o anterior aberto enquanto aparece).
            if c is None or c.end + self.lookahead < t or c.start > t + self.lookahead:
                self._streams.pop(cid).close()
        self._prefetch(t)
        return FrameLayers(t, out)

    def close(self) -> None:
        self._closed = True
        for st in self._streams.values():
            st.close()
        self._streams.clear()
        for fut in self._pending.values():
            fut.add_done_callback(lambda f: f.exception() is None and f.result().close())
        self._pending.clear()
        self._pool.shutdown(wait=False)


# ------------------------------------------------------------------ informação virtual
def first_video_source(seq: timeline.Sequence) -> timeline.Source | None:
    vids = sorted((c for c in seq.clips if c.kind == timeline.VIDEO), key=lambda c: (c.start, c.track))
    return seq.sources.get(vids[0].src) if vids else None


def legal_range(seq: timeline.Sequence) -> bool:
    """Faixa da tela montada para o look (`build_plan(..., legal=...)`): a dos clipes de vídeo.

    Cada clipe é decodificado com a sua faixa (vídeo YUV de faixa legal chega expandido; imagens e vídeo
    de faixa cheia, como estão) e a tela guarda esses valores; o look lê a tela com um perfil só. Vale a
    faixa da maioria dos clipes de vídeo (empate: a do primeiro na linha do tempo); imagens paradas só
    contam numa montagem sem vídeo. Limitação conhecida: clipes log de faixas diferentes na mesma
    montagem usam uma faixa só (perfil de entrada por clipe fica para depois).
    """
    clips = sorted((c for c in seq.clips if c.kind == timeline.VIDEO), key=lambda c: (c.start, c.track))
    srcs = [seq.sources[c.src] for c in clips if c.src in seq.sources and seq.sources[c.src].has_video]
    flags = [media.legal_range(s) for s in srcs if not s.is_image] or [media.legal_range(s) for s in srcs]
    if not flags:
        return True
    legal = sum(flags)
    return flags[0] if legal * 2 == len(flags) else legal * 2 > len(flags)


def media_info(seq: timeline.Sequence) -> media.MediaInfo:
    """`MediaInfo` da sequência para a exportação (tamanho, fps, duração, som e formato do 1º vídeo)."""
    first = first_video_source(seq)
    anyp = first.path if first else next(iter(c.src for c in seq.clips), "")
    base = Path(anyp) if anyp else Path.home() / "sequencia.mp4"
    video = first is not None and not first.is_image
    ext = base.suffix if (video and base.suffix) else ".mp4"
    name = seq.name or (base.stem + "_edicao")
    fr = timeline.parse_fps(seq.fps_str)
    frames = max(1, seq.duration)
    return media.MediaInfo(
        path=str(base.with_name(name + ext)), width=seq.width, height=seq.height, fps=float(fr),
        fps_str=f"{fr.numerator}/{fr.denominator}", frames=frames, duration=frames / float(fr),
        pix_fmt=(first.pix_fmt if video else "") or "yuv420p", bit_depth=first.bit_depth if video else 8,
        codec=(first.codec if video else "") or "h264", profile=first.profile if video else "",
        bitrate=first.bitrate if video else 0, color_space="bt709", color_range="tv", color_transfer="bt709",
        color_primaries="bt709", has_audio=seq.has_audio, audio_codec="pcm_s24le" if seq.has_audio else "",
        container=(first.container if video else "") or "mov,mp4,m4a,3gp,3g2,mj2", is_image=False)


def missing_sources(seq: timeline.Sequence) -> list[str]:
    """Arquivos usados pela sequência que não existem mais no disco."""
    used = {c.src for c in seq.clips}
    return sorted(p for p in used if not os.path.exists(p))
