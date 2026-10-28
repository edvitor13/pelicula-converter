"""Texto em imagem RGBA (títulos e legendas), igual em qualquer computador.

O que garante o mesmo resultado no Windows e no Linux, bit a bit:

- **Só as fontes que vêm com o app** (`pelicula/data/fontes`, SIL OFL, `FAMILIES`). Cada arquivo é
  registrado no banco de fontes do Qt com um nome de família único (`fontfile.FontFile.renamed`), e a
  fonte não mistura outras (`NoFontMerging`): uma fonte do sistema de mesmo nome nunca entra.
- **Shaping do Qt** (`QTextLayout`, HarfBuzz: kerning, ligaduras, acentos) feito no tamanho de 1 em =
  unidades da fonte, sem *hinting*: as posições saem em unidades inteiras da fonte e são arredondadas,
  então o motor de fontes do sistema (DirectWrite no Windows, FreeType no Linux) não muda nada.
- **Contornos lidos do arquivo** (`fontfile`, tabela `glyf`), não do motor de fontes do sistema (que
  arredonda as curvas de outro jeito), e preenchidos pelo rasterizador de caminhos do próprio Qt
  (`QPainter` num `QImage`, software, com antialiasing): uma passada por máscara, sobre fundo vazio.
- **Composição em numpy** (operações elemento a elemento em float32) e desfoque da sombra com somas
  inteiras: nada que dependa de ordem de soma, de SIMD ou de placa de vídeo.

Unidades: tamanhos e distâncias do estilo são **px@1080** (pixels de um quadro de 1080 linhas),
multiplicados por `altura / 1080`. Cores são códigos RGB 0–1 do vídeo (sRGB/Rec.709 já codificado), e
a imagem final é **RGBA com alfa direto (não pré-multiplicado)**, `uint8` (0–255) ou `uint16`
(0–65535); onde o alfa é 0 a cor também é 0. Linha 0 = topo (y para baixo, como os shaders).

Precisa de uma `QGuiApplication` (o banco de fontes do Qt): a janela já tem; o terminal e os testes
criam uma (`ensure_app`). Pode ser usado de threads de trabalho (QImage, QPainter e QTextLayout não
são widgets). Os resultados ficam guardados (`lru_cache`): o mesmo texto no mesmo estilo é
desenhado uma vez só; as matrizes devolvidas são só de leitura.
"""

from __future__ import annotations

import math
import os
import re
import sys
import threading
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import fontfile
from .i18n import N_

FONTS_DIR = Path(__file__).resolve().parent / "data" / "fontes"
SOURCE_FILE = FONTS_DIR / "SOURCE.txt"
REF_HEIGHT = 1080.0


# ------------------------------------------------------------------ catálogo de fontes
@dataclass(frozen=True)
class Face:
    file: str          # caminho dentro de data/fontes, com "/"
    weight: int        # 400 normal, 700 negrito, 900 black
    italic: bool = False


@dataclass(frozen=True)
class Family:
    id: str            # chave ASCII gravada nos projetos: nunca renomear
    name: str          # nome da família (é nome próprio: não se traduz)
    category: str      # chave de CATEGORIES
    faces: tuple[Face, ...]


CATEGORIES = {
    "sans": N_("Sem serifa"),
    "geometrica": N_("Geométrica"),
    "condensada": N_("Condensada"),
    "titulo": N_("Títulos"),
    "serifa": N_("Com serifa"),
    "maquina": N_("Máquina de escrever"),
    "manuscrita": N_("Manuscrita"),
}


def _faces(folder: str, *items: tuple[str, int, bool]) -> tuple[Face, ...]:
    return tuple(Face(f"{folder}/{name}", w, it) for name, w, it in items)


