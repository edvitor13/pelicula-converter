"""Plugin do PeliculaConverter para o DaVinci Resolve: pacote de DCTLs e LUTs.

O pacote tem quatro nós; na árvore do Resolve vão em série, como LOOK → LAB → PRINT:

- **PeliculaConverter Laboratorio** (só cor, o nó "à la SumerFade"): perfil de entrada (espaço de
  cor + curva), exposição e balanço e o laboratório inteiro — negativo, revelação, separação de cores
  (Hue Split), luzes da copiadora, densidades por cor, pé e rolagens, saturações, pele, bleach bypass,
  curvas neutras e cópia —, com "Mostrar curva" para ver as curvas R, G e B por cima da imagem.
- **PeliculaConverter Cor** (só cor): tudo do Laboratório mais o look paramétrico (curva, tons, P&B),
  a cópia paramétrica (2383/2393/3513) e o envelhecimento. Use um dos dois (Laboratório OU Cor).
  É a mesma matemática de `shaders.COMMON` (os testes comparam com `Engine.bake_lut`).
- **PeliculaConverter Textura**: grão (o mesmo ruído PCG + Box–Muller + B-spline do app),
  halação, bloom e névoa (amostragem esparsa numa passada), maciez/nitidez, aberração,
  distorção e vinheta.
- **PeliculaConverter Projetor**: tremor do quadro, cintilação, clarões, cor instável, emendas,
  vazamento de luz, poeira, riscos, fio de cabelo, manchas, marcas de rolo e moldura.

O código dos kernels é escrito uma vez num dialeto comum (C de DCTL com macros) e gerado em
dois sabores: `dctl` (o arquivo que vai para o Resolve) e `glsl` (usado nos testes para rodar o
mesmo kernel na GPU com o moderngl e comparar com o app). Todas as tabelas (gamuts, cópias,
bitolas, filtros, viragens, laboratório) saem das tabelas de `look.py`: o plugin não tem como
"desviar" do app.

Regras do DCTL seguidas aqui (README do Resolve): `DEFINE_UI_PARAMS` (até 64 por tipo e 5
seletores de cor), números de ponto flutuante com `f`, sem sobrecarga de funções (OpenCL),
sem swizzles, tabelas `__CONSTANT__` só de `float`/`int` e `TIMELINE_FRAME_INDEX` (Resolve
19.1+) para animar o grão e os defeitos.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import APP_NAME, __version__, look, params, presets
from . import presets as presets_mod
from .i18n import _

PACKAGE_NAME = "PeliculaConverter"
MARKER = "VERSAO.txt"
DCTL, GLSL, CPP = "dctl", "glsl", "cpp"  # cpp: plugin OpenFX (pelicula/ofx.py)
KINDS = ("cor", "laboratorio", "textura", "projetor")
COLOR_KINDS = ("cor", "laboratorio")  # nós só de cor (entrada por pixel, funcionam como LUT)
FILE_NAMES = {"cor": "PeliculaConverter Cor.dctl", "laboratorio": "PeliculaConverter Laboratorio.dctl",
              "textura": "PeliculaConverter Textura.dctl", "projetor": "PeliculaConverter Projetor.dctl"}
NODE_LABELS = {"cor": "Cor", "laboratorio": "Laboratorio", "textura": "Textura", "projetor": "Projetor"}
LUT_SIZE = 33


class ResolveError(RuntimeError):
    pass


# ------------------------------------------------------------------ texto ASCII para o DCTL
_ASCII_FIX = {"•": "-", "×": "x", "°": " graus", "–": "-", "—": "-", "“": "", "”": "", "’": "", "‘": "",
              "&": "e", "%": " pct", "/": "-", ",": "", "(": "", ")": "", "{": "", "}": "", '"': "", ";": "",
              ":": "", "#": "", "\\": "-", "'": "", "+": " mais ", "=": "", "<": "", ">": "", "|": "-",
              "*": "", "?": "", "!": ""}


def ascii_text(text: str) -> str:
    """Texto só com ASCII seguro para rótulos do DCTL (sem acentos, vírgulas ou parênteses)."""
    out = []
    for ch in str(text):
        if ch in _ASCII_FIX:
            out.append(_ASCII_FIX[ch])
            continue
        base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii")
        out.append(base)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def safe_file_name(name: str) -> str:
    """Nome de arquivo ASCII sem caracteres proibidos no Windows."""
    s = unicodedata.normalize("NFKD", name.replace("•", "-")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r'[<>:"/\\|?*,;]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s or "preset"


def flt(x: float) -> str:
    """Literal float com sufixo f (exigido pelo DCTL; válido também no GLSL 3.30)."""
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(x)
    if abs(x) < 1e-12:
        # Zeros calculados (ex.: fora da diagonal de uma matriz de gamut identidade) saem como 1e-17
        # com sinal e dígitos que mudam conforme a CPU/BLAS; num float32 eles são zero de qualquer jeito.
        return "0.0f"
    s = f"{x:.9g}"
    if "e" in s or "E" in s:
        mant, exp = s.lower().split("e")
        if "." not in mant:
            mant += ".0"
        s = f"{mant}e{int(exp)}"
    elif "." not in s:
        s += ".0"
    return s + "f"


def _ui_num(x: float) -> str:
    """Número para DEFINE_UI_PARAMS (sem sufixo, como no exemplo oficial)."""
    s = f"{float(x):.6g}"
    if "e" in s:
        s = f"{float(x):.6f}".rstrip("0")
    if "." not in s:
        s += ".0"
    return s


# ------------------------------------------------------------------ controles da interface
@dataclass
class Ctl:
    """Um controle do DCTL (`DEFINE_UI_PARAMS`) ligado a uma chave de `params` ou interno."""

    name: str                      # variável no DCTL (chave do app, sem acento)
    label: str                     # rótulo ASCII mostrado no Resolve
    kind: str                      # float | int | check | combo | color
    default: Any
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.01
    choices: list[tuple[str, str]] = field(default_factory=list)  # (valor do app, rótulo ASCII)
    tip: str = ""
    scale: float = 1.0             # valor do app = valor da interface × scale (percentuais: 0,01)
    key: str = ""                  # chave do app (para ler presets); "" = controle interno
    section: str = ""              # controle interno: seção do app onde ele aparece no OpenFX

    @property
    def var(self) -> str:
        """Nome da variável no formato do app usada pelo kernel (v_<chave>)."""
        return "v_" + (self.key or self.name.removeprefix("ui_"))

    @property
    def enum_prefix(self) -> str:
        return "PC" + re.sub(r"[^A-Z0-9]", "", (self.key or self.name.removeprefix("ui_")).upper())

    def enums(self) -> list[str]:
        out = []
        for i, (val, _lab) in enumerate(self.choices):
            tag = re.sub(r"[^A-Z0-9]+", "_", str(val).upper()).strip("_") or str(i)
            out.append(f"{self.enum_prefix}_{tag}")
        return out

    def ui_value(self, app_value: Any) -> Any:
        """Valor do app → valor mostrado na interface do DCTL."""
        if self.kind == "combo":
            keys = [c[0] for c in self.choices]
            return keys.index(str(app_value)) if str(app_value) in keys else 0
        if self.kind == "check":
            return 1 if app_value else 0
        if self.kind == "color":
            return tuple(float(c) for c in app_value)
        if self.kind == "int":
            return int(app_value)
        v = float(app_value) / self.scale
        return min(max(v, self.lo), self.hi)

    def app_expr(self) -> str:
        """Expressão no kernel que devolve o valor no formato do app."""
        if self.kind == "float" and self.scale != 1.0:
            return f"({self.name} * {flt(self.scale)})"
        if self.kind == "color":
            return f"make_float3({self.name}.r, {self.name}.g, {self.name}.b)"
        if self.kind in ("int", "check", "combo"):
            return f"PC_I({self.name})"
        return self.name


def ascii_tip(text: str) -> str:
    """Dica (texto entre aspas no DCTL): ASCII, sem aspas, vírgulas viram travessões."""
    return ascii_text(str(text).replace(", ", " - ").replace(",", " "))


def ctl(key: str, label: str | None = None, tip: str | None = None, **over) -> Ctl:
    """Controle a partir de um parâmetro do app (faixa, padrão, dica e opções iguais).

    A variável no DCTL leva o prefixo `ui_` (nada de colidir com nomes do Resolve ou do kernel).
    """
    p = params.PARAMS[key]
    lab = ascii_text(label if label is not None else p.label)
    t = ascii_tip(tip if tip is not None else p.tip)
    name = "ui_" + key
    if p.kind == "bool":
        c = Ctl(name, lab, "check", 1 if p.default else 0, tip=t, key=key)
    elif p.kind == "choice":
        c = Ctl(name, lab, "combo", p.default, choices=[(v, ascii_text(n)) for v, n in p.choices], tip=t, key=key)
    elif p.kind == "color":
        c = Ctl(name, lab, "color", tuple(p.default), tip=t, key=key)
    elif p.kind == "int":
        c = Ctl(name, lab, "int", int(p.default), p.min, p.max, 1, tip=t, key=key)
    else:
        if p.percent:
            c = Ctl(name, lab, "float", p.default, p.min * 100, p.max * 100, 1.0, tip=t, scale=0.01, key=key)
        else:
            c = Ctl(name, lab, "float", p.default, p.min, p.max, p.step, tip=t, key=key)
    for k, v in over.items():
        setattr(c, k, v)
    return c


# Faixa em que o Resolve entrega o clipe ao nó. Clipes de câmera (YUV, Data Levels Auto/Video) chegam
# expandidos (64–940 → 0–1) e as curvas em código de 10 bits (look.INPUT_DOMAIN: S-Log3, V-Log, N-Log)
# voltam ao código da câmera, como o app faz com o arquivo; "Cheia" é para quando o valor já é o código
# (clipe em Full em Clip Attributes, como a Sony recomenda, ou log que a câmera mandou reescalado pela saída
# HDMI "Limited" — o `log_reescalado` do app).
RANGE_CHOICES = [("legal", "Video faixa legal 64-940"), ("cheia", "Cheia 0-1023")]
ENTRADA_TIP = ("Curva e gamut da camera ou HLG-PQ para video HDR. Se a linha do tempo ja esta em Rec.709 - "
               "Gamma 2.4 deixe Rec.709.")


def range_control() -> Ctl:
    """Faixa do vídeo (controle só do plugin; o app sabe a faixa pelo arquivo: `media.legal_range`)."""
    return Ctl("ui_faixa_video", "Faixa do video", "combo", "legal", choices=list(RANGE_CHOICES),
               tip=ascii_tip("So muda S-Log3 V-Log e N-Log que usam o codigo de 10 bits. Video e o padrao para "
                             "clipes em Data Levels Auto ou Video. Cheia para clipes em Full ou log que a camera "
                             "mandou reescalado pela saida HDMI Limited."),
               section="entrada")


def input_controls() -> list[Ctl]:
    """Perfil do vídeo, faixa, exposição e balanço (o começo dos nós Cor e Laboratório)."""
    return [ctl("entrada", "Perfil do video", ENTRADA_TIP), range_control(),
            ctl("exposicao"), ctl("temperatura"), ctl("tint", "Tonalidade")]


def cor_controls() -> list[Ctl]:
    out = input_controls()
    out += lab_controls()
    out += [
        ctl("cor_on", "Cor da pelicula"),
        ctl("cor_forca"), ctl("contraste"), ctl("meio_tom"), ctl("preto"), ctl("branco"),
        ctl("rolagem_luzes"), ctl("rolagem_sombras"), ctl("saturacao"), ctl("densidade"),
        ctl("sombras_matiz"), ctl("sombras_forca"), ctl("luzes_matiz"), ctl("luzes_forca"), ctl("equilibrio"),
        ctl("contraste_r"), ctl("contraste_g"), ctl("contraste_b"),
        ctl("offset_r"), ctl("offset_g"), ctl("offset_b"),
        ctl("verdes_matiz"), ctl("azuis_matiz"), ctl("pele_sat"), ctl("pele_matiz"), ctl("pele_luz"),
    ]
    out += [
        ctl("pb", "Preto e branco"), ctl("pb_filtro", "Filtro do PeB"), ctl("virada", "Viragem do PeB"),
        ctl("virada_forca"), ctl("envelhecimento"),
        ctl("copia", "Copia print"), ctl("copia_forca", "Forca da copia"),
        ctl("mix_geral", "Forca geral do look"), curve_control(),
    ]
    return out


def lab_controls(with_switch: bool = True) -> list[Ctl]:
    """Laboratório (negativo → cópia): os mesmos controles da seção do app."""
    out = [ctl("lab_on", "Laboratorio negativo e copia")] if with_switch else []
    return out + [
        ctl("lab_negativo", "Lab - Negativo"), ctl("lab_copia", "Lab - Copia"),
        ctl("lab_revelacao", "Lab - Revelacao stops"),
        ctl("lab_separacao", "Lab - Separacao de cores Hue Split"),
        ctl("lab_separacao_eixo", "Lab - Eixo da separacao graus"),
        ctl("lab_luz_r", "Lab - Luz vermelha pt"), ctl("lab_luz_g", "Lab - Luz verde pt"),
        ctl("lab_luz_b", "Lab - Luz azul pt"), ctl("lab_densidade", "Lab - Densidade da copia pt"),
        ctl("lab_dens_r", "Lab - Densidade dos vermelhos"), ctl("lab_dens_g", "Lab - Densidade dos verdes"),
        ctl("lab_dens_b", "Lab - Densidade dos azuis"),
        ctl("lab_pe", "Lab - Pe da copia preto"), ctl("lab_sombras_rolagem", "Lab - Rolagem das sombras"),
        ctl("lab_luzes_rolagem", "Lab - Rolagem das altas luzes"),
        ctl("lab_saturacao_filme", "Lab - Saturacao do filme"), ctl("lab_saturacao", "Lab - Saturacao final"),
        ctl("lab_pele_matiz", "Lab - Matiz da pele graus"), ctl("lab_pele_sat", "Lab - Saturacao da pele"),
        ctl("lab_bypass_negativo", "Lab - Bleach bypass no negativo"),
        ctl("lab_bypass_copia", "Lab - Bleach bypass na copia"),
        ctl("lab_neutro_negativo", "Lab - Curva neutra do negativo"),
        ctl("lab_neutro_copia", "Lab - Curva neutra da copia"),
        ctl("lab_processo", "Lab - Processo"), ctl("lab_processo_forca", "Lab - Forca do processo"),
        ctl("lab_chave", "Lab - Chave preta Technicolor"),
        ctl("lab_diafonia", "Lab - Mistura entre camadas"),
    ]


def curve_control() -> Ctl:
    return Ctl("ui_mostrar_curva", "Mostrar curva", "check", 0,
               tip="Desenha as curvas R G B do ajuste atual por cima da imagem - eixo horizontal de -8 a +8 stops. "
                   "So para ver: desligue antes de renderizar.")


def laboratorio_controls() -> list[Ctl]:
    """Nó Laboratório: entrada, exposição e o laboratório (sempre ligado), como um nó de emulação de filme."""
    return (input_controls() + lab_controls(with_switch=False)
            + [ctl("mix_geral", "Forca geral do look"), curve_control()])


# ------------------------------------------------------------------ dialetos
_GLSL_HEADER = """#version 330
#define float2 vec2
#define float3 vec3
#define float4 vec4
#define make_float2 vec2
#define make_float3 vec3
#define make_float4 vec4
#define _powf pow
#define _logf log
#define _log2f log2
#define _expf exp
#define _exp2f exp2
#define _fabs abs
#define _fmaxf max
#define _fminf min
#define _clampf clamp
#define _sqrtf sqrt
#define _floorf floor
#define _ceilf ceil
#define _sinf sin
#define _cosf cos
#define _atan2f atan
#define _saturatef(x) clamp((x), 0.0, 1.0)
#define PC_F(x) float(x)
#define PC_I(x) int(x)
#define PC_U(x) uint(x)
"""

_DCTL_HEADER = """#define PC_F(x) ((float)(x))
#define PC_I(x) ((int)(x))
#define PC_U(x) ((uint)(x))
"""

_FRAME_DCTL = """#if (__RESOLVE_VER_MAJOR__ > 19) || ((__RESOLVE_VER_MAJOR__ == 19) && (__RESOLVE_VER_MINOR__ >= 1))
#define PC_FRAME (TIMELINE_FRAME_INDEX)
#else
#define PC_FRAME (1)
#endif
"""


def _table(dialect: str, name: str, values: Iterable[float], typ: str = "float") -> str:
    vals = list(values)
    lit = [flt(v) for v in vals] if typ == "float" else [str(int(v)) for v in vals]
    if dialect == DCTL:
        return f"__CONSTANT__ {typ} {name}[{len(vals)}] = {{ {', '.join(lit)} }};\n"
    if dialect == CPP:
        return f"static const {typ} {name}[{len(vals)}] = {{ {', '.join(lit)} }};\n"
    return f"const {typ} {name}[{len(vals)}] = {typ}[{len(vals)}]({', '.join(lit)});\n"


def _define(name: str, value: float) -> str:
    return f"#define {name} {flt(value)}\n"


def _ui_decl(c: Ctl, dialect: str) -> str:
    if dialect == GLSL:
        typ = {"float": "float", "int": "int", "check": "int", "combo": "int", "color": "vec3"}[c.kind]
        out = f"uniform {typ} {c.name};\n"
        if c.kind == "combo":
            out += "".join(f"#define {e} {i}\n" for i, e in enumerate(c.enums()))
        return out
    lab = c.label
    if c.kind == "float":
        line = (f"DEFINE_UI_PARAMS({c.name}, {lab}, DCTLUI_SLIDER_FLOAT, {_ui_num(c.ui_value(c.default))}, "
                f"{_ui_num(c.lo)}, {_ui_num(c.hi)}, {_ui_num(c.step)})")
    elif c.kind == "int":
        line = (f"DEFINE_UI_PARAMS({c.name}, {lab}, DCTLUI_SLIDER_INT, {int(c.default)}, {int(c.lo)}, {int(c.hi)}, "
                f"{max(1, int(c.step))})")
    elif c.kind == "check":
        line = f"DEFINE_UI_PARAMS({c.name}, {lab}, DCTLUI_CHECK_BOX, {int(c.default)})"
    elif c.kind == "combo":
        labels = ", ".join(n for _v, n in c.choices)
        line = (f"DEFINE_UI_PARAMS({c.name}, {lab}, DCTLUI_COMBO_BOX, {c.ui_value(c.default)}, "
                f"{{ {', '.join(c.enums())} }}, {{ {labels} }})")
    else:
        r, g, b = c.default
        line = f"DEFINE_UI_PARAMS({c.name}, {lab}, DCTLUI_COLOR_PICKER, {flt(r)}, {flt(g)}, {flt(b)})"
    out = line + "\n"
    if c.tip:
        out += f'DEFINE_UI_TOOLTIP({lab}, "{c.tip}")\n'
    return out


def _derived(name: str, values: dict) -> Any:
    """Controles internos cujo valor sai dos ajustes do app (`DERIVED`, 1.6)."""
    from . import grao
    if name == "ui_mtf_copia":  # o nó Textura não vê a cópia dos nós Cor/Laboratorio
        return 1 if grao.print_chosen(values) else 0
    raise KeyError(name)


DERIVED = ("ui_mtf_copia",)


def _with_defaults(controls: list[Ctl], values: dict | None) -> list[Ctl]:
    """Copia dos controles com os padrões tirados de `values` (valores do app, já limpos)."""
    if not values:
        return controls
    out = []
    for c in controls:
        if not c.key and c.name in DERIVED:  # 1.6: controle interno que segue os ajustes do app
            c = Ctl(**{**c.__dict__})
            c.default = _derived(c.name, values)
        if c.key and c.key in values:
            v = values[c.key]
            c = Ctl(**{**c.__dict__})
            if c.kind == "float":
                c.default = min(max(float(v), c.lo * c.scale), c.hi * c.scale)
            elif c.kind == "int":
                c.default = int(v)
            elif c.kind == "check":
                c.default = 1 if v else 0
            elif c.kind == "combo":
                c.default = str(v)
            elif c.kind == "color":
                c.default = tuple(float(x) for x in v)
        out.append(c)
    return out


# ------------------------------------------------------------------ kernel comum (cor)
K_COMMON = r"""
// ---------------------------------------------------------------- utilidades
PC_DEVICE float pc_dot3(float3 a, float3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
PC_DEVICE float3 pc_s3(float s) { return make_float3(s, s, s); }
PC_DEVICE float pc_lerp(float a, float b, float t) { return a + (b - a) * t; }
PC_DEVICE float3 pc_lerp3(float3 a, float3 b, float t) { return a + (b - a) * t; }
PC_DEVICE float pc_smooth(float e0, float e1, float x) {
    float t = _saturatef((x - e0) / (e1 - e0));
    return t * t * (3.0f - 2.0f * t);
}
PC_DEVICE float pc_mod(float x, float y) { return x - y * _floorf(x / y); }
PC_DEVICE int pc_clampi(int i, int lo, int hi) { return i < lo ? lo : (i > hi ? hi : i); }
PC_DEVICE float3 pc_mat3(float3 r0, float3 r1, float3 r2, float3 v) {
    return make_float3(pc_dot3(r0, v), pc_dot3(r1, v), pc_dot3(r2, v));
}
PC_DEVICE float3 pc_max3(float3 a, float s) { return make_float3(_fmaxf(a.x, s), _fmaxf(a.y, s), _fmaxf(a.z, s)); }
PC_DEVICE float3 pc_clamp3(float3 a, float lo, float hi) {
    return make_float3(_clampf(a.x, lo, hi), _clampf(a.y, lo, hi), _clampf(a.z, lo, hi));
}
PC_DEVICE float pc_log10(float x) { return _logf(_fmaxf(x, 1e-10f)) * 0.4342944819f; }
PC_DEVICE float pc_luma(float3 c) { return pc_dot3(c, make_float3(0.2126f, 0.7152f, 0.0722f)); }

// ---------------------------------------------------------------- curvas (mesmas do app)
PC_DEVICE float pc_softclip(float u, float p) { return u / _powf(1.0f + _powf(_fabs(u), p), 1.0f / p); }
PC_DEVICE float pc_softclip_inv(float v, float p) {
    float a = _fminf(_fabs(v), 0.99995f);
    float r = a / _powf(1.0f - _powf(a, p), 1.0f / p);
    return v < 0.0f ? -r : (v > 0.0f ? r : 0.0f);
}
PC_DEVICE float pc_curve(float t, float slope, float mid, float black, float white, float ps, float pt) {
    if (t >= 0.0f) {
        float rw = _fmaxf(white - mid, 1e-4f);
        return mid + rw * pc_softclip(t * slope / rw, ps);
    }
    float rb = _fmaxf(mid - black, 1e-4f);
    return mid + rb * pc_softclip(t * slope / rb, pt);
}
PC_DEVICE float pc_curve_inv(float y, float slope, float mid, float black, float white, float ps, float pt) {
    if (y >= mid) {
        float rw = _fmaxf(white - mid, 1e-4f);
        return pc_softclip_inv((y - mid) / rw, ps) * rw / slope;
    }
    float rb = _fmaxf(mid - black, 1e-4f);
    return pc_softclip_inv((y - mid) / rb, pt) * rb / slope;
}
PC_DEVICE float3 pc_disp_to_stops(float3 y) {
    return make_float3(_clampf(pc_curve_inv(y.x, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP), -12.0f, 12.0f),
                       _clampf(pc_curve_inv(y.y, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP), -12.0f, 12.0f),
                       _clampf(pc_curve_inv(y.z, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP), -12.0f, 12.0f));
}
PC_DEVICE float3 pc_stops_to_disp(float3 t) {
    return make_float3(pc_curve(t.x, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP),
                       pc_curve(t.y, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP),
                       pc_curve(t.z, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP));
}
PC_DEVICE float3 pc_lin_to_stops(float3 l) {
    return make_float3(_clampf(_log2f(_fmaxf(l.x, 1e-7f) / 0.18f), -12.0f, 12.0f),
                       _clampf(_log2f(_fmaxf(l.y, 1e-7f) / 0.18f), -12.0f, 12.0f),
                       _clampf(_log2f(_fmaxf(l.z, 1e-7f) / 0.18f), -12.0f, 12.0f));
}
PC_DEVICE float3 pc_stops_to_lin(float3 t) {
    return make_float3(0.18f * _exp2f(t.x), 0.18f * _exp2f(t.y), 0.18f * _exp2f(t.z));
}
PC_DEVICE float3 pc_code_to_lin(float3 c) { return pc_stops_to_lin(pc_disp_to_stops(c)); }
PC_DEVICE float3 pc_lin_to_code(float3 l) { return pc_stops_to_disp(pc_lin_to_stops(l)); }
"""

K_DECODE = r"""
// ---------------------------------------------------------------- perfis de câmera
PC_DEVICE float pc_nlog_dec(float y) {
    float c = y * 1023.0f;
    return (c < 452.0f) ? _powf(_fmaxf(c / 650.0f, 0.0f), 3.0f) - 0.0075f : _expf((c - 619.0f) / 150.0f);
}
PC_DEVICE float pc_slog3_dec(float y) {
    float c = y * 1023.0f;
    return (c >= 171.2102946929f) ? _powf(10.0f, (c - 420.0f) / 261.5f) * 0.19f - 0.01f
                                  : (c - 95.0f) * 0.01125f / (171.2102946929f - 95.0f);
}
PC_DEVICE float pc_logc3_dec(float t) {
    return (t > 0.149658f) ? (_powf(10.0f, (t - 0.385537f) / 0.247190f) - 0.052272f) / 5.555556f
                           : (t - 0.092809f) / 5.367655f;
}
PC_DEVICE float pc_vlog_dec(float y) {
    return (y < 0.181f) ? (y - 0.125f) / 5.6f : _powf(10.0f, (y - 0.598206f) / 0.241514f) - 0.00873f;
}
PC_DEVICE float pc_cineon_dec(float y) {
    return (_powf(10.0f, (y * 1023.0f - 685.0f) / 300.0f) - PC_CIN_BLACK) / (1.0f - PC_CIN_BLACK);
}
PC_DEVICE float pc_di_dec(float y) {
    return (y <= 0.02740668f) ? y / 10.44426855f : _exp2f(y / 0.07329248f - 7.0f) - 0.0075f;
}
PC_DEVICE float pc_l3g10_dec(float y) {
    return (y < 0.0f) ? y / 15.1927f - 0.01f : (_powf(10.0f, y / 0.224282f) - 1.0f) / 155.975327f - 0.01f;
}
// Blackmagic Film Gen 5: D*x + E abaixo do corte; A*ln(x + B) + C acima
PC_DEVICE float pc_bmd5_dec(float y) {
    return (y < 0.13388378308667f) ? (y - 0.09246575342465753f) / 8.283605932402494f
                                   : _expf((y - 0.5300133392291939f) / 0.08692876065491224f) - 0.005494072432257808f;
}
// ARRI LogC4 (a, b, c, s, t da especificacao)
PC_DEVICE float pc_logc4_dec(float e) {
    return (e >= 0.0f) ? (_exp2f(14.0f * (e - PC_C4C) / PC_C4B + 6.0f) - 64.0f) / PC_C4A : e * PC_C4S + PC_C4T;
}
// Apple Log
PC_DEVICE float pc_apple_dec(float p) {
    if (p >= 0.20855531595464202f) return _exp2f((p - 0.69336945f) / 0.08550479f) - 0.00964052f;
    return (p >= 0.0f) ? _sqrtf(p / 47.28711236f) - 0.05641088f : -0.05641088f;
}
// HLG (ITU-R BT.2100): OETF inversa x HLG_K (cinza da BT.2408 em 38% -> 0,18), espelhada abaixo de 0
PC_DEVICE float pc_hlg_dec(float e) {
    if (e <= 0.5f) return e * _fabs(e) / 3.0f * PC_HLG_K;
    return (_expf((e - PC_HLG_C) / PC_HLG_A) + PC_HLG_B) / 12.0f * PC_HLG_K;
}
// PQ (SMPTE ST 2084): luz da tela / 1000 cd/m2, depois a OOTF inversa do HLG (gama 1,2 pela luminancia)
PC_DEVICE float pc_pq_disp(float e) {
    float p = _powf(_fmaxf(e, 0.0f), 1.0f / PC_PQ_M2);
    return 10.0f * _powf(_fmaxf(p - PC_PQ_C1, 0.0f) / _fmaxf(PC_PQ_C2 - PC_PQ_C3 * p, 1e-6f), 1.0f / PC_PQ_M1);
}
PC_DEVICE float3 pc_pq_dec(float3 c) {
    float3 f = make_float3(pc_pq_disp(c.x), pc_pq_disp(c.y), pc_pq_disp(c.z));
    float y = _fmaxf(0.2627f * f.x + 0.6780f * f.y + 0.0593f * f.z, 1e-10f);
    return f * (_powf(y, -1.0f / 6.0f) * PC_HLG_K);
}
// cv = 1: a curva e escrita no codigo de 10 bits (codigo/1023) e o clipe chegou em faixa legal expandida
// (v = (codigo - 64)/876): volta ao codigo antes da formula (look.INPUT_DOMAIN).
PC_DEVICE float3 pc_to_linear(float3 c, int id, int cv) {
    if (cv == 1) c = make_float3((c.x * 876.0f + 64.0f) / 1023.0f, (c.y * 876.0f + 64.0f) / 1023.0f,
                                 (c.z * 876.0f + 64.0f) / 1023.0f);
    if (id == 0) return pc_code_to_lin(c);
    if (id == 1) return c;
    if (id == 2) return make_float3(pc_nlog_dec(c.x), pc_nlog_dec(c.y), pc_nlog_dec(c.z));
    if (id == 3) return make_float3(pc_slog3_dec(c.x), pc_slog3_dec(c.y), pc_slog3_dec(c.z));
    if (id == 4) return make_float3(pc_logc3_dec(c.x), pc_logc3_dec(c.y), pc_logc3_dec(c.z));
    if (id == 5) return make_float3(pc_vlog_dec(c.x), pc_vlog_dec(c.y), pc_vlog_dec(c.z));
    if (id == 7) return make_float3(pc_di_dec(c.x), pc_di_dec(c.y), pc_di_dec(c.z));
    if (id == 8) return make_float3(pc_l3g10_dec(c.x), pc_l3g10_dec(c.y), pc_l3g10_dec(c.z));
    if (id == 9) return make_float3(pc_bmd5_dec(c.x), pc_bmd5_dec(c.y), pc_bmd5_dec(c.z));
    if (id == 10) return make_float3(pc_logc4_dec(c.x), pc_logc4_dec(c.y), pc_logc4_dec(c.z));
    if (id == 11) return make_float3(pc_apple_dec(c.x), pc_apple_dec(c.y), pc_apple_dec(c.z));
    if (id == 12) return make_float3(pc_hlg_dec(c.x), pc_hlg_dec(c.y), pc_hlg_dec(c.z));
    if (id == 13) return pc_pq_dec(c);
    return make_float3(pc_cineon_dec(c.x), pc_cineon_dec(c.y), pc_cineon_dec(c.z));
}
"""

K_LOOK = r"""
// ---------------------------------------------------------------- look de película
PC_DEVICE float pc_hue_ang(float3 c) {
    float Y = pc_luma(c);
    return _atan2f((c.x - Y) / 1.5748f, (c.z - Y) / 1.8556f);
}
PC_DEVICE float pc_hue_w(float h, float h0) {
    float d = _fabs(pc_mod(h - h0 + 3.14159265f, 6.2831853f) - 3.14159265f);
    return pc_smooth(0.8f, 0.0f, d);
}
PC_DEVICE float3 pc_hue_adjust(float3 c, float rg, float rb, float skin, float skin_rot, float skin_lum) {
    if (rg == 0.0f && rb == 0.0f && skin == 0.0f && skin_rot == 0.0f && skin_lum == 0.0f) return c;
    float Y = pc_luma(c);
    float cx = (c.z - Y) / 1.8556f;
    float cy = (c.x - Y) / 1.5748f;
    if (_sqrtf(cx * cx + cy * cy) < 1e-5f) return c;
    float h = _atan2f(cy, cx);
    float wg = pc_hue_w(h, pc_hue_ang(make_float3(0.25f, 0.6f, 0.2f)));
    float wb = pc_hue_w(h, pc_hue_ang(make_float3(0.2f, 0.35f, 0.8f)));
    float ws = pc_hue_w(h, pc_hue_ang(make_float3(0.8f, 0.55f, 0.45f)));
    float rot = rg * wg + rb * wb + skin_rot * ws;
    float cs = _cosf(rot);
    float sn = _sinf(rot);
    float nx = cs * cx - sn * cy;
    float ny = sn * cx + cs * cy;
    float k = _fmaxf(0.0f, 1.0f + skin * ws);
    nx = nx * k;
    ny = ny * k;
    Y = Y * (1.0f + PC_SKIN_LUM * skin_lum * ws);
    float r = Y + 1.5748f * ny;
    float b = Y + 1.8556f * nx;
    float g = (Y - 0.2126f * r - 0.0722f * b) / 0.7152f;
    return make_float3(r, g, b);
}
PC_DEVICE float3 pc_hsv_tint(float hue_deg, float amount) {
    float h = pc_mod(hue_deg, 360.0f) / 60.0f;
    float x = 1.0f - _fabs(pc_mod(h, 2.0f) - 1.0f);
    int sector = pc_clampi(PC_I(_floorf(h)), 0, 5);
    float3 c = make_float3(1.0f, x, 0.0f);
    if (sector == 1) c = make_float3(x, 1.0f, 0.0f);
    if (sector == 2) c = make_float3(0.0f, 1.0f, x);
    if (sector == 3) c = make_float3(0.0f, x, 1.0f);
    if (sector == 4) c = make_float3(x, 0.0f, 1.0f);
    if (sector == 5) c = make_float3(1.0f, 0.0f, x);
    float l = pc_luma(c);
    return (c - pc_s3(l)) * (amount * 0.09f);
}
PC_DEVICE float pc_soft_p(float v) { return 4.0f + (1.15f - 4.0f) * v; }
PC_DEVICE float3 pc_film_look(float3 lin, int bw, float3 bww, float sat, float3 chg, float3 cho, float slope, float mid,
                              float black, float white, float ps, float pt, float dens, float rg, float rb, float skin,
                              float skin_rot, float skin_lum, float3 sh_tint, float3 hi_tint, float bal,
                              float tone_amt, float3 tone_sh, float3 tone_hi) {
    float3 l2 = lin;
    if (bw == 1) l2 = pc_s3(pc_dot3(lin, bww));
    float3 t = pc_clamp3(pc_lin_to_stops(l2), -10.0f, 9.0f);
    float ta = pc_luma(t);
    t = pc_s3(ta) + (t - pc_s3(ta)) * sat;
    t = t * chg + cho;
    float3 y = make_float3(pc_curve(t.x, slope, mid, black, white, ps, pt),
                           pc_curve(t.y, slope, mid, black, white, ps, pt),
                           pc_curve(t.z, slope, mid, black, white, ps, pt));
    float mx = _fmaxf(y.x, _fmaxf(y.y, y.z));
    float mn = _fminf(y.x, _fminf(y.y, y.z));
    y = y * (1.0f - dens * 0.45f * (mx - mn));
    y = pc_hue_adjust(y, rg, rb, skin, skin_rot, skin_lum);
    float lum = pc_luma(y);
    float piv = _clampf(0.45f + 0.3f * bal, 0.1f, 0.9f);
    float ws = 1.0f - pc_smooth(0.0f, piv, lum);
    float wh = pc_smooth(piv, 1.0f, lum);
    y = y + sh_tint * ws + hi_tint * wh;
    if (bw == 1 && tone_amt > 0.0f) {
        float L = _clampf(pc_luma(y), 0.0f, 1.0f);
        float3 toned = pc_lerp3(tone_sh, tone_hi, pc_smooth(0.0f, 1.0f, L)) * L;
        y = pc_lerp3(y, toned, tone_amt);
    }
    return y;
}
PC_DEVICE float3 pc_print_stage(float3 y, float sat, float3 gam, float3 off, float slope, float mid, float black,
                                float white, float ps, float pt) {
    float3 t = pc_disp_to_stops(y);
    float ta = pc_luma(t);
    t = pc_s3(ta) + (t - pc_s3(ta)) * sat;
    t = t * gam + off;
    return make_float3(pc_curve(t.x, slope, mid, black, white, ps, pt),
                       pc_curve(t.y, slope, mid, black, white, ps, pt),
                       pc_curve(t.z, slope, mid, black, white, ps, pt));
}
PC_DEVICE float3 pc_aged(float3 y) {
    float L = pc_luma(y);
    float3 c = pc_lerp3(pc_s3(L), y, 0.6f);
    c = c * 0.82f + pc_s3(0.075f);
    return c * make_float3(1.07f, 0.93f, 0.98f);
}
"""

# Perfil de entrada (curva + gamut): código do vídeo `code` → luz linear `lin_in`. Também no plugin OFX.
# Curvas em código de 10 bits (PC_IN_CV) com o clipe em faixa legal (Faixa do vídeo = Vídeo) voltam ao
# código antes da fórmula, como `u_input_cv`/`u_legal` no app.
B_INPUT = r"""
    int ent = v_entrada;
    int in_cv = (PC_IN_CV[ent] == 1 && v_faixa_video == 0) ? 1 : 0;
    float3 lin_in = pc_to_linear(code, PC_IN_ID[ent], in_cv);
    lin_in = pc_mat3(make_float3(PC_GAM[ent * 9 + 0], PC_GAM[ent * 9 + 1], PC_GAM[ent * 9 + 2]),
                     make_float3(PC_GAM[ent * 9 + 3], PC_GAM[ent * 9 + 4], PC_GAM[ent * 9 + 5]),
                     make_float3(PC_GAM[ent * 9 + 6], PC_GAM[ent * 9 + 7], PC_GAM[ent * 9 + 8]), lin_in);
"""

# Exposição e balanço (u_gain do app) sobre `lin`; `gx` soma ganhos por canal (cintilação etc., no OFX).
B_GAIN = r"""
    float tmp = v_temperatura / 100.0f;
    float tnt = v_tint / 100.0f;
    lin = make_float3(_fmaxf(lin.x, 0.0f) * _exp2f(v_exposicao + 0.28f * tmp + 0.08f * tnt + gx.x),
                      _fmaxf(lin.y, 0.0f) * _exp2f(v_exposicao - 0.22f * tnt + gx.y),
                      _fmaxf(lin.z, 0.0f) * _exp2f(v_exposicao - 0.38f * tmp + 0.08f * tnt + gx.z));
"""

# Corpo da função principal do nó Cor. Variáveis v_<chave> já estão no formato do app.
B_COR = r"""
    float3 code = rgb;
""" + B_INPUT + r"""
    float3 gx = pc_s3(0.0f);
    // "Mostrar curva": uma segunda passada com um cinza de -8 a +8 stops ao longo da largura
    int npass = (v_mostrar_curva == 1) ? 2 : 1;
    float curve_t = -8.0f + 16.0f * (PC_F(p_X) + 0.5f) / PC_F(p_Width);
    float3 res = code;
    float3 curve_y = pc_s3(0.0f);
    for (int pass = 0; pass < npass; pass = pass + 1) {
    float3 lin = lin_in;
    if (pass == 1) lin = pc_s3(0.18f * _exp2f(curve_t));
""" + B_GAIN + r"""
/*LAB*/
/*LOOK*/
    if (pass == 0) res = pc_clamp3(pc_lerp3(code, y, v_mix_geral), 0.0f, 1.0f);
    else curve_y = y;
    }
    if (npass == 2) res = pc_curve_overlay(res, curve_y, p_Y, p_Height);
"""

# O look paramétrico, a cópia e o envelhecimento (só no nó Cor).
B_LOOK = r"""
    float3 neutral = pc_lin_to_code(lin);
    float3 y = neutral;
    if (v_cor_on == 1) {
        int fi = v_pb_filtro;
        int vi = v_virada;
        float tone_amt = (PC_TONE_ON[vi] == 1 && v_pb == 1) ? v_virada_forca : 0.0f;
        float3 film = pc_film_look(lin, v_pb, make_float3(PC_BWW[fi * 3], PC_BWW[fi * 3 + 1], PC_BWW[fi * 3 + 2]),
            v_saturacao, make_float3(v_contraste_r, v_contraste_g, v_contraste_b),
            make_float3(v_offset_r, v_offset_g, v_offset_b), PC_DSLOPE * v_contraste, v_meio_tom, v_preto,
            _fmaxf(v_branco, v_meio_tom + 0.05f), pc_soft_p(v_rolagem_luzes), pc_soft_p(v_rolagem_sombras),
            v_densidade, v_verdes_matiz * 0.0174532925f, v_azuis_matiz * 0.0174532925f, v_pele_sat,
            v_pele_matiz * 0.0174532925f, v_pele_luz,
            pc_hsv_tint(v_sombras_matiz, v_sombras_forca), pc_hsv_tint(v_luzes_matiz, v_luzes_forca), v_equilibrio,
            tone_amt, make_float3(PC_TONE[vi * 6], PC_TONE[vi * 6 + 1], PC_TONE[vi * 6 + 2]),
            make_float3(PC_TONE[vi * 6 + 3], PC_TONE[vi * 6 + 4], PC_TONE[vi * 6 + 5]));
        y = pc_lerp3(neutral, film, v_cor_forca);
    }
    int pi = v_copia;
    if (PC_PR_ON[pi] == 1) {
        float3 pr = pc_print_stage(y, PC_PR[pi * 12 + 0],
            make_float3(PC_PR[pi * 12 + 1], PC_PR[pi * 12 + 2], PC_PR[pi * 12 + 3]),
            make_float3(PC_PR[pi * 12 + 4], PC_PR[pi * 12 + 5], PC_PR[pi * 12 + 6]),
            PC_PR[pi * 12 + 7], PC_PR[pi * 12 + 8], PC_PR[pi * 12 + 9], PC_PR[pi * 12 + 10],
            pc_soft_p(PC_PR_SOFT[pi * 2]), pc_soft_p(PC_PR_SOFT[pi * 2 + 1]));
        y = pc_lerp3(y, pr, v_copia_forca);
    }
    float age = (v_cor_on == 1) ? v_envelhecimento : 0.0f;
    if (age > 0.0f) y = pc_lerp3(y, pc_aged(y), age);
"""

# No nó Laboratório o resultado é o próprio laboratório (curva neutra de volta para o código).
B_LAB_ONLY = r"""
    float3 y = pc_lin_to_code(lin);
"""


def _cor_tables(dialect: str) -> str:
    entradas = [c[0] for c in params.PARAMS["entrada"].choices]
    out = _define("PC_CIN_BLACK", 0.010797752)
    a4 = (2 ** 18 - 16) / 117.45
    b4 = (1023 - 95) / 1023
    c4 = 95 / 1023
    out += _define("PC_C4A", a4) + _define("PC_C4B", b4) + _define("PC_C4C", c4)
    out += _define("PC_C4S", (7 * math.log(2) * 2 ** (7 - 14 * c4 / b4)) / (a4 * b4))
    out += _define("PC_C4T", (2 ** (14 * (-c4 / b4) + 6) - 64) / a4)
    out += _define("PC_SKIN_LUM", 0.25)  # luz da pele: até ±25% (hueAdjust do app)
    out += (_define("PC_HLG_A", look.HLG_A) + _define("PC_HLG_B", look.HLG_B) + _define("PC_HLG_C", look.HLG_C)
            + _define("PC_HLG_K", look.HLG_SCALE))
    out += (_define("PC_PQ_M1", look.PQ_M1) + _define("PC_PQ_M2", look.PQ_M2) + _define("PC_PQ_C1", look.PQ_C1)
            + _define("PC_PQ_C2", look.PQ_C2) + _define("PC_PQ_C3", look.PQ_C3))
    out += _table(dialect, "PC_IN_ID", [look.INPUT_IDS[e] for e in entradas], "int")
    out += _table(dialect, "PC_IN_CV", [1 if look.code_value_curve(e) else 0 for e in entradas], "int")
    gam = []
    for e in entradas:
        m = look.gamut_to_709(look.INPUT_GAMUT[e])
        gam += [float(x) for x in m.flatten()]  # linhas
    out += _table(dialect, "PC_GAM", gam)
    filtros = [c[0] for c in params.PARAMS["pb_filtro"].choices]
    out += _table(dialect, "PC_BWW", [w for f in filtros for w in look.BW_WEIGHTS[f]])
    viradas = [c[0] for c in params.PARAMS["virada"].choices]
    tone, tone_on = [], []
    for vk in viradas:
        t = look.TONES.get(vk)
        tone_on.append(1 if t else 0)
        sh, hi = t if t else ((1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
        tone += list(sh) + list(hi)
    out += _table(dialect, "PC_TONE", tone) + _table(dialect, "PC_TONE_ON", tone_on, "int")
    copias = [c[0] for c in params.PARAMS["copia"].choices]
    pr_on, pr, soft = [], [], []
    for ck in copias:
        p = look.PRINTS.get(ck)
        pr_on.append(1 if p else 0)
        if p:
            pr += [p["sat"], *p["gamma"], *p["offset"], look.D_SLOPE * p["slope"], p["mid"], p["black"],
                   p["white"], 0.0]
            soft += [p["ps"], p["pt"]]
        else:
            pr += [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, look.D_SLOPE, look.D_MID, 0.0, 1.0, 0.0]
            soft += [0.0, 0.0]
    out += _table(dialect, "PC_PR_ON", pr_on, "int") + _table(dialect, "PC_PR", pr)
    out += _table(dialect, "PC_PR_SOFT", soft)
    return out


# ------------------------------------------------------------------ montagem das fontes
@dataclass
class Spec:
    kind: str
    controls: list[Ctl]
    tables: str
    kernel: str
    body: str
    texture: bool




def spec(kind: str, dialect: str = DCTL) -> Spec:
    if kind in COLOR_KINDS:
        lab_only = kind == "laboratorio"
        controls = laboratorio_controls() if lab_only else cor_controls()
        body = B_COR.replace("/*LAB*/", B_LAB).replace("/*LOOK*/", B_LAB_ONLY if lab_only else B_LOOK)
        if lab_only:
            body = "    int v_lab_on = 1;\n" + body  # o nó Laboratório é o laboratório sempre ligado
        kernel = K_COMMON + K_DECODE + K_LOOK + K_LAB + K_CURVE
        return Spec(kind, controls, _cor_tables(dialect) + _lab_tables(dialect), kernel, body, False)
    if kind == "textura":
        tables = _gauge_tables(dialect) + _mtf_table(dialect) + _grao_tables(dialect)
        return Spec("textura", textura_controls(), tables, K_COMMON + K_RAND + K_TEXTURA, _textura_body(), True)
    if kind == "projetor":
        return Spec("projetor", projetor_controls(), _gauge_tables(dialect) + _projetor_tables(dialect),
                    K_COMMON + K_RAND + K_PROJETOR, _projetor_body(), True)
    raise KeyError(kind)


# ------------------------------------------------------------------ laboratório (negativo → cópia)
# Mesmo modelo de look.LabPath. A luz da copiadora que deixa o cinza médio neutro (look._calibrate_print)
# é calculada no próprio kernel, em forma fechada: a cópia tem pé 0, então a curva
# D(x) = g·w·ln((1 + e^(x/w)) / (1 + e^((x − s)/w))) se inverte com x = w·ln((q − 1)/(1 − q·e^(−s/w))),
# q = e^(D/(g·w)). As densidades de cada camada saem de M·D = alvo (M = diafonia + chave; no
# Technicolor de duas cores só há duas camadas e vale o mínimo quadrado, como no app). Assim qualquer
# revelação, diafonia, chave ou força funciona sem tabelas.
NEG_FIELDS = 20     # sens 3x3, gama 3, pé 3, ombro 3, largura, interimage
PRINT_FIELDS = 17   # existe, gama 3, dmax 3, largura, diafonia 3x3
PROC_FIELDS = 40    # tipo (0 normal, 1 prata, 2 caminho B) + negativo (20) + cópia sem "existe" (16) + chave 3


def _neg_row(neg: dict) -> list[float]:
    return ([float(x) for row in neg["sens"] for x in row] + [float(x) for x in neg["gamma"]]
            + [float(x) for x in neg["toe"]] + [float(x) for x in neg["shoulder"]]
            + [float(neg["width"]), float(neg.get("interimage", 0.0))])


def _print_row(pr: dict | None) -> list[float]:
    if pr is None:
        return [0.0] * PRINT_FIELDS
    return ([1.0] + [float(x) for x in pr["gamma"]] + [float(x) for x in pr["dmax"]] + [float(pr["width"])]
            + [float(x) for row in pr["dye"] for x in row])


def _lab_tables(dialect: str) -> str:
    negs = [k for k, _l in params.NEGATIVOS]
    prints = [k for k, _l in params.COPIAS_LAB]
    procs = [k for k, _l in params.PROCESSOS]
    out = _define("PC_LAB_TARGET", look.LAB_TARGET_D) + _define("PC_LAB_POINT", look.LAB_POINT)
    out += _define("PC_LAB_VIEW", look.LAB_VIEW_GAMMA) + _define("PC_LAB_DENS_K", look.LAB_DENS_K)
    out += _define("PC_SPLIT_A", look.SPLIT_STRETCH) + _define("PC_SPLIT_B", look.SPLIT_SQUEEZE)
    out += _define("PC_BYP_C", look.BYPASS_NEG_CONTRAST) + _define("PC_BYP_D", look.BYPASS_NEG_DYE)
    out += f"#define PC_LAB_2383 {prints.index('2383')}\n"
    out += _table(dialect, "PC_NEG", [x for k in negs for x in _neg_row(look.NEGATIVES[k])])
    out += _table(dialect, "PC_LPR", [x for k in prints for x in _print_row(look.LAB_PRINTS[k])])
    rows: list[float] = []
    for k in procs:
        proc = look.LAB_PROCESSES.get(k)
        if proc is None:
            rows += [1.0 if k == "prata" else 0.0] + [0.0] * (PROC_FIELDS - 1)
        else:
            rows += [2.0] + _neg_row(proc) + _print_row(proc["print"])[1:] + [float(x) for x in proc["key"]]
    out += _table(dialect, "PC_PROC", rows)
    return out


K_LAB = r"""
// ---------------------------------------------------------------- laboratório (look.LabPath)
PC_DEVICE float pc_softplus(float z) { return _fmaxf(z, 0.0f) + _logf(1.0f + _expf(-_fabs(z))); }
PC_DEVICE float3 pc_lab_curve(float3 x, float3 g, float3 xt, float3 xs, float w) {
    return make_float3(g.x * w * (pc_softplus((x.x - xt.x) / w) - pc_softplus((x.x - xs.x) / w)),
                       g.y * w * (pc_softplus((x.y - xt.y) / w) - pc_softplus((x.y - xs.y) / w)),
                       g.z * w * (pc_softplus((x.z - xt.z) / w) - pc_softplus((x.z - xs.z) / w)));
}
// os tres canais se aproximam da media deles (curvas neutras)
PC_DEVICE float3 pc_neutral3(float3 v, float t) {
    float m = (v.x + v.y + v.z) / 3.0f;
    return v + (pc_s3(m) - v) * t;
}
// produto de matrizes a*I + b*J: devolve o novo b (o novo a e a1*a2)
PC_DEVICE float pc_aij_b(float a1, float b1, float a2, float b2) { return a1 * b2 + b1 * a2 + 3.0f * b1 * b2; }
// densidade do negativo: dn' = A*dn + B*(soma). Efeito entre camadas k, saturacao do filme fs e prata
// retida no negativo bn: mais contraste neutro e menos cor dos corantes (look.ii_coefs)
PC_DEVICE float2 pc_ii_coefs(float k, float fs, float bn) {
    float a = 1.0f + k;
    float b = -k / 3.0f;
    float nb = pc_aij_b(fs, (1.0f - fs) / 3.0f, a, b);
    a = fs * a;
    b = nb;
    float c = PC_BYP_C * bn;
    float d = PC_BYP_D * bn;
    b = pc_aij_b(1.0f - d, (c + d) / 3.0f, a, b);
    a = (1.0f - d) * a;
    return make_float2(a, b);
}
// cor pura de um matiz (setor HSV, igual a look._hue_rgb)
PC_DEVICE float3 pc_hue_rgb(float hue_deg) {
    float h = pc_mod(hue_deg, 360.0f) / 60.0f;
    float x = 1.0f - _fabs(pc_mod(h, 2.0f) - 1.0f);
    int sector = pc_clampi(PC_I(_floorf(h)), 0, 5);
    float3 c = make_float3(1.0f, x, 0.0f);
    if (sector == 1) c = make_float3(x, 1.0f, 0.0f);
    if (sector == 2) c = make_float3(0.0f, 1.0f, x);
    if (sector == 3) c = make_float3(0.0f, x, 1.0f);
    if (sector == 4) c = make_float3(x, 0.0f, 1.0f);
    if (sector == 5) c = make_float3(1.0f, 0.0f, x);
    return c;
}
// uma linha da matriz da densidade: separacao de cores (Hue Split) S vezes (A*I + B*J) = A*S_i + B
PC_DEVICE float3 pc_ii_row(float3 e, float ui, float vi, float3 u, float3 v, float sa, float sb, float ia, float ib,
                           int on) {
    float3 s = e;
    if (on == 1) s = pc_s3(1.0f / 3.0f) + u * ((1.0f + sa) * ui) + v * ((1.0f - sb) * vi);
    return s * ia + pc_s3(ib);
}
// inversa da curva da copia (pe 0): log da exposicao que da a densidade D
PC_DEVICE float pc_lab_inv(float D, float g, float s, float w) {
    float q = _expf(D / (g * w));
    float k = _expf(-s / w);
    float a = (q - 1.0f) / _fmaxf(1.0f - q * k, 1e-12f);
    return w * _logf(_fmaxf(a, 1e-30f));
}
PC_DEVICE float pc_det3(float3 a, float3 b, float3 c) {
    return a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x);
}
PC_DEVICE float3 pc_lab_path(float3 lin, float3 s0, float3 s1, float3 s2, float3 ng0, float3 nt0, float3 ns,
                             float nw, float3 i0, float3 i1, float3 i2, int has_print, float3 pg, float3 dmax,
                             float pw, float3 d0, float3 d1, float3 d2, float3 key, float push, float xtalk,
                             float3 lights) {
    float3 ng = ng0 * (1.0f + 0.12f * push);
    float3 nt = nt0 + pc_s3(0.08f * push);
    float3 dmid = pc_mat3(i0, i1, i2, pc_lab_curve(pc_s3(0.0f), ng, nt, ns, nw));
    float3 e = pc_max3(pc_mat3(s0, s1, s2, lin), 1e-7f);
    float3 le = make_float3(pc_log10(e.x / 0.18f), pc_log10(e.y / 0.18f), pc_log10(e.z / 0.18f));
    float3 dn = pc_mat3(i0, i1, i2, pc_lab_curve(le, ng, nt, ns, nw));
    if (has_print == 0) {
        // sem copia: inversao digital com o gama nominal do negativo
        float3 st = make_float3((dn.x - dmid.x) / (ng0.x * 0.30103f) - lights.x / 0.30103f,
                                (dn.y - dmid.y) / (ng0.y * 0.30103f) - lights.y / 0.30103f,
                                (dn.z - dmid.z) / (ng0.z * 0.30103f) - lights.z / 0.30103f);
        return pc_stops_to_disp(pc_clamp3(st, -12.0f, 12.0f));
    }
    // diafonia escolhida; colunas sem camada (Technicolor 2 cores) ficam zeradas
    float u0 = (_fabs(d0.x) + _fabs(d1.x) + _fabs(d2.x) > 0.0f) ? 1.0f : 0.0f;
    float u1 = (_fabs(d0.y) + _fabs(d1.y) + _fabs(d2.y) > 0.0f) ? 1.0f : 0.0f;
    float u2 = (_fabs(d0.z) + _fabs(d1.z) + _fabs(d2.z) > 0.0f) ? 1.0f : 0.0f;
    float3 r0 = make_float3((1.0f + xtalk * (d0.x - 1.0f)) * u0, xtalk * d0.y * u1, xtalk * d0.z * u2);
    float3 r1 = make_float3(xtalk * d1.x * u0, (1.0f + xtalk * (d1.y - 1.0f)) * u1, xtalk * d1.z * u2);
    float3 r2 = make_float3(xtalk * d2.x * u0, xtalk * d2.y * u1, (1.0f + xtalk * (d2.z - 1.0f)) * u2);
    // M = diafonia + chave (a chave soma a mesma densidade nos tres canais)
    float3 m0 = r0 + key;
    float3 m1 = r1 + key;
    float3 m2 = r2 + key;
    float T = PC_LAB_TARGET;
    float3 dl = pc_s3(T);
    float c2 = _fabs(m0.z) + _fabs(m1.z) + _fabs(m2.z);
    if (c2 > 1e-9f) {
        float det = pc_det3(m0, m1, m2);
        dl = make_float3(pc_det3(make_float3(T, m0.y, m0.z), make_float3(T, m1.y, m1.z), make_float3(T, m2.y, m2.z)),
                         pc_det3(make_float3(m0.x, T, m0.z), make_float3(m1.x, T, m1.z), make_float3(m2.x, T, m2.z)),
                         pc_det3(make_float3(m0.x, m0.y, T), make_float3(m1.x, m1.y, T), make_float3(m2.x, m2.y, T)))
             * (1.0f / det);
    } else {
        // so duas camadas: minimos quadrados nas colunas 0 e 1
        float3 ca = make_float3(m0.x, m1.x, m2.x);
        float3 cb = make_float3(m0.y, m1.y, m2.y);
        float aa = pc_dot3(ca, ca);
        float ab = pc_dot3(ca, cb);
        float bb = pc_dot3(cb, cb);
        float at = (ca.x + ca.y + ca.z) * T;
        float bt = (cb.x + cb.y + cb.z) * T;
        float det = aa * bb - ab * ab;
        dl = make_float3((at * bb - ab * bt) / det, (aa * bt - ab * at) / det, 0.0f);
    }
    float3 ps = make_float3(dmax.x / pg.x, dmax.y / pg.y, dmax.z / pg.z);
    float off_z = (c2 > 1e-9f) ? pc_lab_inv(dl.z, pg.z, ps.z, pw) + dmid.z : dmid.z + 0.35f;
    float3 off = make_float3(pc_lab_inv(dl.x, pg.x, ps.x, pw) + dmid.x, pc_lab_inv(dl.y, pg.y, ps.y, pw) + dmid.y,
                             off_z);
    off = off + lights;
    float3 dd = pc_lab_curve(off - dn, pg, pc_s3(0.0f), ps, pw);
    float3 d = pc_mat3(r0, r1, r2, dd) + pc_s3(pc_dot3(key, dd));
    float kv = 3.32192809f / PC_LAB_VIEW;
    return make_float3(_exp2f(-d.x * kv), _exp2f(-d.y * kv), _exp2f(-d.z * kv));
}
// depois da copia (look.LabPost): rolagens, saturacao final, densidade por cor e pele
PC_DEVICE float3 pc_lab_post(float3 y, float hi, float lo, float sat, float3 dens, float srot, float ssat) {
    if (hi > 0.0f || lo > 0.0f) {
        float3 t = pc_disp_to_stops(y);
        float ph = pc_soft_p(hi);
        float pl = pc_soft_p(lo);
        y = make_float3(pc_curve(t.x, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, ph, pl),
                        pc_curve(t.y, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, ph, pl),
                        pc_curve(t.z, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, ph, pl));
    }
    if (sat != 1.0f) {
        float L = pc_luma(y);
        y = pc_s3(L) + (y - pc_s3(L)) * sat;
    }
    if (dens.x != 0.0f || dens.y != 0.0f || dens.z != 0.0f) {
        float wr = _fmaxf(0.0f, y.x - _fmaxf(y.y, y.z));
        float wg = _fmaxf(0.0f, y.y - _fmaxf(y.x, y.z));
        float wb = _fmaxf(0.0f, y.z - _fmaxf(y.x, y.y));
        y = y * _clampf(1.0f - PC_LAB_DENS_K * (dens.x * wr + dens.y * wg + dens.z * wb), 0.2f, 2.0f);
    }
    if (srot != 0.0f || ssat != 0.0f) y = pc_hue_adjust(y, 0.0f, 0.0f, ssat, srot, 0.0f);
    return y;
}
"""

# Etapa do laboratório no corpo do nó Cor (antes do look; o resultado volta para luz linear).
B_LAB = r"""
    if (v_lab_on == 1) {
        int ni = v_lab_negativo * 20;
        int lp = v_lab_copia;
        int pk = v_lab_processo * 40;
        float kind = PC_PROC[pk];
        float forca = v_lab_processo_forca;
        float3 lights = make_float3(PC_LAB_POINT * (v_lab_luz_r + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_g + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_b + v_lab_densidade));
        float3 key = pc_s3(0.0f);
        if (kind == 1.0f) {
            key = pc_s3(0.8f * forca / 3.0f);
            if (PC_LPR[lp * 17] == 0.0f) lp = PC_LAB_2383;
        }
        if (v_lab_bypass_copia > 0.0f && PC_LPR[lp * 17] > 0.5f) key = key + pc_s3(0.8f * v_lab_bypass_copia / 3.0f);
        // separacao de cores (Hue Split) na densidade: eixos u (polo quente) e v (perpendicular)
        int split_on = (v_lab_separacao > 0.0f) ? 1 : 0;
        float3 hu = pc_hue_rgb(v_lab_separacao_eixo);
        hu = hu - pc_s3((hu.x + hu.y + hu.z) / 3.0f);
        hu = hu * (1.0f / _sqrtf(pc_dot3(hu, hu)));
        float3 hv = make_float3(hu.z - hu.y, hu.x - hu.z, hu.y - hu.x) * 0.57735027f;
        hv = hv * (1.0f / _sqrtf(pc_dot3(hv, hv)));
        float sa = PC_SPLIT_A * v_lab_separacao;
        float sb = PC_SPLIT_B * v_lab_separacao;
        float toe = _exp2f(-0.6f * v_lab_pe);
        float nn = v_lab_neutro_negativo;
        float np = v_lab_neutro_copia;
        int lq = lp * 17;
        float2 ab = pc_ii_coefs(PC_NEG[ni + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
        float3 la = pc_lab_path(lin,
            make_float3(PC_NEG[ni + 0], PC_NEG[ni + 1], PC_NEG[ni + 2]),
            make_float3(PC_NEG[ni + 3], PC_NEG[ni + 4], PC_NEG[ni + 5]),
            make_float3(PC_NEG[ni + 6], PC_NEG[ni + 7], PC_NEG[ni + 8]),
            pc_neutral3(make_float3(PC_NEG[ni + 9], PC_NEG[ni + 10], PC_NEG[ni + 11]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 12], PC_NEG[ni + 13], PC_NEG[ni + 14]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 15], PC_NEG[ni + 16], PC_NEG[ni + 17]), nn), PC_NEG[ni + 18],
            pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, ab.x, ab.y, split_on),
            (PC_LPR[lq] > 0.5f) ? 1 : 0,
            pc_neutral3(make_float3(PC_LPR[lq + 1], PC_LPR[lq + 2], PC_LPR[lq + 3]), np),
            pc_neutral3(make_float3(PC_LPR[lq + 4], PC_LPR[lq + 5], PC_LPR[lq + 6]), np) * toe, PC_LPR[lq + 7],
            make_float3(PC_LPR[lq + 8], PC_LPR[lq + 9], PC_LPR[lq + 10]),
            make_float3(PC_LPR[lq + 11], PC_LPR[lq + 12], PC_LPR[lq + 13]),
            make_float3(PC_LPR[lq + 14], PC_LPR[lq + 15], PC_LPR[lq + 16]),
            key, v_lab_revelacao, v_lab_diafonia, lights);
        if (kind == 2.0f) {
            int b = pk + 1;
            float2 bb = pc_ii_coefs(PC_PROC[b + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
            float3 lb = pc_lab_path(lin,
                make_float3(PC_PROC[b + 0], PC_PROC[b + 1], PC_PROC[b + 2]),
                make_float3(PC_PROC[b + 3], PC_PROC[b + 4], PC_PROC[b + 5]),
                make_float3(PC_PROC[b + 6], PC_PROC[b + 7], PC_PROC[b + 8]),
                pc_neutral3(make_float3(PC_PROC[b + 9], PC_PROC[b + 10], PC_PROC[b + 11]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 12], PC_PROC[b + 13], PC_PROC[b + 14]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 15], PC_PROC[b + 16], PC_PROC[b + 17]), nn), PC_PROC[b + 18],
                pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, bb.x, bb.y, split_on),
                1,
                pc_neutral3(make_float3(PC_PROC[b + 20], PC_PROC[b + 21], PC_PROC[b + 22]), np),
                pc_neutral3(make_float3(PC_PROC[b + 23], PC_PROC[b + 24], PC_PROC[b + 25]), np) * toe,
                PC_PROC[b + 26],
                make_float3(PC_PROC[b + 27], PC_PROC[b + 28], PC_PROC[b + 29]),
                make_float3(PC_PROC[b + 30], PC_PROC[b + 31], PC_PROC[b + 32]),
                make_float3(PC_PROC[b + 33], PC_PROC[b + 34], PC_PROC[b + 35]),
                make_float3(PC_PROC[b + 36], PC_PROC[b + 37], PC_PROC[b + 38]) * v_lab_chave,
                v_lab_revelacao, v_lab_diafonia, lights);
            la = pc_lerp3(la, lb, forca);
        }
        la = pc_lab_post(la, v_lab_luzes_rolagem, v_lab_sombras_rolagem, v_lab_saturacao,
                         make_float3(v_lab_dens_r - 1.0f, v_lab_dens_g - 1.0f, v_lab_dens_b - 1.0f),
                         v_lab_pele_matiz * 0.0174532925f, v_lab_pele_sat);
        lin = pc_code_to_lin(la);
    }
