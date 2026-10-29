"""Plugin OpenFX (OFX) do PeliculaConverter: o look inteiro num efeito que roda no DaVinci Resolve gratuito.

O DCTL (pacote de `resolve.py`) só funciona no Resolve Studio; plugins OpenFX de terceiros funcionam
também no gratuito (páginas Color e Edit). Este módulo:

- gera o código C++ do plugin a partir dos MESMOS kernels de `resolve.py` (dialeto `cpp`: as funções
  `pc_*`, as tabelas de `look.py` e os trechos do corpo dos nós — entrada, ganho, laboratório, look,
  tremor/defeitos), em `plugins/ofx/generated/`. A orquestração das passadas (desfoques, mipmaps,
  grão por grade, montagem final) fica em `plugins/ofx/src/pc_core.cpp`, escrita à mão seguindo
  `Engine.render()`;
- descreve os parâmetros do efeito (rótulos e dicas do app, faixas dos DCTLs, os presets prontos e
  a leitura de um look .json/.plc exportado pelo app);
- acha, instala e confere o pacote `PeliculaConverter.ofx.bundle` (a instalação pede administrador:
  a pasta padrão do OFX fica em Program Files / /usr).

Compilar: `python plugins/ofx/build.py` (MSVC no Windows, g++ no Linux). Os testes
(`tests/test_ofx.py`) compilam o núcleo com uma interface C e comparam com o app na GPU.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, __version__, labx, look, params, presets, resolve
from .i18n import _
from .resolve import CPP, Ctl

PLUGIN_ID = "com.peliculaconverter.pelicula"
PLUGIN_LABEL = "PeliculaConverter"
BUNDLE_NAME = resolve.OFX_BUNDLE_NAME
BINARY_NAME = "PeliculaConverter.ofx"
VERSION_FILE = "pelicula-ofx.txt"  # em Contents/Resources: versão do app que gerou o binário
ARCH_DIRS = {"win32": "Win64", "linux": "Linux-x86-64", "darwin": "MacOS"}
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "plugins" / "ofx"
GENERATED = ("pc_kernels.h", "pc_params.h")
KIND_CODES = {"float": 0, "int": 1, "check": 2, "combo": 3, "color": 4}
SKIP = ("ui_qualidade", "ui_fps")  # só fazem sentido no DCTL (o OFX tem a imagem inteira e o fps do clipe)
SKIP += ("ui_mtf_copia",)  # 1.6: o OFX vê a cópia direto (copia, lab_on, lab_copia)
# Rótulo, dica e opções com acento dos controles só do plugin (os do app vêm de params.py).
INTERNAL_TEXT = {
    "ui_faixa_video": ("Faixa do vídeo",
                       "Só muda S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log, curvas escritas no código de 10 bits. "
                       "Vídeo (padrão): clipe "
                       "em Data Levels Auto ou Video, que o Resolve expande de 64–940 para 0–1 (o plugin volta ao "
                       "código da câmera). Cheia: o valor já é o código — clipe em Full em Clip Attributes (como "
                       "a Sony recomenda) ou log que a câmera mandou reescalado pela saída HDMI “Limited”.",
                       ["Vídeo (faixa legal, 64–940)", "Cheia (0–1023)"]),
}
# Ajustes do clipe, não do look: escolher um preset ou carregar um look .json não muda (como no app,
# presets.SOURCE_KEYS que existem no plugin) — o perfil e a faixa do vídeo dependem do clipe no Resolve.
KEEP_ON_PRESET = ("entrada", "faixa_video", "logc3_ei", "proteger_cores")


class OfxError(RuntimeError):
    pass


# ------------------------------------------------------------------ controles do efeito
@dataclass
class Slot:
    ctl: Ctl
    field: str     # campo de pc_vals (chave do app)
    offset: int    # posição no vetor de valores da interface (cores ocupam 3)
    group: str     # chave da seção do app (agrupa os parâmetros no Resolve)

    @property
    def size(self) -> int:
        return 3 if self.ctl.kind == "color" else 1


def _section_of(key: str) -> str:
    for sec in params.SECTIONS:
        if any(p.key == key for p in sec.params):
            return sec.key
    return params.SECTIONS[0].key


def controls() -> list[Ctl]:
    """Todos os controles do plugin: os do nó Cor + Textura + Projetor, sem repetir."""
    out, seen = [], set()
    extra = resolve.lab_grain_controls()  # 1.6: "Grão no negativo" (o resto já vem do Textura)
    extra += resolve.lab_extra_controls()  # 1.6 (labx.py): scanner, película vencida e pré-exposição
    for c in resolve.cor_controls() + resolve.textura_controls() + resolve.projetor_controls() + extra:
        if c.name in SKIP or c.name in seen:
            continue
        seen.add(c.name)
        out.append(c)
    return out


def slots() -> list[Slot]:
    """Controles na ordem das seções do app, com o lugar de cada um no vetor de valores."""
    order = {s.key: i for i, s in enumerate(params.SECTIONS)}
    items = []
    for i, c in enumerate(controls()):
        group = _section_of(c.key) if c.key else (c.section or params.SECTIONS[0].key)
        items.append((order.get(group, 0), i, c, group))
    items.sort()
    out, off = [], 0
    for _o, _i, c, group in items:
        s = Slot(c, c.var[2:], off, group)
        out.append(s)
        off += s.size
    return out


def ui_size() -> int:
    return sum(s.size for s in slots())


def ui_values(values: dict | None = None) -> list[float]:
    """Vetor de valores da interface do plugin para os ajustes do app (padrão quando falta a chave)."""
    vals = params.sanitize(values or {}) if values is not None else None
    out: list[float] = []
    for s in slots():
        c = s.ctl
        v = vals.get(c.key, c.default) if (vals is not None and c.key) else c.default
        u = c.ui_value(v)
        if c.kind == "color":
            out += [float(x) for x in u]
        else:
            out.append(float(u))
    return out


def label_of(c: Ctl) -> str:
    """Rótulo com acentos (o mesmo do app); percentuais avisam a unidade."""
    if not c.key:
        return INTERNAL_TEXT[c.name][0] if c.name in INTERNAL_TEXT else c.label
    p = params.PARAMS[c.key]
    return p.label + (" (%)" if p.percent else "")


def hint_of(c: Ctl) -> str:
    if not c.key:
        return INTERNAL_TEXT[c.name][1] if c.name in INTERNAL_TEXT else c.tip
    return params.PARAMS[c.key].tip


def choice_labels(c: Ctl) -> list[str]:
    """Opções de um combo com acentos: as do app ou as de INTERNAL_TEXT (senão, os rótulos ASCII)."""
    if c.key:
        names = dict(params.PARAMS[c.key].choices)
        return [names.get(v, lab) for v, lab in c.choices]
    if c.name in INTERNAL_TEXT:
        return list(INTERNAL_TEXT[c.name][2])
    return [lab for _v, lab in c.choices]


def group_title(key: str) -> str:
    return next(s.title for s in params.SECTIONS if s.key == key)


# ------------------------------------------------------------------ geração do C++
_CPP_DIALECT = r"""
#include <cmath>

