"""Legendas (sem Qt): modelo, estilos prontos, tempo pela montagem, SRT/WebVTT, faixa na exportação e
o desenho gravado no vídeo.

Modelo
------
Uma legenda (`Cue`) tem início, fim, texto e, quando veio da transcrição, as palavras com o tempo de cada
uma (`Word`, para o destaque palavra por palavra). As legendas de um projeto (`Subtitles`) ficam de dois
jeitos:

- **presas a um arquivo** (`Subtitles.sources[caminho]`): tempos em segundos *do arquivo*, como
  `timeline.Clip.src_in`. É o que a transcrição e a importação de um .srt "do arquivo" produzem. Elas
  acompanham a montagem: `map_cues` leva cada legenda para todos os clipes que mostram aquele trecho do
  arquivo (cortes, aparas, mudanças de lugar e de velocidade), usando `Sequence.src_time`. Quadro
  congelado não mostra fala nova: fica de fora. O que um corte tirou some (palavras inclusive).
- **da sequência** (`Subtitles.cues`): tempos em segundos da sequência, não mudam com a montagem.

`timeline_cues` junta os dois em tempo da sequência: é o que a exportação, o .srt exportado e o desenho
no vídeo usam. Tudo aqui é puro e determinístico (mesma entrada → mesma saída).

Arquivos
--------
`parse`/`load` leem SRT e WebVTT (BOM, CRLF, numeração com buracos ou ausente, sobreposições, `<i>`/`<b>`,
tags de cor e `{\\an8}` ignoradas, cabeçalho do VTT, configurações de posição da legenda ignoradas, blocos
NOTE/STYLE/REGION pulados, tempos por palavra `<00:00:01.500>` do VTT viram palavras). `to_srt`/`to_vtt`
gravam em UTF-8; `relative` recorta e desloca para o trecho exportado (como `chapters.relative`).

Na exportação, `export_file` grava o trecho num arquivo temporário e devolve um `Embed` que
`export.build_encoder_cmd(..., subtitles=)` põe como faixa de legenda: `mov_text` no MP4/MOV, SRT no MKV
e WebVTT no WebM (`EMBED_CODECS`). Outros recipientes não guardam legenda (o .srt sai ao lado).

Gravada no vídeo
----------------
`overlay` desenha (via `textrender`) as legendas ativas num quadro da sequência, com o estilo e o
destaque da palavra falada, e devolve a imagem e a posição. Dois lugares possíveis para a composição
(`BURN_MODES`), decididos na integração com o render:

- **"copia" — gravada na cópia**: o texto entra na imagem *antes* do look, como uma legenda impressa na
  película (passa pelo grão, pela halação, pelo tremor e pela cor da emulação);
- **"digital"**: o texto entra *depois* do look, nítido, como num player.

Chave de formato do projeto: o bloco `"legendas"` (`Subtitles.to_json`); o recurso que marca o formato 3
do projeto é `FEATURE_ID`.
"""

from __future__ import annotations

import bisect
import html
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from . import textrender
from .i18n import N_, _

FEATURE_ID = "legendas"          # recurso do projeto (formato 3) quando há legendas
FORMAT = 1                       # versão do bloco "legendas"
EPS = 1e-6
MAX_TIME = 100 * 3600.0          # limite de qualquer tempo (s)
MAX_TEXT = 1000                  # caracteres por legenda
MAX_WORDS = 400                  # palavras por legenda
MAX_CUES = 50_000                # legendas por lista
MAX_FILE = 20 << 20              # tamanho máximo de um .srt/.vtt lido
MIN_PIECE = 0.25                 # s: pedaço de legenda que sobra de um corte e é curto demais para ler
BURN_MODES = ("nao", "copia", "digital")
EMBED_CODECS = {"mp4": "mov_text", "mov": "mov_text", "mkv": "srt", "webm": "webvtt"}
_ISO639_2 = {"pt": "por", "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita", "ja": "jpn",
             "zh": "zho", "ko": "kor", "ru": "rus", "nl": "nld", "pl": "pol", "tr": "tur", "ar": "ara",
             "hi": "hin", "uk": "ukr", "sv": "swe", "ca": "cat", "gl": "glg", "eu": "eus"}


# ------------------------------------------------------------------ modelo
def _num(v: Any, lo: float = 0.0, hi: float = MAX_TIME) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return min(max(f, lo), hi)


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​﻿]")


def clean_text(text: Any, limit: int = MAX_TEXT) -> str:
    """Texto de uma legenda: NFC, quebras de linha "\\n", sem caracteres de controle, linhas sem espaços nas
    pontas e sem linhas vazias."""
    t = unicodedata.normalize("NFC", str(text if text is not None else ""))
    t = _CTRL.sub("", t.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " "))
    lines = [" ".join(ln.split()) for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)[:limit]


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str

    def to_json(self) -> list:
        return [float(round(self.start, 4)), float(round(self.end, 4)), self.text]  # float: ida e volta igual

    @classmethod
    def from_json(cls, d: Any) -> "Word | None":
        if not isinstance(d, (list, tuple)) or len(d) < 3:
            return None
        a, b, text = _num(d[0]), _num(d[1]), clean_text(d[2], 200).replace("\n", " ")
        if a is None or b is None or not text:
            return None
        return cls(a, max(a, b), text)