# Todas do Google Fonts (commit fixo em data/fontes/SOURCE.txt), SIL OFL 1.1. Família nova: arquivo
# estático .ttf (sem gvar), OFL.txt na pasta, linha no SOURCE.txt (SHA-256) e créditos no README.
FAMILIES: tuple[Family, ...] = (
    Family("atkinson", "Atkinson Hyperlegible", "sans", _faces(
        "atkinsonhyperlegible", ("AtkinsonHyperlegible-Regular.ttf", 400, False),
        ("AtkinsonHyperlegible-Italic.ttf", 400, True), ("AtkinsonHyperlegible-Bold.ttf", 700, False),
        ("AtkinsonHyperlegible-BoldItalic.ttf", 700, True))),
    Family("poppins", "Poppins", "geometrica", _faces(
        "poppins", ("Poppins-Regular.ttf", 400, False), ("Poppins-Italic.ttf", 400, True),
        ("Poppins-Bold.ttf", 700, False), ("Poppins-BoldItalic.ttf", 700, True), ("Poppins-Black.ttf", 900, False))),
    Family("barlow_condensada", "Barlow Condensed", "condensada", _faces(
        "barlowcondensed", ("BarlowCondensed-Regular.ttf", 400, False), ("BarlowCondensed-Bold.ttf", 700, False))),
    Family("bebas", "Bebas Neue", "titulo", _faces("bebasneue", ("BebasNeue-Regular.ttf", 400, False))),
    Family("anton", "Anton", "titulo", _faces("anton", ("Anton-Regular.ttf", 400, False))),
    Family("archivo_black", "Archivo Black", "titulo", _faces("archivoblack", ("ArchivoBlack-Regular.ttf", 900, False))),
    Family("dm_serif", "DM Serif Display", "serifa", _faces(
        "dmserifdisplay", ("DMSerifDisplay-Regular.ttf", 400, False), ("DMSerifDisplay-Italic.ttf", 400, True))),
    Family("crimson", "Crimson Text", "serifa", _faces(
        "crimsontext", ("CrimsonText-Regular.ttf", 400, False), ("CrimsonText-Italic.ttf", 400, True),
        ("CrimsonText-Bold.ttf", 700, False), ("CrimsonText-BoldItalic.ttf", 700, True))),
    Family("courier_prime", "Courier Prime", "maquina", _faces(
        "courierprime", ("CourierPrime-Regular.ttf", 400, False), ("CourierPrime-Italic.ttf", 400, True),
        ("CourierPrime-Bold.ttf", 700, False), ("CourierPrime-BoldItalic.ttf", 700, True))),
    Family("patrick_hand", "Patrick Hand", "manuscrita", _faces("patrickhand", ("PatrickHand-Regular.ttf", 400, False))),
    Family("pacifico", "Pacifico", "manuscrita", _faces("pacifico", ("Pacifico-Regular.ttf", 400, False))),
)
DEFAULT_FAMILY = "atkinson"
_BY_ID = {f.id: f for f in FAMILIES}


def family(family_id: str) -> Family:
    """A família pelo id; id desconhecido (projeto de uma versão mais nova) cai na padrão."""
    return _BY_ID.get(family_id) or _BY_ID[DEFAULT_FAMILY]


def face_for(family_id: str, weight: int = 400, italic: bool = False) -> Face:
    """O arquivo mais próximo do pedido: itálico se houver, depois o peso mais perto (empate: o mais pesado)."""
    fam = family(family_id)
    same = [f for f in fam.faces if f.italic == italic] or list(fam.faces)
    return min(same, key=lambda f: (abs(f.weight - weight), -f.weight))


def source_manifest() -> dict[str, str]:
    """`SOURCE.txt` → {caminho: sha256} de cada arquivo de fonte e licença."""
    out = {}
    for line in SOURCE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            digest, _sep, path = line.partition("  ")
            out[path] = digest
    return out


@lru_cache(maxsize=None)
def font_file(face: Face) -> fontfile.FontFile:
    return fontfile.FontFile((FONTS_DIR / face.file).read_bytes())


def missing_chars(text: str, family_id: str, weight: int = 400, italic: bool = False) -> str:
    """Caracteres do texto que a fonte não tem (aparecem como um retângulo): para avisar na interface."""
    return font_file(face_for(family_id, weight, italic)).missing(unicodedata.normalize("NFC", text))


# ------------------------------------------------------------------ estilo
Color = tuple[float, float, float]
ALIGNS = ("esquerda", "centro", "direita")
BOX_MODES = ("linha", "bloco")


def parse_color(value: Any, default: Color = (1.0, 1.0, 1.0)) -> Color:
    """"#rrggbb", "#rgb" ou [r, g, b] (0–1) → (r, g, b) 0–1."""
    if isinstance(value, str):
        m = re.fullmatch(r"#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})", value.strip())
        if not m:
            return default
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    try:
        r, g, b = (float(v) for v in list(value)[:3])
    except (TypeError, ValueError):
        return default
    if not all(math.isfinite(v) for v in (r, g, b)):
        return default
    return (min(max(r, 0.0), 1.0), min(max(g, 0.0), 1.0), min(max(b, 0.0), 1.0))


def color_hex(c: Color) -> str:
    return "#" + "".join(f"{int(round(min(max(v, 0.0), 1.0) * 255)):02x}" for v in c)