"""

# Curvas R, G e B do ajuste atual desenhadas por cima da imagem ("Mostrar curva").
K_CURVE = r"""
// ---------------------------------------------------------------- curva sobreposta
PC_DEVICE float3 pc_curve_overlay(float3 img, float3 cy, int py, int ph) {
    float H = PC_F(ph);
    float fy = (PC_F(py) + 0.5f) / H;
    float th = 1.2f * H / 1080.0f + 0.8f;
    float3 o = img;
    float dm = _fabs(fy - (1.0f - PC_DMID)) * H;
    o = pc_lerp3(o, pc_s3(0.5f), 0.35f * _clampf(1.0f - dm, 0.0f, 1.0f));
    float dr = _fabs(fy - (1.0f - cy.x)) * H;
    float dg = _fabs(fy - (1.0f - cy.y)) * H;
    float db = _fabs(fy - (1.0f - cy.z)) * H;
    o = pc_lerp3(o, make_float3(1.0f, 0.25f, 0.2f), 0.9f * _clampf(th - dr + 1.0f, 0.0f, 1.0f));
    o = pc_lerp3(o, make_float3(0.3f, 1.0f, 0.35f), 0.9f * _clampf(th - dg + 1.0f, 0.0f, 1.0f));
    o = pc_lerp3(o, make_float3(0.35f, 0.55f, 1.0f), 0.9f * _clampf(th - db + 1.0f, 0.0f, 1.0f));
    return o;
}
"""


def _prelude(controls: list[Ctl]) -> str:
    """Converte os controles da interface para o formato do app (variáveis v_<nome>)."""
    lines = []
    for c in controls:
        typ = {"float": "float", "int": "int", "check": "int", "combo": "int", "color": "float3"}[c.kind]
        lines.append(f"    {typ} {c.var} = {c.app_expr()};")
    return "\n".join(lines) + "\n"


def source(kind: str, dialect: str = DCTL, values: dict | None = None, title: str = "") -> str:
    """Código-fonte completo de um nó (`cor`, `textura` ou `projetor`) no dialeto pedido."""
    sp = spec(kind, dialect)
    controls = _with_defaults(sp.controls, values)
    head = (f"// {APP_NAME} {__version__} - {ascii_text(title or FILE_NAMES[kind][:-5])}\n"
            "// Gerado pelo PeliculaConverter. Nao edite: gere de novo pelo app (Configuracoes > Plugin para o "
            "DaVinci Resolve).\n")
    kernel = sp.kernel.replace("PC_DEVICE ", "__DEVICE__ " if dialect == DCTL else "")
    out = []
    if dialect == GLSL:
        out.append(_GLSL_HEADER)
        out.append("in vec2 v_uv;\nout vec4 f_out;\n")
        out.append("uniform sampler2D t_img;\nuniform int u_frame;\n#define PC_FRAME u_frame\n")
        out.append("#define PC_RGB(X, Y) texelFetch(t_img, ivec2((X), (Y)), 0).rgb\n")
    else:
        out.append(head)
        out.append(_DCTL_HEADER)
        if sp.texture:
            out.append(_FRAME_DCTL)
            out.append("#define PC_RGB(X, Y) make_float3(_tex2D(p_TexR, (X), (Y)), _tex2D(p_TexG, (X), (Y)), "
                       "_tex2D(p_TexB, (X), (Y)))\n")
    out.append("\n")
    out += [_ui_decl(c, dialect) for c in controls]
    out.append("\n")
    out.append(_define("PC_DSLOPE", look.D_SLOPE) + _define("PC_DMID", look.D_MID) + _define("PC_DP", look.D_P))
    out.append(sp.tables)
    out.append(kernel)
    pre = _prelude(controls)
    if dialect == DCTL:
        if sp.texture:
            sig = ("__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, __TEXTURE__ p_TexR, "
                   "__TEXTURE__ p_TexG, __TEXTURE__ p_TexB)")
            first = ""
        else:
            sig = ("__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, "
                   "float p_B)")
            first = "    float3 rgb = make_float3(p_R, p_G, p_B);\n"
        out.append(f"\n{sig}\n{{\n{first}{pre}{sp.body}    return res;\n}}\n")
    else:
        if sp.texture:
            first = ("    int p_Width = textureSize(t_img, 0).x;\n    int p_Height = textureSize(t_img, 0).y;\n"
                     "    int p_X = int(gl_FragCoord.x);\n    int p_Y = int(gl_FragCoord.y);\n")
        else:
            first = ("    int p_Width = textureSize(t_img, 0).x;\n    int p_Height = textureSize(t_img, 0).y;\n"
                     "    int p_X = int(gl_FragCoord.x);\n    int p_Y = int(gl_FragCoord.y);\n"
                     "    vec3 rgb = texelFetch(t_img, ivec2(gl_FragCoord.xy), 0).rgb;\n")
        out.append(f"\nvoid main() {{\n{first}{pre}{sp.body}    f_out = vec4(res, 1.0);\n}}\n")
    return ascii_source("".join(out))


def ascii_source(text: str) -> str:
    """Tira os acentos dos comentários: o arquivo .dctl sai só com ASCII (nenhum compilador reclama)."""
    for a, b in (("→", "->"), ("—", "-"), ("–", "-"), ("×", "x"), ("•", "-"), ("²", "2"), ("ⁿ", "n")):
        text = text.replace(a, b)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def ui_uniforms(kind: str, values: dict) -> dict[str, Any]:
    """Valores dos controles (no formato da interface) para rodar o dialeto GLSL nos testes."""
    out = {}
    for c in spec(kind, GLSL).controls:
        v = values.get(c.key, c.default) if c.key else c.default
        if not c.key and c.name in DERIVED:
            v = _derived(c.name, values)
        out[c.name] = c.ui_value(v)
    return out


# ------------------------------------------------------------------ ruído (comum a Textura e Projetor)
K_RAND = r"""
// ---------------------------------------------------------------- ruído determinístico (mesmo do app)
PC_DEVICE uint pc_pcg(uint v) {
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}
PC_DEVICE float pc_rnd(uint a, uint b, uint c) {
    return PC_F(pc_pcg(a + pc_pcg(b + pc_pcg(c)))) * (1.0f / 4294967296.0f);
}
// _hash() e _vnoise() de look.py (tremor, cintilação e eventos dos defeitos)
PC_DEVICE float pc_hash(int i, int s) {
    uint x = PC_U(i) * 0x9E3779B1u + PC_U(s) * 0x85EBCA77u + 0x165667B1u;
    x = x ^ (x >> 15u);
    x = x * 0x2C1B3C6Du;
    x = x ^ (x >> 12u);
    x = x * 0x297A2D39u;
    x = x ^ (x >> 15u);
    return PC_F(x) / 4294967295.0f;
}
PC_DEVICE float pc_vnoise(float x, int s) {
    float fi = _floorf(x);
    float f = x - fi;
    float u = f * f * (3.0f - 2.0f * f);
    int i = PC_I(fi);
    return (pc_hash(i, s) * (1.0f - u) + pc_hash(i + 1, s) * u) * 2.0f - 1.0f;
}
PC_DEVICE float pc_vnoise2(float x, float y) {
    float ix = _floorf(x);
    float iy = _floorf(y);
    float fx = x - ix;
    float fy = y - iy;
    float ux = fx * fx * (3.0f - 2.0f * fx);
    float uy = fy * fy * (3.0f - 2.0f * fy);
    uint bx = PC_U(PC_I(ix) + 65536);
    uint by = PC_U(PC_I(iy) + 65536);
    float a = pc_rnd(bx, by, 911u);
    float c = pc_rnd(bx + 1u, by, 911u);
    float d = pc_rnd(bx, by + 1u, 911u);
    float e = pc_rnd(bx + 1u, by + 1u, 911u);
    return pc_lerp(pc_lerp(a, c, ux), pc_lerp(d, e, ux), uy);
}
PC_DEVICE float pc_fbm2(float x, float y) {
    float v = 0.0f;
    float a = 0.5f;
    for (int i = 0; i < 4; i++) {
        v = v + a * pc_vnoise2(x, y);
        x = x * 2.03f + 17.0f;
        y = y * 2.03f + 17.0f;
        a = a * 0.5f;
    }
    return v / 0.9375f;
}
"""

# ------------------------------------------------------------------ Textura
K_TEXTURA = r"""
// ---------------------------------------------------------------- lente, vinheta, brilho e grão
PC_DEVICE float2 pc_lens(float u, float v, float W, float H, float dist, float k) {
    float qx = (u - 0.5f) * W / (0.5f * H);
    float qy = (v - 0.5f) * H / (0.5f * H);
    float rc2 = (W * W) / (H * H) + 1.0f;
    float f = (1.0f + dist * (qx * qx + qy * qy)) / (1.0f + _fmaxf(dist, 0.0f) * rc2) * k;
    return make_float2(qx * f * (0.5f * H) / W + 0.5f, qy * f * (0.5f * H) / H + 0.5f);
}
PC_DEVICE float pc_vignette(float u, float v, float W, float H, float amt, float rad, float soft, float rnd) {
    float px = (u - 0.5f) * 2.0f;
    float py = (v - 0.5f) * 2.0f;
    float ax = pc_lerp(1.0f, W / H, rnd);
    px = px * ax;
    float d = _sqrtf(px * px + py * py) / _sqrtf(ax * ax + 1.0f);
    float t = pc_smooth(rad - soft * 0.5f, rad + soft * 0.5f, d);
    return _exp2f(-amt * 2.0f * t);
}
// ruído de gradiente intercalado: gira a espiral de amostras de pixel a pixel sem formar manchas
PC_DEVICE float pc_ign(float x, float y) {
    float a = 0.06711056f * x + 0.00583715f * y;
    float b = 52.9829189f * (a - _floorf(a));
    return b - _floorf(b);
}
PC_DEVICE float3 pc_extract(float3 lin, float thr, float limit, int lum_only) {
    float l = pc_luma(lin);
    float k = (thr > 0.0f) ? pc_smooth(thr * 0.5f, thr * 1.5f, l) : 1.0f;
    float3 e = lin * k;
    e = make_float3(e.x / (1.0f + e.x / limit), e.y / (1.0f + e.y / limit), e.z / (1.0f + e.z / limit));
    if (lum_only == 1) e = pc_s3(pc_luma(e));
    return e;
}
PC_DEVICE float4 pc_gauss4(uint qx, uint qy, uint s) {
    float a1 = _fmaxf(pc_rnd(qx, qy, s), 1e-7f);
    float a2 = pc_rnd(qx, qy, s + 1u);
    float b1 = _fmaxf(pc_rnd(qx, qy, s + 2u), 1e-7f);
    float b2 = pc_rnd(qx, qy, s + 3u);
    float ra = _sqrtf(-2.0f * _logf(a1));
    float rb = _sqrtf(-2.0f * _logf(b1));
    return make_float4(ra * _cosf(6.2831853f * a2), ra * _sinf(6.2831853f * a2),
                       rb * _cosf(6.2831853f * b2), rb * _sinf(6.2831853f * b2));
}
PC_DEVICE float pc_cubw(float v, int k) {
    float n1 = 1.0f - v;
    float n2 = 2.0f - v;
    float n3 = 3.0f - v;
    float sx = n1 * n1 * n1;
    float sy = n2 * n2 * n2;
    float sz = n3 * n3 * n3;
    float x = sx;
    float y = sy - 4.0f * sx;
    float z = sz - 4.0f * sy + 6.0f * sx;
    float w = 6.0f - x - y - z;
    float r = (k == 0) ? x : ((k == 1) ? y : ((k == 2) ? z : w));
    return r * (1.0f / 6.0f);
}
// B-spline cúbica sobre a grade do ruído (o texBicubic do app, sem a filtragem do hardware)
PC_DEVICE float4 pc_noise(float u, float v, int gw, int gh, uint s) {
    float x = u * PC_F(gw) - 0.5f;
    float y = v * PC_F(gh) - 0.5f;
    float ix = _floorf(x);
    float iy = _floorf(y);
    float fx = x - ix;
    float fy = y - iy;
    float4 acc = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
    for (int b = 0; b < 4; b++) {
        float wy = pc_cubw(fy, b);
        int ty = pc_clampi(PC_I(iy) - 1 + b, 0, gh - 1);
        for (int a = 0; a < 4; a++) {
            float wx = pc_cubw(fx, a);
            int tx = pc_clampi(PC_I(ix) - 1 + a, 0, gw - 1);
            acc = acc + pc_gauss4(PC_U(tx), PC_U(ty), s) * (wx * wy);
        }
    }
    return acc;
}
PC_DEVICE float3 pc_apply_grain(float3 y, float4 nf, float4 nc, float rough, float chroma, float3 resp, float amt) {
    float r = rough;
    float4 n = (nf * (1.0f - r) + nc * r) * (1.0f / _sqrtf((1.0f - r) * (1.0f - r) + r * r));
    float c = chroma;
    float3 g = (pc_s3(n.w) * (1.0f - c) + make_float3(n.x, n.y, n.z) * c)
               * (1.0f / _sqrtf((1.0f - c) * (1.0f - c) + c * c));
    float L = _clampf(pc_luma(y), 0.0f, 1.0f);
    float a0 = (L - 0.10f) / 0.16f;
    float a1 = (L - 0.45f) / 0.22f;
    float a2 = (L - 0.88f) / 0.16f;
    float w = resp.x * _expf(-a0 * a0) + resp.y * _expf(-a1 * a1) + resp.z * _expf(-a2 * a2);
    return y + g * (amt * w);
}
"""


def _indent(code: str, n: int) -> str:
    pad = " " * n
    return "\n".join((pad + ln) if ln.strip() else ln for ln in code.splitlines()) + "\n"


def _bilin(name: str, px: str, py: str) -> str:
    """Amostra bilinear (como o filtro LINEAR do app) na posição em pixels (px, py) da imagem."""
    return f"""float3 {name};
{{
    float gx_ = ({px}) - 0.5f;
    float gy_ = ({py}) - 0.5f;
    float x0f_ = _floorf(gx_);
    float y0f_ = _floorf(gy_);
    float ax_ = gx_ - x0f_;
    float ay_ = gy_ - y0f_;
    int x0_ = pc_clampi(PC_I(x0f_), 0, p_Width - 1);
    int x1_ = pc_clampi(PC_I(x0f_) + 1, 0, p_Width - 1);
    int y0_ = pc_clampi(PC_I(y0f_), 0, p_Height - 1);
    int y1_ = pc_clampi(PC_I(y0f_) + 1, 0, p_Height - 1);
    {name} = pc_lerp3(pc_lerp3(PC_RGB(x0_, y0_), PC_RGB(x1_, y0_), ax_),
                      pc_lerp3(PC_RGB(x0_, y1_), PC_RGB(x1_, y1_), ax_), ay_);
}}"""


def _glow(name: str, flag: str, sigma: str, thr: str, limit: str, lum_only: int, salt: int) -> str:
    """Brilho em volta das luzes numa passada: amostras com distribuição gaussiana (pesos iguais) numa
    espiral dourada girada por pixel (padrão fixo, que não pisca entre quadros)."""
    return f"""float3 {name} = pc_s3(0.0f);