@dataclass(frozen=True)
class Cue:
    """Uma legenda. Tempos em segundos (do arquivo ou da sequência, conforme a lista onde está)."""
    start: float
    end: float
    text: str
    words: tuple[Word, ...] = ()
    italic: bool = False
    bold: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start

    def shifted(self, dt: float) -> "Cue":
        return replace(self, start=self.start + dt, end=self.end + dt,
                       words=tuple(Word(w.start + dt, w.end + dt, w.text) for w in self.words))

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"inicio": float(round(self.start, 4)), "fim": float(round(self.end, 4)),
                               "texto": self.text}
        if self.words:
            out["palavras"] = [w.to_json() for w in self.words]
        if self.italic:
            out["italico"] = True
        if self.bold:
            out["negrito"] = True
        return out

    @classmethod
    def from_json(cls, d: Any) -> "Cue | None":
        if not isinstance(d, dict):
            return None
        a, b = _num(d.get("inicio")), _num(d.get("fim"))
        text = clean_text(d.get("texto"))
        if a is None or b is None or b <= a + EPS or not text:
            return None
        raw = d.get("palavras") if isinstance(d.get("palavras"), list) else []
        words = tuple(w for w in (Word.from_json(x) for x in raw[:MAX_WORDS]) if w is not None)
        return cls(a, b, text, tuple(sorted(words, key=lambda w: (w.start, w.end))),
                   d.get("italico") is True, d.get("negrito") is True)


def cues_from_json(raw: Any) -> list[Cue]:
    items = raw if isinstance(raw, list) else []
    return sort_cues(c for c in (Cue.from_json(x) for x in items[:MAX_CUES]) if c is not None)


def sort_cues(cues: Iterable[Cue]) -> list[Cue]:
    return sorted(cues, key=lambda c: (c.start, c.end, c.text))


def tokens(text: str) -> list[str]:
    """As palavras do texto como o desenho conta (`textrender.words_of`): o índice do destaque."""
    return [w for par in textrender.words_of(text) for w in par]


# ------------------------------------------------------------------ montar legendas a partir de palavras
_SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")


def balance_lines(text: str, max_chars: int = 42) -> str:
    """Quebra em duas linhas de tamanho parecido (no espaço mais perto do meio) quando passa de `max_chars`."""
    text = " ".join(text.split())
    if len(text) <= max_chars or " " not in text:
        return text
    mid = len(text) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    cut = min(spaces, key=lambda i: (abs(i - mid), i))
    return text[:cut] + "\n" + text[cut + 1:]


def cues_from_words(words: Iterable[Word], max_chars: int = 42, max_lines: int = 2, max_dur: float = 7.0,
                    max_gap: float = 1.0, min_dur: float = 0.8) -> list[Cue]:
    """Agrupa palavras (da transcrição) em legendas: quebra em pausas longas, no fim de frase, quando passa
    de `max_lines` linhas de `max_chars` ou de `max_dur` segundos. Cada legenda fica pelo menos `min_dur`
    na tela (sem invadir a seguinte)."""
    ws = [w for w in words if w.text.strip()]
    ws.sort(key=lambda w: (w.start, w.end))
    limit = max_chars * max(1, max_lines)
    groups: list[list[Word]] = []
    cur: list[Word] = []
    length = 0
    for w in ws:
        if cur:
            last = cur[-1].text
            gap = w.start - cur[-1].end
            sentence = last.endswith(_SENTENCE_END) and length >= 16
            clause = last.endswith((",", ";", ":")) and length >= max_chars
            if (gap > max_gap or length + 1 + len(w.text) > limit or w.end - cur[0].start > max_dur
                    or sentence or clause):
                groups.append(cur)
                cur, length = [], 0
        cur.append(w)
        length += len(w.text) + (1 if length else 0)
    if cur:
        groups.append(cur)
    out: list[Cue] = []
    for i, g in enumerate(groups):
        start, end = g[0].start, max(w.end for w in g)
        nxt = groups[i + 1][0].start if i + 1 < len(groups) else math.inf
        end = max(end, min(start + min_dur, nxt))
        if end <= start + EPS:
            end = start + 0.05
        text = balance_lines(" ".join(w.text for w in g), max_chars) if max_lines > 1 else " ".join(w.text for w in g)
        out.append(Cue(start, end, text, tuple(g)))
    return out


# ------------------------------------------------------------------ tempo pela montagem
def clips_for(seq, path: str) -> list:
    """Clipes que mostram a fala do arquivo: os de som dele; sem som na sequência, os de vídeo (menos os
    congelados, que não mostram fala nova)."""
    from .timeline import AUDIO, VIDEO
    audio = [c for c in seq.clips if c.src == path and c.kind == AUDIO]
    if audio:
        return audio
    return [c for c in seq.clips if c.src == path and c.kind == VIDEO and not c.frozen]


@dataclass(frozen=True)
class Mapping:
    """Como um clipe mostra o arquivo: o segundo `a` do arquivo aparece no segundo `t0` da sequência e o tempo
    anda `speed` vezes mais rápido no arquivo (o mesmo de `Sequence.src_time`). Com rampa ou reverso, `tm` é o
    `timemap.TimeMap` do clipe e as contas passam por ele (no reverso, o fim de uma legenda no arquivo vem antes
    do começo na sequência)."""
    clip: str
    a: float
    t0: float
    speed: float
    tm: Any = field(default=None, compare=False, repr=False)

    @property
    def reverse(self) -> bool:
        return self.tm is not None and self.tm.reverse

    def to_seq(self, x: float) -> float:
        if self.tm is not None:
            return self.t0 + self.tm.out_at(x)
        return self.t0 + (x - self.a) / self.speed

    def to_file(self, t: float) -> float:
        if self.tm is not None:
            return self.tm.src_at(t - self.t0)
        return self.a + (t - self.t0) * self.speed

    def span(self, lo: float, hi: float) -> tuple[float, float]:
        """O trecho [lo, hi] do arquivo em segundos da sequência, em ordem."""
        s, e = self.to_seq(lo), self.to_seq(hi)
        return (e, s) if self.reverse else (s, e)


