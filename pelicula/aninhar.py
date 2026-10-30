"""Aninhar seleção e desaninhar (#57, ARQUITETURA §41.7): funções puras sobre `timeline.Sequence`, sem Qt nem GPU.

**A promessa: aninhar não muda a imagem nem o som.** Os clipes escolhidos (e os ligados a eles) vão, com os mesmos ids,
para uma sequência nova do projeto, e na de fora fica um clipe só (um de vídeo e um de som, ligados) que mostra essa
sequência sem nenhum ajuste. Onde a promessa não se sustenta, a operação recusa (`Refusal`, com o motivo e o que fazer) ou
avisa (`NestResult.warnings`); nunca muda em silêncio.

`nest` primeiro confere tudo (`_plan_nest`, sem mexer em nada) e só então mexe, então uma recusa deixa o projeto como
estava. `unnest` é o inverso: devolve os clipes de dentro, cortados no trecho que o clipe de fora mostrava, para a
sequência de fora. Aninhar e desaninhar sem mexer em nada dá o mesmo quadro e o mesmo som de antes dos dois.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from . import audiomix, editparams, luz_plano, timeline
from .i18n import _
from .timeline import AUDIO, VIDEO, Clip, Sequence, Track

VOLUME_RANGE = (-60.0, 12.0)   # dB de uma faixa de som (`Track.from_json` limita nisto)
TWO_CLIP_IN = ("dissolver",) + editparams.EXTRA_TWO_CLIP  # entradas que mostram a cauda do clipe anterior da faixa
NONLINEAR = ("voz", "reducao_ruido", "normalizar")        # ajustes de som em que a ordem do ganho muda o som


class Refusal(Exception):
    """A operação não dá: `text` é a frase curta (PT-BR) que diz o motivo e o que fazer; nada foi mudado."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


@dataclass
class NestResult:
    inner: Sequence                                       # a sequência nova
    clips: list[Clip]                                     # os clipes de fora (vídeo e som, ligados)
    warnings: list[str] = field(default_factory=list)     # o que não se sustenta a ponto de recusar


@dataclass
class UnnestResult:
    inner: Sequence
    clips: list[Clip]                                     # os clipes que voltaram para a sequência de fora


@dataclass
class _Plan:
    sel: list[Clip]
    a: int
    b: int
    vtracks: list[int]            # faixas de vídeo de fora usadas pela seleção (em ordem)
    atracks: list[int]
    v_land: int | None            # onde o clipe de vídeo de fora cai
    a_land: int | None            # faixa de som onde o clipe de som cai (None = nenhuma; NEW = uma faixa nova)
    a_delta: float                # dB da faixa onde o som cai (a de dentro desconta isto)
    transparent: bool
    below: bool
    warnings: list[str]


NEW = -1   # `_Plan.a_land`: o clipe de som cai numa faixa nova, no fim das faixas de som


def default_name(kind: str, idx: int) -> str:
    return ("V" if kind == VIDEO else "A") + str(idx + 1)


def _is_default(name: str, kind: str) -> bool:
    return not name or re.fullmatch(("V" if kind == VIDEO else "A") + r"\d+", name) is not None


def _label(seq: Sequence, kind: str, idx: int) -> str:
    tr = seq.track(kind, idx)
    return (tr.name if tr is not None and tr.name else default_name(kind, idx))


def _hidden(seq: Sequence, kind: str, idx: int) -> bool:
    tr = seq.track(kind, idx)
    return bool(tr is not None and tr.muted)


def _overlaps(c: Clip, a: int, b: int) -> bool:
    return c.end > a and c.start < b


def _in_range(db: float) -> bool:
    return VOLUME_RANGE[0] - 1e-9 <= db <= VOLUME_RANGE[1] + 1e-9


def _clamp_db(db: float) -> float:
    return min(max(db, VOLUME_RANGE[0]), VOLUME_RANGE[1])