# (atributo, chave JSON, mínimo, máximo) dos números; cores e escolhas têm tratamento próprio.
_NUMS = (("weight", "peso", 100, 900), ("size", "tamanho", 4.0, 600.0), ("opacity", "opacidade", 0.0, 1.0),
         ("line_spacing", "entrelinha", 0.5, 3.0), ("letter_spacing", "espacamento", -20.0, 100.0),
         ("wrap", "largura", 0.0, 8000.0), ("outline", "contorno", 0.0, 40.0),
         ("shadow", "sombra", 0.0, 1.0), ("shadow_x", "sombra_x", -100.0, 100.0),
         ("shadow_y", "sombra_y", -100.0, 100.0), ("shadow_blur", "sombra_desfoque", 0.0, 100.0),
         ("box", "caixa", 0.0, 1.0), ("box_padding", "caixa_margem", 0.0, 200.0),
         ("box_radius", "caixa_raio", 0.0, 200.0))
_COLORS = (("color", "cor"), ("outline_color", "cor_contorno"), ("shadow_color", "cor_sombra"),
           ("box_color", "cor_caixa"))


@dataclass(frozen=True)
class TextStyle:
    """Aparência do texto. Distâncias em px@1080; o padrão é texto branco simples, sem efeitos."""
    family: str = DEFAULT_FAMILY
    weight: int = 400
    italic: bool = False
    size: float = 54.0                  # tamanho do "em" (px@1080)
    color: Color = (1.0, 1.0, 1.0)
    opacity: float = 1.0                # texto, contorno e sombra
    align: str = "centro"
    line_spacing: float = 1.0           # × a altura de linha da fonte
    letter_spacing: float = 0.0         # px@1080 entre letras
    wrap: float = 0.0                   # largura máxima da linha (px@1080; 0 = sem quebra automática)
    uppercase: bool = False
    outline: float = 0.0                # espessura do contorno (px@1080; 0 = sem)
    outline_color: Color = (0.0, 0.0, 0.0)
    shadow: float = 0.0                 # opacidade da sombra (0 = sem)
    shadow_x: float = 0.0
    shadow_y: float = 3.0
    shadow_blur: float = 4.0
    shadow_color: Color = (0.0, 0.0, 0.0)
    box: float = 0.0                    # opacidade da caixa de fundo (0 = sem)
    box_color: Color = (0.0, 0.0, 0.0)
    box_padding: float = 10.0
    box_radius: float = 6.0
    box_mode: str = "linha"             # "linha" (uma caixa por linha) ou "bloco" (uma para o texto todo)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"fonte": self.family, "italico": self.italic, "alinhamento": self.align,
                               "maiusculas": self.uppercase, "caixa_modo": self.box_mode}
        for attr, key, _lo, _hi in _NUMS:
            v = getattr(self, attr)
            out[key] = int(v) if attr == "weight" else round(float(v), 4)
        for attr, key in _COLORS:
            out[key] = color_hex(getattr(self, attr))
        return out

    @classmethod
    def from_json(cls, d: Any) -> "TextStyle":
        """Do JSON do projeto, com cada valor conferido (o que faltar ou vier errado fica no padrão)."""
        d = d if isinstance(d, dict) else {}
        base = cls()
        kw: dict[str, Any] = {}
        fam = d.get("fonte")
        kw["family"] = fam if isinstance(fam, str) and fam in _BY_ID else base.family
        for attr, key, lo, hi in _NUMS:
            default = getattr(base, attr)
            try:
                v = float(d.get(key, default))
                v = v if math.isfinite(v) else float(default)
            except (TypeError, ValueError):
                v = float(default)
            v = min(max(v, lo), hi)
            kw[attr] = int(round(v)) if attr == "weight" else v
        for attr, key in _COLORS:
            kw[attr] = parse_color(d.get(key), getattr(base, attr))
        kw["italic"] = d.get("italico") is True
        kw["uppercase"] = d.get("maiusculas") is True
        kw["align"] = d.get("alinhamento") if d.get("alinhamento") in ALIGNS else base.align
        kw["box_mode"] = d.get("caixa_modo") if d.get("caixa_modo") in BOX_MODES else base.box_mode
        return cls(**kw)

    def sanitized(self) -> "TextStyle":
        return TextStyle.from_json(self.to_json())


@dataclass(frozen=True)
class WordOverride:
    """Mudança numa palavra (destaque palavra por palavra): cor do preenchimento, escala (em volta do centro
    da palavra, sem mexer na posição das outras) e uma caixa de destaque atrás dela."""
    color: Color | None = None
    scale: float = 1.0
    box_color: Color | None = None   # caixa só atrás desta palavra (com a margem e o raio do estilo)
    box_opacity: float = 1.0


Overrides = tuple[tuple[int, WordOverride], ...]


def _overrides(value: dict[int, WordOverride] | Iterable[tuple[int, WordOverride]] | None) -> Overrides:
    if not value:
        return ()
    items = value.items() if isinstance(value, dict) else value
    return tuple(sorted((int(i), o) for i, o in items if isinstance(o, WordOverride)))


# ------------------------------------------------------------------ Qt: aplicação e banco de fontes
_APP = None
_reg_lock = threading.Lock()