def mapping_of(seq, clip) -> Mapping:
    """O `Mapping` do clipe (o mesmo de `mapped`)."""
    tm = seq.time_map(clip) if clip.retimed else None
    return Mapping(clip.id, seq.src_time(clip, clip.start), clip.start / seq.fps, clip.speed, tm)


def mapped(seq, path: str, cues: Iterable[Cue], min_piece: float = MIN_PIECE):
    """Cada pedaço visível das legendas presas ao arquivo `path`: (índice da legenda em `cues`, `Mapping` do clipe,
    legenda em segundos da sequência), na ordem dos clipes. É a regra de `map_cues` (que junta e tira as
    repetidas); a interface usa isto para saber de onde veio cada legenda que aparece."""
    cues = list(cues)
    for c in clips_for(seq, path):
        a, b = sorted((seq.src_time(c, c.start), seq.src_time(c, c.end)))  # trecho do arquivo que o clipe mostra
        if b <= a + EPS:
            continue
        m = mapping_of(seq, c)
        for i, cue in enumerate(cues):
            lo, hi = max(cue.start, a), min(cue.end, b)
            if hi <= lo + EPS:
                continue
            words = tuple(sorted((Word(*m.span(max(w.start, a), min(w.end, b)), w.text) for w in cue.words
                                  if a - EPS <= (w.start + w.end) / 2 < b - EPS), key=lambda w: w.start))
            if cue.words and not words:
                continue
            cut = lo > cue.start + EPS or hi < cue.end - EPS
            s, e = m.span(lo, hi)
            if cut and e - s < min_piece:
                continue
            text = cue.text if len(words) == len(cue.words) else " ".join(w.text for w in words)
            yield i, m, Cue(s, e, text, words, cue.italic, cue.bold)


def cue_key(cue: Cue) -> tuple:
    """Duas legendas iguais na tela (som em duas faixas do mesmo arquivo) contam uma vez só."""
    return round(cue.start, 3), round(cue.end, 3), cue.text


def map_cues(seq, path: str, cues: Iterable[Cue], min_piece: float = MIN_PIECE) -> list[Cue]:
    """Legendas presas ao arquivo `path` (segundos do arquivo) → segundos da sequência, uma cópia para cada
    clipe que mostra aquele trecho. O que fica fora do clipe é cortado; com palavras, ficam só as que têm o
    meio dentro do clipe (e o texto passa a ser o delas). Um pedaço cortado mais curto que `min_piece` some."""
    out = [cue for _i, _m, cue in mapped(seq, path, cues, min_piece)]
    seen: set[tuple] = set()
    uniq = []
    for cue in sort_cues(out):  # som em duas faixas do mesmo arquivo: a mesma legenda uma vez só
        key = cue_key(cue)
        if key not in seen:
            seen.add(key)
            uniq.append(cue)
    return uniq


# ------------------------------------------------------------------ estilos
POSITIONS = ("baixo", "meio", "cima")


@dataclass(frozen=True)
class SubStyle:
    """Aparência e lugar da legenda gravada no vídeo. Distâncias em px@1080."""
    id: str
    name: str
    text: textrender.TextStyle
    position: str = "baixo"            # "baixo", "meio" ou "cima"
    margin: float = 60.0               # da borda (baixo/cima) ou deslocamento a partir do meio (+ = para baixo)
    width: float = 0.84                # largura máxima do texto, fração da largura do quadro
    max_words: int = 0                 # palavras por tela (0 = a legenda inteira)
    highlight: textrender.WordOverride | None = None   # destaque da palavra falada

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "texto": self.text.to_json(), "posicao": self.position,
                               "margem": float(round(self.margin, 3)), "largura": float(round(self.width, 4)),
                               "palavras_por_tela": self.max_words}
        if self.highlight is not None:
            h = self.highlight
            out["destaque"] = {"cor": textrender.color_hex(h.color) if h.color else None,
                               "escala": float(round(h.scale, 4)),
                               "caixa": textrender.color_hex(h.box_color) if h.box_color else None,
                               "caixa_opacidade": float(round(h.box_opacity, 4))}
        elif STYLES.get(self.id) is not None and STYLES[self.id].highlight is not None:
            out["destaque"] = None   # destaque do estilo pronto desligado
        return out

    @classmethod
    def from_json(cls, d: Any) -> "SubStyle":
        """Do projeto: começa do estilo pronto do mesmo id e aplica o que veio (conferido)."""
        d = d if isinstance(d, dict) else {}
        base = STYLES.get(d.get("id")) or STYLES[DEFAULT_STYLE]
        kw: dict[str, Any] = {}
        if isinstance(d.get("texto"), dict):
            kw["text"] = textrender.TextStyle.from_json({**base.text.to_json(), **d["texto"]})
        if d.get("posicao") in POSITIONS:
            kw["position"] = d["posicao"]
        for key, attr, lo, hi in (("margem", "margin", -1000.0, 1000.0), ("largura", "width", 0.1, 1.0)):
            v = _num(d.get(key), lo, hi)
            if v is not None:
                kw[attr] = v
        mw = _num(d.get("palavras_por_tela"), 0, 50)
        if mw is not None:
            kw["max_words"] = int(mw)
        if "destaque" in d:
            h = d.get("destaque")
            if isinstance(h, dict):
                col = textrender.parse_color(h["cor"]) if isinstance(h.get("cor"), str) else None
                box = textrender.parse_color(h["caixa"]) if isinstance(h.get("caixa"), str) else None
                scale = _num(h.get("escala"), 0.5, 2.0)
                box_op = _num(h.get("caixa_opacidade"), 0.0, 1.0)
                kw["highlight"] = textrender.WordOverride(color=col, scale=1.0 if scale is None else scale,
                                                          box_color=box, box_opacity=1.0 if box_op is None else box_op)
            else:
                kw["highlight"] = None
        return replace(base, **kw)