if ({flag} == 1) {{
    float sg_ = _fmaxf({sigma}, 0.5f);
    float rot_ = (pc_ign(PC_F(p_X), PC_F(p_Y)) + {salt}.0f * 0.618034f) * 6.2831853f;
    float3 acc_ = pc_s3(0.0f);
    for (int i_ = 0; i_ < ns; i_++) {{
        float q_ = (PC_F(i_) + 0.5f) / PC_F(ns);
        float rr_ = sg_ * _sqrtf(-2.0f * _logf(1.0f - q_));
        float an_ = PC_F(i_) * 2.39996323f + rot_;
        int sx_ = pc_clampi(PC_I(_floorf(fx + rr_ * _cosf(an_))), 0, p_Width - 1);
        int sy_ = pc_clampi(PC_I(_floorf(fy + rr_ * _sinf(an_))), 0, p_Height - 1);
        acc_ = acc_ + pc_extract(pc_code_to_lin(PC_RGB(sx_, sy_)), {thr}, {limit}, {lum_only});
    }}
    {name} = acc_ * (1.0f / PC_F(ns));
}}"""


def _textura_body() -> str:
    lens = _indent(_bilin("cg", "pg.x * W", "pg.y * H"), 8)
    ca = _indent(_bilin("cr", "pr.x * W", "pr.y * H") + "\n" + _bilin("cb", "pb.x * W", "pb.y * H"), 12)
    glows = _indent("\n".join([
        _glow("gm", "mist", "v_nevoa_raio * scale", "0.0f", "3.0f", 0, 31),
        "if (mist == 1) lin = pc_lerp3(lin, gm, 0.3f * v_nevoa_forca) + gm * (0.35f * v_nevoa_forca);",
        _glow("gb", "bloom", "v_bloom_raio * scale", "0.18f * _exp2f(v_bloom_limiar)", "6.0f", 0, 37),
        "if (bloom == 1) lin = lin + gb * (v_bloom_forca * 0.22f);",
        _glow("gh", "hal", "v_hal_raio * PC_GAUGE[gi * 7 + 5] * scale", "0.18f * _exp2f(v_hal_limiar)", "8.0f", 1,
              41),
        "if (hal == 1) lin = lin + v_hal_cor * (gh.x * v_hal_forca * 0.32f);",
    ]), 8)
    return r"""
    float W = PC_F(p_Width);
    float H = PC_F(p_Height);
    float scale = H / 1080.0f;
    float fx = PC_F(p_X) + 0.5f;
    float fy = PC_F(p_Y) + 0.5f;
    float u = fx / W;
    float v = fy / H;
    int gi = v_bitola;
    float iso = PC_ISO[v_iso];
    int ns = PC_QUAL[v_qualidade];
    // lente: distorção e aberração cromática (lens() do app)
    float dist = (v_lente_on == 1) ? v_distorcao : 0.0f;
    float ca = (v_lente_on == 1) ? (v_aberracao * scale / (0.5f * H)) : 0.0f;
    float2 pg = pc_lens(u, v, W, H, dist, 1.0f);
    float3 c0 = PC_RGB(p_X, p_Y);
    if (dist != 0.0f || ca != 0.0f) {
""" + lens + r"""        c0 = cg;
        if (ca != 0.0f) {
            float2 pr = pc_lens(u, v, W, H, dist, 1.0f + ca);
            float2 pb = pc_lens(u, v, W, H, dist, 1.0f - ca);
""" + ca + r"""            c0 = make_float3(cr.x, cg.y, cb.z);
        }
    }
    // maciez da bitola e da lente / recuperar detalhe (gaussiana em luz linear)
    float sig_g = (v_bitola_desfoque_on == 1) ? PC_GAUGE[gi * 7 + 2] * v_bitola_resolucao : 0.0f;
    float sig_u = (v_lente_on == 1) ? v_raio_maciez * v_maciez * 2.0f : 0.0f;
    float sig_m = PC_MTF[v_mtf] * 2.0f * v_mtf_forca;  // MTF da pelicula (look.mtf_sigma)
    float sig_r = 0.0f;  // 1.6: maciez pelo grao (grao.soft_sigma)
    if (v_grao_maciez > 0.0f && v_grao_on == 1 && v_grao_forca > 0.0f)
        sig_r = PC_GRAIN_SOFT_K * 0.8f * v_grao_tamanho * PC_GAUGE[gi * 7 + 0] * _powf(iso / 250.0f, 0.18f)
                * v_grao_maciez;
    float soft = _sqrtf(sig_g * sig_g + sig_u * sig_u + sig_m * sig_m + sig_r * sig_r) * scale;
    float sharp = (v_lente_on == 1) ? v_nitidez : 0.0f;
    float sigma = 0.0f;
    float soft_mix = 0.0f;
    if (soft > 0.05f) {
        sigma = soft;
        soft_mix = 1.0f;
    } else if (sharp > 0.0f) {
        sigma = _fmaxf(v_raio_maciez * scale, 0.6f);
    }
    // 1.6: diferenca de nitidez entre camadas (grao.layer_softness): um sigma por canal
    int layers = 0;
    float3 s3 = pc_s3(0.0f);
    if (v_mtf_camadas > 0.0f) {
        int lo = (v_mtf_copia == 1) ? 3 : 0;
        float kl = 2.0f * v_mtf_camadas * PC_PX_MM[gi] * 0.001f * scale;
        float dr = PC_MTF_LAYERS[lo] * kl;
        float dg = PC_MTF_LAYERS[lo + 1] * kl;
        float db = PC_MTF_LAYERS[lo + 2] * kl;
        float3 t3 = make_float3(_sqrtf(soft * soft + dr * dr), _sqrtf(soft * soft + dg * dg),
                                _sqrtf(soft * soft + db * db));
        float tm = _fmaxf(t3.x, _fmaxf(t3.y, t3.z));
        if (tm > 0.05f) {
            layers = 1;
            s3 = t3;
            sigma = tm;
            soft_mix = 1.0f;
        }
    }
    float vig_amt = _fminf(((v_lente_on == 1) ? v_vinheta : 0.0f) + PC_GAUGE[gi * 7 + 4] * v_bitola_vinheta, 1.5f);
    float vig = (vig_amt > 0.0f)
        ? pc_vignette(u, v, W, H, vig_amt, v_vinheta_raio, v_vinheta_suavidade, v_vinheta_redondeza) : 1.0f;
    int hal = (v_hal_on == 1 && v_hal_forca > 0.0f) ? 1 : 0;
    int bloom = (v_bloom_on == 1 && v_bloom_forca > 0.0f) ? 1 : 0;
    int mist = (v_bloom_on == 1 && v_nevoa_forca > 0.0f) ? 1 : 0;
    float3 y = c0;
    if (sigma > 0.0f || vig != 1.0f || hal == 1 || bloom == 1 || mist == 1) {
        float3 lin = pc_code_to_lin(c0) * vig;
        if (sigma > 0.0f) {
            int cx = pc_clampi(PC_I(_floorf(pg.x * W)), 0, p_Width - 1);
            int cy = pc_clampi(PC_I(_floorf(pg.y * H)), 0, p_Height - 1);
            int rad = PC_I(_ceilf(sigma * 3.0f));
            int stp = 1;
            if (rad > 6) {
                stp = PC_I(_ceilf(PC_F(rad) / 6.0f));
                rad = 6 * stp;
            }
            // 1.6: com a diferenca entre camadas, um sigma por canal no mesmo laco (sem ela, o calculo de antes)
            float3 kk3 = pc_s3(-0.5f / (sigma * sigma));
            if (layers == 1) {
                float3 sc = pc_max3(s3, 1e-3f);
                kk3 = make_float3(-0.5f / (sc.x * sc.x), -0.5f / (sc.y * sc.y), -0.5f / (sc.z * sc.z));
            }
            float3 acc = pc_s3(0.0f);
            float3 wsum = pc_s3(0.0f);
            for (int j = -rad; j <= rad; j += stp) {
                for (int i = -rad; i <= rad; i += stp) {
                    float d2 = PC_F(i * i + j * j);
                    float w0 = _expf(d2 * kk3.x);
                    float3 w = (layers == 1) ? make_float3(w0, _expf(d2 * kk3.y), _expf(d2 * kk3.z)) : pc_s3(w0);
                    int sx = pc_clampi(cx + i, 0, p_Width - 1);
                    int sy = pc_clampi(cy + j, 0, p_Height - 1);
                    acc = acc + pc_code_to_lin(PC_RGB(sx, sy)) * w;
                    wsum = wsum + w;
                }
            }
            float3 b = make_float3(acc.x * (vig / wsum.x), acc.y * (vig / wsum.y), acc.z * (vig / wsum.z));
            float3 base = pc_lerp3(lin, b, soft_mix);
            lin = pc_max3(base + (lin - b) * sharp, 0.0f);
        }
""" + glows + r"""        y = pc_lin_to_code(lin);
    }
    if (v_grao_on == 1 && v_grao_forca > 0.0f) {
        float iso_amt = _powf(iso / 250.0f, 0.35f);
        float iso_size = _powf(iso / 250.0f, 0.18f);
        float size = 0.8f * v_grao_tamanho * PC_GAUGE[gi * 7 + 0] * iso_size * scale;
        float gsz = _fmaxf(size, 1.0f);
        int seed = v_grao_semente * 7919 + ((v_grao_animado == 1) ? PC_FRAME : 0);
        int gw = PC_I(_ceilf(W / gsz));
        int gh2 = PC_I(_ceilf(H / gsz));
        gw = gw < 2 ? 2 : gw;
        gh2 = gh2 < 2 ? 2 : gh2;
        float amt = 0.011f * v_grao_forca * PC_GAUGE[gi * 7 + 1] * iso_amt * _sqrtf(_fminf(1.0f, size));
        uint s8 = PC_U(seed) * 8u;
        float4 nf = pc_noise(u, v, gw, gh2, s8) * 2.08f;
        float4 nc = pc_noise(u * 0.4347f + 0.311f, v * 0.4347f + 0.173f, gw, gh2, s8) * 2.08f;
        y = pc_apply_grain(y, nf, nc, v_grao_aspereza, v_grao_cor,
                           make_float3(v_grao_sombras, v_grao_meios, v_grao_luzes), amt);
    }
    float3 res = pc_clamp3(y, 0.0f, 1.0f);