def ensure_app():
    """A `QGuiApplication` que o banco de fontes do Qt precisa; cria uma sem janela se não houver (só na
    thread principal: terminal e scripts). A janela do app já tem a sua."""
    global _APP
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("textrender: crie a QGuiApplication na thread principal antes de desenhar texto")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _APP = app = QGuiApplication([sys.argv[0] if sys.argv else "pelicula"])
    return app


def _require_app() -> None:
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        raise RuntimeError("textrender precisa de uma QGuiApplication (veja textrender.ensure_app)")


def _family_name(face: Face) -> str:
    stem = face.file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return "PeliculaTexto " + re.sub(r"[^A-Za-z0-9]", "", stem)


@lru_cache(maxsize=None)
def _registered(face: Face) -> str:
    """Registra a cópia renomeada da fonte no banco do Qt (uma vez) e devolve o nome da família."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QFontDatabase
    _require_app()
    name = _family_name(face)
    with _reg_lock:
        fid = QFontDatabase.addApplicationFontFromData(QByteArray(font_file(face).renamed(name)))
        if fid < 0 or name not in QFontDatabase.applicationFontFamilies(fid):
            raise RuntimeError(f"textrender: o Qt não carregou a fonte {face.file}")
    return name


_tls = threading.local()  # QFont por thread (o Qt guarda os motores de fonte por thread)


def _qfont(face: Face):
    cache = getattr(_tls, "fonts", None)
    if cache is None:
        cache = _tls.fonts = {}
    qf = cache.get(face)
    if qf is None:
        from PySide6.QtGui import QFont, QFontDatabase
        name = _registered(face)
        styles = QFontDatabase.styles(name)
        qf = QFontDatabase.font(name, styles[0] if styles else "", 12)
        qf.setPixelSize(font_file(face).units_per_em)   # 1 em = unidades da fonte: posições inteiras
        qf.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        qf.setStyleStrategy(QFont.StyleStrategy(QFont.StyleStrategy.NoFontMerging | QFont.StyleStrategy.PreferOutline))
        qf.setKerning(True)
        cache[face] = qf
    return qf


@dataclass(frozen=True)
class Shaped:
    """Uma palavra moldada: glifos e posições em unidades da fonte (inteiras), largura do avanço."""
    glyphs: tuple[int, ...]
    xs: tuple[int, ...]
    ys: tuple[int, ...]     # deslocamento vertical (acentos combinados), y para baixo
    advance: int


@lru_cache(maxsize=8192)
def shape(face: Face, word: str) -> Shaped:
    """Shaping de uma palavra (sem espaços) pelo Qt/HarfBuzz no tamanho de 1 em = unidades da fonte."""
    if not word:
        return Shaped((), (), (), 0)
    from PySide6.QtGui import QTextLayout, QTextOption
    name = _registered(face)
    lay = QTextLayout(word, _qfont(face))
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.NoWrap)
    opt.setUseDesignMetrics(True)
    lay.setTextOption(opt)
    lay.beginLayout()
    line = lay.createLine()
    lay.endLayout()
    asc = line.ascent()
    gl: list[int] = []
    xs: list[int] = []
    ys: list[int] = []
    for run in lay.glyphRuns():
        if run.rawFont().familyName() != name:
            raise RuntimeError(f"textrender: o Qt usou outra fonte ({run.rawFont().familyName()}) no lugar de {name}")
        for g, p in zip(run.glyphIndexes(), run.positions()):
            gl.append(int(g))
            xs.append(int(round(p.x())))
            ys.append(int(round(p.y() - asc)))
    return Shaped(tuple(gl), tuple(xs), tuple(ys), int(round(line.naturalTextWidth())))


# ------------------------------------------------------------------ layout (medidas)
@dataclass(frozen=True)
class WordBox:
    index: int          # posição da palavra no texto (conta todas as linhas), usada nos destaques
    text: str
    line: int
    x: float            # caixa lógica (avanço × altura da linha), px no espaço do bloco
    y: float
    w: float
    h: float
    baseline: float


@dataclass(frozen=True)
class LineBox:
    index: int
    x: float
    y: float
    w: float
    h: float
    baseline: float
    words: tuple[int, ...]


@dataclass(frozen=True)
class Layout:
    """Medidas do texto em pixels do quadro de saída, com origem no canto de cima à esquerda do bloco.

    `width`/`height`: o bloco lógico (a linha mais larga × as linhas); `ink`: a área que tem tinta
    (x0, y0, x1, y1), sem contorno, sombra nem caixa.
    """
    scale: float                  # px por px@1080 (altura / 1080)
    width: float
    height: float
    lines: tuple[LineBox, ...]
    words: tuple[WordBox, ...]
    ink: tuple[float, float, float, float]
    face: Face
    em: float                     # px por unidade da fonte
    ascender: float               # px
    descender: float              # px (negativo)


_SPACE = re.compile(r"[ \t  -​　]+")


def words_of(text: str) -> list[list[str]]:
    """Parágrafos (quebras de linha do texto) → palavras (separadas por espaços)."""
    text = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [[w for w in _SPACE.split(par) if w] for par in text.split("\n")]


@lru_cache(maxsize=None)
def _glyph_bbox(face: Face, gid: int) -> tuple[float, float, float, float] | None:
    pts = [(x, y) for c in font_file(face).outline(gid) for x, y, _on in c]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


@lru_cache(maxsize=512)
def layout(text: str, style: TextStyle, height: int) -> Layout:
    """Posição de cada linha e palavra (quebra automática na largura `style.wrap`, alinhamento)."""
    _require_app()
    scale = max(1, int(height)) / REF_HEIGHT
    face = face_for(style.family, style.weight, style.italic)
    ff = font_file(face)
    m = ff.metrics
    em = style.size * scale / m.units_per_em
    track = style.letter_spacing * scale
    space = ff.advance(ff.glyph_index(" ")) * em + track
    natural = m.line_height * em
    line_h = natural * style.line_spacing
    lead = (line_h - (m.ascender - m.descender) * em) / 2.0
    max_w = style.wrap * scale
    paragraphs = words_of(text.upper() if style.uppercase else text)

    def width_of(word: str) -> float:
        sh = shape(face, word)
        return sh.advance * em + track * max(0, len(sh.glyphs) - 1)

    rows: list[list[tuple[str, float]]] = []
    for par in paragraphs:
        row: list[tuple[str, float]] = []
        used = 0.0
        for w in par:
            ww = width_of(w)
            need = ww if not row else used + space + ww
            if row and max_w > 0 and need > max_w + 1e-9:
                rows.append(row)
                row, used = [(w, ww)], ww
            else:
                row.append((w, ww))
                used = need
        rows.append(row)
    widths = [sum(ww for _w, ww in r) + space * max(0, len(r) - 1) for r in rows]
    block_w = max(widths, default=0.0)
    k = {"esquerda": 0.0, "centro": 0.5, "direita": 1.0}.get(style.align, 0.5)
    lines: list[LineBox] = []
    words: list[WordBox] = []
    ink = [math.inf, math.inf, -math.inf, -math.inf]
    idx = 0
    for li, (row, lw) in enumerate(zip(rows, widths)):
        top = li * line_h
        base = top + lead + m.ascender * em
        x = (block_w - lw) * k
        mine = []
        for w, ww in row:
            words.append(WordBox(idx, w, li, x, top, ww, line_h, base))
            sh = shape(face, w)
            for i, (g, gx, gy) in enumerate(zip(sh.glyphs, sh.xs, sh.ys)):
                bb = _glyph_bbox(face, g)
                if bb is None:
                    continue
                ox, oy = x + gx * em + track * i, base + gy * em
                ink[0] = min(ink[0], ox + bb[0] * em)
                ink[2] = max(ink[2], ox + bb[2] * em)
                ink[1] = min(ink[1], oy - bb[3] * em)
                ink[3] = max(ink[3], oy - bb[1] * em)
            mine.append(idx)
            idx += 1
            x += ww + space
        lines.append(LineBox(li, (block_w - lw) * k, top, lw, line_h, base, tuple(mine)))
    if not math.isfinite(ink[0]):
        ink = [0.0, 0.0, 0.0, 0.0]
    return Layout(scale, block_w, line_h * len(rows), tuple(lines), tuple(words), tuple(ink), face, em,
                  m.ascender * em, m.descender * em)


# ------------------------------------------------------------------ desenho
@dataclass(frozen=True)
class TextImage:
    """O texto desenhado: `rgba` (altura × largura × 4, alfa direto, só leitura) e onde o canto de cima à
    esquerda da imagem fica no espaço do bloco (`left`, `top`, inteiros; podem ser negativos por causa do
    contorno, da sombra e da caixa). Para pôr o bloco em (bx, by) no quadro, a imagem vai em
    (bx + left, by + top) — com `bx`, `by` inteiros; a fração vai em `render(..., offset=)`."""
    rgba: np.ndarray
    left: int
    top: int
    layout: Layout

    @property
    def width(self) -> int:
        return int(self.rgba.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgba.shape[0])


def _glyph_path(path, face: Face, gid: int, ox: float, oy: float, em: float, sx: float = 1.0,
                cx: float = 0.0, cy: float = 0.0) -> None:
    """Acrescenta ao QPainterPath o contorno TrueType (quadrático) do glifo com origem em (ox, oy), y para
    baixo; `sx` escala em volta de (cx, cy)."""
    def tr(x: float, y: float) -> tuple[float, float]:
        px, py = ox + x * em, oy - y * em
        if sx != 1.0:
            px, py = cx + (px - cx) * sx, cy + (py - cy) * sx
        return px, py

    for contour in font_file(face).outline(gid):
        pts = list(contour)
        n = len(pts)
        if n < 2:
            continue
        first_on = next((i for i, p in enumerate(pts) if p[2]), None)
        if first_on is None:  # só pontos de controle: começa no meio do primeiro par
            a, b = pts[-1], pts[0]
            pts = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, True)] + pts
        else:
            pts = pts[first_on:] + pts[:first_on]
        start = pts[0]
        path.moveTo(*tr(start[0], start[1]))
        ctrl = None
        for x, y, on in pts[1:] + [start]:
            if on:
                if ctrl is None:
                    path.lineTo(*tr(x, y))
                else:
                    path.quadTo(*tr(*ctrl), *tr(x, y))
                    ctrl = None
            else:
                if ctrl is not None:  # dois controles seguidos: ponto implícito no meio
                    mx, my = (ctrl[0] + x) / 2, (ctrl[1] + y) / 2
                    path.quadTo(*tr(*ctrl), *tr(mx, my))
                ctrl = (x, y)
        path.closeSubpath()


def _raster(path, w: int, h: int) -> np.ndarray:
    """Cobertura (0–255) de um caminho preenchido (regra de enrolamento), num fundo vazio."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    if not path.isEmpty():
        path.setFillRule(Qt.FillRule.WindingFill)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillPath(path, QColor(255, 255, 255, 255))
        p.end()
    bpl = img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)[:, : w * 4]
    alpha = 3 if sys.byteorder == "little" else 0
    return np.ascontiguousarray(arr[:, alpha::4])


