"""1.9, rastreio de ponto (F3, #68; ARQUITETURA §51.3). Sem GPU nem Qt.

O usuário escolhe um ponto do clipe na prévia; `run` o segue no arquivo para a frente e para trás (um trabalho de CPU da
fila) e devolve um `Track` no **tempo do arquivo** (quadro da fonte → uv do clipe), guardado no clipe
(`Clip.fx["rastros"]`, JSON "efeitos"; recurso `"efeitos_clipe_dados"` do formato 7). "Aplicar a…" (`apply`) assa o
rastro em **chaves de animação** de um alvo (`TARGETS`): a posição do próprio clipe (o ponto fica parado na tela), a
posição de um clipe acima (um título segue o ponto) ou — depois da integração da F2 — o centro da máscara. As chaves são
simplificadas (Ramer–Douglas–Peucker, `TOLERANCE_PX` px@1080) e ficam no tempo do clipe de destino: aparar e mudar a
velocidade as levam junto, como qualquer chave. "Reaplicar" (`reapply`) assa de novo para o mesmo alvo depois de editar.
Nada disso entra no render: a imagem só vê as chaves (decisão 8 do coordenador: o rastro não é uma ligação viva).

Como segue (`track`): correlação cruzada normalizada (`movimento.ncc_map`, FFT + imagens integrais) do quadrado em volta
do ponto no quadro anterior numa janela de busca em volta da posição prevista (velocidade constante), pico com parábola;
o modelo do quadro escolhido corrige a deriva quando ainda casa bem (`ANCHOR_SCORE`). Abaixo de `MIN_SCORE` o ponto se
perdeu: o rastro para ali, com a mensagem do quadro.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

import numpy as np

from . import keyframes, movimento, vfx
from .i18n import N_, _

FX_KEY = "rastros"          # `Clip.fx[FX_KEY]`: lista de rastros (JSON); a interface usa o último
TRACK_H = 720               # altura da decodificação do rastreio (px)
MIN_SCORE = 0.5             # NCC abaixo disto: o ponto se perdeu
ANCHOR_SCORE = 0.85         # o modelo do quadro escolhido ainda casa: ele corrige a deriva
KEY_MARGIN = 0.02           # o modelo-chave vale enquanto casa quase tão bem quanto o do quadro anterior
ANCHOR_SEARCH = 3           # px (da imagem do rastreio) em volta da posição achada para o modelo do quadro escolhido
CHUNK = 48                  # quadros decodificados por vez ao seguir para trás
TOLERANCE_PX = 0.5          # px@1080: quanto as chaves simplificadas podem se afastar do rastro


class TrackError(RuntimeError):
    """O rastreio ou o aplicar não puderam ser feitos (mensagem para o usuário)."""


# ------------------------------------------------------------------ o rastro
@dataclass
class Track:
    """Um ponto seguido no arquivo: `uv[i]` (fração da imagem da fonte, y para baixo) no quadro `first + i` do arquivo;
    `score[i]` = NCC do casamento (1 no quadro escolhido). `ref` = quadro do arquivo em que o ponto foi escolhido; `box`
    = lado do alvo em px@1080; `lost` = mensagem quando parou antes do fim; `target` = o último "Aplicar a…"
    ({"tipo": id de `TARGETS`, "clipe": id do clipe}), para o "Reaplicar"."""
    ref: int
    first: int
    uv: np.ndarray
    score: np.ndarray
    box: float = 64.0
    lost: str = ""
    target: dict = field(default_factory=dict)
    id: str = "r1"

    @property
    def last(self) -> int:
        return self.first + len(self.uv) - 1

    def at(self, src_frame: int) -> tuple[float, float] | None:
        """uv do ponto no quadro do arquivo (None fora do rastro)."""
        i = int(src_frame) - self.first
        if 0 <= i < len(self.uv):
            return float(self.uv[i, 0]), float(self.uv[i, 1])
        return None

    def to_json(self) -> dict[str, Any]:
        out = {"id": self.id, "ref": int(self.ref), "inicio": int(self.first),
               "uv": vfx.pack(np.asarray(self.uv, np.float32)), "nota": vfx.pack(np.asarray(self.score, np.float32)),
               "caixa": float(self.box)}
        if self.lost:
            out["perdido"] = self.lost
        if self.target:
            out["alvo"] = dict(self.target)
        return out

    @classmethod
    def from_json(cls, d: Any) -> "Track | None":
        if not isinstance(d, dict):
            return None
        uv = vfx.unpack(d.get("uv"))
        if uv is None or uv.ndim != 2 or uv.shape[1] != 2 or len(uv) == 0:
            return None
        score = vfx.unpack(d.get("nota"))
        if score is None or score.shape != (len(uv),):
            score = np.ones(len(uv), np.float32)
        try:
            return cls(ref=int(d.get("ref", 0)), first=int(d.get("inicio", 0)), uv=np.array(uv, np.float64),
                       score=np.array(score, np.float64), box=float(d.get("caixa", 64.0)),
                       lost=str(d.get("perdido") or ""),
                       target=dict(d["alvo"]) if isinstance(d.get("alvo"), dict) else {}, id=str(d.get("id") or "r1"))
        except (TypeError, ValueError):
            return None


def tracks_of(clip) -> list[Track]:
    """Os rastros guardados no clipe (os inválidos ficam de fora)."""
    raw = (getattr(clip, "fx", None) or {}).get(FX_KEY)
    return [t for t in (Track.from_json(d) for d in (raw if isinstance(raw, list) else [])) if t is not None]


def track_of(clip) -> Track | None:
    """O rastro que a interface mostra e aplica (o último)."""
    tracks = tracks_of(clip)
    return tracks[-1] if tracks else None


def store(clip, track: Track | None) -> None:
    """Guarda o rastro no clipe (substitui o de antes; None apaga). Faça dentro de um passo do desfazer
    (`TimelineModel.apply_edit`)."""
    fx = {k: v for k, v in (clip.fx or {}).items() if k != FX_KEY}
    if track is not None:
        fx[FX_KEY] = [track.to_json()]
    clip.fx = fx


# ------------------------------------------------------------------ seguir o ponto
def _patch(img: np.ndarray, p: tuple[float, float], size: int) -> tuple[np.ndarray, np.ndarray] | None:
    """O quadrado `size` × `size` (pixels inteiros) em volta do ponto contínuo p e o canto dele; None se sai da imagem."""
    h, w = img.shape
    x0 = int(round(p[0] - size / 2.0))
    y0 = int(round(p[1] - size / 2.0))
    if x0 < 0 or y0 < 0 or x0 + size > w or y0 + size > h:
        return None
    return img[y0:y0 + size, x0:x0 + size], np.array([x0, y0], np.float64)


def _match(img: np.ndarray, tpl: np.ndarray, center: np.ndarray, radius: int) -> tuple[np.ndarray, float] | None:
    """Onde o canto do modelo cai em `img` procurando `radius` px em volta do canto `center` (contínuo): (canto, NCC)."""
    h, w = img.shape
    b = tpl.shape[0]
    sx = int(round(center[0])) - radius
    sy = int(round(center[1])) - radius
    x0, y0 = max(0, sx), max(0, sy)
    x1, y1 = min(w, sx + b + 2 * radius), min(h, sy + b + 2 * radius)
    if x1 - x0 < b + 2 or y1 - y0 < b + 2:
        return None
    m = movimento.ncc_map(img[y0:y1, x0:x1], tpl)
    y, x, score = movimento.subpixel_peak(m)
    return np.array([x0 + x, y0 + y]), float(score)


class _Follower:
    """Segue o ponto quadro a quadro numa direção (o quadro anterior dá o modelo; o do quadro escolhido corrige)."""

    def __init__(self, ref_img: np.ndarray, p: np.ndarray, box: int, search: int):
        got = _patch(ref_img, tuple(p), box)
        if got is None:
            raise TrackError(_("O ponto está perto demais da borda da imagem: escolha um ponto mais para dentro ou "
                               "diminua o tamanho do alvo."))
        self.ref_tpl, corner = got
        self.ref_off = p - corner
        if float(self.ref_tpl.std()) < 1e-3:
            raise TrackError(_("Não há detalhe em volta deste ponto para seguir: escolha um ponto com textura ou "
                               "contraste."))
        self.box, self.search = box, search
        self.reset()

    def reset(self) -> None:
        """Volta ao modelo-chave do quadro escolhido (antes de seguir na outra direção)."""
        self.key_tpl, self.key_off = self.ref_tpl, self.ref_off

    def step(self, prev: np.ndarray, p_prev: np.ndarray, cur: np.ndarray,
             predicted: np.ndarray) -> tuple[np.ndarray, float] | None:
        got = _patch(prev, tuple(p_prev), self.box)
        if got is None:
            return None
        tpl, corner = got
        off = p_prev - corner
        if float(tpl.std()) < 1e-3:
            tpl, off = self.ref_tpl, self.ref_off
        found = _match(cur, tpl, predicted - off, self.search)
        if found is None:
            return None
        pos, score = found[0] + off, found[1]
        # o modelo-chave tira a deriva que o modelo do quadro anterior acumula; quando o alvo mudou (girou, mudou de
        # tamanho) e ele já não casa tão bem quanto o anterior, troca pelo quadrado atual
        key = _match(cur, self.key_tpl, pos - self.key_off, ANCHOR_SEARCH)
        if key is not None and key[1] >= max(ANCHOR_SCORE, score - KEY_MARGIN):
            pos = key[0] + self.key_off
            score = max(score, key[1])
        elif score >= ANCHOR_SCORE:
            fresh = _patch(cur, tuple(pos), self.box)
            if fresh is not None and float(fresh[0].std()) >= 1e-3:
                self.key_tpl, self.key_off = fresh[0], pos - fresh[1]
        return pos, score


def _follow(frames: Iterable[tuple[int, np.ndarray]], follower: _Follower, p0: np.ndarray,
            cancel: Callable[[], bool] | None, tick: Callable[[], None]) -> tuple[list[tuple[int, np.ndarray, float]], int]:
    """Segue a partir do primeiro quadro de `frames` (o escolhido, já com p0). Devolve ([(quadro, posição, nota)] sem o
    primeiro, quadro em que se perdeu ou −1)."""
    out: list[tuple[int, np.ndarray, float]] = []
    prev = None
    p = p0
    vel = np.zeros(2)
    for k, img in frames:
        if cancel is not None and cancel():
            from .jobs import Cancelled
            raise Cancelled()
        if prev is None:
            prev = img
            continue
        got = follower.step(prev, p, img, p + vel)
        tick()
        if got is None or got[1] < MIN_SCORE:
            return out, int(k)
        vel = got[0] - p
        p = got[0]
        out.append((int(k), p.copy(), float(got[1])))
        prev = img
    return out, -1


def track(get_range: Callable[[int, int], Iterator[tuple[int, np.ndarray]]], size: tuple[int, int], ref: int,
          uv: tuple[float, float], first: int, last: int, box: float = 64.0, search: float = 48.0,
          cancel: Callable[[], bool] | None = None, report: Callable[[int, int], None] | None = None) -> Track:
    """Segue o ponto `uv` do quadro `ref` do arquivo de `first` a `last` (quadros do arquivo, inclusive).
    `get_range(a, b)` dá os quadros a…b em cinza (float32, `size`), em ordem crescente. `box`/`search` em px@1080."""
    w, h = size
    k = h / 1080.0
    b = max(8, int(round(box * k)))
    b += b % 2
    r = max(2, int(round(search * k)))
    ref = min(max(int(ref), int(first)), int(last))
    total = max(1, int(last) - int(first))
    done = [0]

    def tick():
        done[0] += 1
        if report is not None:
            report(done[0], total)

    p0 = np.array([uv[0] * w, uv[1] * h], np.float64)
    fwd_frames = get_range(ref, int(last))
    first_frame = next(fwd_frames, None)
    if first_frame is None:
        raise TrackError(_("Não foi possível ler o quadro escolhido do arquivo."))
    follower = _Follower(first_frame[1], p0, b, r)
    ahead, lost_fwd = _follow(_chain([first_frame], fwd_frames), follower, p0, cancel, tick)

    def backwards() -> Iterator[tuple[int, np.ndarray]]:
        end = ref
        while end > first:
            start = max(int(first), end - CHUNK)
            chunk = list(get_range(start, end))
            for item in reversed(chunk):
                yield item
            end = start
            if chunk and chunk[0][0] != start:
                return

    follower.reset()
    behind, lost_bwd = _follow(_dedupe(backwards()), follower, p0, cancel, tick)
    pts = {ref: (p0, 1.0)}
    for kk, p, s in ahead + behind:
        pts[kk] = (p, s)
    lo, hi = min(pts), max(pts)
    keys = list(range(lo, hi + 1))
    uv_arr = np.array([[pts[q][0][0] / w, pts[q][0][1] / h] for q in keys], np.float64)
    score = np.array([pts[q][1] for q in keys], np.float64)
    lost = ""
    if lost_fwd >= 0 or lost_bwd >= 0:
        where = [q for q in (lost_bwd, lost_fwd) if q >= 0]
        lost = _("O ponto se perdeu no quadro {quadro} do arquivo: o rastro vai do quadro {a} ao {b}.").format(
            quadro=", ".join(str(q) for q in where), a=lo, b=hi)
    return Track(ref=ref, first=lo, uv=uv_arr, score=score, box=float(box), lost=lost)


def _chain(head, rest):
    yield from head
    yield from rest


def _dedupe(frames: Iterator[tuple[int, np.ndarray]]) -> Iterator[tuple[int, np.ndarray]]:
    """Os blocos para trás repetem o quadro da emenda: cada quadro uma vez só."""
    seen = None
    for k, img in frames:
        if k == seen:
            continue
        seen = k
        yield k, img


def source_frames(seq, clip) -> tuple[int, int]:
    """(primeiro, último) quadro do arquivo que o clipe mostra."""
    frames = [seq.src_frame(clip, t) for t in (clip.start, clip.end - 1)]
    if clip.retimed:
        frames = [seq.src_frame(clip, t) for t in range(clip.start, clip.end)]
    return min(frames), max(frames)


def run(src, ref: int, uv: tuple[float, float], first: int, last: int, box: float = 64.0, search: float = 48.0,
        cancel: threading.Event | None = None, report: Callable[[int, int], None] | None = None) -> Track:
    """O rastreio de verdade, lendo o arquivo (um trabalho de CPU da fila: nunca na thread da interface)."""
    if src is None or not src.is_file or src.is_image or not src.has_video:
        raise TrackError(_("Só dá para rastrear um ponto num vídeo."))
    info = src.to_info()
    size = movimento.analysis_size(src.width, src.height, TRACK_H)
    stop = (lambda: cancel.is_set()) if cancel is not None else None

    def get_range(a: int, b: int):
        return movimento.read_gray(info, a, b - a + 1, size, stop)

    return track(get_range, size, ref, uv, first, last, box, search, stop, report)


# ------------------------------------------------------------------ onde o ponto está na tela
def canvas_point(seq, clip, t: int, uv: tuple[float, float], values: dict | None = None) -> np.ndarray:
    """O ponto uv do clipe em px da tela da sequência (`seq.width` × `seq.height`) no quadro t, com o enquadramento e a
    geometria dos efeitos (estabilização). `values`: os ajustes a usar (None = os do quadro, com as chaves)."""
    from . import compositor
    from .timeline import Layer
    v = values if values is not None else seq.values_at(clip, t)
    layer = Layer(clip, seq.src_frame(clip, t), values=v)
    m = compositor.transform(seq, clip, seq.width, seq.height, v)
    m = vfx.geometry(seq, layer, m, seq.width, seq.height)
    p = np.linalg.solve(m, np.array([uv[0], uv[1], 1.0]))
    return p[:2] / p[2]


def clip_uv(seq, clip, t: int, fx: float, fy: float) -> tuple[float, float] | None:
    """O uv do clipe no ponto da tela (fração, y para baixo) no quadro t, com a geometria dos efeitos; None fora."""
    from . import compositor
    from .timeline import Layer
    v = seq.values_at(clip, t)
    layer = Layer(clip, seq.src_frame(clip, t), values=v)
    m = vfx.geometry(seq, layer, compositor.transform(seq, clip, seq.width, seq.height, v), seq.width, seq.height)
    u, w, z = m @ np.array([fx * seq.width, fy * seq.height, 1.0])
    u, w = u / z, w / z
    if not (0.0 <= u <= 1.0 and 0.0 <= w <= 1.0):
        return None
    return float(u), float(w)


# ------------------------------------------------------------------ alvos e chaves
@dataclass(frozen=True)
class Target:
    """Um alvo do "Aplicar a…": `keys` (x, y) recebem as chaves; `clips(seq, rastreado)` = os clipes que podem receber;
    `value(seq, rastreado, destino, t, uv)` = o par de valores que acompanha o ponto no quadro t. `relative`: as chaves
    somam ao valor que o destino tem no quadro de referência o quanto `value` andou desde ele (o lugar escolhido fica).
    `units`: em que os valores estão, para a tolerância da simplificação em px@1080 — "janela" (frações da janela
    útil, como `pos_x`/`pos_y`), "clipe" (uv do clipe de destino) ou "px_clipe" (px@1080 do clipe de destino, como
    `mascara_x`/`mascara_y`)."""
    id: str
    label: str
    keys: tuple[str, str]
    clips: Callable[[Any, Any], list]
    value: Callable[[Any, Any, Any, int, tuple[float, float]], tuple[float, float]]
    relative: bool = True
    units: str = "janela"


def _window(seq) -> tuple[float, float]:
    _x, _y, aw, ah = seq.window_rect(seq.width, seq.height)
    return float(aw), float(ah)


def follow_value(seq, tracked, dest, t: int, uv) -> tuple[float, float]:
    """O ponto na tela em frações da janela útil (as unidades de `pos_x`/`pos_y`)."""
    p = canvas_point(seq, tracked, t, uv)
    aw, ah = _window(seq)
    return float(p[0] / aw), float(p[1] / ah)


def own_value(seq, tracked, dest, t: int, uv) -> tuple[float, float]:
    """O contrário do caminho do ponto na tela, medido com a posição do clipe parada: somado à posição, o ponto fica."""
    v = dict(seq.values_at(tracked, t))
    base = tracked.values
    v["pos_x"], v["pos_y"] = base["pos_x"], base["pos_y"]
    p = canvas_point(seq, tracked, t, uv, v)
    aw, ah = _window(seq)
    return float(-p[0] / aw), float(-p[1] / ah)


def uv_value(seq, tracked, dest, t: int, uv) -> tuple[float, float]:
    """O próprio uv do clipe (para um alvo no espaço do clipe, como o centro da máscara da F2)."""
    return float(uv[0]), float(uv[1])


def mask_value(seq, tracked, dest, t: int, uv) -> tuple[float, float]:
    """O uv do clipe em px@1080 do clipe a partir do centro (as unidades de `mascara_x`/`mascara_y`, §50.2), na
    proporção da textura em que ele é decodificado (a mesma que a máscara usa no quadro)."""
    from . import mascaras_clipe, sequence
    tw, th = sequence.decode_size(seq, dest, seq.width, seq.height)
    p = mascaras_clipe.clip_px(uv, tw, th)
    return float(p[0]), float(p[1])


def same_clip(seq, clip) -> list:
    return [clip]


def with_mask(seq, clip) -> list:
    """O próprio clipe, se ele tem uma máscara de forma (§50.2)."""
    return [clip] if clip.values.get("mascara_forma", "nenhuma") != "nenhuma" else []


def clips_above(seq, clip) -> list:
    """Clipes de vídeo nas faixas acima do rastreado que passam junto com ele (títulos, imagens, outros vídeos)."""
    from .timeline import VIDEO
    return [c for c in seq.clips if c.kind == VIDEO and c.track > clip.track and c.id != clip.id
            and c.start < clip.end and c.end > clip.start]


# Alvos do "Aplicar a…" (ordem do menu). As chaves precisam ser animáveis. A máscara da F2 (§50.2) guarda o centro em
# px@1080 do clipe: `mask_value` converte o uv e `units="px_clipe"` dá a tolerância.
TARGETS: dict[str, Target] = {
    "proprio": Target("proprio", N_("O próprio clipe (o ponto fica parado na tela)"), ("pos_x", "pos_y"), same_clip,
                      own_value),
    "acima": Target("acima", N_("Um clipe acima (título, imagem…)"), ("pos_x", "pos_y"), clips_above, follow_value),
    "mascara": Target("mascara", N_("O centro da máscara do clipe"), ("mascara_x", "mascara_y"), with_mask,
                      mask_value, units="px_clipe"),
}


def rdp(points: np.ndarray, tolerance: float) -> list[int]:
    """Índices dos pontos que ficam (Ramer–Douglas–Peucker) de uma curva [(t, x, y)] em ordem de t: a reta entre dois
    pontos guardados (interpolação linear no tempo, como as chaves) passa a menos de `tolerance` de todo ponto tirado."""
    n = len(points)
    if n <= 2:
        return list(range(n))
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        seg = points[i + 1:j]
        s = (seg[:, 0] - points[i, 0]) / max(points[j, 0] - points[i, 0], 1e-12)
        line = points[i, 1:] + s[:, None] * (points[j, 1:] - points[i, 1:])
        d = np.hypot(*(seg[:, 1:] - line).T)
        k = int(np.argmax(d))
        if d[k] > tolerance:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return [int(i) for i in np.flatnonzero(keep)]


def _ref_frame(seq, clip, track: Track, frames: list[int]) -> int:
    """O quadro da sequência de referência: o que mostra o quadro escolhido do arquivo (ou o mais perto dele)."""
    return min(frames, key=lambda t: (abs(seq.src_frame(clip, t) - track.ref), t))


def bake(seq, tracked, track: Track, target: Target, dest) -> dict[str, list]:
    """As chaves (no tempo do clipe `dest`) que levam `target.keys` pelo rastro, simplificadas: {chave: [Key]}.
    Vazio se o rastro não cobre nenhum quadro em que os dois clipes aparecem."""
    from .params import _clean
    from . import editparams
    lo, hi = max(tracked.start, dest.start), min(tracked.end, dest.end)
    frames, vals = [], []
    for t in range(lo, hi):
        uv = track.at(seq.src_frame(tracked, t))
        if uv is None:
            continue
        frames.append(t)
        vals.append(target.value(seq, tracked, dest, t, uv))
    if not frames:
        return {}
    vals = np.array(vals, np.float64)
    t_ref = _ref_frame(seq, tracked, track, frames)
    i_ref = frames.index(t_ref)
    if target.relative:
        cur = seq.values_at(dest, t_ref)
        base = np.array([float(cur[target.keys[0]]), float(cur[target.keys[1]])])
        vals = base + (vals - vals[i_ref])
    px = 1080.0 / seq.height
    if target.units == "clipe":  # uv do destino: o tamanho dele na tela (encaixe e escala)
        from . import compositor
        bw, bh = compositor.fit_box(seq, dest, seq.width, seq.height)
        sx, sy = compositor.axis_scale(dest.values)
        scale = np.array([bw * sx * px, bh * sy * px])
    elif target.units == "px_clipe":  # px@1080 do destino: 1080 deles = a altura dele na tela
        from . import compositor
        _bw, bh = compositor.fit_box(seq, dest, seq.width, seq.height)
        sx, sy = compositor.axis_scale(dest.values)
        scale = np.array([bh * sx * px / 1080.0, bh * sy * px / 1080.0])
    else:
        aw, ah = _window(seq)
        scale = np.array([aw * px, ah * px])
    curve = np.column_stack([np.array(frames, np.float64), vals * scale])
    params = editparams.VIDEO.params
    out: dict[str, list] = {target.keys[0]: [], target.keys[1]: []}
    # o quadro de referência sempre vira chave: ali o destino fica exatamente onde o usuário o pôs
    keep = rdp(curve[:i_ref + 1], TOLERANCE_PX) + [i_ref + i for i in rdp(curve[i_ref:], TOLERANCE_PX)[1:]]
    for i in keep:
        tau = float(seq.clip_time(dest, frames[i]))
        for j, key in enumerate(target.keys):
            out[key].append(keyframes.Key(tau, _clean(params[key], vals[i, j]), keyframes.LINEAR))
    return out


def _replace_keys(clip, baked: dict[str, list]) -> None:
    """Troca as chaves de cada ajuste dentro do trecho assado (as de fora ficam)."""
    from . import editparams
    keys = dict(clip.keys)
    for key, new in baked.items():
        if not new:
            continue
        a, b = new[0].t, new[-1].t
        old = [k for k in keys.get(key, []) if k.t < a or k.t > b]
        keys[key] = sorted(old + list(new), key=lambda k: k.t)
    clip.keys = keyframes.clean_keys(editparams.VIDEO, keys)


def apply(seq, tracked_id: str, target_id: str, dest_id: str) -> int:
    """"Aplicar a…": assa o rastro do clipe `tracked_id` no alvo `target_id` do clipe `dest_id` e guarda o alvo no
    rastro (para o "Reaplicar"). Devolve quantas chaves ficaram em cada ajuste. TrackError com o motivo. Faça dentro de
    um passo do desfazer (`TimelineModel.apply_edit`)."""
    tracked = seq.find(tracked_id)
    track = track_of(tracked) if tracked is not None else None
    if track is None:
        raise TrackError(_("Este clipe não tem um ponto rastreado."))
    target = TARGETS.get(target_id)
    dest = seq.find(dest_id)
    if target is None or dest is None or dest.id not in {c.id for c in target.clips(seq, tracked)}:
        raise TrackError(_("O clipe de destino não está mais junto do clipe rastreado."))
    if seq.locked(dest):
        raise TrackError(_("A faixa do clipe de destino está travada."))
    baked = bake(seq, tracked, track, target, dest)
    if not baked or not baked[target.keys[0]]:
        raise TrackError(_("O rastro não passa pelos quadros em que o destino aparece."))
    _replace_keys(dest, baked)
    track.target = {"tipo": target.id, "clipe": dest.id}
    store(tracked, track)
    return len(baked[target.keys[0]])


def reapply(seq, tracked_id: str) -> int:
    """"Reaplicar": assa de novo no último alvo do rastro (depois de mover, aparar ou rastrear outra vez)."""
    tracked = seq.find(tracked_id)
    track = track_of(tracked) if tracked is not None else None
    if track is None or not track.target:
        raise TrackError(_("Aplique o rastro a um alvo antes de reaplicar."))
    return apply(seq, tracked_id, str(track.target.get("tipo")), str(track.target.get("clipe")))


def targets_for(seq, clip) -> list[tuple[Target, Any]]:
    """[(alvo, clipe de destino)] que o menu "Aplicar a…" oferece para o clipe rastreado."""
    out = []
    for target in TARGETS.values():
        for dest in target.clips(seq, clip):
            out.append((target, dest))
    return out


def describe(track: Track | None) -> str:
    """Uma linha para o cartão."""
    if track is None:
        return _("Nenhum ponto rastreado.")
    text = _("Ponto rastreado em {n} quadros do arquivo.").format(n=len(track.uv))
    if track.lost:
        text += " " + track.lost
    return text


__all__ = ["Track", "Target", "TARGETS", "TrackError", "track", "run", "apply", "reapply", "bake", "rdp",
           "canvas_point", "clip_uv", "tracks_of", "track_of", "store", "targets_for", "source_frames"]
