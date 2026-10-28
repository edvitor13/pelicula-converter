"""Decodificação dos quadros de uma sequência do modo Edição (sem GPU e sem Qt).

O resultado de cada quadro é um `FrameLayers`: as imagens dos clipes ativos, de baixo para cima,
já no tamanho certo para a tela. A montagem (cor, enquadramento, mesclagem) é feita depois na GPU
por `Engine.compose()`, na thread dona do contexto OpenGL.

- `grab()` decodifica um quadro qualquer (arrastar a linha do tempo, "Salvar quadro").
- `SequenceReader` lê em sequência (reprodução e exportação): um `media.FrameReader` por clipe,
  aberto antes do clipe começar (sem engasgo nos cortes), andando para a frente e repetindo o último
  quadro em câmera lenta. O quadro do arquivo mostrado vem sempre de `Sequence.src_frame()`, então
  o quadro N lido em sequência é igual ao quadro N buscado direto. Um clipe em reverso (`Clip.reverse`) usa
  `_ReverseStream`: lê blocos do arquivo para a frente e entrega de trás para a frente, com o próximo bloco
  (o de antes, no arquivo) decodificado ao fundo; a memória fica limitada a dois blocos (`REVERSE_BUDGET`).
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


# ------------------------------------------------------------------ clipes sem arquivo
# Geradores das fontes sem arquivo (`timeline.Source.kind` ≠ "arquivo": título, cor, contagem, legenda…):
#     RENDERERS[tipo] = fn(seq, clip, quadro, largura, altura, profundidade) -> np.ndarray
# `quadro` é o quadro da fonte (`Layer.src_frame` = `Sequence.src_frame`: já com aparar, velocidade e congelar;
# em segundos, quadro / fonte.fps); largura × altura é o tamanho de decodificação (`decode_size`, a caixa do
# clipe na tela). O gerador desenha só o conteúdo (o que está em `src.data`): posição, escala, giro, corte,
# opacidade, cor e transições do clipe o shader CLIP aplica depois, como em qualquer clipe.
# Devolve h × w × 4 RGBA **pré-multiplicado** (ou h × w × 3, opaco), uint8 (profundidade 8) ou uint16 (16);
# uint8 numa profundidade 16 e float 0–1 são convertidos. A mesma função serve `grab` (prévia, "Salvar
# quadro") e `SequenceReader` (exportação): prévia = exportação. Regras: puro e determinístico (nada de
# random/time; só seq, clipe, quadro e `src.data`), sem OpenGL e sem widgets — roda na thread de quem lê, às
# vezes em duas ao mesmo tempo; um QImage/QPainter serve (com a QGuiApplication criada). Cache, se precisar,
# por conta do gerador. Tipo sem gerador registrado (projeto de uma versão mais nova): camada transparente.
Renderer = Callable[[timeline.Sequence, timeline.Clip, int, int, int, int], np.ndarray]
RENDERERS: dict[str, Renderer] = {}


def _as_layer(img, w: int, h: int, depth: int, kind: str) -> np.ndarray:
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[:2] != (h, w) or arr.shape[2] not in (3, 4):
        raise ValueError(f"o gerador {kind!r} devolveu {arr.shape}; esperado ({h}, {w}, 4) ou ({h}, {w}, 3)")
    want = np.uint8 if depth == 8 else np.uint16
    if arr.dtype == want:
        return np.ascontiguousarray(arr)
    if arr.dtype == np.uint8:  # 8 bits numa leitura de 16: ×257 (exato)
        return arr.astype(np.uint16) * np.uint16(257)
    if np.issubdtype(arr.dtype, np.floating):
        mx = 255.0 if depth == 8 else 65535.0
        return np.clip(np.rint(arr.astype(np.float64) * mx), 0, mx).astype(want)
    raise ValueError(f"o gerador {kind!r} devolveu {arr.dtype}; esperado uint8/uint16 ou float 0–1")


def render_source(seq: timeline.Sequence, clip: timeline.Clip, frame: int, w: int, h: int,
                  depth: int) -> np.ndarray:
    """Imagem de um clipe sem arquivo no quadro `frame` da fonte (o gerador de `RENDERERS`, conferido)."""
    src = seq.sources[clip.src]
    fn = RENDERERS.get(src.kind)
    if fn is None:
        return np.zeros((h, w, 4), dtype=np.uint8 if depth == 8 else np.uint16)
    return _as_layer(fn(seq, clip, int(frame), int(w), int(h), int(depth)), int(w), int(h), depth, src.kind)


# Quadro da fonte que a miniatura mostra, por tipo (padrão 0): um título que surge aos poucos mostra o texto inteiro.
THUMBNAIL_FRAME: dict[str, Callable[[timeline.Source], int]] = {}


def source_thumbnail(src: timeline.Source, w: int, h: int, rgba: bool = False) -> np.ndarray:
    """Miniatura RGB (8 bits) de uma fonte sem arquivo para a Mídia: o gerador no quadro 0 (ou o de
    `THUMBNAIL_FRAME`), sobre preto. `rgba`: a imagem do gerador (RGBA pré-multiplicado), para mostrar sobre o
    xadrez (`ui/alphaview.py`)."""
    seq = timeline.Sequence.for_source(src)
    pick = THUMBNAIL_FRAME.get(src.kind)
    frame = max(0, int(pick(src))) if pick is not None else 0
    img = render_source(seq, seq.clips[0], frame, w, h, 8)
    if rgba and img.shape[2] == 4:
        return np.ascontiguousarray(img)
    return np.ascontiguousarray(img[..., :3])  # pré-multiplicado sobre preto = o próprio RGB


# ------------------------------------------------------------------ acesso direto
_CACHE: OrderedDict = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 16


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def present(src: timeline.Source) -> bool:
    """O arquivo da fonte está no disco? (sequência de imagens: o primeiro quadro dela)"""
    return media.path_exists(src.path, src.seq_start)


def _cached_grab(src: timeline.Source, frame: int, w: int, h: int, depth: int, hq: bool) -> np.ndarray:
    try:
        mtime = os.path.getmtime(media.sequence_file(src.path, src.seq_start + frame) if src.is_sequence
                                 else src.path)
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
        if src is None or not src.has_video:
            continue
        w, h = decode_size(seq, layer.clip, canvas_w, canvas_h)
        if not src.is_file:
            out.append(LayerImage(layer, render_source(seq, layer.clip, layer.src_frame, w, h, depth)))
            continue
        if not present(src):
            continue
        out.append(LayerImage(layer, _cached_grab(src, layer.src_frame, w, h, depth, hq)))
    return FrameLayers(int(frame), out)


# ------------------------------------------------------------------ leitura em sequência
REVERSE_BUDGET = 192 * 1024 * 1024  # bytes por bloco de um clipe em reverso
REVERSE_MAX_FRAMES = 48             # quadros por bloco (no máximo)


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


class _ReverseStream:
    """Um clipe em reverso: o arquivo é lido em blocos para a frente (um `FrameReader` por bloco, que termina no
    quadro pedido) e entregue de trás para a frente. Enquanto um bloco é mostrado, o anterior do arquivo é
    decodificado ao fundo; a memória fica em dois blocos de até `REVERSE_BUDGET` bytes cada."""

    def __init__(self, src: timeline.Source, start: int, w: int, h: int, depth: int, hq: bool, perf):
        self.src, self.w, self.h, self.depth, self.hq, self.perf = src, w, h, depth, hq, perf
        bpp = (4 if src.has_alpha else 3) * (1 if depth == 8 else 2)
        self.n = max(2, min(REVERSE_MAX_FRAMES, REVERSE_BUDGET // max(1, w * h * bpp)))
        self.error = ""
        self.loads = 0  # blocos decodificados (os testes conferem que a leitura anda em blocos)
        self._ahead: tuple[int, int, Future] | None = None
        self._pool: ThreadPoolExecutor | None = None
        self.cache: dict[int, np.ndarray] = self._load(max(0, start))

    def _load(self, f: int) -> dict[int, np.ndarray]:
        """O bloco que termina no quadro `f` do arquivo: {quadro: imagem}."""
        self.loads += 1
        lo = max(0, f - self.n + 1)
        out: dict[int, np.ndarray] = {}
        reader = media.FrameReader(self.src.to_info(), self.w, self.h, self.depth, lo, f - lo + 1, hq=self.hq,
                                   perf=self.perf, alpha=self.src.has_alpha)
        try:
            for k in range(lo, f + 1):
                img = reader.read()
                if img is None:
                    if not self.error:
                        self.error = reader.error
                    break
                out[k] = img
        finally:
            reader.close()
        return out

    def _prefetch(self, lo: int) -> None:
        """Começa ao fundo o bloco que vem antes de `lo` no arquivo (o próximo a aparecer)."""
        if lo <= 0 or (self._ahead is not None and self._ahead[1] == lo - 1):
            return
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="seq-reverse")
        end = lo - 1
        self._ahead = (max(0, end - self.n + 1), end, self._pool.submit(self._load, end))

    def get(self, f: int, jump: int) -> np.ndarray:
        img = self.cache.get(f)
        if img is None:
            ahead, self._ahead = self._ahead, None
            self.cache = {}
            if ahead is not None and ahead[0] <= f <= ahead[1]:
                try:
                    self.cache = ahead[2].result()
                except Exception as exc:  # noqa: BLE001
                    self.error = self.error or str(exc)
            elif ahead is not None:
                ahead[2].cancel()
            if f not in self.cache:
                self.cache = self._load(f)
            img = self.cache.get(f)
            if img is None:  # passou do fim do arquivo: o último quadro que existe (como o leitor para a frente)
                img = self.cache[max(self.cache)] if self.cache else _blank(self.w, self.h, self.depth)
        if self.cache:
            self._prefetch(min(self.cache))
        return img

    def close(self) -> None:
        self.cache = {}
        if self._ahead is not None:
            self._ahead[2].cancel()
            self._ahead = None
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None


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

    def _new_stream(self, clip: timeline.Clip, first: int) -> _ClipStream | _ReverseStream:
        w, h = self._size(clip)
        kind = _ReverseStream if clip.reverse and not clip.frozen else _ClipStream
        return kind(self.seq.sources[clip.src], first, w, h, self.depth, self.hq, self.perf)

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

    def _render(self, layer: timeline.Layer) -> np.ndarray:
        """Clipe sem arquivo: o mesmo gerador de `grab` (`render_source`); um erro vira camada transparente."""
        w, h = self._size(layer.clip)
        try:
            return render_source(self.seq, layer.clip, layer.src_frame, w, h, self.depth)
        except Exception as exc:  # noqa: BLE001 — a exportação continua; o erro aparece no fim
            self._errors.append(str(exc))
            return np.zeros((h, w, 4), dtype=np.uint8 if self.depth == 8 else np.uint16)

    def _prefetch(self, t: int) -> None:
        """Abre antes da hora os leitores dos clipes que começam nos próximos quadros."""
        horizon = t + self.lookahead
        for c in self.seq.clips:
            if (c.kind != timeline.VIDEO or c.id in self._streams or c.id in self._pending
                    or not (t < c.start <= horizon)):
                continue
            src = self.seq.sources.get(c.src)
            if (src is None or src.is_image or not src.has_video or not src.is_file
                    or not present(src)):
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
            if src is None or not src.has_video:
                continue
            if not src.is_file:
                out.append(LayerImage(layer, self._render(layer)))
                continue
            if not present(src):
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
def _file_sources(seq: timeline.Sequence) -> set[str]:
    return {p for p, s in seq.sources.items() if s.is_file}


def first_video_source(seq: timeline.Sequence) -> timeline.Source | None:
    """O arquivo do primeiro clipe de vídeo (clipes sem arquivo não contam)."""
    files = _file_sources(seq)
    vids = sorted((c for c in seq.clips if c.kind == timeline.VIDEO and c.src in files),
                  key=lambda c: (c.start, c.track))
    return seq.sources.get(vids[0].src) if vids else None


def legal_range(seq: timeline.Sequence) -> bool:
    """Faixa da tela montada para o look (`build_plan(..., legal=...)`): a dos clipes de vídeo.

    Cada clipe é decodificado com a sua faixa (vídeo YUV de faixa legal chega expandido; imagens e vídeo
    de faixa cheia, como estão) e a tela guarda esses valores; o look lê a tela com um perfil só. Vale a
    faixa da maioria dos clipes de vídeo (empate: a do primeiro na linha do tempo); imagens paradas e
    clipes sem arquivo (RGB de faixa cheia) só contam numa montagem sem vídeo. Limitação conhecida: clipes
    log de faixas diferentes na mesma montagem usam uma faixa só (perfil de entrada por clipe fica para depois).
    """
    clips = sorted((c for c in seq.clips if c.kind == timeline.VIDEO), key=lambda c: (c.start, c.track))
    srcs = [seq.sources[c.src] for c in clips if c.src in seq.sources and seq.sources[c.src].has_video]
    flags = ([media.legal_range(s) for s in srcs if s.is_file and not s.is_image]
             or [media.legal_range(s) for s in srcs])
    if not flags:
        return True
    legal = sum(flags)
    return flags[0] if legal * 2 == len(flags) else legal * 2 > len(flags)


def media_info(seq: timeline.Sequence) -> media.MediaInfo:
    """`MediaInfo` da sequência para a exportação (tamanho, fps, duração, som e formato do 1º vídeo)."""
    first = first_video_source(seq)
    files = _file_sources(seq)
    anyp = first.path if first else next(iter(c.src for c in seq.clips if c.src in files), "")
    base = Path(anyp) if anyp else Path.home() / "sequencia.mp4"
    video = first is not None and not first.is_image
    ext = base.suffix if (video and base.suffix) else ".mp4"
    if first is not None and first.is_sequence:  # plano_%04d.png → plano_edicao.mov
        ext = ".mov"
    name = seq.name or (media.sequence_stem(str(base)) + "_edicao")
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
    """Arquivos usados pela sequência que não existem mais no disco (clipes sem arquivo não contam)."""
    used = {c.src for c in seq.clips} & _file_sources(seq)
    return sorted(p for p in used if not present(seq.sources[p]))


# ------------------------------------------------------------------ geradores que vêm com o app
# Registram-se aqui (desenho, som e miniatura) para valer em todo lugar que lê uma montagem: janela, exportação
# e terminal. Ficam registrados mesmo com o módulo desligado (a renderização nunca consulta `modules`).
from . import generators as _generators, titles as _titles  # noqa: E402

_generators.register()
_titles.register()
