"""Leitura de arquivos de fonte TrueType (.ttf) sem Qt: métricas, mapa de caracteres e contornos.

O `textrender` usa o Qt só para o *shaping* (que glifo vai em que posição, com kerning e ligaduras)
e para preencher os contornos. Os contornos em si saem daqui, lidos direto da tabela `glyf` do
arquivo: o `QRawFont.pathForGlyph` do Qt depende do motor de fontes do sistema (DirectWrite no
Windows, FreeType no Linux e no modo *offscreen*), e os dois devolvem coordenadas ligeiramente
diferentes (a conversão das curvas quadráticas em cúbicas arredonda de outro jeito). Lendo o
arquivo, o mesmo glifo dá o mesmo contorno em qualquer sistema, até o último bit.

Só TrueType com contornos quadráticos (`glyf`), estático (sem `gvar`): é o formato de todas as
fontes que acompanham o app (`pelicula/data/fontes`). Glifos compostos (letras acentuadas montadas
a partir da base e do acento) são resolvidos com a transformação de cada componente.

`renamed()` devolve uma cópia do arquivo com outro nome de família (só na memória): é o que o
`textrender` registra no banco de fontes do Qt, para que uma fonte de mesmo nome instalada no
computador nunca seja usada no lugar da que vem com o app.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import cached_property

Point = tuple[float, float, bool]   # (x, y, sobre a curva) em unidades da fonte, y para cima
Contour = tuple[Point, ...]

# Bandeiras dos glifos simples
_ON_CURVE = 0x01
_X_SHORT = 0x02
_Y_SHORT = 0x04
_REPEAT = 0x08
_X_SAME = 0x10
_Y_SAME = 0x20
# Bandeiras dos componentes de um glifo composto
_ARG_WORDS = 0x0001
_ARGS_XY = 0x0002
_SCALE = 0x0008
_MORE = 0x0020
_XY_SCALE = 0x0040
_TWO_BY_TWO = 0x0080
_SCALED_OFFSET = 0x0800
_MAX_DEPTH = 8                     # componentes dentro de componentes (limite contra arquivo malformado)


class FontError(ValueError):
    """Arquivo de fonte que este leitor não entende (não TrueType, tabela faltando, malformado)."""


def _f2dot14(v: int) -> float:
    return (v - 65536 if v >= 32768 else v) / 16384.0


@dataclass(frozen=True)
class Metrics:
    units_per_em: int
    ascender: int          # unidades da fonte, positivo para cima
    descender: int         # negativo
    line_gap: int

    @property
    def line_height(self) -> int:
        return self.ascender - self.descender + self.line_gap


class FontFile:
    """Um arquivo .ttf na memória. Tudo é lido sob demanda e guardado (contornos por glifo)."""

    def __init__(self, data: bytes):
        self.data = bytes(data)
        if len(self.data) < 12:
            raise FontError("arquivo de fonte vazio ou curto demais")
        version, count = struct.unpack_from(">IH", self.data, 0)
        if version not in (0x00010000, 0x74727565):  # TrueType ("OTTO" = CFF, não suportado)
            raise FontError("só fontes TrueType (.ttf com contornos glyf) são suportadas")
        self.tables: dict[str, tuple[int, int]] = {}
        for i in range(count):
            tag, _sum, off, length = struct.unpack_from(">4sIII", self.data, 12 + 16 * i)
            if off + length > len(self.data):
                raise FontError(f"tabela {tag!r} passa do fim do arquivo")
            self.tables[tag.decode("latin-1")] = (off, length)
        for need in ("head", "hhea", "hmtx", "maxp", "loca", "glyf", "cmap"):
            if need not in self.tables:
                raise FontError(f"tabela {need} não encontrada")
        if "gvar" in self.tables:
            raise FontError("fontes variáveis não são suportadas: use as instâncias estáticas")
        self._outlines: dict[int, tuple[Contour, ...]] = {}

    # ------------------------------------------------------------ tabelas
    def table(self, tag: str) -> bytes:
        off, length = self.tables[tag]
        return self.data[off:off + length]

    @cached_property
    def units_per_em(self) -> int:
        return struct.unpack_from(">H", self.data, self.tables["head"][0] + 18)[0]

    @cached_property
    def num_glyphs(self) -> int:
        return struct.unpack_from(">H", self.data, self.tables["maxp"][0] + 4)[0]

    @cached_property
    def metrics(self) -> Metrics:
        off = self.tables["hhea"][0]
        asc, desc, gap = struct.unpack_from(">hhh", self.data, off + 4)
        return Metrics(self.units_per_em, asc, desc, gap)

    @cached_property
    def weight(self) -> int:
        """Peso do OS/2 (400 normal, 700 negrito, 900 black)."""
        if "OS/2" not in self.tables:
            return 700 if self._mac_style & 1 else 400
        return struct.unpack_from(">H", self.data, self.tables["OS/2"][0] + 4)[0]

    @cached_property
    def _mac_style(self) -> int:
        return struct.unpack_from(">H", self.data, self.tables["head"][0] + 44)[0]

    @cached_property
    def italic(self) -> bool:
        if "OS/2" in self.tables:
            sel = struct.unpack_from(">H", self.data, self.tables["OS/2"][0] + 62)[0]
            if sel & 0x01:
                return True
        return bool(self._mac_style & 2)

    @cached_property
    def _hmetrics(self) -> tuple[int, bytes]:
        n = struct.unpack_from(">H", self.data, self.tables["hhea"][0] + 34)[0]
        return n, self.table("hmtx")

    def advance(self, gid: int) -> int:
        """Avanço horizontal do glifo (unidades da fonte)."""
        n, hmtx = self._hmetrics
        i = min(max(0, gid), n - 1)
        return struct.unpack_from(">H", hmtx, 4 * i)[0]

    @cached_property
    def _loca(self) -> tuple[int, ...]:
        long_format = struct.unpack_from(">h", self.data, self.tables["head"][0] + 50)[0] == 1
        raw = self.table("loca")
        n = self.num_glyphs + 1
        if long_format:
            return struct.unpack_from(f">{n}I", raw, 0)
        return tuple(2 * v for v in struct.unpack_from(f">{n}H", raw, 0))

    # ------------------------------------------------------------ nomes
    @cached_property
    def names(self) -> dict[int, str]:
        """Nomes da tabela `name` (plataforma Windows, Unicode; senão Mac Roman), por nameID."""
        if "name" not in self.tables:
            return {}
        raw = self.table("name")
        _fmt, count, base = struct.unpack_from(">HHH", raw, 0)
        out: dict[int, str] = {}
        rank: dict[int, int] = {}
        for i in range(count):
            pid, eid, lang, nid, length, off = struct.unpack_from(">HHHHHH", raw, 6 + 12 * i)
            blob = raw[base + off: base + off + length]
            if pid == 3 and eid in (0, 1, 10):
                score, text = (2 if lang == 0x409 else 1), blob.decode("utf-16-be", "replace")
            elif pid == 1 and eid == 0:
                score, text = 0, blob.decode("mac_roman", "replace")
            else:
                continue
            if score > rank.get(nid, -1):
                out[nid], rank[nid] = text, score
        return out

    @property
    def family(self) -> str:
        return self.names.get(16) or self.names.get(1) or ""

    @property
    def subfamily(self) -> str:
        return self.names.get(17) or self.names.get(2) or "Regular"

    # ------------------------------------------------------------ caracteres
    @cached_property
    def cmap(self) -> dict[int, int]:
        """Código Unicode → glifo (subtabelas formato 4 e 12 da plataforma Unicode/Windows)."""
        raw = self.table("cmap")
        _ver, count = struct.unpack_from(">HH", raw, 0)
        subs = []
        for i in range(count):
            pid, eid, off = struct.unpack_from(">HHI", raw, 4 + 8 * i)
            fmt = struct.unpack_from(">H", raw, off)[0]
            if (pid == 3 and eid in (1, 10)) or pid == 0:
                subs.append(((fmt == 12) * 2 + (pid == 3), fmt, off))
        out: dict[int, int] = {}
        for _rank, fmt, off in sorted(subs):  # o melhor por último (sobrescreve)
            if fmt == 4:
                out.update(self._cmap4(raw, off))
            elif fmt == 12:
                out.update(self._cmap12(raw, off))
        return out

    @staticmethod
    def _cmap4(raw: bytes, off: int) -> dict[int, int]:
        seg2 = struct.unpack_from(">H", raw, off + 6)[0]
        n = seg2 // 2
        ends = struct.unpack_from(f">{n}H", raw, off + 14)
        starts = struct.unpack_from(f">{n}H", raw, off + 16 + seg2)
        deltas = struct.unpack_from(f">{n}h", raw, off + 16 + 2 * seg2)
        ro_off = off + 16 + 3 * seg2
        ranges = struct.unpack_from(f">{n}H", raw, ro_off)
        out = {}
        for i in range(n):
            for c in range(starts[i], ends[i] + 1):
                if c == 0xFFFF:
                    continue
                if ranges[i] == 0:
                    g = (c + deltas[i]) & 0xFFFF
                else:
                    pos = ro_off + 2 * i + ranges[i] + 2 * (c - starts[i])
                    g = struct.unpack_from(">H", raw, pos)[0]
                    if g:
                        g = (g + deltas[i]) & 0xFFFF
                if g:
                    out[c] = g
        return out

    @staticmethod
    def _cmap12(raw: bytes, off: int) -> dict[int, int]:
        n = struct.unpack_from(">I", raw, off + 12)[0]
        out = {}
        for i in range(n):
            a, b, g = struct.unpack_from(">III", raw, off + 16 + 12 * i)
            for c in range(a, min(b, a + 0x10000) + 1):
                out[c] = g + (c - a)
        return out

    def glyph_index(self, ch: str) -> int:
        """Glifo do caractere (0 = a fonte não tem)."""
        return self.cmap.get(ord(ch), 0)

    def missing(self, text: str) -> str:
        """Caracteres de `text` que a fonte não tem (espaços e quebras de linha não contam)."""
        seen = []
        for ch in text:
            if ch.isspace() or ch in seen:
                continue
            if not self.glyph_index(ch):
                seen.append(ch)
        return "".join(seen)

    # ------------------------------------------------------------ contornos
    def outline(self, gid: int) -> tuple[Contour, ...]:
        """Contornos do glifo em unidades da fonte (y para cima), como estão no arquivo."""
        hit = self._outlines.get(gid)
        if hit is None:
            hit = self._outline(gid, 0)
            self._outlines[gid] = hit
        return hit

    def _outline(self, gid: int, depth: int) -> tuple[Contour, ...]:
        if not 0 <= gid < self.num_glyphs or depth > _MAX_DEPTH:
            return ()
        loca = self._loca
        a, b = loca[gid], loca[gid + 1]
        if b <= a:
            return ()  # glifo vazio (espaço)
        base = self.tables["glyf"][0] + a
        n_contours = struct.unpack_from(">h", self.data, base)[0]
        if n_contours >= 0:
            return self._simple(base, n_contours)
        return self._composite(base + 10, depth)

    def _simple(self, base: int, n_contours: int) -> tuple[Contour, ...]:
        data = self.data
        p = base + 10
        ends = struct.unpack_from(f">{n_contours}H", data, p)
        p += 2 * n_contours
        n_instr = struct.unpack_from(">H", data, p)[0]
        p += 2 + n_instr
        n_points = (ends[-1] + 1) if ends else 0
        flags = []
        while len(flags) < n_points:
            f = data[p]
            p += 1
            flags.append(f)
            if f & _REPEAT:
                flags.extend([f] * data[p])
                p += 1
        flags = flags[:n_points]
        xs, ys = [], []
        for axis, short, same, out in ((0, _X_SHORT, _X_SAME, xs), (1, _Y_SHORT, _Y_SAME, ys)):
            v = 0
            for f in flags:
                if f & short:
                    d = data[p]
                    p += 1
                    v += d if f & same else -d
                elif not f & same:
                    v += struct.unpack_from(">h", data, p)[0]
                    p += 2
                out.append(v)
        contours = []
        start = 0
        for e in ends:
            contours.append(tuple((float(xs[i]), float(ys[i]), bool(flags[i] & _ON_CURVE))
                                  for i in range(start, e + 1)))
            start = e + 1
        return tuple(c for c in contours if c)

    def _composite(self, p: int, depth: int) -> tuple[Contour, ...]:
        data = self.data
        out: list[Contour] = []
        while True:
            flags, child = struct.unpack_from(">HH", data, p)
            p += 4
            if flags & _ARG_WORDS:
                fmt = ">hh" if flags & _ARGS_XY else ">HH"
                a1, a2 = struct.unpack_from(fmt, data, p)
                p += 4
            else:
                fmt = ">bb" if flags & _ARGS_XY else ">BB"
                a1, a2 = struct.unpack_from(fmt, data, p)
                p += 2
            xx, xy, yx, yy = 1.0, 0.0, 0.0, 1.0
            if flags & _SCALE:
                xx = yy = _f2dot14(struct.unpack_from(">H", data, p)[0])
                p += 2
            elif flags & _XY_SCALE:
                xx, yy = (_f2dot14(v) for v in struct.unpack_from(">HH", data, p))
                p += 4
            elif flags & _TWO_BY_TWO:
                xx, xy, yx, yy = (_f2dot14(v) for v in struct.unpack_from(">HHHH", data, p))
                p += 8
            parts = self._outline(child, depth + 1)
            moved = [tuple((xx * x + yx * y, xy * x + yy * y, on) for x, y, on in c) for c in parts]
            if flags & _ARGS_XY:
                dx, dy = float(a1), float(a2)
                if flags & _SCALED_OFFSET:
                    dx, dy = xx * dx + yx * dy, xy * dx + yy * dy
            else:  # pontos casados: o ponto a2 do componente vai para o ponto a1 do que já foi montado
                mine = [pt for c in out for pt in c]
                theirs = [pt for c in moved for pt in c]
                if a1 < len(mine) and a2 < len(theirs):
                    dx, dy = mine[a1][0] - theirs[a2][0], mine[a1][1] - theirs[a2][1]
                else:
                    dx = dy = 0.0
            out.extend(tuple((x + dx, y + dy, on) for x, y, on in c) for c in moved)
            if not flags & _MORE:
                break
        return tuple(out)

    # ------------------------------------------------------------ cópia com outro nome
    def renamed(self, family: str) -> bytes:
        """O mesmo arquivo com outro nome de família (nameID 1, 4, 6 e 16), para o banco de fontes do Qt.

        Só a tabela `name` muda; glifos, métricas e tabelas de *shaping* ficam iguais byte a byte. As
        somas de conferência das tabelas e o `checkSumAdjustment` do `head` são recalculados.
        """
        sub = self.subfamily
        ps = "".join(ch for ch in f"{family}-{sub}" if ch.isascii() and (ch.isalnum() or ch == "-"))[:63]
        records = {1: family, 2: sub, 4: f"{family} {sub}", 6: ps, 16: family, 17: sub}
        strings = b""
        recs = []
        for nid in sorted(records):
            blob = records[nid].encode("utf-16-be")
            recs.append(struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(blob), len(strings)))
            strings += blob
        name = struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs)) + b"".join(recs) + strings
        tables = {tag: self.table(tag) for tag in self.tables}
        tables["name"] = name
        return _build_sfnt(tables)


def _checksum(data: bytes) -> int:
    padded = data + b"\0" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF


def _build_sfnt(tables: dict[str, bytes]) -> bytes:
    tags = sorted(tables)
    n = len(tags)
    entry = 1 << (n.bit_length() - 1)
    search = entry * 16
    header = struct.pack(">IHHHH", 0x00010000, n, search, entry.bit_length() - 1, n * 16 - search)
    offset = 12 + 16 * n
    directory = b""
    body = b""
    head_at = None
    for tag in tags:
        data = tables[tag]
        if tag == "head":
            data = data[:8] + b"\0\0\0\0" + data[12:]  # checkSumAdjustment zerado antes da conta
            head_at = offset + len(body)
        directory += struct.pack(">4sIII", tag.encode("latin-1"), _checksum(data), offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    font = bytearray(header + directory + body)
    if head_at is not None:
        adjust = (0xB1B0AFBA - _checksum(bytes(font))) & 0xFFFFFFFF
        struct.pack_into(">I", font, head_at + 8, adjust)
    return bytes(font)