"""


QUALITY_SAMPLES = {"rapida": 32, "normal": 64, "alta": 128}


def textura_controls() -> list[Ctl]:
    return [
        ctl("bitola"), ctl("iso", "Sensibilidade ISO"),
        ctl("bitola_desfoque_on"), ctl("bitola_resolucao"), ctl("bitola_vinheta"),
        ctl("mtf", "MTF da pelicula"), ctl("mtf_forca", "MTF - Quantidade"),
        ctl("mtf_camadas", "MTF - Diferenca entre camadas"),
        Ctl("ui_mtf_copia", "MTF - Camadas com copia", "check", 0, section="pelicula",
            tip="Ligue quando houver copia print no no Cor ou Laboratorio: na copia o azul fica mais macio "
                "(Diferenca entre camadas)."),
        ctl("grao_on", "Grao"), ctl("grao_forca", "Grao - Intensidade"), ctl("grao_tamanho", "Grao - Tamanho"),
        ctl("grao_aspereza", "Grao - Aspereza"), ctl("grao_cor", "Grao - Colorido"),
        ctl("grao_sombras", "Grao - Nas sombras"), ctl("grao_meios", "Grao - Nos tons medios"),
        ctl("grao_luzes", "Grao - Nas altas luzes"), ctl("grao_animado", "Grao - Muda a cada quadro"),
        ctl("grao_semente", "Grao - Semente"), ctl("grao_maciez", "Grao - Maciez pelo grao"),
        ctl("hal_on", "Halacao"), ctl("hal_forca", "Halacao - Intensidade"),
        ctl("hal_raio", "Halacao - Raio px em 1080p"), ctl("hal_limiar", "Halacao - Limiar EV"),
        ctl("hal_cor", "Halacao - Cor"),
        ctl("bloom_on", "Bloom e difusao"), ctl("bloom_forca", "Bloom - Intensidade"),
        ctl("bloom_raio", "Bloom - Raio px em 1080p"), ctl("bloom_limiar", "Bloom - Limiar EV"),
        ctl("nevoa_forca", "Nevoa - Filtro difusor"), ctl("nevoa_raio", "Nevoa - Raio px em 1080p"),
        ctl("lente_on", "Lente"), ctl("maciez", "Lente - Maciez"), ctl("raio_maciez", "Lente - Raio da maciez"),
        ctl("nitidez", "Lente - Recuperar detalhe"), ctl("aberracao", "Lente - Aberracao cromatica"),
        ctl("distorcao", "Lente - Distorcao"), ctl("vinheta", "Lente - Vinheta"),
        ctl("vinheta_raio", "Vinheta - Raio"), ctl("vinheta_suavidade", "Vinheta - Suavidade"),
        ctl("vinheta_redondeza", "Vinheta - Redondeza"),
        Ctl("ui_qualidade", "Qualidade do brilho", "combo", "normal",
            choices=[("rapida", "Rapida"), ("normal", "Normal"), ("alta", "Alta")],
            tip="Amostras da halacao do bloom e da nevoa. Alta fica mais suave e mais lenta."),
    ]


def _mtf_table(dialect: str) -> str:
    return _table(dialect, "PC_MTF", [look.MTF_SIGMA[k] for k, _l in params.MTFS])


def _grao_tables(dialect: str) -> str:
    """Constantes do grão e da textura da 1.6 (`pelicula/grao.py`) para os nós e o OpenFX."""
    from . import grao
    out = _define("PC_GRAIN_SOFT_K", grao.GRAIN_SOFT_K)
    # nitidez por camada: px@1080 por mm de cada bitola e as diferenças das camadas (sem cópia, com cópia), em µm
    out += _table(dialect, "PC_PX_MM", [grao.REF_WIDTH_PX / grao.frame_width_mm(k) for k, _l in params.BITOLAS])
    out += _table(dialect, "PC_MTF_LAYERS", list(grao.layer_dsigma_um(False)) + list(grao.layer_dsigma_um(True)))
    copias = [k for k, _l in params.COPIAS]
    lab_copias = [k for k, _l in params.COPIAS_LAB]
    out += f"#define PC_COPIA_NENHUMA {copias.index('nenhuma')}\n"
    out += f"#define PC_LAB_COPIA_NENHUMA {lab_copias.index('nenhuma')}\n"
    return out


def _gauge_tables(dialect: str) -> str:
    g = []
    for key, _label in params.BITOLAS:
        d = look.GAUGES[key]
        g += [d["grain_size"], d["grain_amt"], d["blur"], d["weave"], d["vignette"], d["hal"], d["aspect"] or 0.0]
    out = _table(dialect, "PC_GAUGE", g)
    out += _table(dialect, "PC_ISO", [float(v) for v, _l in params.ISOS])
    out += _table(dialect, "PC_QUAL", [QUALITY_SAMPLES[k] for k in ("rapida", "normal", "alta")], "int")
    return out


# ------------------------------------------------------------------ Projetor
FPS_CHOICES = [("23.976", "23976"), ("24", "24"), ("25", "25"), ("29.97", "2997"), ("30", "30"), ("48", "48"),
               ("50", "50"), ("59.94", "5994"), ("60", "60")]
FPS_VALUES = {"23.976": 24000 / 1001, "24": 24.0, "25": 25.0, "29.97": 30000 / 1001, "30": 30.0, "48": 48.0,
              "50": 50.0, "59.94": 60000 / 1001, "60": 60.0}


def projetor_controls() -> list[Ctl]:
    return [
        Ctl("ui_fps", "Quadros por segundo", "combo", "24", choices=list(FPS_CHOICES),
            tip="Os mesmos da linha do tempo: o tremor e os defeitos seguem o tempo real."),
        ctl("bitola"),
        ctl("proj_on", "Projetor"), ctl("tremor_x", "Tremor horizontal px em 1080p"),
        ctl("tremor_y", "Tremor vertical px em 1080p"), ctl("tremor_rot", "Tremor de rotacao graus"),
        ctl("tremor_vel"), ctl("cintilacao", "Cintilacao EV"), ctl("cintilacao_vel"),
        ctl("desg_on", "Defeitos da pelicula"),
        ctl("poeira_on", "Poeira"), ctl("poeira", "Poeira - Quantidade"), ctl("poeira_tamanho", "Poeira - Tamanho"),
        ctl("poeira_tipo", "Poeira - Tipo"),
        ctl("riscos_on", "Riscos"), ctl("riscos", "Riscos - Quantidade"),
        ctl("riscos_largura", "Riscos - Largura px"),
        ctl("cabelo_on", "Fio de cabelo"), ctl("cabelo", "Fio - Frequencia"), ctl("cabelo_tamanho", "Fio - Tamanho"),
        ctl("manchas_on", "Manchas quimicas"), ctl("manchas", "Manchas - Frequencia"),
        ctl("queima_on", "Claroes de fim de rolo"), ctl("queima", "Claroes - Frequencia"),
        ctl("marcas_on", "Marcas de troca de rolo"), ctl("marcas_intervalo", "Marcas - Intervalo s"),
        ctl("cor_instavel_on", "Cor instavel"), ctl("cor_instavel", "Cor instavel - Intensidade"),
        ctl("emenda_on", "Emendas"), ctl("emenda", "Emendas - Frequencia"),
        ctl("vazamento_on", "Vazamento de luz"), ctl("vazamento", "Vazamento - Intensidade"),
        ctl("vazamento_cor", "Vazamento - Cor"), ctl("vazamento_vel", "Vazamento - Velocidade"),
        ctl("desgaste_semente", "Defeitos - Semente"),
        ctl("mold_on", "Moldura"), ctl("proporcao"), ctl("cantos"), ctl("borda_suave"), ctl("borda_irregular"),
        ctl("cor_barras"),
    ]


def _projetor_tables(dialect: str) -> str:
    out = _table(dialect, "PC_FPS", [FPS_VALUES[k] for k, _v in FPS_CHOICES])
    prop = [0.0 if key == "original" else (-1.0 if key == "bitola" else float(key)) for key, _l in params.PROPORCOES]
    return out + _table(dialect, "PC_PROP", prop)


K_PROJETOR = r"""
// ---------------------------------------------------------------- defeitos e moldura (damage() e frameMask() do app)
PC_DEVICE float pc_seg(float px, float py, float ax, float ay, float bx, float by) {
    float pax = px - ax;
    float pay = py - ay;
    float bax = bx - ax;
    float bay = by - ay;
    float h = _clampf((pax * bax + pay * bay) / _fmaxf(bax * bax + bay * bay, 1e-6f), 0.0f, 1.0f);
    float dx = pax - bax * h;
    float dy = pay - bay * h;
    return _sqrtf(dx * dx + dy * dy);
}
PC_DEVICE float3 pc_leak(float u, float v, float a, float4 L0, float4 L1, float3 col, float amt) {
    float d0x = (u - L0.x) * a;
    float d0y = v - L0.y;
    float d1x = (u - L1.x) * a;
    float d1y = v - L1.y;
    float acc = _expf(-(d0x * d0x + d0y * d0y) / _fmaxf(L0.z * L0.z, 0.0025f) * 2.0f) * L0.w
              + _expf(-(d1x * d1x + d1y * d1y) / _fmaxf(L1.z * L1.z, 0.0025f) * 2.0f) * L1.w;
    return col * (acc * amt * 1.6f);
}
PC_DEVICE float3 pc_damage(float3 y, float u, float v, float W, float H, int frame, int seed, float stain_amt,
                           float stain_seed, float hair_on, float hair_seed, float hair_size, float hair_wig,
                           float cue, float splice_on, float splice_y, float dust, float dust_size, int dust_type,
                           float scratch, float scratch_w) {
    float pxx = u * (W / H) * 1080.0f;
    float pxy = v * 1080.0f;
    float Wd = W / H * 1080.0f;
    if (stain_amt > 0.0f) {
        float qx = pxx / 1080.0f * 2.2f + stain_seed * 7.31f;
        float qy = pxy / 1080.0f * 2.2f + stain_seed * 3.17f;
        float n = pc_fbm2(qx, qy);
        float body = pc_smooth(0.6f, 0.71f, n);
        float rim = pc_smooth(0.56f, 0.6f, n) * (1.0f - pc_smooth(0.6f, 0.67f, n));
        float3 tint = (pc_mod(stain_seed * 0.37f, 1.0f) < 0.5f) ? make_float3(1.2f, 0.86f, 1.12f)
                                                              : make_float3(0.9f, 1.12f, 0.84f);
        y = pc_lerp3(y, y * tint * 1.08f + pc_s3(0.04f), body * stain_amt);
        y = y * (1.0f - 0.08f * rim * stain_amt);
    }
    if (hair_on > 0.0f) {
        uint hs = PC_U(PC_I(hair_seed));
        float side = _floorf(pc_rnd(hs, 1u, 77u) * 4.0f);
        float t0 = 0.12f + 0.76f * pc_rnd(hs, 2u, 77u);
        float ax = Wd + 4.0f;
        float ay = t0 * 1080.0f;
        float dirx = -1.0f;
        float diry = 0.0f;
        if (side < 1.0f) { ax = t0 * Wd; ay = -4.0f; dirx = 0.0f; diry = 1.0f; }
        else if (side < 2.0f) { ax = t0 * Wd; ay = 1084.0f; dirx = 0.0f; diry = -1.0f; }
        else if (side < 3.0f) { ax = -4.0f; ay = t0 * 1080.0f; dirx = 1.0f; diry = 0.0f; }
        float L = (120.0f + 200.0f * pc_rnd(hs, 3u, 77u)) * hair_size;
        float perpx = -diry;
        float perpy = dirx;
        float bend = (pc_rnd(hs, 4u, 77u) - 0.5f) * 0.9f * L;
        float curl = (0.05f + 0.1f * pc_rnd(hs, 5u, 77u)) * L;
        float ph = pc_rnd(hs, 6u, 77u) * 6.2831853f;
        float dmin = 1e9f;
        float prx = ax;
        float pry = ay;
        for (int i = 1; i <= 40; i++) {
            float t = PC_F(i) / 40.0f;
            float off = bend * t * t + curl * _sinf(t * 7.5f + ph) * t + hair_wig * t * 1.5f;
            float ext = L * t * (0.75f + 0.25f * _cosf(t * 3.0f + ph));
            float bx = ax + dirx * ext + perpx * off;
            float by = ay + diry * ext + perpy * off;
            dmin = _fminf(dmin, pc_seg(pxx, pxy, prx, pry, bx, by));
            prx = bx;
            pry = by;
        }
        float th = 1.6f * hair_size;
        float m = 1.0f - pc_smooth(th * 0.4f, th + 1.4f, dmin);
        y = y * (1.0f - 0.9f * m);
    }
    if (cue > 0.0f) {
        float ccx = Wd - 1080.0f * 0.105f;
        float ccy = 1080.0f * 0.1f;
        float r = 1080.0f * 0.021f;
        float ddx = pxx - ccx;
        float ddy = pxy - ccy;
        float d = _sqrtf(ddx * ddx + ddy * ddy) + (pc_vnoise2(pxx * 0.3f, pxy * 0.3f) - 0.5f) * 2.2f;
        float disc = pc_smooth(r, r - 1.6f, d);
        float rim = pc_smooth(r + 2.6f, r + 0.4f, d) - disc;
        y = pc_lerp3(y, pc_s3(0.025f), disc * 0.9f);
        y = pc_lerp3(y, make_float3(0.9f, 0.88f, 0.8f), _fmaxf(rim, 0.0f) * 0.55f);
    }
    if (splice_on > 0.0f) {
        float yy = splice_y * 1080.0f;
        float line = pc_smooth(2.4f, 0.4f, _fabs(pxy - yy));
        float band = pc_smooth(16.0f, 11.0f, _fabs(pxy - yy - 9.0f));
        y = pc_lerp3(y, make_float3(0.9f, 0.89f, 0.84f), line * 0.6f);
        y = y * (1.0f - 0.1f * band);
    }
    uint fr = PC_U(frame);
    uint sd = PC_U(seed);
    if (dust > 0.0f) {
        float cell = 90.0f;
        int c0x = PC_I(_floorf(pxx / cell));
        int c0y = PC_I(_floorf(pxy / cell));
        float dark = 0.0f;
        float light = 0.0f;
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                int cx = c0x + i;
                int cy = c0y + j;
                uint kx = PC_U(cx + 100000);
                uint ky = PC_U(cy + 100000);
                uint kz = fr * 131u + sd;
                if (pc_rnd(kx, ky, kz) < dust * 0.045f) {
                    float ctx = (PC_F(cx) + pc_rnd(kx, ky, kz + 1u)) * cell;
                    float cty = (PC_F(cy) + pc_rnd(kx, ky, kz + 2u)) * cell;
                    float q3 = pc_rnd(kx, ky, kz + 3u);
                    float rad = dust_size * (0.8f + 3.2f * q3 * q3);
                    float ang = pc_rnd(kx, ky, kz + 4u) * 6.2831853f;
                    float q5 = pc_rnd(kx, ky, kz + 5u);
                    float el = 1.0f + 3.0f * q5 * q5 * q5;
                    float dx = pxx - ctx;
                    float dy = pxy - cty;
                    float rx = (_cosf(ang) * dx + _sinf(ang) * dy) / el;
                    float ry = -_sinf(ang) * dx + _cosf(ang) * dy;
                    float m = pc_smooth(rad, rad * 0.45f, _sqrtf(rx * rx + ry * ry));
                    int is_light = (dust_type == 1 || (dust_type == 2 && pc_rnd(kx, ky, kz + 6u) < 0.5f)) ? 1 : 0;
                    if (is_light == 1) light = _fmaxf(light, m); else dark = _fmaxf(dark, m);
                }
            }
        }
        y = y * (1.0f - 0.88f * dark);
        y = pc_lerp3(y, make_float3(0.93f, 0.92f, 0.88f), light * 0.85f);
    }
    if (scratch > 0.0f) {
        uint epoch = PC_U(frame / 14);
        for (int k = 0; k < 6; k++) {
            uint kx = PC_U(k) + 7000u;
            if (pc_rnd(kx, epoch, sd) < scratch * 0.4f) {
                float x = pc_rnd(kx, epoch, sd + 1u) * Wd + 3.0f * _sinf(PC_F(frame) * 0.37f + PC_F(k))
                        + (pc_rnd(PC_U(k), fr, sd + 5u) - 0.5f) * 2.0f;
                float w = scratch_w * (0.6f + 0.8f * pc_rnd(kx, epoch, sd + 2u));
                float a = pc_smooth(1.0f, 0.0f, _fabs(pxx - x) / w);
                float along = 0.55f + 0.45f * _sinf(pxy * (0.004f + 0.01f * pc_rnd(kx, epoch, sd + 3u))
                                                    + PC_F(k) * 2.1f + PC_F(frame) * 0.2f);
                float vis = 0.35f + 0.65f * pc_rnd(PC_U(k) + 50u, fr, sd);
                y = pc_lerp3(y, make_float3(0.92f, 0.93f, 0.88f), a * along * vis * 0.7f);
            }
        }
    }
    return y;
}
PC_DEVICE float pc_vnoise1(float x) {
    float i = _floorf(x);
    float f = x - i;
    float u = f * f * (3.0f - 2.0f * f);
    float a = pc_rnd(PC_U(PC_I(i) + 100000), 3u, 9u);
    float b = pc_rnd(PC_U(PC_I(i) + 100001), 3u, 9u);
    return pc_lerp(a, b, u) * 2.0f - 1.0f;
}
PC_DEVICE float3 pc_frame_mask(float3 y, float u, float v, float W, float H, float scale, float aspect_t,
                               float corner, float edge_soft, float edge_rough, float3 bar) {
    if (aspect_t <= 0.0f && corner <= 0.0f && edge_rough <= 0.0f) return y;
    float A = W / H;
    float hbx = 0.5f;
    float hby = 0.5f;
    if (aspect_t > 0.0f) {
        if (aspect_t > A) hby = 0.5f * A / aspect_t; else hbx = 0.5f * aspect_t / A;
    }
    float px = (u - 0.5f) * W;
    float py = (v - 0.5f) * H;
    float hx = hbx * W + 0.5f;
    float hy = hby * H + 0.5f;
    float rad = corner * _fminf(hx, hy) * 2.0f;
    float qx = _fabs(px) - hx + rad;
    float qy = _fabs(py) - hy + rad;
    float mx = _fmaxf(qx, 0.0f);
    float my = _fmaxf(qy, 0.0f);
    float sd = _sqrtf(mx * mx + my * my) + _fminf(_fmaxf(qx, qy), 0.0f) - rad;
    if (edge_rough > 0.0f) {
        float n = pc_vnoise1(px * 0.02f / scale + 13.0f) + pc_vnoise1(py * 0.02f / scale + 71.0f)
                + 0.5f * pc_vnoise1(px * 0.11f / scale) + 0.5f * pc_vnoise1(py * 0.11f / scale + 5.0f);
        sd = sd + (n + 1.5f) * edge_rough * 5.0f * scale;
    }
    float soft = _fmaxf(edge_soft * H, 0.7f);
    float m = 1.0f - pc_smooth(-soft, soft, sd);
    return pc_lerp3(bar, y, m);
}
"""

# Parâmetros do quadro (tremor, ganhos e eventos), iguais aos de look.build_plan.
B_FRAME = r"""
    float W = PC_F(p_Width);
    float H = PC_F(p_Height);
    float scale = H / 1080.0f;
    int frame = PC_FRAME;
    float fps = PC_FPS[v_fps];
    float t = PC_F(frame) / fps;
    int gi = v_bitola;
    float weave = PC_GAUGE[gi * 7 + 3];
    float sh_x = 0.0f;
    float sh_y = 0.0f;
    float rot = 0.0f;
    float zoom = 1.0f;
    float g0 = 0.0f;
    float g1 = 0.0f;
    float g2 = 0.0f;
    if (v_proj_on == 1) {
        float ww = weave * scale;
        float vel = v_tremor_vel;
        sh_x = v_tremor_x * ww * (0.7f * pc_vnoise(t * 2.2f * vel, 101) + 0.3f * (pc_hash(frame, 102) * 2.0f - 1.0f));
        sh_y = v_tremor_y * ww * (0.7f * pc_vnoise(t * 1.9f * vel, 103) + 0.3f * (pc_hash(frame, 104) * 2.0f - 1.0f));
        rot = (v_tremor_rot * weave * 0.0174532925f)
            * (0.7f * pc_vnoise(t * 1.6f * vel, 105) + 0.3f * (pc_hash(frame, 106) * 2.0f - 1.0f));
        float margin = _fmaxf(v_tremor_x, v_tremor_y) * ww * 1.1f + _fabs(rot) * W * 0.5f;
        zoom = 1.0f + 2.0f * margin / _fmaxf(1.0f, _fminf(W, H));
        float fl = v_cintilacao * (0.6f * pc_vnoise(t * 7.0f * v_cintilacao_vel, 107)
                                   + 0.4f * (pc_hash(frame, 108) * 2.0f - 1.0f));
        g0 = g0 + fl;
        g1 = g1 + fl;
        g2 = g2 + fl;
    }
    int sd = v_desgaste_semente;
    int dg = v_desg_on;
    float splice_on = 0.0f;
    float splice_y = 0.5f;
    if (dg == 1) {
        if (v_queima_on == 1 && v_queima > 0.0f) {
            int ep = PC_I(_floorf(t / 6.0f));
            if (pc_hash(ep, sd + 401) < v_queima * 0.55f) {
                float st = PC_F(ep) * 6.0f + pc_hash(ep, sd + 402) * 5.0f;
                if (t >= st) {
                    float f = _expf(-(t - st) / 0.13f);
                    g0 = g0 + 2.6f * f;
                    g1 = g1 + 2.0f * f;
                    g2 = g2 + 1.1f * f;
                }
            }
        }
        if (v_cor_instavel_on == 1 && v_cor_instavel > 0.0f) {
            float a = v_cor_instavel * 0.12f;
            g0 = g0 + a * (0.6f * pc_vnoise(t * 5.0f, sd + 410) + 0.4f * (pc_hash(frame, sd + 420) * 2.0f - 1.0f));
            g1 = g1 + a * (0.6f * pc_vnoise(t * 5.0f, sd + 411) + 0.4f * (pc_hash(frame, sd + 421) * 2.0f - 1.0f));
            g2 = g2 + a * (0.6f * pc_vnoise(t * 5.0f, sd + 412) + 0.4f * (pc_hash(frame, sd + 422) * 2.0f - 1.0f));
        }
        if (v_emenda_on == 1 && v_emenda > 0.0f) {
            int ep = PC_I(_floorf(t / 2.5f));
            if (pc_hash(ep, sd + 501) < v_emenda * 0.4f) {
                int sf = PC_I(_floorf((PC_F(ep) * 2.5f + pc_hash(ep, sd + 502) * 2.0f) * fps + 0.5f));
                if (frame == sf) {
                    sh_y = sh_y + 14.0f * scale;
                    splice_on = 1.0f;
                    splice_y = 0.15f + 0.7f * pc_hash(ep, sd + 503);
                } else if (frame == sf + 1) {
                    sh_y = sh_y + 6.0f * scale;
                }
            }
        }
    }
    float hair_on = 0.0f;
    float hair_seed = 0.0f;
    float hair_wig = 0.0f;
    if (dg == 1 && v_cabelo_on == 1 && v_cabelo > 0.0f) {
        int ep = PC_I(_floorf(t / 3.0f));
        if (pc_hash(ep, sd + 201) < v_cabelo * 0.7f) {
            hair_wig = 3.0f * pc_vnoise(t * 9.0f, sd + 202) + 1.2f * (pc_hash(frame, sd + 203) * 2.0f - 1.0f);
            hair_on = 1.0f;
            hair_seed = PC_F(ep - (ep / 100000) * 100000 + sd * 7);
        }
    }
    float stain_amt = 0.0f;
    float stain_seed = 0.0f;
    if (dg == 1 && v_manchas_on == 1 && v_manchas > 0.0f) {
        int ep = frame / 3;
        if (pc_hash(ep, sd + 301) < v_manchas * 0.18f) {
            stain_amt = _fminf(1.0f, 0.5f + v_manchas);
            stain_seed = PC_F(ep - (ep / 9973) * 9973);
        }
    }
    float cue = 0.0f;
    if (dg == 1 && v_marcas_on == 1) {
        int per = PC_I(_floorf(v_marcas_intervalo * fps + 0.5f));
        per = per < 8 ? 8 : per;
        if (frame - (frame / per) * per < 4 && frame >= 4) cue = 1.0f;
    }
    float leak_on = 0.0f;
    float4 L0 = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
    float4 L1 = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
    if (dg == 1 && v_vazamento_on == 1 && v_vazamento > 0.0f) {
        leak_on = 1.0f;
        float tl = t * 0.35f * v_vazamento_vel;
        for (int k = 0; k < 2; k++) {
            float side = (pc_hash(k, sd + 3) < 0.5f) ? 0.0f : 1.0f;
            float bx = side + ((side == 0.0f) ? 0.12f : -0.12f) * pc_vnoise(tl + PC_F(k) * 7.3f, sd + 10 + k);
            float by = 0.5f + 0.55f * pc_vnoise(tl * 0.8f + PC_F(k) * 3.1f, sd + 20 + k);
            float br = 0.35f + 0.2f * pc_vnoise(tl * 1.3f + PC_F(k), sd + 30 + k);
            float ba = _fmaxf(0.0f, 0.55f + 0.6f * pc_vnoise(tl * 1.7f + PC_F(k) * 5.0f, sd + 40 + k));
            if (k == 0) L0 = make_float4(bx, by, br, ba); else L1 = make_float4(bx, by, br, ba);
        }
    }