def _box_sizes(sigma: float, n: int = 3) -> list[int]:
    """Larguras ímpares de n caixas cujo desfoque somado se aproxima de uma gaussiana de desvio `sigma`."""
    ideal = math.sqrt(12.0 * sigma * sigma / n + 1.0)
    lo = int(math.floor(ideal))
    lo -= (lo % 2 == 0)
    hi = lo + 2
    m = round((12.0 * sigma * sigma - n * lo * lo - 4 * n * lo - 3 * n) / (-4 * lo - 4))
    return [lo if i < m else hi for i in range(n)]


def _box_blur(a: np.ndarray, size: int, axis: int) -> np.ndarray:
    """Média móvel inteira (com arredondamento) de largura ímpar `size` ao longo de `axis`; bordas em zero."""
    if size <= 1:
        return a
    r = size // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a.astype(np.int64), pad), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, np.arange(size, size + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo + size // 2) // size


def _blur(mask: np.ndarray, sigma: float) -> np.ndarray:
    if sigma < 0.3:
        return mask
    out = mask.astype(np.int64)
    for s in _box_sizes(sigma):
        out = _box_blur(out, s, 1)
        out = _box_blur(out, s, 0)
    return np.clip(out, 0, 255).astype(np.uint8)


def _shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    out = np.zeros_like(mask)
    h, w = mask.shape
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    if abs(dx) < w and abs(dy) < h:
        out[yd, xd] = mask[ys, xs]
    return out


