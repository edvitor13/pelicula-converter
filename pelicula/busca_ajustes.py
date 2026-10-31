"""Busca nos ajustes (sem Qt): quais seções e quais controles combinam com o que a pessoa digitou.

O filtro "Filtrar ajustes…" dos painéis (`ui/filtro_ajustes.py`) pergunta aqui. O índice sai dos objetos
`params.Section` / `params.Param` (título e subtítulo da seção, rótulo e dica de cada controle, rótulos das
opções dos menus e a chave interna) e guarda cada texto em português (o texto-fonte) **e** nas traduções
para inglês e espanhol, lidas dos catálogos sem mudar o idioma da interface: digitar "chromatic" acha a
aberração cromática com a interface em português, e "aberración" acha com ela em inglês.

Regras da busca:
- sem diferença de maiúsculas nem de acentos ("aberracao" acha "aberração");
- cada palavra digitada precisa aparecer, em qualquer ordem, como pedaço do texto da seção ou de algum
  controle (uma palavra pode bater no título e outra num controle);
- só quando nada bate de forma exata, vale um erro de digitação em palavras de 5 letras ou mais.

Os índices são montados no primeiro uso (não pesam na abertura do app) e guardados. A busca nunca muda
`Section` nem `Param`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from . import i18n

# Idiomas indexados: o texto-fonte (pt_BR) e as traduções dos catálogos.
LANGS = (i18n.SOURCE, "en", "es")

# Palavras que a pessoa usa e que não estão nos rótulos: chave da seção → termos (em qualquer idioma).
# Os termos entram só no texto da seção, e a seção inteira conta como encontrada.
KEYWORDS: dict[str, tuple[str, ...]] = {
    # Película (look)
    "lente": ("chromatic", "aberration", "CA", "franja", "fringe", "fringing", "aberracion", "blur", "soft",
              "sharpen", "vignette", "viñeta", "vinheta", "lens", "desfoque", "nitidez"),
    "halacao": ("halation", "halo", "glow", "red glow", "brillo rojo", "bright", "halacion"),
    "grao": ("grain", "noise", "ruido", "granulado", "granulation", "textura", "texture", "iso"),
    "lut": ("lut", "cube", ".cube", "look up table", "luts", "premiere", "resolve"),
    "bloom": ("glow", "difusion", "diffusion", "mist", "pro-mist", "promist", "soft glow"),
    "projetor": ("flicker", "weave", "gate weave", "jitter", "shake", "parpadeo", "cintilacao"),
    "desgaste": ("dust", "scratches", "hair", "damage", "dirt", "polvo", "arañazos", "poeira", "riscos",
                 "sujeira", "leak", "light leak", "burn"),
    "moldura": ("letterbox", "bars", "aspect", "aspect ratio", "crop", "barras", "mask", "pillarbox"),
    "scan": ("sprocket", "perforations", "edge", "borde", "furos", "scan", "border"),
    "lab": ("negative", "print", "negativo", "copia", "density", "densidad", "developing", "bleach", "bypass",
            "printer lights", "luces", "technicolor"),
    "cor": ("color", "colour", "curve", "tone", "saturation", "contrast", "tint", "cast", "toe", "shoulder"),
    "entrada": ("input", "log", "camera profile", "color space", "gamut", "rec709", "exposure", "white balance"),
    "pelicula": ("gauge", "format", "film stock", "stock", "8mm", "16mm", "35mm", "imax", "bitola", "film",
                 "iso", "print stock"),
    "planos": ("depth", "foreground", "background", "skin", "mask", "profundidade", "piel", "fondo"),
    "obturador": ("shutter", "motion blur", "180", "obturacion", "rastro"),
    "anamorfico": ("anamorphic", "flare", "streak", "desqueeze", "anamorfico", "anamorfica"),
    "data": ("date", "date stamp", "timestamp", "fecha", "datestamp"),
    "montagem_filme": ("splice", "reel", "cut", "emenda", "rolo", "empalme"),
    # Edição (clipe)
    "luz": ("exposure", "brightness", "highlights", "shadows", "whites", "blacks", "exposicao", "brillo"),
    "hsl": ("hue", "saturation", "luminance", "matiz", "tono", "color range"),
    "rodas": ("color wheels", "lift", "gamma", "gain", "ruedas", "shadows midtones highlights"),
    "curva": ("curves", "tone curve", "curvas"),
    "detalhe": ("sharpen", "sharpness", "clarity", "blur", "denoise", "noise reduction", "ruido", "reducao de "
                "ruido", "desenfoque", "suavizar"),
    "efeitos": ("vignette", "fade", "faded", "viñeta", "vinheta", "desbotado"),
    "transformar": ("scale", "position", "rotate", "rotation", "crop", "opacity", "zoom", "transform", "flip",
                    "escala", "rotacao", "opacidade", "recorte"),
    "tempo": ("speed", "slow motion", "slowmo", "timelapse", "freeze", "reverse", "velocidad", "camera lenta"),
    "transicao": ("transition", "dissolve", "fade in", "fade out", "wipe", "transicion", "dip to black"),
    "camera": ("camera profile", "log", "input", "color space"),
    "pele": ("skin", "skin tone", "piel"),
    "alvo": ("eyedropper", "pick color", "secondary", "qualifier", "cuentagotas", "conta-gotas"),
    "degrade": ("gradient", "graduated", "sky", "ceiling", "degradado", "ceu", "chao"),
    "manivela": ("hand crank", "crank", "18fps", "16fps", "cadence"),
    "luz_copiadora": ("printer lights", "copier", "timing", "tape", "luz", "luces"),
    "som": ("volume", "audio", "sound", "gain", "pan", "fade", "balance", "sonido"),
    "eq": ("equalizer", "equalizar", "bass", "treble", "voice", "denoise", "noise", "eq", "graves", "agudos",
           "voz", "ruido", "highpass", "lowpass"),
}


def norm(text: str) -> str:
    """Minúsculas e sem acentos (como `ui.looks._norm`)."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