def _has_tone(seq: Sequence, clips: list[Clip]) -> bool:
    """Algum clipe de vídeo visível desses toca um tom (o bipe da ponta)? O tom não passa pela faixa de som."""
    if not audiomix.TONES:
        return False
    for c in clips:
        src = seq.sources.get(c.src)
        if c.kind == VIDEO and src is not None and not src.is_file and src.kind in audiomix.TONES \
                and not _hidden(seq, VIDEO, c.track):
            return True
    return False


# ------------------------------------------------------------------ aninhar
def _plan_nest(seq: Sequence, ids, look: dict | None) -> _Plan:
    sel = seq.expand(ids)
    if not sel:
        raise Refusal(_("Selecione os clipes que quer aninhar."))
    if any(seq.locked(c) for c in sel):
        raise Refusal(_("Há clipes numa faixa travada. Destrave a faixa para aninhar."))
    sel_ids = {c.id for c in sel}
    a, b = min(c.start for c in sel), max(c.end for c in sel)
    others = [c for c in seq.clips if c.id not in sel_ids and _overlaps(c, a, b)]
    used = {(c.kind, c.track) for c in sel}
    for o in others:
        if (o.kind, o.track) in used:
            raise Refusal(_("Um clipe que não está na seleção fica no meio dela, na faixa {faixa}. Inclua-o na "
                            "seleção ou aninhe só um trecho sem ele.").format(faixa=_label(seq, o.kind, o.track)))
    vis = [c.track for c in sel if c.kind == VIDEO and not _hidden(seq, VIDEO, c.track)]
    low, high = (min(vis), max(vis)) if vis else (0, 0)
    for o in others:
        if o.kind == VIDEO and low < o.track < high and not _hidden(seq, VIDEO, o.track):
            raise Refusal(_("Um clipe da faixa {faixa} fica entre os da seleção. Incluí-lo na seleção mantém a ordem "
                            "das camadas.").format(faixa=_label(seq, VIDEO, o.track)))
    for c in seq.clips:  # a transição que usa o vizinho: o clipe de dentro não tem sobra além das pontas
        if c.kind != VIDEO or c.values.get("entrada_tipo") not in TWO_CLIP_IN:
            continue
        prev = seq.previous_on_track(c)
        if prev is not None and (c.id in sel_ids) != (prev.id in sel_ids):
            raise Refusal(_("Uma transição liga um clipe da seleção a um que não está nela. Inclua o vizinho ou tire a "
                            "transição."))
    heads, _tails = audiomix.crossfades(seq)
    for c in seq.clips:
        prev = seq.previous_on_track(c) if c.id in heads else None
        if prev is not None and (c.id in sel_ids) != (prev.id in sel_ids):
            raise Refusal(_("Uma transição de som liga um clipe da seleção a um que não está nela. Inclua o vizinho ou "
                            "tire a transição."))
    group = seq.siblings
    above = group._levels_above(seq) if group is not None else 0
    kids = [k for k in (seq.nested(c) for c in sel) if k is not None]
    below_levels = 1 + max((group._levels_below(k) for k in kids), default=0)
    if above + 1 + below_levels > timeline.MAX_NEST:
        raise Refusal(_("Sequência dentro de sequência passa de {n} níveis. Aninhe menos coisas ou use o conteúdo de "
                        "uma sequência interna direto.").format(n=timeline.MAX_NEST))

    vtracks = sorted({c.track for c in sel if c.kind == VIDEO})
    atracks = sorted({c.track for c in sel if c.kind == AUDIO})
    v_vis = [t for t in vtracks if not _hidden(seq, VIDEO, t)]
    v_land = min(v_vis) if v_vis else (min(vtracks) if vtracks else None)
    below = any(o.kind == VIDEO and v_land is not None and o.track < v_land and not _hidden(seq, VIDEO, o.track)
                for o in others)
    a_land, delta, warn = _plan_audio(seq, sel, atracks)
    transparent = bool(seq.transparent or below)
    warnings = list(warn)
    blend = any(c.kind == VIDEO and c.values.get("mesclagem", "normal") != "normal" for c in sel)
    if blend and transparent:
        warnings.append(_("A mesclagem de um clipe agora vale dentro da sequência, e não sobre o que ficou embaixo "
                          "dela."))
    if look and (look.get("mfilme_on") or (look.get("lab_on") and any(
            c.kind == VIDEO and luz_plano.has_lights(c.values) for c in sel))):
        warnings.append(_("O look que lê os cortes da montagem agora vê a seleção como um plano só."))
    return _Plan(sel, a, b, vtracks, atracks, v_land, a_land, delta, transparent, below, warnings)