def _over(dst: np.ndarray, mask: np.ndarray, color: Color, alpha: float) -> None:
    """dst (pré-multiplicado, float32) ← camada de cor sólida com cobertura `mask` por cima."""
    if alpha <= 0:
        return
    a = mask.astype(np.float32) * np.float32(alpha / 255.0)
    keep = np.float32(1.0) - a
    for c in range(3):
        dst[..., c] = a * np.float32(color[c]) + dst[..., c] * keep
    dst[..., 3] = a + dst[..., 3] * keep


def _rounded(path, x0: float, y0: float, x1: float, y1: float, radius: float) -> None:
    from PySide6.QtCore import QRectF
    r = max(0.0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    path.addRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), r, r)


@lru_cache(maxsize=256)
def _render(text: str, style: TextStyle, height: int, overrides: Overrides, depth: int,
            offset: tuple[float, float]) -> TextImage:
    from PySide6.QtGui import QPainterPath, QPainterPathStroker
    from PySide6.QtCore import Qt
    lay = layout(text, style, height)
    face, em, s = lay.face, lay.em, lay.scale
    ox, oy = offset
    over = dict(overrides)
    pad = style.box_padding * s
    outline = style.outline * s
    track = style.letter_spacing * s
    asc, desc = lay.ascender, lay.descender

    # Geometria de cada palavra (com a escala do destaque em volta do centro da palavra).
    groups: dict[tuple, list[WordBox]] = {}
    for wb in lay.words:
        o = over.get(wb.index)
        col = o.color if o is not None and o.color is not None else style.color
        groups.setdefault(col, []).append(wb)

    def word_path(path, wb: WordBox) -> None:
        o = over.get(wb.index)
        sx = o.scale if o is not None else 1.0
        sx = min(max(float(sx), 0.1), 4.0)
        cx, cy = ox + wb.x + wb.w / 2, oy + wb.baseline - (asc + desc) / 2
        sh = shape(face, wb.text)
        for i, (g, gx, gy) in enumerate(zip(sh.glyphs, sh.xs, sh.ys)):
            _glyph_path(path, face, g, ox + wb.x + gx * em + track * i, oy + wb.baseline + gy * em, em, sx, cx, cy)

    def box_rect(x0: float, x1: float, base: float) -> tuple[float, float, float, float]:
        return ox + x0 - pad, oy + base - asc - pad, ox + x1 + pad, oy + base - desc + pad

    boxes: list[tuple[float, float, float, float]] = []
    if style.box > 0:
        full = [ln for ln in lay.lines if ln.words]
        if style.box_mode == "bloco" and full:
            bx0, bx1 = min(ln.x for ln in full), max(ln.x + ln.w for ln in full)
            boxes.append((ox + bx0 - pad, oy + lay.lines[0].baseline - asc - pad, ox + bx1 + pad,
                          oy + lay.lines[-1].baseline - desc + pad))
        else:
            boxes += [box_rect(ln.x, ln.x + ln.w, ln.baseline) for ln in full]
    word_boxes: dict[tuple[Color, float], list] = {}
    for wb in lay.words:
        o = over.get(wb.index)
        if o is not None and o.box_color is not None and o.box_opacity > 0:
            sx = min(max(float(o.scale), 0.1), 4.0)
            x0, y0, x1, y1 = box_rect(wb.x, wb.x + wb.w, wb.baseline)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            word_boxes.setdefault((o.box_color, float(o.box_opacity)), []).append(
                (cx + (x0 - cx) * sx, cy + (y0 - cy) * sx, cx + (x1 - cx) * sx, cy + (y1 - cy) * sx))

    # Tamanho da imagem: tinta (com a maior escala de destaque) + contorno + sombra + caixas.
    grow = max([1.0] + [min(max(float(o.scale), 0.1), 4.0) for _i, o in overrides])
    ix0, iy0, ix1, iy1 = lay.ink
    if lay.words:
        cxm, cym = (ix0 + ix1) / 2, (iy0 + iy1) / 2
        hw, hh = (ix1 - ix0) / 2 * grow + lay.ascender * (grow - 1), (iy1 - iy0) / 2 * grow + lay.ascender * (grow - 1)
        ix0, ix1, iy0, iy1 = cxm - hw, cxm + hw, cym - hh, cym + hh
    margin = outline + 2.0
    x0, y0, x1, y1 = ox + ix0 - margin, oy + iy0 - margin, ox + ix1 + margin, oy + iy1 + margin
    if style.shadow > 0:
        blur = style.shadow_blur * s * 1.5 + 2
        sxp, syp = style.shadow_x * s, style.shadow_y * s
        x0, y0 = min(x0, x0 + sxp - blur), min(y0, y0 + syp - blur)
        x1, y1 = max(x1, x1 + sxp + blur), max(y1, y1 + syp + blur)
    for bx0, by0, bx1, by1 in boxes + [b for v in word_boxes.values() for b in v]:
        x0, y0, x1, y1 = min(x0, bx0 - 1), min(y0, by0 - 1), max(x1, bx1 + 1), max(y1, by1 + 1)
    left, top = int(math.floor(x0)), int(math.floor(y0))
    w, h = max(1, int(math.ceil(x1)) - left), max(1, int(math.ceil(y1)) - top)
    if w * h > 64_000_000:
        raise ValueError("textrender: texto grande demais para desenhar")

    def local(path):
        path.translate(-left, -top)
        return path

    premult = np.zeros((h, w, 4), np.float32)
    if boxes:
        bp = QPainterPath()
        for b in boxes:
            _rounded(bp, *b, style.box_radius * s)
        _over(premult, _raster(local(bp), w, h), style.box_color, style.box)
    for (col, alpha), rects in word_boxes.items():
        bp = QPainterPath()
        for b in rects:
            _rounded(bp, *b, style.box_radius * s)
        _over(premult, _raster(local(bp), w, h), col, alpha)

    fills = []
    whole = QPainterPath()
    for col, wbs in groups.items():
        p = QPainterPath()
        for wb in wbs:
            word_path(p, wb)
        whole.addPath(p)
        fills.append((col, _raster(local(p), w, h)))
    whole = local(whole)
    text_mask = np.zeros((h, w), np.uint8)
    for _col, mk in fills:
        text_mask = np.maximum(text_mask, mk)
    shape_mask = text_mask
    if outline > 0 and not whole.isEmpty():
        st = QPainterPathStroker()
        st.setWidth(2 * outline)
        st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        st.setCapStyle(Qt.PenCapStyle.RoundCap)
        shape_mask = np.maximum(_raster(st.createStroke(whole), w, h), text_mask)
    if style.shadow > 0:
        sh = _shift(shape_mask, int(round(style.shadow_x * s)), int(round(style.shadow_y * s)))
        sh = _blur(sh, style.shadow_blur * s / 2.0)
        _over(premult, sh, style.shadow_color, style.shadow * style.opacity)
    # Texto (contorno por baixo, preenchimento por cima) montado opaco e depois com a opacidade do estilo.
    txt = np.zeros((h, w, 4), np.float32)
    if outline > 0:
        _over(txt, shape_mask, style.outline_color, 1.0)
    for col, mk in fills:
        _over(txt, mk, col, 1.0)
    if style.opacity < 1.0:
        txt *= np.float32(style.opacity)
    keep = np.float32(1.0) - txt[..., 3:4]
    premult = txt + premult * keep

    a = premult[..., 3]
    rgb = np.zeros((h, w, 3), np.float32)
    nz = a > 0
    rgb[nz] = premult[..., :3][nz] / a[nz][:, None]
    out = np.concatenate([np.clip(rgb, 0, 1), np.clip(a, 0, 1)[..., None]], axis=2)
    peak = 65535.0 if depth == 16 else 255.0
    arr = np.round(out * np.float32(peak)).astype(np.uint16 if depth == 16 else np.uint8)
    arr[~nz] = 0
    arr.flags.writeable = False
    return TextImage(arr, left, top, lay)