_TR = textrender.TextStyle
_C = textrender.parse_color   # cores em #rrggbb: o JSON do projeto guarda assim (ida e volta exata)
STYLES: dict[str, SubStyle] = {s.id: s for s in (
    # YouTube: texto claro numa caixa escura por linha, embaixo.
    SubStyle("youtube", N_("YouTube"),
             _TR(family="atkinson", weight=400, size=46, color=_C("#ffffff"), box=0.75, box_color=_C("#080808"),
                 box_padding=9, box_radius=5, line_spacing=1.05),
             position="baixo", margin=64, width=0.8),
    # Reels/Shorts/TikTok (vídeo vertical): grande, no meio, em negrito, poucas palavras e a palavra falada em destaque.
    SubStyle("reels", N_("Reels e Shorts (vertical)"),
             _TR(family="poppins", weight=900, size=62, uppercase=True, color=_C("#ffffff"), outline=5,
                 outline_color=_C("#000000"), shadow=0.55, shadow_y=4, shadow_blur=6, line_spacing=0.95),
             position="meio", margin=120, width=0.86, max_words=3,
             highlight=textrender.WordOverride(color=_C("#ffd600"), scale=1.08)),
    # Cinema: discreta, embaixo, sem caixa, com uma sombra leve.
    SubStyle("cinema", N_("Cinema"),
             _TR(family="atkinson", weight=400, size=40, color=_C("#f5f5ed"), shadow=0.7, shadow_x=0, shadow_y=2,
                 shadow_blur=3.5, line_spacing=1.05),
             position="baixo", margin=70, width=0.76),
)}
DEFAULT_STYLE = "youtube"


def style(style_id: str) -> SubStyle:
    return STYLES.get(style_id) or STYLES[DEFAULT_STYLE]


# ------------------------------------------------------------------ as legendas do projeto
@dataclass
class Subtitles:
    """Bloco "legendas" do projeto."""
    sources: dict[str, list[Cue]] = field(default_factory=dict)  # caminho do arquivo → legendas (s do arquivo)
    cues: list[Cue] = field(default_factory=list)                # legendas da sequência (s da sequência)
    language: str = ""                                           # ISO 639-1 ("pt", "en", "es"; "" = não se sabe)
    style: SubStyle = field(default_factory=lambda: STYLES[DEFAULT_STYLE])
    burn: str = "nao"                                            # gravar no vídeo: um de BURN_MODES
    embed: bool = True                                           # faixa de legenda no arquivo exportado

    def is_empty(self) -> bool:
        return not self.cues and not any(self.sources.values())

    def is_default(self) -> bool:
        """Nada a guardar: sem legendas e com as opções padrão (o bloco "legendas" fica fora do projeto)."""
        return self.is_empty() and self.to_json() == Subtitles().to_json()

    def relink(self, old: str, new: str) -> None:
        """O arquivo mudou de lugar (`Sequence.relink`): as legendas dele vão junto."""
        if old in self.sources and old != new:
            self.sources[new] = self.sources.pop(old) + self.sources.get(new, [])
            self.sources[new] = sort_cues(self.sources[new])

    def timeline_cues(self, seq=None, path: str | None = None) -> list[Cue]:
        """Todas as legendas em segundos da sequência. Sem `seq` (modo Película), o arquivo `path` é a
        própria sequência: as legendas dele valem como estão."""
        out = list(self.cues)
        if seq is None:
            out += self.sources.get(path or "", [])
        else:
            for p, cues in self.sources.items():
                if cues:
                    out += map_cues(seq, p, cues)
        return sort_cues(out)

    def to_json(self) -> dict[str, Any]:
        return {"versao": FORMAT, "idioma": self.language, "estilo": self.style.to_json(), "gravar": self.burn,
                "faixa": self.embed,
                "fontes": {p: [c.to_json() for c in cues] for p, cues in sorted(self.sources.items()) if cues},
                "sequencia": [c.to_json() for c in self.cues]}

    @classmethod
    def from_json(cls, d: Any) -> "Subtitles":
        d = d if isinstance(d, dict) else {}
        sources: dict[str, list[Cue]] = {}
        raw = d.get("fontes") if isinstance(d.get("fontes"), dict) else {}
        for p, items in raw.items():
            if isinstance(p, str) and p and len(p) <= 4096 and not _CTRL.search(p):
                cues = cues_from_json(items)
                if cues:
                    sources[p] = cues
        lang = d.get("idioma") if isinstance(d.get("idioma"), str) else ""
        lang = lang.lower() if re.fullmatch(r"[A-Za-z]{2,3}", lang or "") else ""
        return cls(sources=sources, cues=cues_from_json(d.get("sequencia")), language=lang,
                   style=SubStyle.from_json(d.get("estilo")),
                   burn=d.get("gravar") if d.get("gravar") in BURN_MODES else "nao",
                   embed=d.get("faixa") is not False)


# ------------------------------------------------------------------ SRT e WebVTT
_TS = r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?"
_TIMING = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}(?:\s+(.*))?\s*$")
_TAG = re.compile(r"<\s*(/?)\s*([A-Za-z]*)[^>]*>")
_ASS = re.compile(r"\{\\[^}]*\}")
# No SRT só estas tags são tags (o resto é texto); no WebVTT o texto vem escapado e toda tag é tag.
_SRT_TAGS = frozenset({"i", "b", "u", "s", "font", "c", "v", "span", "lang", "ruby", "rt"})
_VTT_STAMP = re.compile(r"<((?:\d{1,3}:)?\d{1,2}:\d{1,2}\.\d{1,3})>")