def _plan_audio(seq: Sequence, sel: list[Clip], atracks: list[int]) -> tuple[int | None, float, list[str]]:
    """Onde o som cai e o quanto da faixa de lá a faixa de dentro desconta: `volume da faixa de dentro = o de antes - o
    da faixa de fora`, para o ganho valer uma vez só. Devolve (faixa, dB, avisos)."""
    tracks = seq.kind_tracks(AUDIO)
    solo = any(t.solo for t in tracks)

    def audible(i: int) -> bool:
        return not tracks[i].muted and (not solo or tracks[i].solo)

    cands = [i for i in atracks if audible(i)]
    tone = _has_tone(seq, sel)
    if not cands and not tone:
        return None, 0.0, []
    for i in cands:
        t = tracks[i].volume
        if tone and abs(t) > 1e-9:
            continue  # o tom não passa pela faixa de dentro: só uma faixa a 0 dB deixa o volume dele como estava
        if all(_in_range(tracks[j].volume - t) for j in cands):
            warn = []
            if abs(t) > 1e-9 and any(c.kind == AUDIO and any(c.values.get(k) for k in NONLINEAR) for c in sel):
                warn.append(_("O volume da faixa de som agora vem depois dos efeitos de voz, ruído ou normalização do "
                              "clipe: o som pode mudar um pouco."))
            return i, t, warn
    if tone:
        return NEW, 0.0, []
    raise Refusal(_("Os volumes das faixas de som são tão diferentes que o de dentro sairia do limite (-60 a +12 dB). "
                    "Aproxime os volumes das faixas antes de aninhar."))


def nest(seq: Sequence, ids, name: str = "", look: dict | None = None) -> NestResult:
    """Aninha os clipes `ids` (mais os ligados a eles) numa sequência nova do projeto. `look`: os ajustes do look, só para
    avisar que ele lê os cortes. Levanta `Refusal` sem ter mudado nada."""
    p = _plan_nest(seq, ids, look)
    group = seq.ensure_set()
    sel_ids = {c.id for c in p.sel}
    if seq.window:
        _x, _y, w, h = seq.window_rect(seq.width, seq.height)
    else:
        w, h = seq.width, seq.height
    inner = group.create(w, h, seq.fps_str, name.strip())
    inner.background = tuple(seq.background)
    inner.micro_fade = seq.micro_fade
    inner.transparent = p.transparent

    # Faixas: só as usadas, na mesma ordem relativa e com as mesmas propriedades. O som de dentro desconta o volume da
    # faixa onde o clipe de fora cai, e silencia o que o solo já silenciava.
    solo = any(t.solo for t in seq.kind_tracks(AUDIO))
    vmap = {t: i for i, t in enumerate(p.vtracks)}
    amap = {t: i for i, t in enumerate(p.atracks)}
    tracks: list[Track] = []
    for old in p.vtracks:
        t = seq.track(VIDEO, old)
        tracks.append(Track(VIDEO, t.name if not _is_default(t.name, VIDEO) else default_name(VIDEO, vmap[old]),
                            muted=t.muted, solo=t.solo, volume=t.volume))
    if not p.vtracks:
        tracks.append(Track(VIDEO, default_name(VIDEO, 0)))
    for old in p.atracks:
        t = seq.track(AUDIO, old)
        tracks.append(Track(AUDIO, t.name if not _is_default(t.name, AUDIO) else default_name(AUDIO, amap[old]),
                            muted=bool(t.muted or (solo and not t.solo)), solo=t.solo,
                            volume=_clamp_db(t.volume - p.a_delta)))
    if not p.atracks:
        tracks.append(Track(AUDIO, default_name(AUDIO, 0)))
    inner.tracks = tracks

    # Os clipes andam (não são copiados): os mesmos ids, `src_in`, chaves, valores e ligações; só o tempo e a faixa mudam.
    seq.clips = [c for c in seq.clips if c.id not in sel_ids]
    for c in p.sel:
        c.start -= p.a
        c.track = (vmap if c.kind == VIDEO else amap)[c.track]
        inner.clips.append(c)
    v1 = sorted((c for c in inner.clips if c.kind == VIDEO and c.track == 0), key=lambda c: c.start)
    gap_free = not v1 or (v1[0].start == 0 and all(x.end == y.start for x, y in zip(v1, v1[1:])))
    inner.magnetic = bool(seq.magnetic and gap_free)

    # Os clipes de fora: a sequência inteira, sem ajuste nenhum (encaixe "ajustar", escala 1: a tela toda ou a janela).
    group.sync()
    key = f"{timeline.SOURCE_SEQUENCE}:{inner.id}"
    src = seq.sources[key]
    made: list[Clip] = []
    dur = p.b - p.a
    if src.has_video and p.v_land is not None and any(c.kind == VIDEO for c in inner.clips):
        made.append(Clip(timeline.new_id(), VIDEO, key, p.v_land, p.a, dur))
    if src.has_audio and p.a_land is not None:
        land = seq.add_track(AUDIO) if p.a_land == NEW else p.a_land
        made.append(Clip(timeline.new_id(), AUDIO, key, land, p.a, dur))
    if len(made) == 2:  # vídeo e som ligados, como um arquivo com os dois
        made[0].link = made[1].link = timeline.new_id()
    seq.clips.extend(made)
    return NestResult(inner, made, p.warnings)