"""


def _projetor_body() -> str:
    weave = _indent(_bilin("cw", "(rx / W + 0.5f) * W", "(ry / H + 0.5f) * H"), 8)
    return B_FRAME + r"""
    float fx = PC_F(p_X) + 0.5f;
    float fy = PC_F(p_Y) + 0.5f;
    float u = fx / W;
    float v = fy / H;
    float3 c0 = PC_RGB(p_X, p_Y);
    if (sh_x != 0.0f || sh_y != 0.0f || rot != 0.0f || zoom != 1.0f) {
        float px = (u - 0.5f) * W / zoom;
        float py = (v - 0.5f) * H / zoom;
        float cr = _cosf(rot);
        float sr = _sinf(rot);
        float rx = cr * px - sr * py - sh_x;
        float ry = sr * px + cr * py - sh_y;
""" + weave + r"""        c0 = cw;
    }
    float3 y = c0;
    if (g0 != 0.0f || g1 != 0.0f || g2 != 0.0f || leak_on > 0.0f) {
        float3 lin = pc_code_to_lin(c0);
        lin = make_float3(lin.x * _exp2f(g0), lin.y * _exp2f(g1), lin.z * _exp2f(g2));
        if (leak_on > 0.0f) lin = lin + pc_leak(u, v, W / H, L0, L1, v_vazamento_cor, v_vazamento);
        y = pc_lin_to_code(lin);
    }
    float dust = (dg == 1 && v_poeira_on == 1) ? v_poeira : 0.0f;
    float scr = (dg == 1 && v_riscos_on == 1) ? v_riscos : 0.0f;
    if (dust > 0.0f || scr > 0.0f || hair_on > 0.0f || stain_amt > 0.0f || cue > 0.0f || splice_on > 0.0f) {
        y = pc_damage(y, u, v, W, H, frame, sd, stain_amt, stain_seed, hair_on, hair_seed, v_cabelo_tamanho,
                      hair_wig, cue, splice_on, splice_y, dust, v_poeira_tamanho, v_poeira_tipo, scr,
                      v_riscos_largura);
    }
    if (v_mold_on == 1) {
        float asp = PC_PROP[v_proporcao];
        if (asp < 0.0f) asp = PC_GAUGE[gi * 7 + 6];
        y = pc_frame_mask(y, u, v, W, H, scale, asp, v_cantos, v_borda_suave, v_borda_irregular, v_cor_barras);
    }
    float3 res = pc_clamp3(y, 0.0f, 1.0f);