def _secs(h: str | None, m: str, s: str, frac: str | None) -> float:
    f = int(frac) / 10 ** len(frac) if frac else 0.0
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + f


def _stamp_secs(text: str) -> float:
    m = re.fullmatch(_TS, text.strip())
    return _secs(*m.groups()) if m else 0.0


def _markup(raw: str, vtt: bool = True) -> tuple[str, bool, bool]:
    """Tira as tags (<i>, <b>, <u>, <font>, <c.x>, <v Nome>...) e diz se o texto todo está em itálico/negrito.

    No SRT só as tags conhecidas saem (`_SRT_TAGS`): lá não há escape, e "<fim>" é texto."""
    raw = _ASS.sub("", raw)
    depth = {"i": 0, "b": 0}
    parts: list[str] = []
    inside = {"i": [], "b": []}
    pos = 0
    found = [m for m in _TAG.finditer(raw) if vtt or m.group(2).lower() in _SRT_TAGS]
    for m in [*found, None]:
        chunk = raw[pos:m.start() if m is not None else len(raw)]
        if chunk:
            parts.append(chunk)
            if chunk.strip():
                for k in depth:
                    inside[k].append(depth[k] > 0)
        if m is None:
            break
        name = m.group(2).lower()
        if name in depth:
            depth[name] = max(0, depth[name] + (-1 if m.group(1) else 1))
        pos = m.end()
    text = "".join(parts)
    return text, bool(inside["i"]) and all(inside["i"]), bool(inside["b"]) and all(inside["b"])


def decode(data: bytes) -> str:
    """Bytes de um .srt/.vtt → texto: UTF-8 (com ou sem BOM); se não for, Windows-1252 (legendas antigas)."""
    encodings = ("utf-16", "utf-8-sig") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig",)
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("cp1252", errors="replace")


def _lines(text: str) -> list[str]:
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _make(a: float, b: float, body: list[str], vtt: bool) -> Cue | None:
    raw = "\n".join(body)
    words: tuple[Word, ...] = ()
    if vtt and _VTT_STAMP.search(raw):
        words = _vtt_words(raw, a, b)
        raw = _VTT_STAMP.sub("", raw)
    text, italic, bold = _markup(raw, vtt)
    if vtt:
        text = html.unescape(text)
    text = clean_text(text)
    if not text or b <= a + EPS or a > MAX_TIME:
        return None
    if words and len(words) != len(tokens(text)):
        words = ()
    return Cue(a, min(b, MAX_TIME), text, words, italic, bold)


def _vtt_words(raw: str, a: float, b: float) -> tuple[Word, ...]:
    """Tempos por palavra do WebVTT ("<00:00:01.500>"): cada trecho começa no seu tempo e vai até o próximo."""
    pieces = _VTT_STAMP.split(raw)
    segs = [(a, pieces[0])] + [(_stamp_secs(pieces[i]), pieces[i + 1]) for i in range(1, len(pieces) - 1, 2)]
    out: list[Word] = []
    for i, (t, chunk) in enumerate(segs):
        nxt = segs[i + 1][0] if i + 1 < len(segs) else b
        text = clean_text(html.unescape(_markup(chunk)[0])).replace("\n", " ")
        toks = text.split()
        if not toks:
            continue
        t = min(max(t, a), b)
        nxt = min(max(nxt, t), b)
        step = (nxt - t) / len(toks)
        out += [Word(t + j * step, t + (j + 1) * step, w) for j, w in enumerate(toks)]
    return tuple(out)


def parse_srt(text: str) -> list[Cue]:
    lines = _lines(text)
    n = len(lines)
    out: list[Cue] = []
    i = 0
    while i < n and len(out) < MAX_CUES:
        m = _TIMING.match(lines[i])
        if not m:
            i += 1
            continue
        g = m.groups()
        a, b = _secs(*g[0:4]), _secs(*g[4:8])
        i += 1
        body: list[str] = []
        while i < n and lines[i].strip():
            if _TIMING.match(lines[i]):
                break
            if lines[i].strip().isdigit() and i + 1 < n and _TIMING.match(lines[i + 1]):
                break  # número da próxima legenda sem a linha em branco antes
            body.append(lines[i])
            i += 1
        cue = _make(a, b, body, vtt=False)
        if cue is not None:
            out.append(cue)
    return sort_cues(out)


def parse_vtt(text: str) -> list[Cue]:
    lines = _lines(text)
    n = len(lines)
    i = 0
    if lines and lines[0].startswith("WEBVTT"):
        while i < n and lines[i].strip():   # cabeçalho até a primeira linha em branco
            i += 1
    out: list[Cue] = []
    while i < n and len(out) < MAX_CUES:
        while i < n and not lines[i].strip():
            i += 1
        block: list[str] = []
        while i < n and lines[i].strip():
            block.append(lines[i])
            i += 1
        if not block:
            break
        head = block[0].strip()
        if head.startswith(("NOTE", "STYLE", "REGION")) and "-->" not in head:
            continue
        k = 0 if _TIMING.match(block[0]) else 1 if len(block) > 1 and _TIMING.match(block[1]) else -1
        if k < 0:
            continue
        g = _TIMING.match(block[k]).groups()
        cue = _make(_secs(*g[0:4]), _secs(*g[4:8]), block[k + 1:], vtt=True)
        if cue is not None:
            out.append(cue)
    return sort_cues(out)