# ------------------------------------------------------------------ desaninhar
def _speed_text() -> str:
    return _("Este clipe de sequência tem velocidade, rampa, reverso ou quadro congelado, que não dá para levar ao "
             "desaninhar. Volte a velocidade para 1× antes.")


def _members(seq: Sequence, cid: str) -> tuple[Clip, Sequence, list[Clip]]:
    n = seq.find(cid)
    inner = seq.nested(n) if n is not None else None
    if n is None or inner is None:
        raise Refusal(_("Este clipe não é uma sequência."))
    return n, inner, [g for g in seq.group(n) if g.src == n.src]


def _check_unnest(seq: Sequence, cid: str) -> tuple[Sequence, list[Clip]]:
    n, inner, members = _members(seq, cid)
    if any(seq.locked(m) for m in members):
        raise Refusal(_("O clipe está numa faixa travada. Destrave a faixa para desaninhar."))
    if any(m.retimed or abs(m.speed - 1.0) > 1e-9 or m.frozen for m in members):
        raise Refusal(_speed_text())
    if abs(inner.fps - seq.fps) > 1e-6:
        raise Refusal(_("A sequência de dentro tem outro número de quadros por segundo ({a} e {b}): desaninhar mudaria "
                        "o tempo dos clipes.").format(a=f"{inner.fps:g}", b=f"{seq.fps:g}"))
    return inner, members


def _describe(kind: str, values: dict, keys: dict) -> list[str]:
    """O que há de não padrão num clipe de sequência (o que o desaninhar perderia), em poucas palavras."""
    schema = editparams.SCHEMAS[kind]
    base = schema.defaults()
    changed = {k for k, v in schema.sanitize(values).items() if v != base[k]}
    out: list[str] = []
    if kind == VIDEO:
        if "opacidade" in changed:
            out.append(_("opacidade"))
        if "mesclagem" in changed:
            out.append(_("mesclagem"))
        if any(k.startswith(("entrada_", "saida_")) for k in changed):
            out.append(_("transições"))
        geom = {"escala", "escala_x", "escala_y", "pos_x", "pos_y", "rotacao", "espelhar_h", "espelhar_v", "encaixe",
                "desespremer", "desespremer_taxa", "corte_esq", "corte_dir", "corte_topo", "corte_base"}
        if changed & geom:
            out.append(_("enquadramento"))
        rest = changed - geom - {"opacidade", "mesclagem", "velocidade", "congelar"}
        if any(not k.startswith(("entrada_", "saida_")) for k in rest):
            out.append(_("cor e detalhe"))
    else:
        if "volume" in changed:
            out.append(_("volume"))
        if "mudo" in changed:
            out.append(_("mudo"))
        if changed & {"fade_in", "fade_out", "transicao"}:
            out.append(_("fades e transição de som"))
        if changed - {"volume", "mudo", "fade_in", "fade_out", "transicao", "velocidade"}:
            out.append(_("equalização e limpeza do som"))
    if keys:
        out.append(_("animação (chaves)"))
    return out