def render(text: str, style: TextStyle | None = None, height: int = 1080, *,
           overrides: dict[int, WordOverride] | Iterable[tuple[int, WordOverride]] | None = None,
           depth: int = 8, offset: tuple[float, float] = (0.0, 0.0)) -> TextImage:
    """Desenha o texto para um quadro de `height` linhas (distâncias do estilo em px@1080).

    `overrides`: {índice da palavra: WordOverride} (destaque palavra por palavra; o índice conta as
    palavras do texto todo, como em `Layout.words`). `depth`: 8 (uint8) ou 16 (uint16). `offset`: fração
    de pixel (0–1) para posicionar o bloco fora da grade de pixels. Mesmo pedido → mesma imagem.
    """
    st = (style or TextStyle()).sanitized()
    fx = float(offset[0]) % 1.0
    fy = float(offset[1]) % 1.0
    return _render(str(text or ""), st, max(1, int(height)), _overrides(overrides), 16 if depth == 16 else 8,
                   (round(fx, 4), round(fy, 4)))


def measure(text: str, style: TextStyle | None = None, height: int = 1080) -> Layout:
    """Só as medidas (linhas, palavras, tinta), sem desenhar."""
    return layout(str(text or ""), (style or TextStyle()).sanitized(), max(1, int(height)))