_WORD = re.compile(r"[a-z0-9]+")
_catalogs: dict[str, dict[str, str]] = {}


def _catalog(code: str) -> dict[str, str]:
    if code not in _catalogs:
        _catalogs[code] = i18n.load_catalog(code)
    return _catalogs[code]


def variants(text: str) -> list[str]:
    """O texto normalizado em cada idioma indexado (o original em português e as traduções)."""
    out = []
    for code in LANGS:
        t = text if code == i18n.SOURCE else _catalog(code).get(text, "")
        if t:
            n = norm(t)
            if n not in out:
                out.append(n)
    return out


@dataclass(frozen=True)
class Entry:
    """Texto pesquisável de um pedaço (a seção ou um controle): o texto junto e as palavras dele."""
    text: str
    words: frozenset[str]

    @staticmethod
    def of(*parts: str) -> Entry:
        text = " | ".join(p for p in parts if p)
        return Entry(text, frozenset(_WORD.findall(text)))


@dataclass
class SectionIndex:
    key: str
    section: Entry
    params: dict[str, Entry]


def _param_entry(p) -> Entry:
    parts: list[str] = []
    for text in (p.label, p.tip):
        if text:
            parts += variants(text)
    for _value, label in (p.choices or ()):
        parts += variants(label)
    parts.append(norm(p.key))
    parts.append(norm(p.key).replace("_", " "))
    return Entry.of(*parts)


def _section_entry(sec) -> Entry:
    parts: list[str] = []
    for text in (sec.title, sec.subtitle):
        if text:
            parts += variants(text)
    for word in KEYWORDS.get(sec.key, ()):
        parts.append(norm(word))
    toggle = next((p for p in sec.params if p.key == sec.toggle), None)
    if toggle is not None:  # a chave do liga/desliga não tem linha: o texto dela é da seção
        parts.append(_param_entry(toggle).text)
    return Entry.of(*parts)


def build_index(sections) -> list[SectionIndex]:
    """O índice de uma lista de `Section` (sem guardar nada)."""
    return [SectionIndex(sec.key, _section_entry(sec),
                         {p.key: _param_entry(p) for p in sec.params if p.key != sec.toggle})
            for sec in sections]


_cache: dict[int, tuple[list, list[SectionIndex]]] = {}


def index_of(sections) -> list[SectionIndex]:
    """O índice guardado de `sections` (montado no primeiro uso; a lista é guardada junto para o id valer)."""
    hit = _cache.get(id(sections))
    if hit is None or hit[0] is not sections:
        hit = (sections, build_index(sections))
        _cache[id(sections)] = hit
    return hit[1]


def clear_cache() -> None:
    """Esquece índices e catálogos (testes que trocam os catálogos)."""
    _cache.clear()
    _catalogs.clear()


def within_one(a: str, b: str) -> bool:
    """Distância de Levenshtein de no máximo 1 (troca, falta ou sobra de uma letra)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = 0
    while i < la and i < lb and a[i] == b[i]:
        i += 1
    if la == lb:
        return a[i + 1:] == b[i + 1:]
    if la < lb:
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i:]


MIN_FUZZY = 5  # palavras com menos letras só entram na busca exata


def _hit(term: str, entry: Entry, fuzzy: bool) -> bool:
    if term in entry.text:
        return True
    if not fuzzy or len(term) < MIN_FUZZY:
        return False
    n = len(term)
    for w in entry.words:
        if len(w) >= n - 1 and (within_one(term, w) or within_one(term, w[:n]) or within_one(term, w[:n - 1])
                                or within_one(term, w[:n + 1])):
            return True
    return False


@dataclass(frozen=True)
class Match:
    """Resultado de uma seção: `section` = a própria seção bateu em todas as palavras; `keys` = chaves dos controles
    que bateram (são os destacados; o cartão mostra as linhas todas nos dois casos)."""
    section: bool
    keys: frozenset[str]


def _search(terms: list[str], idx: list[SectionIndex], fuzzy: bool) -> dict[str, Match]:
    out: dict[str, Match] = {}
    for s in idx:
        keys: set[str] = set()
        whole = True
        ok = True
        for t in terms:
            hits = {k for k, e in s.params.items() if _hit(t, e, fuzzy)}
            if _hit(t, s.section, fuzzy):
                keys |= hits
                continue
            whole = False
            if not hits:
                ok = False
                break
            keys |= hits
        if ok:
            out[s.key] = Match(whole, frozenset(keys))
    return out


def search(query: str, sections) -> dict[str, Match]:
    """Seções (por chave) que combinam com `query`. Texto vazio = nada a filtrar (dicionário vazio).

    Primeiro a busca exata; só se ela não achar nada, a tolerante a um erro de digitação."""
    terms = norm(query).split()
    if not terms:
        return {}
    idx = index_of(sections)
    found = _search(terms, idx, False)
    if not found and any(len(t) >= MIN_FUZZY for t in terms):
        found = _search(terms, idx, True)
    return found


__all__ = ["KEYWORDS", "Match", "norm", "search", "index_of", "build_index", "within_one"]