def unnest_loss(seq: Sequence, cid: str) -> list[str]:
    """O que se perderia ao desaninhar o clipe (vazio = nada; a interface pergunta antes quando não é). Levanta `Refusal`
    quando não dá (velocidade, rampa, reverso, faixa travada, outro fps)."""
    inner, members = _check_unnest(seq, cid)
    lost: list[str] = []
    for m in members:
        for w in _describe(m.kind, m.values, m.keys):
            if w not in lost:
                lost.append(w)
    if inner.window or tuple(inner.background) != tuple(seq.background) \
            or inner.width * seq.height != inner.height * seq.width:
        lost.append(_("o fundo, a janela ou a proporção da sequência"))
    return lost


def _trim(inner: Sequence, clip: Clip, u0: int, u1: int) -> Clip:
    """Uma cópia do clipe de dentro cortada em [u0, u1) (quadros de dentro), com a conta de dividir (`Sequence._cut`): a ponta
    cortada ganha o `src_in` do ponto, as chaves ficam onde estavam em relação à imagem e a transição daquela ponta sai
    (a de entrada fica só na parte da esquerda; a de saída, só na da direita)."""
    part = copy.deepcopy(clip)
    if part.start < u0:
        cut = u0 - part.start
        part.src_in = inner.src_time(clip, u0)
        part.start, part.dur = u0, part.dur - cut
        part.shift_head(cut)
        if part.kind == VIDEO:
            part.values["entrada_tipo"] = "corte"
        else:
            part.values["fade_in"] = 0.0
            part.values["transicao"] = 0.0
    if part.end > u1:
        part.dur = u1 - part.start
        if part.kind == VIDEO:
            part.values["saida_tipo"] = "corte"
        else:
            part.values["fade_out"] = 0.0
    return part


def _insert_track(seq: Sequence, kind: str, pos: int, track: Track) -> int:
    """Põe a faixa na posição `pos` das faixas do tipo (as de cima, e os clipes delas, sobem uma). Devolve `pos`."""
    ts = seq.kind_tracks(kind)
    pos = min(max(pos, 0), len(ts))
    for c in seq.clips:
        if c.kind == kind and c.track >= pos:
            c.track += 1
    if pos < len(ts):
        seq.tracks.insert(seq.tracks.index(ts[pos]), track)
    else:
        seq.tracks.insert(seq.tracks.index(ts[-1]) + 1 if ts else len(seq.tracks), track)
    for i, t in enumerate(seq.kind_tracks(kind)):  # os nomes de fábrica acompanham a posição; os que a pessoa deu ficam
        if _is_default(t.name, kind):
            t.name = default_name(kind, i)
    return pos


def _free(seq: Sequence, kind: str, idx: int, a: int, b: int, ignore: set[str]) -> bool:
    return all(c.id in ignore or not _overlaps(c, a, b) for c in seq.clips if c.kind == kind and c.track == idx)