"""


# ------------------------------------------------------------------ pacote
README_TEXT = """PeliculaConverter {versao} - plugin para o DaVinci Resolve
=====================================================

PORTUGUES
---------
Este pacote traz o look do PeliculaConverter para o DaVinci Resolve em nos que vao em serie,
na mesma ordem de um laboratorio de cinema (como LOOK -> LAB -> PRINT):

  1. PeliculaConverter Laboratorio - so o laboratorio, como um no de emulacao de filme: perfil do
                                   video, exposicao, negativo, copia, separacao de cores (Hue Split),
                                   luzes da copiadora, densidade por cor, pe e rolagens, saturacoes,
                                   pele, bleach bypass e curvas neutras. "Mostrar curva" desenha as
                                   curvas R, G e B por cima da imagem.
     ou PeliculaConverter Cor    - tudo do Laboratorio mais o look de pelicula, a copia
                                   (2383/2393/3513) e o envelhecimento. Use UM dos dois.
                                   E a mesma conta do app: o resultado e igual ao do PeliculaConverter.
  2. PeliculaConverter Textura   - grao, halacao, bloom, nevoa, maciez, MTF da pelicula, aberracao
                                   e vinheta.
  3. PeliculaConverter Projetor  - tremor, cintilacao, defeitos (poeira, riscos, fio, manchas),
                                   vazamento de luz e moldura.