typedef unsigned int uint;
struct float2 { float x, y; };
struct float3 { float x, y, z; };
struct float4 { float x, y, z, w; };
struct pc_color3 { float r, g, b; };
static inline float2 make_float2(float x, float y) { float2 v = {x, y}; return v; }
static inline float3 make_float3(float x, float y, float z) { float3 v = {x, y, z}; return v; }
static inline float4 make_float4(float x, float y, float z, float w) { float4 v = {x, y, z, w}; return v; }
static inline float2 operator+(float2 a, float2 b) { return make_float2(a.x + b.x, a.y + b.y); }
static inline float2 operator-(float2 a, float2 b) { return make_float2(a.x - b.x, a.y - b.y); }
static inline float2 operator*(float2 a, float s) { return make_float2(a.x * s, a.y * s); }
static inline float3 operator+(float3 a, float3 b) { return make_float3(a.x + b.x, a.y + b.y, a.z + b.z); }
static inline float3 operator-(float3 a, float3 b) { return make_float3(a.x - b.x, a.y - b.y, a.z - b.z); }
static inline float3 operator-(float3 a) { return make_float3(-a.x, -a.y, -a.z); }
static inline float3 operator*(float3 a, float3 b) { return make_float3(a.x * b.x, a.y * b.y, a.z * b.z); }
static inline float3 operator*(float3 a, float s) { return make_float3(a.x * s, a.y * s, a.z * s); }
static inline float3 operator*(float s, float3 a) { return make_float3(a.x * s, a.y * s, a.z * s); }
static inline float3 operator/(float3 a, float s) { return make_float3(a.x / s, a.y / s, a.z / s); }
static inline float4 operator+(float4 a, float4 b) { return make_float4(a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w); }
static inline float4 operator-(float4 a, float4 b) { return make_float4(a.x - b.x, a.y - b.y, a.z - b.z, a.w - b.w); }
static inline float4 operator*(float4 a, float s) { return make_float4(a.x * s, a.y * s, a.z * s, a.w * s); }
static inline float _powf(float a, float b) { return std::pow(a, b); }
static inline float _logf(float a) { return std::log(a); }
static inline float _log2f(float a) { return std::log2(a); }
static inline float _expf(float a) { return std::exp(a); }
static inline float _exp2f(float a) { return std::exp2(a); }
static inline float _fabs(float a) { return std::fabs(a); }
static inline float _fmaxf(float a, float b) { return std::fmax(a, b); }
static inline float _fminf(float a, float b) { return std::fmin(a, b); }
static inline float _clampf(float x, float lo, float hi) { return std::fmin(std::fmax(x, lo), hi); }
static inline float _saturatef(float x) { return _clampf(x, 0.0f, 1.0f); }
static inline float _sqrtf(float a) { return std::sqrt(a); }
static inline float _floorf(float a) { return std::floor(a); }
static inline float _ceilf(float a) { return std::ceil(a); }
static inline float _sinf(float a) { return std::sin(a); }
static inline float _cosf(float a) { return std::cos(a); }
static inline float _atan2f(float y, float x) { return std::atan2(y, x); }
#define PC_F(x) ((float)(x))
#define PC_I(x) ((int)(x))
#define PC_U(x) ((uint)(x))
"""

# Trechos dos corpos dos nós reaproveitados no C++ (a mesma matemática dos DCTLs).
_FRAME_FIX = (("int frame = PC_FRAME;", "int frame = p_frame;"), ("float fps = PC_FPS[v_fps];", "float fps = p_fps;"))
FRAME_FIELDS = [("float", n) for n in ("scale", "sh_x", "sh_y", "rot", "zoom", "g0", "g1", "g2", "splice_on",
                                         "splice_y", "hair_on", "hair_seed", "hair_wig", "stain_amt", "stain_seed",
                                         "cue", "leak_on")] + [("int", "sd"), ("int", "dg"), ("float4", "L0"),
                                                               ("float4", "L1")]


def _ctype(c: Ctl) -> str:
    return {"float": "float", "int": "int", "check": "int", "combo": "int", "color": "float3"}[c.kind]


def _locals(sl: list[Slot]) -> str:
    """Desempacota pc_vals em variáveis v_<chave> (os trechos dos DCTLs usam esses nomes)."""
    return "".join(f"    {_ctype(s.ctl)} {s.ctl.var} = V.{s.field};\n" for s in sl) + \
        "".join(f"    (void){s.ctl.var};\n" for s in sl)


def _cstr(text: str) -> str:
    """Literal C em UTF-8 com escapes octais (nenhum compilador reclama do arquivo)."""
    out = []
    for b in str(text).encode("utf-8"):
        ch = chr(b)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif 32 <= b < 127:
            out.append(ch)
        else:
            out.append(f"\\{b:03o}")
    return '"' + "".join(out) + '"'


def _f(x: float) -> str:
    return resolve.flt(x)


def kernels_source() -> str:
    """plugins/ofx/generated/pc_kernels.h: dialeto, tabelas, kernels e funções de etapa."""
    sl = slots()
    head = [f"// {APP_NAME} {__version__} - nucleo de cor e textura do plugin OpenFX.\n",
            "// Gerado por pelicula/ofx.py a partir dos kernels de pelicula/resolve.py. Nao edite: rode\n",
            "// \"python tools/gerar_ofx.py\" (ou pelicula-cli resolve --ofx-fonte DIR).\n",
            "#pragma once\n", _CPP_DIALECT, "\n"]
    head.append(resolve._define("PC_DSLOPE", look.D_SLOPE) + resolve._define("PC_DMID", look.D_MID)
                + resolve._define("PC_DP", look.D_P))
    tables = (resolve._cor_tables(CPP) + resolve._lab_tables(CPP) + resolve._gauge_tables(CPP)
              + resolve._mtf_table(CPP) + resolve._projetor_tables(CPP) + resolve._grao_tables(CPP)
              + labx.tables(resolve._define, resolve._table, CPP))
    # 1.6: K_RAND e o grão físico (K_PGRAIN) antes do laboratório, que soma o grão físico na densidade; o
    # pc_lab_path_x (labx) é cópia do pc_lab_path já com o grão físico
    k_lab = resolve.K_LAB.replace("/*PGRAIN*/", resolve.B_PGRAIN_LAB)
    kernel = (resolve.K_COMMON + resolve.K_DECODE + resolve.K_LOOK + resolve.K_RAND + resolve.K_PGRAIN
              + k_lab + resolve.K_CURVE
              + resolve.K_TEXTURA + resolve.K_PROJETOR + resolve.K_NGRAIN + resolve.K_BREATH
              + labx.kernel(k_lab)
              ).replace("PC_DEVICE ", "static inline ")
    body = []
    body.append("\n// ---------------------------------------------------------------- valores (formato do app)\n")
    body.append("struct pc_vals {\n" + "".join(f"    {_ctype(s.ctl)} {s.field};\n" for s in sl) + "};\n")
    body.append(f"#define PC_UI_SIZE {ui_size()}\n")
    unpack = ["static inline void pc_unpack(const float* ui, pc_vals* V) {\n"]
    for s in sl:
        c = s.ctl
        if c.kind == "color":
            unpack.append(f"    pc_color3 {c.name} = {{ui[{s.offset}], ui[{s.offset + 1}], ui[{s.offset + 2}]}};\n")
        else:
            unpack.append(f"    float {c.name} = ui[{s.offset}];\n")
        unpack.append(f"    V->{s.field} = {c.app_expr()};\n")
    unpack.append("}\n")
    body += unpack
    loc = _locals(sl)
    body.append("\n// perfil de entrada: codigo do video -> luz linear (B_INPUT)\n")
    body.append(f"static inline float3 pc_input(const pc_vals& V, float3 code) {{\n{loc}{resolve.B_INPUT}"
                "    return lin_in;\n}\n")
    body.append("// exposicao e balanco + ganhos extras por canal (B_GAIN)\n")
    body.append(f"static inline float3 pc_gain(const pc_vals& V, float3 lin, float3 gx) {{\n{loc}{resolve.B_GAIN}"
                "    return lin;\n}\n")
    body.append("// colorPipe do app: laboratorio + look + copia + envelhecimento (B_LAB + B_LOOK)\n")
    lab = labx.body(resolve.B_LAB).replace("/*NGRAIN*/", "")  # 1.6: com véu, pré-exposição e scanner (labx.py)
    body.append(f"static inline float3 pc_colorpipe(const pc_vals& V, float3 lin) {{\n{loc}{lab}"
                f"{resolve.B_LOOK}    return y;\n}}\n")
    # 1.6: a mesma conta com o grão no negativo (`gn_in` = densidade do grão de cada camada neste pixel)
    lab_ng = labx.body(resolve.B_LAB).replace("/*NGRAIN*/", "        gn = gn_in;\n")
    body.append("// colorPipe com o grao no negativo (grao.negative_grain)\n")
    body.append(f"static inline float3 pc_colorpipe_ng(const pc_vals& V, float3 lin, float3 gn_in) {{\n{loc}{lab_ng}"
                f"{resolve.B_LOOK}    return y;\n}}\n")
    # 1.6: a mesma conta com o grão físico (`ga_in` = fração por camada, `gq_in` = posição px@1080, raio e fração
    # própria, `gs_in` = semente do quadro); a densidade de cada camada decide o resto dentro de pc_lab_path
    lab_pg = resolve.B_LAB.replace("/*NGRAIN*/", "        ga = ga_in;\n        gq = gq_in;\n        gs = gs_in;\n")
    body.append("// colorPipe com o grao fisico no negativo (grao_fisico.negative_grain)\n")
    body.append("static inline float3 pc_colorpipe_pg(const pc_vals& V, float3 lin, float3 ga_in, float4 gq_in, "
                f"int gs_in) {{\n{loc}{lab_pg}{resolve.B_LOOK}    return y;\n}}\n")
    frame_body = resolve.B_FRAME
    for a, b in _FRAME_FIX:
        assert a in frame_body, a
        frame_body = frame_body.replace(a, b)
    body.append("\n// tremor, cintilacao e eventos dos defeitos de um quadro (B_FRAME = look.build_plan)\n")
    body.append("struct pc_frame {\n" + "".join(f"    {t} {n};\n" for t, n in FRAME_FIELDS) + "};\n")
    body.append("static inline void pc_frame_params(const pc_vals& V, int p_Width, int p_Height, int p_frame, "
                f"float p_fps, pc_frame* o) {{\n{loc}{frame_body}"
                + "".join(f"    o->{n} = {n};\n" for _t, n in FRAME_FIELDS) + "}\n")
    return resolve.ascii_source("".join(head) + tables + kernel + "".join(body))


def params_source() -> str:
    """plugins/ofx/generated/pc_params.h: parâmetros do efeito, presets e leitura de looks .json."""
    sl = slots()
    out = [f"// {APP_NAME} {__version__} - parametros do plugin OpenFX (gerado por pelicula/ofx.py; nao edite).\n",
           "#pragma once\n\n",
           "struct pc_param_def {\n    const char* name;   // nome do parametro no OFX (chave do app)\n"
           "    const char* key;    // chave do app (\"\" = interno)\n    const char* label;\n"
           "    const char* hint;\n    const char* group;  // chave da secao\n"
           "    int kind;           // 0 float, 1 int, 2 bool, 3 escolha, 4 cor\n"
           "    int offset;         // posicao no vetor de valores (cores: 3)\n"
           "    double def[3];\n    double lo, hi, step, scale;\n"
           "    int nchoices;\n    const char* const* choice_labels;\n"
           "    const char* const* choice_values;\n"
           "    int keep;           // 1 = preset e look .json nao mudam (ajuste do clipe: perfil e faixa)\n};\n\n"]
    for i, s in enumerate(sl):
        c = s.ctl
        if c.kind == "combo":
            labels = choice_labels(c)
            out.append(f"static const char* const PC_CHL_{i}[] = {{{', '.join(_cstr(x) for x in labels)}}};\n")
            out.append(f"static const char* const PC_CHV_{i}[] = {{{', '.join(_cstr(v) for v, _l in c.choices)}}};\n")
    out.append(f"\n#define PC_PARAM_COUNT {len(sl)}\n")
    out.append("static const pc_param_def PC_PARAMS[PC_PARAM_COUNT] = {\n")
    start = ui_values(presets.builtin_values(presets.DEFAULT_ID))  # o efeito novo já sai com o look padrão do app
    for i, s in enumerate(sl):
        c = s.ctl
        d = start[s.offset:s.offset + 3] if c.kind == "color" else [start[s.offset], 0.0, 0.0]
        lo, hi = (0.0, 1.0) if c.kind == "color" else (float(c.lo), float(c.hi))
        if c.kind == "combo":
            lo, hi = 0.0, float(len(c.choices) - 1)
        elif c.kind == "check":
            lo, hi = 0.0, 1.0
        nch = len(c.choices) if c.kind == "combo" else 0
        chl = f"PC_CHL_{i}" if nch else "0"
        chv = f"PC_CHV_{i}" if nch else "0"
        keep = 1 if s.field in KEEP_ON_PRESET else 0
        out.append(f"    {{{_cstr(s.field)}, {_cstr(c.key)}, {_cstr(label_of(c))}, {_cstr(hint_of(c))}, "
                   f"{_cstr(s.group)}, {KIND_CODES[c.kind]}, {s.offset}, "
                   f"{{{', '.join(repr(float(x)) for x in d)}}}, {lo!r}, {hi!r}, {float(c.step)!r}, "
                   f"{float(c.scale)!r}, {nch}, {chl}, {chv}, {keep}}},\n")
    out.append("};\n\n")
    groups = []
    for s in sl:
        if s.group not in groups:
            groups.append(s.group)
    out.append(f"#define PC_GROUP_COUNT {len(groups)}\n")
    out.append("static const char* const PC_GROUP_KEYS[PC_GROUP_COUNT] = {"
               + ", ".join(_cstr(g) for g in groups) + "};\n")
    out.append("static const char* const PC_GROUP_TITLES[PC_GROUP_COUNT] = {"
               + ", ".join(_cstr(group_title(g)) for g in groups) + "};\n\n")
    items = presets.BUILTIN
    out.append(f"#define PC_PRESET_COUNT {len(items)}\n")
    out.append("static const char* const PC_PRESET_NAMES[PC_PRESET_COUNT] = {\n"
               + "".join(f"    {_cstr(p['nome'])},\n" for p in items) + "};\n")
    out.append("static const char* const PC_PRESET_IDS[PC_PRESET_COUNT] = {\n"
               + "".join(f"    {_cstr(p['id'])},\n" for p in items) + "};\n")
    out.append(f"static const float PC_PRESET_VALUES[PC_PRESET_COUNT][{ui_size()}] = {{\n")
    for p in items:
        vals = ui_values(presets.builtin_values(p["id"]))
        out.append("    {" + ", ".join(_f(x) for x in vals) + "},\n")
    out.append("};\n")
    out.append("// ajustes padrao do app (params.defaults): base para ler um look .json\n"
               f"static const float PC_APP_DEFAULTS[{ui_size()}] = {{"
               + ", ".join(_f(x) for x in ui_values(params.defaults())) + "};\n")
    out.append(f"#define PC_DEFAULT_PRESET {[p['id'] for p in items].index(presets.DEFAULT_ID)}\n")
    out.append(f"#define PC_PLUGIN_ID {_cstr(PLUGIN_ID)}\n#define PC_PLUGIN_LABEL {_cstr(PLUGIN_LABEL)}\n")
    major, minor = (int(x) for x in __version__.split(".")[:2])
    out.append(f"#define PC_VERSION_MAJOR {major}\n#define PC_VERSION_MINOR {minor}\n"
               f"#define PC_VERSION_TEXT {_cstr(__version__)}\n")
    return "".join(out)


def generate(dest: str | Path | None = None) -> list[Path]:
    """Grava os arquivos gerados (padrão: plugins/ofx/generated). Devolve os caminhos."""
    folder = Path(dest) if dest else SRC_DIR / "generated"
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for name, text in (("pc_kernels.h", kernels_source()), ("pc_params.h", params_source())):
        path = folder / name
        with open(path, "w", encoding="ascii", newline="\n") as fh:
            fh.write(text)
        files.append(path)
    return files


_NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?f?")


def _same_code(a: str, b: str, rel: float = 1e-6, absolute: float = 1e-9) -> str:
    """"" se os dois códigos são iguais; senão, a primeira linha diferente (para a mensagem do teste).

    Os números são comparados com tolerância: tabelas calculadas com o numpy (matrizes de gamut,
    calibração) podem mudar no último dígito impresso entre máquinas com outra CPU/BLAS.
    """
    la, lb = a.splitlines(), b.splitlines()
    if len(la) != len(lb):
        return f"{len(la)} linhas × {len(lb)} linhas"
    for i, (x, y) in enumerate(zip(la, lb), 1):
        if x == y:
            continue
        if _NUM.sub("#", x) != _NUM.sub("#", y):
            return f"linha {i}:\n  {x.strip()[:160]}\n  {y.strip()[:160]}"
        for n1, n2 in zip(_NUM.findall(x), _NUM.findall(y)):
            f1, f2 = float(n1.rstrip("fF")), float(n2.rstrip("fF"))
            if abs(f1 - f2) > max(rel * max(abs(f1), abs(f2)), absolute):
                return f"linha {i}: {n1} × {n2}"
    return ""


def generated_up_to_date(details: dict[str, str] | None = None) -> list[str]:
    """Arquivos gerados que estão diferentes do que o código atual produziria (vazio = em dia)."""
    stale = []
    for name, text in (("pc_kernels.h", kernels_source()), ("pc_params.h", params_source())):
        path = SRC_DIR / "generated" / name
        diff = "arquivo não existe" if not path.is_file() else _same_code(path.read_text(encoding="ascii"), text)
        if diff:
            stale.append(name)
            if details is not None:
                details[name] = diff
    return stale


# ------------------------------------------------------------------ pacote e instalação
def arch_dir() -> str:
    return ARCH_DIRS.get(sys.platform, "Linux-x86-64")


def bundle_path() -> Path | None:
    """Pacote pronto: o que vem com o app (PyInstaller: _internal/ofx, ou ofx/ ao lado do executável)
    ou, rodando do código-fonte, o compilado em plugins/ofx/dist."""
    cands = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(Path(base) / "ofx" / BUNDLE_NAME)
    if getattr(sys, "frozen", False):
        cands.append(Path(sys.executable).resolve().parent / "ofx" / BUNDLE_NAME)
    cands.append(SRC_DIR / "dist" / BUNDLE_NAME)
    for c in cands:
        if (c / "Contents" / arch_dir() / BINARY_NAME).is_file():
            return c
    return None


def bundle_version(bundle: str | Path | None) -> str | None:
    if not bundle:
        return None
    f = Path(bundle) / "Contents" / "Resources" / VERSION_FILE
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("versao="):
                return line.split("=", 1)[1].strip()
    except OSError:
        return None
    return "?"


def install_dir() -> Path:
    """Pasta padrão dos plugins OpenFX, onde o Resolve (gratuito ou Studio) procura."""
    if sys.platform == "win32":
        common = os.environ.get("CommonProgramFiles") or r"C:\Program Files\Common Files"
        return Path(common) / "OFX" / "Plugins"
    if sys.platform == "darwin":
        return Path("/Library/OFX/Plugins")
    return Path("/usr/OFX/Plugins")


def installed_version(folder: str | Path | None = None) -> str | None:
    base = Path(folder) if folder else install_dir()
    b = base / BUNDLE_NAME
    if not (b / "Contents").is_dir():
        return None
    return bundle_version(b)


def _copy_bundle(src: Path, dest_dir: Path) -> Path:
    """Cópia direta (pasta com permissão de escrita): troca o pacote antigo de uma vez."""
    dest = dest_dir / BUNDLE_NAME
    staging = dest_dir / (BUNDLE_NAME + ".novo")
    old = dest_dir / (BUNDLE_NAME + ".antigo")
    dest_dir.mkdir(parents=True, exist_ok=True)
    for p in (staging, old):
        if p.exists():
            shutil.rmtree(p)
    shutil.copytree(src, staging)
    if dest.exists():
        dest.rename(old)
    staging.rename(dest)
    shutil.rmtree(old, ignore_errors=True)
    return dest


def elevated_command(src: Path, dest_dir: Path) -> list[str]:
    """Comando que copia o pacote com permissão de administrador (o sistema pede confirmação)."""
    dest = dest_dir / BUNDLE_NAME
    if sys.platform == "win32":
        def q(p: Path) -> str:
            return "'" + str(p).replace("'", "''") + "'"
        inner = (f"$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Force -Path {q(dest_dir)} | Out-Null; "
                 f"if (Test-Path {q(dest)}) {{ Remove-Item -Recurse -Force {q(dest)} }}; "
                 f"Copy-Item -Recurse -Force {q(src)} {q(dest)}")
        script = ("$p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
                  "-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-Command', \"" + inner.replace('"', '`"')
                  + "\"); exit $p.ExitCode")
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    return ["pkexec", "sh", "-c", f'mkdir -p "{dest_dir}" && rm -rf "{dest}" && cp -r "{src}" "{dest}"']


def install(target_dir: str | Path | None = None, bundle: str | Path | None = None, elevate: bool = True) -> Path:
    """Instala o plugin OpenFX. Sem permissão de escrita, pede administrador (UAC no Windows, pkexec no Linux).

    `target_dir` troca a pasta (testes e instalações portáteis); `elevate=False` nunca pede administrador.
    """
    src = Path(bundle) if bundle else bundle_path()
    if src is None or not (src / "Contents").is_dir():
        raise OfxError(_("O plugin OpenFX não está neste pacote do app. Compile com \"python plugins/ofx/build.py\" "
                         "ou use uma versão do PeliculaConverter que já traga o plugin."))
    dest_dir = Path(target_dir) if target_dir else install_dir()
    try:
        return _copy_bundle(src, dest_dir)
    except OSError as exc:
        if not elevate:
            raise OfxError(_("Não foi possível gravar em {pasta}.\n\n{erro}").format(pasta=dest_dir, erro=exc)) from exc
    if sys.platform not in ("win32",) and not shutil.which("pkexec"):
        raise OfxError(_("Para instalar em {pasta} é preciso permissão de administrador. Rode no terminal:\n\n"
                         "sudo mkdir -p \"{pasta}\" && sudo cp -r \"{origem}\" \"{pasta}/\"").format(
            pasta=dest_dir, origem=src))
    # Copia antes para uma pasta temporária (o processo elevado não enxerga _MEIPASS de outro usuário).
    tmp = Path(tempfile.mkdtemp(prefix="pelicula_ofx_"))
    try:
        staged = tmp / BUNDLE_NAME
        shutil.copytree(src, staged)
        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        res = subprocess.run(elevated_command(staged, dest_dir), capture_output=True, **flags)
        if res.returncode != 0 or installed_version(dest_dir) is None:
            err = (res.stderr or res.stdout or b"").decode("utf-8", "replace").strip()
            raise OfxError(_("A instalação do plugin OpenFX não foi concluída: a permissão de administrador foi "
                             "negada ou o plugin está em uso (feche o DaVinci Resolve e tente de novo).\n\n"
                             "{erro}").format(erro=err[-800:] or res.returncode))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest_dir / BUNDLE_NAME


def save_bundle(dest_dir: str | Path, bundle: str | Path | None = None) -> Path:
    """Copia o pacote para uma pasta qualquer (para instalar em outro computador)."""
    src = Path(bundle) if bundle else bundle_path()
    if src is None:
        raise OfxError(_("O plugin OpenFX não está neste pacote do app."))
    return _copy_bundle(src, Path(dest_dir))
