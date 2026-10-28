"""Edição das legendas como elas aparecem na montagem (sem Qt): o que o painel e a faixa "Legendas" usam.

As legendas do projeto (`subtitles.Subtitles`) ficam presas aos arquivos (segundos do arquivo) ou à sequência
(segundos da sequência). Na tela, tudo aparece no tempo da sequência (`Subtitles.timeline_cues`). Cada
legenda que aparece é um `Item`: a legenda na tela, de onde ela veio (`Ref`: o arquivo e a posição na lista,
ou a lista da sequência) e, para as presas a um arquivo, como o clipe mostra o arquivo (`subtitles.Mapping`).

Toda função que muda algo recebe o `Subtitles` e mexe nele (a interface chama dentro de
`TimelineModel.edit_subtitles`, um passo de desfazer). Tempos dados em segundos da sequência voltam para o
arquivo pelo `Mapping` do item, então a legenda continua presa ao arquivo e acompanha os cortes; texto e
estilo mudam a legenda inteira do arquivo (todas as vezes em que ela aparece). As listas ficam sempre em
ordem (`subtitles.sort_cues`); quem precisa achar uma legenda depois de mudar usa a própria `Cue` devolvida
(`find`).

Regras de palavras (destaque palavra por palavra): mudar o texto mantém o tempo das palavras quando o número
de palavras é o mesmo (só a grafia muda) e tira as palavras quando não é; aparar as pontas não mexe no tempo
delas (só o que fica fora do novo trecho é encostado na ponta); mover leva tudo junto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from . import subtitles as sb
from .subtitles import Cue, Word

MIN_DUR = 0.1        # s: menor legenda que dá para fazer arrastando
NEW_DUR = 2.0        # s: duração de uma legenda nova


@dataclass(frozen=True)
class Ref:
    """De onde vem uma legenda: a lista do arquivo `path` (None = a lista da sequência) e a posição nela."""
    path: str | None
    index: int


@dataclass(frozen=True)
class Item:
    ref: Ref
    cue: Cue                               # como aparece, em segundos da sequência
    mapping: sb.Mapping | None = None      # None = legenda da sequência (tempo fixo)

    @property
    def fixed(self) -> bool:
        """Legenda da sequência: o tempo não acompanha os cortes."""
        return self.ref.path is None


def _lists(subs: sb.Subtitles, path: str | None) -> list[Cue]:
    if path is None:
        return subs.cues
    return subs.sources.setdefault(path, [])


def items(seq, subs: sb.Subtitles | None) -> list[Item]:
    """Todas as legendas como aparecem na montagem, em ordem (as mesmas de `Subtitles.timeline_cues(seq)`)."""
    if subs is None:
        return []
    out = [Item(Ref(None, i), c) for i, c in enumerate(subs.cues)]
    for path, cues in subs.sources.items():
        if not cues:
            continue
        seen: set[tuple] = set()
        for i, m, cue in sb.mapped(seq, path, cues):
            key = sb.cue_key(cue)
            if key in seen:
                continue
            seen.add(key)
            out.append(Item(Ref(path, i), cue, m))
    out.sort(key=lambda it: (it.cue.start, it.cue.end, it.cue.text))
    return out


def mapping_for(seq, clip) -> sb.Mapping:
    """Como o clipe mostra o arquivo dele (o mesmo `Mapping` de `subtitles.mapped`)."""
    return sb.Mapping(clip.id, seq.src_time(clip, clip.start), clip.start / seq.fps, clip.speed)


def anchor_at(seq, frame: int) -> tuple[str | None, sb.Mapping | None]:
    """O arquivo em que uma legenda nova no quadro `frame` fica presa: o som de um arquivo que toca ali (ou, de
    um arquivo sem som na sequência, a imagem de cima), pelo clipe que mostra aquele trecho. (None, None) =
    nada de arquivo ali (vão, imagem parada, gerador): a legenda fica no tempo da sequência."""
    from .timeline import AUDIO, VIDEO
    cands = [c for c in seq.clips_at(frame, AUDIO)] + list(reversed(seq.clips_at(frame, VIDEO)))
    for c in cands:
        src = seq.sources.get(c.src)
        if src is None or not src.is_file or src.is_image or c.frozen:
            continue
        if any(x.id == c.id for x in sb.clips_for(seq, c.src)):
            return c.src, mapping_for(seq, c)
    return None, None


def source(subs: sb.Subtitles, ref: Ref) -> Cue | None:
    """A legenda guardada (no tempo do arquivo ou da sequência)."""
    lst = subs.cues if ref.path is None else subs.sources.get(ref.path, [])
    return lst[ref.index] if 0 <= ref.index < len(lst) else None


def find(subs: sb.Subtitles, cue: Cue, path: str | None) -> Ref | None:
    """A posição da legenda guardada `cue` (a mesma, ou uma igual) depois de uma mudança."""
    lst = subs.cues if path is None else subs.sources.get(path, [])
    for i, c in enumerate(lst):
        if c is cue:
            return Ref(path, i)
    for i, c in enumerate(lst):
        if c == cue:
            return Ref(path, i)
    return None


def item_for(items_: Iterable[Item], ref: Ref | None) -> Item | None:
    if ref is None:
        return None
    return next((it for it in items_ if it.ref == ref), None)


def _put(subs: sb.Subtitles, ref: Ref, cue: Cue | None) -> None:
    """Troca (ou tira, com None) a legenda guardada e põe a lista em ordem."""
    lst = _lists(subs, ref.path)
    if cue is None:
        del lst[ref.index]
    else:
        lst[ref.index] = cue
    lst[:] = sb.sort_cues(lst)
    if ref.path is not None and not lst:
        subs.sources.pop(ref.path, None)


def _clamp_words(words: tuple[Word, ...], a: float, b: float) -> tuple[Word, ...]:
    return tuple(Word(min(max(w.start, a), b), min(max(w.end, a), b), w.text) for w in words)


def with_text(cue: Cue, text: str) -> Cue:
    """A legenda com outro texto: as palavras ficam (com a grafia nova) se o número de palavras é o mesmo."""
    text = sb.clean_text(text)
    toks = sb.tokens(text)
    words = cue.words
    if words:
        words = tuple(Word(w.start, w.end, t) for w, t in zip(words, toks)) if len(toks) == len(words) else ()
    return replace(cue, text=text, words=words)


# ------------------------------------------------------------------ mudanças
def set_text(subs: sb.Subtitles, ref: Ref, text: str) -> Cue | None:
    """Novo texto (a legenda inteira do arquivo). Texto vazio apaga a legenda. Devolve a legenda guardada."""
    cue = source(subs, ref)
    if cue is None:
        return None
    if not sb.clean_text(text):
        _put(subs, ref, None)
        return None
    new = with_text(cue, text)
    _put(subs, ref, new)
    return new


def set_style(subs: sb.Subtitles, ref: Ref, italic: bool | None = None, bold: bool | None = None) -> Cue | None:
    cue = source(subs, ref)
    if cue is None:
        return None
    new = replace(cue, italic=cue.italic if italic is None else bool(italic),
                  bold=cue.bold if bold is None else bool(bold))
    _put(subs, ref, new)
    return new


def _to_store(item: Item, t: float) -> float:
    return item.mapping.to_file(t) if item.mapping is not None else t


def set_times(subs: sb.Subtitles, item: Item, start: float | None = None, end: float | None = None) -> Cue | None:
    """Novo início e/ou fim (segundos da sequência). Só a ponta que mudou anda na legenda guardada (uma legenda
    cortada por um clipe continua com o pedaço que não aparece)."""
    cue = source(subs, item.ref)
    if cue is None:
        return None
    s, e = cue.start, cue.end
    head = start is not None and abs(start - item.cue.start) > 1e-9
    if head:
        s = max(0.0, _to_store(item, max(0.0, start)))
    if end is not None and abs(end - item.cue.end) > 1e-9:
        e = _to_store(item, max(0.0, end))
    shortest = MIN_DUR * (item.mapping.speed if item.mapping is not None else 1.0)  # no tempo guardado
    if e - s < shortest - 1e-9:
        if head:
            s = max(0.0, e - shortest)
        e = max(e, s + shortest)
    new = replace(cue, start=s, end=e, words=_clamp_words(cue.words, s, e))
    _put(subs, item.ref, new)
    return new


def move(subs: sb.Subtitles, item: Item, dt: float) -> Cue | None:
    """Leva a legenda (e as palavras) `dt` segundos da sequência para a frente (negativo: para trás)."""
    cue = source(subs, item.ref)
    if cue is None:
        return None
    d = dt * (item.mapping.speed if item.mapping is not None else 1.0)
    d = max(d, -cue.start)
    new = cue.shifted(d)
    _put(subs, item.ref, new)
    return new


def add(subs: sb.Subtitles, start: float, end: float, text: str, mapping: sb.Mapping | None = None,
        path: str | None = None) -> Cue | None:
    """Legenda nova de `start` a `end` (segundos da sequência). Com `path` e o `mapping` do clipe que mostra o
    arquivo, ela fica presa ao arquivo; sem, fica no tempo da sequência."""
    text = sb.clean_text(text)
    if not text or end <= start:
        return None
    if path is not None and mapping is not None:
        s, e = mapping.to_file(start), mapping.to_file(end)
    else:
        path, s, e = None, start, end
    cue = Cue(max(0.0, s), max(0.0, e), text)
    lst = _lists(subs, path)
    lst.append(cue)
    lst[:] = sb.sort_cues(lst)
    return cue


def delete(subs: sb.Subtitles, refs: Iterable[Ref]) -> int:
    """Apaga as legendas guardadas (todas as vezes em que aparecem). Devolve quantas."""
    by_list: dict[str | None, set[int]] = {}
    for r in refs:
        by_list.setdefault(r.path, set()).add(r.index)
    n = 0
    for path, idx in by_list.items():
        lst = subs.cues if path is None else subs.sources.get(path)
        if not lst:
            continue
        keep = [c for i, c in enumerate(lst) if i not in idx]
        n += len(lst) - len(keep)
        lst[:] = keep
        if path is not None and not lst:
            subs.sources.pop(path, None)
    return n


def _split_text(text: str, frac: float) -> tuple[str, str]:
    toks = text.split()
    if len(toks) < 2:
        return text, text
    k = min(len(toks) - 1, max(1, round(len(toks) * frac)))
    return " ".join(toks[:k]), " ".join(toks[k:])


def split(subs: sb.Subtitles, item: Item, t: float) -> tuple[Cue, Cue] | None:
    """Divide a legenda no instante `t` (segundos da sequência). Com palavras, cada parte fica com as dela."""
    cue = source(subs, item.ref)
    if cue is None or not (item.cue.start + 1e-6 < t < item.cue.end - 1e-6):
        return None
    x = _to_store(item, t)
    if not cue.start < x < cue.end:
        return None
    if cue.words:
        left_w = tuple(w for w in cue.words if (w.start + w.end) / 2 < x)
        right_w = tuple(w for w in cue.words if (w.start + w.end) / 2 >= x)
        if not left_w or not right_w:
            lt, rt = _split_text(cue.text, (x - cue.start) / cue.duration)
            left_w = right_w = ()
        else:
            lt = sb.balance_lines(" ".join(w.text for w in left_w))
            rt = sb.balance_lines(" ".join(w.text for w in right_w))
    else:
        lt, rt = _split_text(cue.text, (x - cue.start) / cue.duration)
        left_w = right_w = ()
    left = replace(cue, end=x, text=lt, words=_clamp_words(left_w, cue.start, x))
    right = replace(cue, start=x, text=rt, words=_clamp_words(right_w, x, cue.end))
    lst = _lists(subs, item.ref.path)
    lst[item.ref.index] = left
    lst.append(right)
    lst[:] = sb.sort_cues(lst)
    return left, right


def merge(subs: sb.Subtitles, refs: Iterable[Ref]) -> Cue | None:
    """Junta legendas da mesma lista (o mesmo arquivo ou a sequência) numa só. None se são de listas diferentes."""
    refs = sorted(set(refs), key=lambda r: r.index)
    if len(refs) < 2 or len({r.path for r in refs}) != 1:
        return None
    path = refs[0].path
    cues = [c for c in (source(subs, r) for r in refs) if c is not None]
    if len(cues) < 2:
        return None
    cues = sb.sort_cues(cues)
    words = tuple(w for c in cues for w in c.words) if all(c.words for c in cues) else ()
    text = " ".join(" ".join(c.text.split()) for c in cues)
    new = Cue(min(c.start for c in cues), max(c.end for c in cues), sb.balance_lines(text), words,
              all(c.italic for c in cues), all(c.bold for c in cues))
    delete(subs, refs)
    lst = _lists(subs, path)
    lst.append(new)
    lst[:] = sb.sort_cues(lst)
    return new


def neighbor(items_: list[Item], item: Item, step: int = 1) -> Item | None:
    """A legenda seguinte (ou a anterior) na tela."""
    try:
        i = next(k for k, it in enumerate(items_) if it.ref == item.ref and it.cue == item.cue)
    except StopIteration:
        return None
    j = i + step
    return items_[j] if 0 <= j < len(items_) else None


# ------------------------------------------------------------------ buscar e substituir
def _pattern(query: str, case: bool) -> re.Pattern | None:
    if not query:
        return None
    return re.compile(re.escape(query), 0 if case else re.IGNORECASE)


def matches(items_: Iterable[Item], query: str, case: bool = False) -> list[Item]:
    pat = _pattern(query, case)
    if pat is None:
        return list(items_)
    return [it for it in items_ if pat.search(it.cue.text)]


def replace_all(subs: sb.Subtitles, query: str, repl: str, case: bool = False) -> int:
    """Troca o texto em todas as legendas guardadas. Devolve quantas trocas."""
    pat = _pattern(query, case)
    if pat is None:
        return 0
    total = 0
    for path in [None, *list(subs.sources)]:
        lst = _lists(subs, path)
        out = []
        for c in lst:
            text, n = pat.subn(lambda _m: repl, c.text)
            total += n
            if n:
                text = sb.clean_text(text)
                if not text:
                    continue
                c = with_text(c, text)
            out.append(c)
        lst[:] = sb.sort_cues(out)
        if path is not None and not lst:
            subs.sources.pop(path, None)
    return total


# ------------------------------------------------------------------ importar e trechos removidos
def import_cues(subs: sb.Subtitles, cues: Iterable[Cue], path: str | None = None, replace_all_: bool = False) -> int:
    """Põe legendas lidas de um .srt/.vtt: presas ao arquivo `path` (os tempos do .srt são do arquivo) ou, sem,
    no tempo da sequência. `replace_all_` troca as que já havia nessa lista."""
    cues = list(cues)
    lst = _lists(subs, path)
    if replace_all_:
        lst.clear()
    lst.extend(cues)
    lst[:] = sb.sort_cues(lst)
    if path is not None and not lst:
        subs.sources.pop(path, None)
    return len(cues)


def remove_time(subs: sb.Subtitles, a: float, b: float) -> None:
    """O trecho [a, b) segundos da sequência saiu da montagem e o resto encostou: as legendas da sequência
    acompanham (as de dentro somem, as que cruzam são cortadas, as de depois andam). As presas aos arquivos
    não precisam: acompanham os clipes sozinhas."""
    if b <= a:
        return
    n = b - a
    out = []
    for c in subs.cues:
        if c.end <= a + 1e-9:
            out.append(c)
            continue
        if c.start >= b - 1e-9:
            out.append(c.shifted(-n))
            continue
        # cruza o trecho: fica o que sobra antes e depois, encostado
        s = c.start if c.start < a else a
        e = c.end - n if c.end > b else a
        if e - s < sb.MIN_PIECE:
            continue
        words = tuple(Word(w.start if w.start < a else max(a, w.start - n),
                           w.end if w.end <= a else max(a, w.end - n), w.text)
                      for w in c.words if not (a <= (w.start + w.end) / 2 < b))
        text = c.text if len(words) == len(c.words) else (" ".join(w.text for w in words) or c.text)
        out.append(replace(c, start=s, end=e, text=text, words=words))
    subs.cues = sb.sort_cues(out)


def words(items_: Iterable[Item]) -> list[Word]:
    """As palavras na tela (segundos da sequência), em ordem: a transcrição do "Cortar pelo texto"."""
    out = [w for it in items_ for w in it.cue.words]
    out.sort(key=lambda w: (w.start, w.end))
    return out