Como usar (pagina Color):
  - Crie tres nos em serie (Alt+S). Em cada um, arraste OpenFX > ResolveFX Color > DCTL e escolha
    "PeliculaConverter Laboratorio" (ou "PeliculaConverter Cor"), "PeliculaConverter Textura" e
    "PeliculaConverter Projetor".
  - No primeiro no, escolha em "Perfil do video" a curva da camera (S-Log3, LogC3, LogC4, V-Log, N-Log,
    Blackmagic Film Gen 5, Apple Log, DWG...) ou HLG / PQ para video HDR (celulares gravam em HLG). Se a
    linha do tempo ja estiver em Rec.709 (Gamma 2.4), deixe Rec.709. Outra opcao e colocar um Color Space
    Transform antes convertendo para Rec.709 / Gamma 2.4.
  - "Faixa do video" so muda S-Log3, V-Log e N-Log (curvas no codigo de 10 bits): deixe "Video" com o
    clipe em Data Levels Auto/Video (o padrao do Resolve) e use "Cheia" com o clipe em Full (Clip
    Attributes) ou com log que a camera mandou reescalado pela saida HDMI "Limited".
  - "Mostrar curva" e so para ver o ajuste: desligue antes de renderizar.
  - Na Textura e no Projetor, escolha a mesma bitola. No Projetor, escolha os quadros por segundo
    da linha do tempo (o tremor e os defeitos seguem o tempo real).
  - Na pasta Presets ha um no Cor, um Textura e (quando o preset usa) um Laboratorio e um Projetor
    para cada preset do app, ja com os valores do preset.
  - Na pasta LUTs ha um .cube por preset (so a cor, entrada Rec.709). Os LUTs funcionam tambem no
    Resolve gratuito, no Premiere, no Final Cut e em qualquer programa que aceite .cube.