def paste(dst: np.ndarray, img: TextImage, x: int, y: int) -> None:
    """Põe a imagem do texto por cima de `dst` (RGBA alfa direto, mesma profundidade) com o canto do bloco em
    (x, y) inteiros. Composição "por cima" em float32; o que sai do quadro é cortado."""
    h, w = dst.shape[:2]
    ax, ay = x + img.left, y + img.top
    x0, y0, x1, y1 = max(0, ax), max(0, ay), min(w, ax + img.width), min(h, ay + img.height)
    if x0 >= x1 or y0 >= y1:
        return
    peak = np.float32(65535.0 if dst.dtype == np.uint16 else 255.0)
    src = img.rgba[y0 - ay:y1 - ay, x0 - ax:x1 - ax].astype(np.float32) / peak
    if img.rgba.dtype != dst.dtype:
        src = np.round(src * peak) / peak
    cur = dst[y0:y1, x0:x1].astype(np.float32) / peak
    sa, da = src[..., 3:4], cur[..., 3:4]
    oa = sa + da * (np.float32(1.0) - sa)
    num = src[..., :3] * sa + cur[..., :3] * da * (np.float32(1.0) - sa)
    rgb = np.where(oa > 0, num / np.where(oa > 0, oa, np.float32(1.0)), np.float32(0.0))
    res = np.concatenate([rgb, oa], axis=2)
    res[oa[..., 0] <= 0] = 0
    dst[y0:y1, x0:x1] = np.round(np.clip(res, 0, 1) * peak).astype(dst.dtype)


def credits() -> list[tuple[str, str]]:
    """(família, licença) de cada fonte que acompanha o app, para a tela Sobre e o README."""
    return [(f.name, "SIL Open Font License 1.1") for f in FAMILIES]