def parse(text: str) -> list[Cue]:
    """SRT ou WebVTT (pelo cabeçalho "WEBVTT")."""
    first = next((ln for ln in _lines(text) if ln.strip()), "")
    return parse_vtt(text) if first.startswith("WEBVTT") else parse_srt(text)


def load(path: str | os.PathLike) -> list[Cue]:
    """Lê um .srt ou .vtt. ValueError (mensagem para o usuário) se não for legenda."""
    p = os.fspath(path)
    try:
        if os.path.getsize(p) > MAX_FILE:
            raise ValueError(_("O arquivo de legendas é grande demais: {arquivo}").format(arquivo=os.path.basename(p)))
        with open(p, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise ValueError(_("Não foi possível ler {arquivo}: {erro}").format(arquivo=os.path.basename(p), erro=exc)) from exc
    cues = parse(decode(data))
    if not cues:
        raise ValueError(_("Nenhuma legenda encontrada em {arquivo}. Use um arquivo .srt ou .vtt.").format(
            arquivo=os.path.basename(p)))
    return cues


def fmt_time(t: float, sep: str = ",") -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def _wrap(text: str, cue: Cue) -> str:
    if cue.bold:
        text = f"<b>{text}</b>"
    if cue.italic:
        text = f"<i>{text}</i>"
    return text


def _usable(cues: Iterable[Cue]) -> list[Cue]:
    """Na ordem, sem legendas que somem ao arredondar para milissegundos."""
    return [c for c in sort_cues(cues) if int(round(c.end * 1000)) > int(round(c.start * 1000)) and c.text]


def to_srt(cues: Iterable[Cue]) -> str:
    out = []
    for n, c in enumerate(_usable(cues), 1):
        out.append(f"{n}\n{fmt_time(c.start)} --> {fmt_time(c.end)}\n{_wrap(c.text, c)}\n")
    return "\n".join(out)


def to_vtt(cues: Iterable[Cue]) -> str:
    out = ["WEBVTT\n"]
    for c in _usable(cues):
        text = c.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        out.append(f"{fmt_time(c.start, '.')} --> {fmt_time(c.end, '.')}\n{_wrap(text, c)}\n")
    return "\n".join(out)


def save(path: str | os.PathLike, cues: Iterable[Cue]) -> None:
    """Grava .srt ou .vtt (pela extensão), UTF-8 sem BOM, linhas com "\\n"."""
    p = os.fspath(path)
    text = to_vtt(cues) if p.lower().endswith(".vtt") else to_srt(cues)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def relative(cues: Iterable[Cue], start: float, end: float) -> list[Cue]:
    """Legendas dentro de [start, end) segundos, com o tempo contado do `start` e cortadas nas pontas."""
    out = []
    for c in sort_cues(cues):
        a, b = max(c.start, start), min(c.end, end)
        if b <= a + EPS:
            continue
        words = tuple(Word(max(w.start, a) - start, min(w.end, b) - start, w.text) for w in c.words
                      if w.end > a + EPS and w.start < b - EPS)
        out.append(Cue(a - start, b - start, c.text, words, c.italic, c.bold))
    return out


# ------------------------------------------------------------------ faixa de legenda na exportação
@dataclass(frozen=True)
class Embed:
    """Faixa de legenda para `export.build_encoder_cmd(..., subtitles=)` (o arquivo é apagado por quem pediu)."""
    path: str
    codec: str          # "mov_text", "srt" ou "webvtt"
    language: str = ""  # ISO 639-2 ("por", "eng", "spa"); "" = sem idioma


def iso639_2(language: str) -> str:
    lang = (language or "").lower()
    return lang if len(lang) == 3 else _ISO639_2.get(lang, "und" if lang else "")


def job_payload(cues: Iterable[Cue], language: str = "") -> dict[str, Any]:
    """O que o trabalho de exportação guarda (`ExportJob.subtitles`): as legendas em tempo da sequência."""
    cues = list(cues)
    return {"idioma": language, "legendas": [c.to_json() for c in cues]} if cues else {}


SIDECAR_FORMATS = ("srt", "vtt")
# Como as legendas saem numa exportação (janela Exportar e `pelicula-cli exportar --legendas`).
DELIVERY = ("nao", "faixa", "copia", "digital", "srt", "vtt")


def default_delivery(subs: "Subtitles | None", container: str) -> str:
    """O padrão do projeto: gravadas no vídeo (se o projeto pede), senão a faixa no arquivo quando o recipiente
    guarda legenda, senão o .srt ao lado. "nao" sem legendas."""
    if subs is None or subs.is_empty():
        return "nao"
    if subs.burn in ("copia", "digital"):
        return subs.burn
    if not subs.embed:
        return "nao"
    return "faixa" if container in EMBED_CODECS else "srt"


def delivery_fields(choice: str, subs: "Subtitles | None", cues: Iterable[Cue], container: str) -> dict[str, Any]:
    """Os campos do `export.ExportJob` para a escolha: `subtitles` (faixa), `burn` (gravadas) e `subtitle_file`
    (.srt/.vtt ao lado). Faixa num recipiente que não guarda legenda vira o .srt ao lado."""
    out: dict[str, Any] = {"subtitles": {}, "burn": {}, "subtitle_file": {}}
    cues = list(cues)
    if subs is None or not cues or choice not in DELIVERY or choice == "nao":
        return out
    if choice == "faixa" and container not in EMBED_CODECS:
        choice = "srt"
    if choice == "faixa":
        out["subtitles"] = job_payload(cues, subs.language)
    elif choice in ("copia", "digital"):
        burn = Burn.make(choice, subs.style, cues)
        out["burn"] = burn.to_json() if burn is not None else {}
    else:
        out["subtitle_file"] = sidecar_payload(cues, choice, subs.language)
    return out


def sidecar_payload(cues: Iterable[Cue], fmt: str, language: str = "") -> dict[str, Any]:
    """O .srt/.vtt ao lado do vídeo exportado (`ExportJob.subtitle_file`): formato e legendas da sequência."""
    out = job_payload(cues, language)
    if out and fmt in SIDECAR_FORMATS:
        out["formato"] = fmt
        return out
    return {}


def sidecar_path(out_path: str, fmt: str) -> str:
    """O arquivo de legendas ao lado do vídeo: o mesmo nome com .srt ou .vtt."""
    return os.path.splitext(out_path)[0] + "." + fmt


def write_sidecar(payload: dict[str, Any] | None, out_path: str, start: int, end: int, fps: float) -> str | None:
    """Grava o trecho [start, end) quadros (tempo contado do começo do trecho) ao lado de `out_path`. Devolve o
    caminho, ou None sem legendas no trecho. OSError se não der para gravar."""
    if not payload or payload.get("formato") not in SIDECAR_FORMATS or end <= start:
        return None
    fps = fps if fps and fps > 0 else 24.0
    cues = relative(cues_from_json(payload.get("legendas")), start / fps, end / fps)
    if not cues:
        return None
    path = sidecar_path(out_path, payload["formato"])
    save(path, cues)
    return path


def export_file(payload: dict[str, Any] | None, container: str, start: int, end: int, fps: float) -> Embed | None:
    """Grava o trecho [start, end) quadros das legendas do trabalho num WebVTT temporário (o ffmpeg converte para
    o formato do recipiente; o WebVTT tem escape, então "<" e "&" chegam intactos). None quando o recipiente
    não guarda legenda ou não há legenda no trecho."""
    if not payload or container not in EMBED_CODECS or end <= start:
        return None
    fps = fps if fps and fps > 0 else 24.0
    cues = relative(cues_from_json(payload.get("legendas")), start / fps, end / fps)
    if not cues:
        return None
    codec = EMBED_CODECS[container]
    fd, path = tempfile.mkstemp(prefix="pelicula_legendas_", suffix=".vtt")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(to_vtt(cues))
    lang = payload.get("idioma") if isinstance(payload.get("idioma"), str) else ""
    return Embed(path, codec, iso639_2(lang))


def encoder_args(embed: Embed, n_input: int, absolute: bool = False) -> tuple[list[str], list[str]]:
    """(entrada, saída) do ffmpeg para a faixa: `-i arquivo` e `-map n:s:0 -c:s codec [-metadata idioma]`."""
    path = os.path.abspath(embed.path) if absolute else embed.path
    out = ["-map", f"{n_input}:s:0", "-c:s", embed.codec]
    if embed.language:
        out += ["-metadata:s:s:0", f"language={embed.language}"]
    return ["-f", "webvtt", "-i", path], out


# ------------------------------------------------------------------ gravada no vídeo
@dataclass(frozen=True)
class Overlay:
    """Legenda desenhada para um quadro: a imagem e onde o canto do bloco de texto fica no quadro."""
    image: textrender.TextImage
    x: int
    y: int

    def paste(self, frame) -> None:
        """Compõe por cima de um quadro RGBA (alfa direto, mesma profundidade) — veja `textrender.paste`."""
        textrender.paste(frame, self.image, self.x, self.y)


def active(cues: Iterable[Cue], t: float) -> list[Cue]:
    """Legendas na tela no instante t (início incluído, fim excluído)."""
    return [c for c in sort_cues(cues) if c.start - EPS <= t < c.end - EPS]


def _spoken(cue: Cue, t: float) -> int | None:
    """Índice da palavra falada no instante t (a última que já começou), ou None antes da primeira."""
    idx = None
    for i, w in enumerate(cue.words):
        if w.start <= t + EPS:
            idx = i
        else:
            break
    return idx


def visible_text(cue: Cue, t: float, st: SubStyle) -> tuple[str, int | None]:
    """O texto da legenda que aparece em t e o índice (nesse texto) da palavra a destacar.

    Com `st.max_words`, mostra só a "página" de palavras que contém a palavra falada."""
    toks = tokens(cue.text)
    aligned = bool(cue.words) and len(cue.words) == len(toks)
    spoken = _spoken(cue, t) if aligned else None
    if aligned and st.max_words > 0 and len(toks) > st.max_words:
        n = st.max_words
        page = (spoken or 0) // n
        part = cue.words[page * n:(page + 1) * n]
        return " ".join(w.text for w in part), (spoken - page * n) if spoken is not None else None
    return cue.text, spoken


def overlay(cues: Iterable[Cue], frame: int, fps: float, st: SubStyle, width: int, height: int,
            depth: int = 8) -> Overlay | None:
    """As legendas do quadro `frame` (da sequência) desenhadas com o estilo, para um quadro de
    `width` × `height`. None quando não há legenda nesse quadro. Precisa de `textrender.ensure_app()`."""
    fps = fps if fps and fps > 0 else 24.0
    t = frame / fps
    return draw(active(cues, t), t, st, width, height, depth)


def draw(act: list[Cue], t: float, st: SubStyle, width: int, height: int, depth: int = 8) -> Overlay | None:
    """As legendas `act` (as que estão na tela no instante t, em ordem) desenhadas com o estilo."""
    if not act:
        return None
    parts: list[str] = []
    overrides: dict[int, textrender.WordOverride] = {}
    base = 0
    for cue in act:
        text, hi = visible_text(cue, t, st)
        if hi is not None and st.highlight is not None:
            overrides[base + hi] = st.highlight
        base += len(tokens(text))
        parts.append(text)
    scale = max(1, int(height)) / textrender.REF_HEIGHT
    ts = st.text
    italic = all(c.italic for c in act)
    bold = all(c.bold for c in act)
    ts = replace(ts, wrap=st.width * width / scale, italic=ts.italic or italic,
                 weight=max(ts.weight, 700) if bold else ts.weight)
    img = textrender.render("\n".join(parts), ts, height, overrides=overrides, depth=depth)
    lay = img.layout
    x = int(round((width - lay.width) / 2))
    if st.position == "cima":
        y = st.margin * scale
    elif st.position == "meio":
        y = (height - lay.height) / 2 + st.margin * scale
    else:
        y = height - st.margin * scale - lay.height
    return Overlay(img, x, int(round(y)))


def composite(frame, ov: Overlay):
    """Uma cópia do quadro com a legenda por cima (o quadro dado não muda). Quadro RGB (h × w × 3, uint8 ou
    uint16): a imagem do texto é pré-multiplicada pelo alfa e composta "por cima" em float32 e arredondada;
    quadro RGBA (alfa direto): `textrender.paste`. Mesma entrada → mesmos bits."""
    import numpy as np
    out = np.array(frame, copy=True)
    if out.ndim != 3 or out.shape[2] not in (3, 4):
        return out
    if out.shape[2] == 4:
        textrender.paste(out, ov.image, ov.x, ov.y)
        return out
    img = ov.image
    h, w = out.shape[:2]
    ax, ay = ov.x + img.left, ov.y + img.top
    x0, y0, x1, y1 = max(0, ax), max(0, ay), min(w, ax + img.width), min(h, ay + img.height)
    if x0 >= x1 or y0 >= y1:
        return out
    peak = np.float32(65535.0 if out.dtype == np.uint16 else 255.0)
    src_peak = np.float32(65535.0 if img.rgba.dtype == np.uint16 else 255.0)
    src = img.rgba[y0 - ay:y1 - ay, x0 - ax:x1 - ax].astype(np.float32) / src_peak
    a = src[..., 3:4]
    cur = out[y0:y1, x0:x1].astype(np.float32) / peak
    res = src[..., :3] * a + cur * (np.float32(1.0) - a)   # pré-multiplicado, "por cima"
    out[y0:y1, x0:x1] = np.round(np.clip(res, 0.0, 1.0) * peak).astype(out.dtype)
    return out


@dataclass(frozen=True)
class Burn:
    """Legendas gravadas no vídeo, para `frame.Recipe.burn`: o modo ("copia", antes do look, ou "digital",
    depois), o estilo e as legendas em segundos da saída (a sequência). `apply` desenha as do instante t num
    quadro; a prévia, "Salvar quadro", a exportação e a linha de comando usam a mesma receita.

    Desenhar precisa de uma `QGuiApplication` (`textrender.ensure_app`, criada na thread principal)."""
    mode: str
    style: SubStyle
    cues: tuple[Cue, ...]

    @classmethod
    def make(cls, mode: str, style: SubStyle, cues: Iterable[Cue]) -> "Burn | None":
        """None quando não há o que gravar (modo "nao" ou sem legendas)."""
        cues = tuple(c for c in sort_cues(cues) if c.end > c.start + EPS and c.text)
        if mode not in BURN_MODES or mode == "nao" or not cues:
            return None
        return cls(mode, style, cues)

    @classmethod
    def for_project(cls, subs: "Subtitles | None", seq=None, path: str | None = None,
                    mode: str | None = None) -> "Burn | None":
        """Das legendas do projeto no tempo da montagem (`Subtitles.timeline_cues`), no modo do projeto (ou no
        modo dado)."""
        if subs is None:
            return None
        return cls.make(subs.burn if mode is None else mode, subs.style, subs.timeline_cues(seq, path))

    def to_json(self) -> dict[str, Any]:
        """O que o trabalho de exportação guarda (`ExportJob.burn`, "legendas_gravadas" no JSON)."""
        return {"modo": self.mode, "estilo": self.style.to_json(), "legendas": [c.to_json() for c in self.cues]}

    @classmethod
    def from_json(cls, d: Any) -> "Burn | None":
        if not isinstance(d, dict) or not d:
            return None
        mode = d.get("modo") if isinstance(d.get("modo"), str) else "nao"
        return cls.make(mode, SubStyle.from_json(d.get("estilo")), cues_from_json(d.get("legendas")))

    def __post_init__(self) -> None:
        object.__setattr__(self, "_starts", [c.start for c in self.cues])   # para achar as ativas com bisect
        object.__setattr__(self, "_longest", max((c.end - c.start for c in self.cues), default=0.0))

    def active(self, t: float) -> list[Cue]:
        """As legendas na tela no instante t (as mesmas de `active`, sem percorrer a lista toda)."""
        hi = bisect.bisect_right(self._starts, t + EPS)
        lo = bisect.bisect_left(self._starts, t - self._longest - EPS)
        return [c for c in self.cues[lo:hi] if c.start - EPS <= t < c.end - EPS]

    def overlay(self, t: float, width: int, height: int, depth: int = 8) -> Overlay | None:
        """A legenda do instante t (s) desenhada para um quadro de `width` × `height` (None: nada na tela)."""
        act = self.active(t)
        if not act:
            return None
        textrender.ensure_app()
        return draw(act, t, self.style, width, height, depth)

    def apply(self, frame, t: float):
        """O quadro com a legenda do instante t por cima; sem legenda nesse instante, o mesmo objeto."""
        import numpy as np
        h, w = frame.shape[:2]
        ov = self.overlay(t, w, h, 16 if frame.dtype == np.uint16 else 8)
        return frame if ov is None else composite(frame, ov)