Resolve Studio x gratuito: o efeito DCTL (OpenFX > DCTL) e do DaVinci Resolve Studio. No Resolve
GRATUITO use o plugin OpenFX "PeliculaConverter" (o look inteiro num efeito so): instale pelo app em
Configuracoes > Plugin para o DaVinci Resolve > Plugin OpenFX > Instalar (ou "pelicula-cli resolve
--ofx-instalar") e use Color > OpenFX > PeliculaConverter. Os LUTs da pasta LUTs tambem funcionam
(clique com o botao direito no no > LUT).
O grao e os defeitos mudam a cada quadro a partir do Resolve 19.1 (TIMELINE_FRAME_INDEX).

Atualizar: no PeliculaConverter, Configuracoes > Plugin para o DaVinci Resolve > Instalar (ou
"pelicula-cli resolve --instalar"). Depois, no Resolve, clique em "Refresh" na lista de LUTs ou
reabra o programa.

ENGLISH
-------
DaVinci Resolve nodes with the PeliculaConverter look, in film-lab order (LOOK -> LAB -> PRINT):
"PeliculaConverter Laboratorio" (film emulation only: input profile, exposure, negative, print, hue
split, printer lights, per-color density, toe and roll-offs, saturation, skin, bleach bypass, neutral
curves and a "Mostrar curva" R/G/B curve overlay) or "PeliculaConverter Cor" (the same lab plus the
parametric film look, print stock and fading - identical math to the app), then "PeliculaConverter
Textura" (grain, halation, bloom, mist, softness, film MTF, aberration, vignette) and "PeliculaConverter
Projetor" (gate weave, flicker, dust, scratches, hair, stains, light leaks, frame mask). Color page: add
three serial nodes and drop OpenFX > ResolveFX Color > DCTL on each one. Set "Perfil do video" to the
camera log, or HLG / PQ for HDR video (or put a Color Space Transform to Rec.709/Gamma 2.4 before it).
"Faixa do video" only affects S-Log3, V-Log and N-Log: keep "Video" for clips at Auto/Video data levels
and pick "Cheia" for clips set to Full (or HDMI "Limited" log recordings). The DCTL effect requires
DaVinci Resolve Studio; on the free version use the "PeliculaConverter" OpenFX plugin (install it from
the app: Settings > DaVinci Resolve plugin > OpenFX plugin, then Color > OpenFX > PeliculaConverter) or
the .cube LUTs in the LUTs folder. Grain and damage
animate per frame on Resolve 19.1+. Presets/ has one node set per app preset. Update from the app
(Settings > DaVinci Resolve plugin > Install) and press Refresh in Resolve.

Os nomes de filmes sao aproximacoes artisticas, sem relacao com os fabricantes.
Film names are artistic approximations, not affiliated with the manufacturers.
"""


def _preset_items() -> list[dict]:
    return [p for p in presets.BUILTIN if p["valores"] is not None]


def preset_files(p: dict) -> list[str]:
    """Nós gerados para um preset: Cor e Textura sempre; Laboratório quando o preset usa o laboratório;
    Projetor quando usa tremor, defeitos ou moldura."""
    v = presets.builtin_values(p["id"])
    kinds = ["cor", "textura"]
    if v.get("lab_on"):
        kinds.insert(1, "laboratorio")
    if v.get("proj_on") or v.get("desg_on") or v.get("mold_on"):
        kinds.append("projetor")
    return kinds


def _bake_luts(items: list[tuple[str, dict]], size: int, engine=None) -> dict[str, Any]:
    """LUTs .cube da cor de cada preset. Usa o motor dado (mesma thread) ou cria um numa thread própria."""
    if engine is not None:
        return {name: engine.bake_lut(vals, size) for name, vals in items}
    import threading
    out: dict[str, Any] = {}
    err: list[BaseException] = []

    def work():
        eng = None
        try:
            from .engine import Engine
            eng = Engine()
            for name, vals in items:
                out[name] = eng.bake_lut(vals, size)
        except BaseException as exc:  # noqa: BLE001
            err.append(exc)
        finally:
            if eng is not None:
                eng.release()

    th = threading.Thread(target=work, daemon=True, name="resolve-luts")
    th.start()
    th.join()
    if err:
        raise err[0]
    return out


def build_package(dest_dir: str | Path, presets: bool = True, luts: bool = True, engine=None,
                  lut_size: int = LUT_SIZE) -> list[Path]:
    """Grava a pasta `<dest_dir>/PeliculaConverter` com os DCTLs, os presets e os LUTs. Devolve os arquivos.

    Sem OpenGL os LUTs ficam de fora (os DCTLs são gerados mesmo assim).
    """
    from . import luts as luts_mod
    root = Path(dest_dir) / PACKAGE_NAME
    root.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    def write(path: Path, text: str, encoding: str = "ascii") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
        files.append(path)

    start = _preset_values(presets_mod.DEFAULT_ID)
    for kind in KINDS:
        write(root / FILE_NAMES[kind], source(kind, values=start))
    items = _preset_items()
    if presets:
        for p in items:
            vals = _preset_values(p["id"])
            base = safe_file_name(p["nome"])
            for kind in preset_files(p):
                label = NODE_LABELS[kind]
                write(root / "Presets" / f"{base} - {label}.dctl", source(kind, values=vals, title=p["nome"]))
    if luts:
        try:
            baked = _bake_luts([(p["nome"], _preset_values(p["id"])) for p in items], lut_size, engine)
        except Exception:  # noqa: BLE001  (sem OpenGL: pacote sem LUTs)
            baked = {}
        for p in items:
            data = baked.get(p["nome"])
            if data is None:
                continue
            path = root / "LUTs" / f"{safe_file_name(p['nome'])}.cube"
            path.parent.mkdir(parents=True, exist_ok=True)
            luts_mod.save_cube(str(path), data, lut_size, ascii_text(p["nome"]) or "PeliculaConverter")
            files.append(path)
    write(root / "LEIA-ME.txt", README_TEXT.format(versao=__version__), "utf-8")
    write(root / MARKER, f"{APP_NAME}\nversao={__version__}\ngerado_em={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
    return files


def _preset_values(pid: str) -> dict:
    return presets.builtin_values(pid)


# ------------------------------------------------------------------ instalação no Resolve
def lut_dirs() -> list[Path]:
    """Pastas de LUTs do DaVinci Resolve neste sistema (as que existem primeiro)."""
    if sys.platform == "win32":
        pd = os.environ.get("ProgramData") or r"C:\ProgramData"
        cands = [Path(pd) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT"]
    elif sys.platform == "darwin":
        cands = [Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT"),
                 Path.home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "LUT"]
    else:
        cands = [Path.home() / ".local" / "share" / "DaVinciResolve" / "LUT", Path("/opt/resolve/LUT")]
    return sorted(cands, key=lambda p: not p.is_dir())


def default_install_dir() -> Path | None:
    """Pasta de LUTs onde instalar: a primeira que existe e aceita gravação (ou a primeira que existe)."""
    existing = [d for d in lut_dirs() if d.is_dir()]
    for d in existing:
        if os.access(d, os.W_OK):
            return d
    return existing[0] if existing else None


def _marker(folder: Path) -> Path:
    return folder / PACKAGE_NAME / MARKER


def installed_version(folder: str | Path | None = None) -> str | None:
    """Versão do plugin instalado (lida do marcador) ou None."""
    dirs = [Path(folder)] if folder else lut_dirs()
    for d in dirs:
        m = _marker(d)
        if m.is_file():
            try:
                for line in m.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("versao="):
                        return line.split("=", 1)[1].strip()
            except OSError:
                continue
            return "?"
    return None


def is_installed(folder: str | Path | None = None) -> bool:
    return installed_version(folder) is not None


def install(target_dir: str | Path | None = None, engine=None) -> Path:
    """Instala (ou atualiza) o pacote em `<pasta de LUTs>/PeliculaConverter`. Devolve a pasta instalada."""
    base = Path(target_dir) if target_dir else default_install_dir()
    if base is None:
        raise ResolveError(_("Não encontrei a pasta de LUTs do DaVinci Resolve neste computador. Instale o "
                             "Resolve ou use \"Salvar o pacote numa pasta…\" e copie a pasta PeliculaConverter "
                             "para a pasta de LUTs (no Resolve: Project Settings > Color Management > "
                             "Open LUT Folder)."))
    dest = base / PACKAGE_NAME
    if dest.exists() and not (dest / MARKER).is_file() and any(dest.iterdir()):
        raise ResolveError(_("A pasta {pasta} já existe e não foi criada pelo PeliculaConverter. Apague ou "
                             "renomeie essa pasta e tente de novo.").format(pasta=dest))
    tmp = Path(tempfile.mkdtemp(prefix="pelicula_resolve_"))
    staging = base / (PACKAGE_NAME + ".novo")
    old = base / (PACKAGE_NAME + ".antigo")
    try:
        build_package(tmp, engine=engine)
        try:
            base.mkdir(parents=True, exist_ok=True)
            for p in (staging, old):
                if p.exists():
                    shutil.rmtree(p)
            shutil.copytree(tmp / PACKAGE_NAME, staging)
            if dest.exists():
                dest.rename(old)
            staging.rename(dest)
            if old.exists():
                shutil.rmtree(old, ignore_errors=True)
        except OSError as exc:
            for p in (staging,):
                shutil.rmtree(p, ignore_errors=True)
            if old.exists() and not dest.exists():
                try:
                    old.rename(dest)
                except OSError:
                    pass
            raise ResolveError(_("Não foi possível gravar em {pasta}.\n\n{erro}\n\nUse \"Salvar o pacote numa "
                                 "pasta…\" e copie a pasta PeliculaConverter para lá manualmente (pode pedir "
                                 "permissão de administrador).").format(pasta=base, erro=exc)) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest


def control_counts(kind: str) -> dict[str, int]:
    """Quantos controles de cada tipo um nó tem (o Resolve aceita até 64 por tipo e 5 seletores de cor)."""
    out: dict[str, int] = {}
    for c in spec(kind).controls:
        out[c.kind] = out.get(c.kind, 0) + 1
    return out


# ------------------------------------------------------------------ plugin OpenFX (funciona no Resolve gratuito)
# A implementação fica em ofx.py (que importa este módulo); aqui só os atalhos usados pela janela e pela CLI.
OFX_BUNDLE_NAME = "PeliculaConverter.ofx.bundle"

def ofx_bundle_path() -> Path | None:
    """Pacote PeliculaConverter.ofx.bundle que vem com o app (ou compilado em plugins/ofx/dist)."""
    from . import ofx
    return ofx.bundle_path()


def ofx_bundle_version() -> str | None:
    from . import ofx
    return ofx.bundle_version(ofx.bundle_path())


def ofx_install_dir() -> Path:
    """Pasta padrão do OpenFX: Windows "%CommonProgramFiles%/OFX/Plugins", Linux /usr/OFX/Plugins."""
    from . import ofx
    return ofx.install_dir()


def ofx_installed_version(folder: str | Path | None = None) -> str | None:
    from . import ofx
    return ofx.installed_version(folder)


def ofx_install(target_dir: str | Path | None = None) -> Path:
    """Instala o plugin OpenFX (pede administrador quando a pasta é do sistema)."""
    from . import ofx
    return ofx.install(target_dir)


def ofx_save_bundle(dest_dir: str | Path) -> Path:
    from . import ofx
    return ofx.save_bundle(dest_dir)


def ofx_generate(dest_dir: str | Path | None = None) -> list[Path]:
    """Gera o código C++ do plugin OpenFX (kernels e parâmetros) a partir dos kernels deste módulo."""
    from . import ofx
    return ofx.generate(dest_dir)