def unnest(seq: Sequence, cid: str) -> UnnestResult:
    """Devolve à sequência os clipes de dentro do clipe de sequência `cid` (e do ligado a ele): cortados no trecho que ele
    mostrava, no tempo de fora, com os ids de dentro (novos só se já existem aqui). A sequência de dentro fica no projeto.
    Quem chama já perguntou sobre o que `unnest_loss` diz."""
    inner, members = _check_unnest(seq, cid)
    ignore = {m.id for m in members}
    fps = inner.fps
    ranges = {m.id: (int(round(m.src_in * fps)), int(round(m.src_in * fps)) + m.dur) for m in members}
    outer_audio = seq.kind_tracks(AUDIO)
    solo = any(t.solo for t in outer_audio)
    pieces: list[tuple[Clip, Clip]] = []   # (membro, parte)
    for m in members:
        u0, u1 = ranges[m.id]
        for c in inner.clips:
            if c.kind == m.kind and _overlaps(c, u0, u1):
                part = _trim(inner, c, u0, u1)
                part.start += m.start - u0
                pieces.append((m, part))
    for m in members:  # o limite do volume se confere antes de mexer em qualquer coisa
        land = seq.track(AUDIO, m.track) if m.kind == AUDIO else None
        for old in {c.track for mm, c in pieces if mm is m and m.kind == AUDIO}:
            if not _in_range(inner.kind_tracks(AUDIO)[old].volume + (land.volume if land is not None else 0.0)):
                raise Refusal(_("O volume das faixas de som passaria do limite (-60 a +12 dB). Aproxime o volume da "
                                "faixa onde o clipe está do das faixas de dentro."))
    # As faixas de dentro que têm parte, com o que elas valem na sequência de fora.
    inner_tracks = {k: inner.kind_tracks(k) for k in (VIDEO, AUDIO)}
    placed: dict[tuple[str, int, int], int] = {}   # (tipo, membro, faixa de dentro) → faixa de fora
    for m in members:
        a, b = m.start, m.end
        used = sorted({c.track for mm, c in pieces if mm is m})
        if not used:
            continue
        if m.kind == VIDEO:
            land_hidden = _hidden(seq, VIDEO, m.track)
            pos = m.track
            for old in used:
                it = inner_tracks[VIDEO][old]
                muted = bool(it.muted or land_hidden)
                tr = seq.track(VIDEO, pos)
                if tr is None or tr.locked or tr.muted != muted or not _free(seq, VIDEO, pos, a, b, ignore):
                    _insert_track(seq, VIDEO, pos, Track(VIDEO, it.name if not _is_default(it.name, VIDEO) else "",
                                                          muted=muted))
                placed[(VIDEO, id(m), old)] = pos
                pos += 1
        else:
            land = seq.track(AUDIO, m.track)
            delta = land.volume if land is not None else 0.0
            land_ok = land is not None and not land.muted and (not solo or land.solo)
            in_solo = any(t.solo for t in inner_tracks[AUDIO])
            for old in used:
                it = inner_tracks[AUDIO][old]
                audible = land_ok and not it.muted and (not in_solo or it.solo)
                vol = it.volume + delta
                want = (not audible, bool(solo and audible), _clamp_db(vol))
                idx = next((i for i in range(m.track, len(seq.kind_tracks(AUDIO)))
                            if _same_audio(seq.track(AUDIO, i), want) and _free(seq, AUDIO, i, a, b, ignore)), None)
                if idx is None:
                    idx = seq.add_track(AUDIO)
                    t = seq.track(AUDIO, idx)
                    t.muted, t.solo, t.volume = want
                    if not _is_default(it.name, AUDIO):
                        t.name = it.name
                placed[(AUDIO, id(m), old)] = idx
    taken = {c.id for c in seq.clips if c.id not in ignore}
    out: list[Clip] = []
    for m, c in pieces:
        c.track = placed[(m.kind, id(m), c.track)]
        if c.id in taken:
            c.id = timeline.new_id()
        taken.add(c.id)
        out.append(c)
    links: dict[str, int] = {}
    for c in out:
        if c.link:
            links[c.link] = links.get(c.link, 0) + 1
    other_links = {c.link for c in seq.clips if c.link and c.id not in ignore}
    remap: dict[str, str] = {}
    for c in out:
        if c.link and links[c.link] < 2:
            c.link = ""
        elif c.link in other_links:
            c.link = remap.setdefault(c.link, timeline.new_id())
    seq.clips = [c for c in seq.clips if c.id not in ignore] + out
    return UnnestResult(inner, out)


def _same_audio(track: Track | None, want: tuple[bool, bool, float]) -> bool:
    return (track is not None and not track.locked and track.muted == want[0] and track.solo == want[1]
            and abs(track.volume - want[2]) < 1e-9)
