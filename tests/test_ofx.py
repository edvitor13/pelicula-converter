"""Plugin OpenFX (DaVinci Resolve gratuito): código gerado, binário, paridade com o app e instalação.

O núcleo em C++ (plugins/ofx) é compilado na hora (MSVC no Windows, g++ no Linux; pula sem
compilador) e carregado com ctypes: o próprio PeliculaConverter.ofx exporta uma interface C
(`pc_render`, `pc_color`...) além das funções do OpenFX. A cor é comparada com `Engine.bake_lut` e o
quadro inteiro com `Engine.render`, na GPU. Nada é instalado nas pastas do sistema: só pastas temporárias.
"""

from __future__ import annotations

import ctypes
import importlib.util
import itertools
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

from pelicula import __version__, look, ofx, params, presets, resolve

ROOT = Path(__file__).resolve().parents[1]


def _load_build():
    spec = importlib.util.spec_from_file_location("pelicula_ofx_build", ROOT / "plugins" / "ofx" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILD = _load_build()
FP = ctypes.POINTER(ctypes.c_float)


class OfxPlugin(ctypes.Structure):
    _fields_ = [("pluginApi", ctypes.c_char_p), ("apiVersion", ctypes.c_int),
                ("pluginIdentifier", ctypes.c_char_p), ("pluginVersionMajor", ctypes.c_uint),
                ("pluginVersionMinor", ctypes.c_uint), ("setHost", ctypes.c_void_p), ("mainEntry", ctypes.c_void_p)]


class Core:
    """O binário compilado, com ajudantes em numpy."""

    def __init__(self, binary: Path):
        self.path = binary
        self.lib = lib = ctypes.CDLL(str(binary))
        lib.OfxGetPlugin.restype = ctypes.POINTER(OfxPlugin)
        lib.OfxGetPlugin.argtypes = [ctypes.c_int]
        lib.pc_render.argtypes = [FP, FP, FP, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_float, ctypes.c_int]
        lib.pc_color.argtypes = [FP, FP, FP, ctypes.c_int, ctypes.c_int]
        lib.pc_preset_ui.argtypes = [ctypes.c_int, FP]
        lib.pc_load_look.argtypes = [ctypes.c_char_p, FP, ctypes.c_char_p, ctypes.c_int]
        lib.pc_lut_exact_fraction.restype = ctypes.c_float
        lib.pc_lut_exact_fraction.argtypes = [FP]
        lib.pc_set_lut_tolerance.argtypes = [ctypes.c_float]

    @staticmethod
    def _p(a: np.ndarray):
        return a.ctypes.data_as(FP)

    def ui(self, values: dict) -> np.ndarray:
        return np.array(ofx.ui_values(values), np.float32)

    def color(self, values: dict, rgb: np.ndarray, exact: bool = True) -> np.ndarray:
        ui = self.ui(values)
        src = np.ascontiguousarray(rgb.reshape(-1, 3), np.float32)
        out = np.zeros_like(src)
        self.lib.pc_color(self._p(ui), self._p(src), self._p(out), src.shape[0], int(exact))
        return out.reshape(rgb.shape)

    def render(self, values: dict, rgb: np.ndarray, frame: int = 0, fps: float = 24.0, exact: bool = True):
        ui = self.ui(values)
        src = np.ascontiguousarray(rgb, np.float32)
        if rgb.dtype == np.uint8:
            src = np.ascontiguousarray(rgb.astype(np.float32) / 255.0)
        out = np.zeros_like(src)
        h, w = src.shape[:2]
        self.lib.pc_render(self._p(ui), self._p(src), self._p(out), w, h, frame, fps, int(exact))
        return out


def _dist_binary() -> Path | None:
    """O pacote de plugins/ofx/dist, se foi compilado destas mesmas fontes (o CI compila antes dos testes)."""
    bundle = ROOT / "plugins" / "ofx" / "dist" / BUILD.BUNDLE
    binary = bundle / "Contents" / BUILD.ARCH.get(sys.platform, "Linux-x86-64") / BUILD.BINARY
    info = bundle / "Contents" / "Resources" / ofx.VERSION_FILE
    if binary.is_file() and info.is_file() and f"fontes={BUILD.source_hash()}" in info.read_text(encoding="utf-8"):
        return binary
    return None


@pytest.fixture(scope="session")
def core() -> Core:
    shipped = _dist_binary()
    if shipped is not None:
        return Core(shipped)
    if BUILD.find_compiler() is None:
        pytest.skip("sem compilador C++ (Windows: Visual Studio Build Tools; Linux: g++)")
    cache = ROOT / "plugins" / "ofx" / "build"
    tag = "teste-" + BUILD.source_hash()
    if cache.is_dir():
        for old in cache.glob("teste-*"):
            if old.name != tag:
                shutil.rmtree(old, ignore_errors=True)
    out = cache / tag
    binary = out / BUILD.BUNDLE / "Contents" / BUILD.ARCH.get(sys.platform, "Linux-x86-64") / BUILD.BINARY
    if not binary.is_file():
        BUILD.build(out, out / "obj")
    return Core(binary)


def _grid(n: int) -> np.ndarray:
    """A mesma grade do Engine.bake_lut (R mais rápido, depois G, depois B)."""
    axis = np.linspace(0.0, 1.0, n, dtype=np.float32)
    img = np.zeros((n, n * n, 3), dtype=np.float32)
    for g in range(n):
        img[:, g * n:(g + 1) * n, 0] = axis[None, :]
        img[:, g * n:(g + 1) * n, 1] = axis[g]
    img[:, :, 2] = axis[:, None]
    return img


def _color_diff(core: Core, gl_engine, values: dict, n: int = 17) -> float:
    vals = dict(values, proj_on=False, lut_on=False)
    want = np.clip(gl_engine.bake_lut(vals, n), 0.0, 1.0)
    got = np.clip(core.color(vals, _grid(n)).reshape(-1, 3), 0.0, 1.0)
    return float(np.abs(want - got).max())


# ------------------------------------------------------------------ código gerado (sem compilador)
def test_generated_files_are_up_to_date():
    """plugins/ofx/generated vem dos kernels de resolve.py e das tabelas do app: rode tools/gerar_ofx.py."""
    details: dict[str, str] = {}
    assert ofx.generated_up_to_date(details) == [], details


def test_generated_comparison_tolerates_last_digit_only():
    a = "float m[3] = {0.123456789f, 1.0f};\nint k = 3;"
    assert ofx._same_code(a, a.replace("0.123456789f", "0.123456788f")) == ""
    assert ofx._same_code(a, a.replace("0.123456789f", "0.1235f")) != ""
    assert ofx._same_code(a, a.replace("int k", "int j")) != ""


def test_plugin_has_every_control_of_the_dctl_nodes():
    names = [s.ctl.name for s in ofx.slots()]
    assert len(names) == len(set(names))
    want = {c.name for c in resolve.cor_controls() + resolve.textura_controls() + resolve.projetor_controls()}
    assert set(names) == want - set(ofx.SKIP)
    keys = {s.ctl.key for s in ofx.slots() if s.ctl.key}
    for k in ("lab_separacao", "lab_dens_r", "lab_bypass_copia", "lab_neutro_negativo", "mtf", "entrada",
              "grao_forca", "hal_forca", "tremor_x", "poeira", "proporcao", "mix_geral"):
        assert k in keys, k
    assert ofx.ui_size() == sum(s.size for s in ofx.slots())
    # as seções do app viram os grupos do efeito, na ordem da janela
    order = [s.key for s in params.SECTIONS]
    groups = [s.group for s in ofx.slots()]
    assert groups == sorted(groups, key=order.index)


def test_cpp_dialect_shares_the_kernel_with_the_dctl():
    src = (ROOT / "plugins" / "ofx" / "generated" / "pc_kernels.h").read_text(encoding="ascii")
    for snippet in (resolve.K_LAB.strip().splitlines()[3], resolve.B_GAIN.strip().splitlines()[-1]):
        assert snippet.strip() in src
    assert "__DEVICE__" not in src and "PC_DEVICE" not in src
    assert "static const float PC_NEG[" in src  # tabelas do Laboratório no dialeto C++
    assert "p_frame" in src and "PC_FRAME" not in src.split("struct pc_frame")[1]


def test_params_header_lists_presets_and_utf8_labels():
    src = (ROOT / "plugins" / "ofx" / "generated" / "pc_params.h").read_text(encoding="ascii")
    assert f"#define PC_PRESET_COUNT {len(presets.BUILTIN)}" in src
    assert ofx._cstr("Película") in src  # rótulos com acento, em UTF-8 escapado
    assert ofx._cstr(presets.BUILTIN[0]["nome"]) in src


def test_ui_values_round_trip_the_app_values():
    v = presets.builtin_values("lab_teal_orange_5201")
    ui = ofx.ui_values(v)
    for s in ofx.slots():
        c = s.ctl
        if not c.key:
            continue
        got = ui[s.offset:s.offset + s.size]
        if c.kind == "color":
            assert got == pytest.approx(list(v[c.key]))
        elif c.kind == "combo":
            assert c.choices[int(got[0])][0] == str(v[c.key])
        elif c.kind == "check":
            assert bool(got[0]) == bool(v[c.key])
        elif c.kind == "float":
            assert got[0] * c.scale == pytest.approx(min(max(float(v[c.key]), c.lo * c.scale), c.hi * c.scale),
                                                     abs=1e-6)


# ------------------------------------------------------------------ pacote e instalação (sem compilador)
def _fake_bundle(root: Path, version: str = "9.9.9") -> Path:
    b = root / ofx.BUNDLE_NAME
    (b / "Contents" / ofx.arch_dir()).mkdir(parents=True)
    (b / "Contents" / ofx.arch_dir() / ofx.BINARY_NAME).write_bytes(b"binario")
    (b / "Contents" / "Resources").mkdir()
    (b / "Contents" / "Resources" / ofx.VERSION_FILE).write_text(f"versao={version}\n", encoding="utf-8")
    return b


def test_install_into_a_folder_replaces_the_old_bundle(tmp_path):
    dest = tmp_path / "OFX" / "Plugins"
    assert ofx.installed_version(dest) is None
    b1 = _fake_bundle(tmp_path / "v1", "1.0.0")
    assert ofx.install(dest, bundle=b1, elevate=False) == dest / ofx.BUNDLE_NAME
    assert ofx.installed_version(dest) == "1.0.0"
    (dest / ofx.BUNDLE_NAME / "Contents" / "velho.txt").write_text("x")
    b2 = _fake_bundle(tmp_path / "v2", "1.2.0")
    ofx.install(dest, bundle=b2, elevate=False)
    assert ofx.installed_version(dest) == "1.2.0"
    assert not (dest / ofx.BUNDLE_NAME / "Contents" / "velho.txt").exists()
    assert sorted(p.name for p in dest.iterdir()) == [ofx.BUNDLE_NAME]


def test_install_without_bundle_explains_how_to_build(tmp_path, monkeypatch):
    monkeypatch.setattr(ofx, "bundle_path", lambda: None)
    with pytest.raises(ofx.OfxError, match="build"):
        ofx.install(tmp_path, elevate=False)


def test_bundle_path_prefers_the_frozen_app(tmp_path, monkeypatch):
    meipass = tmp_path / "app"
    _fake_bundle(meipass / "ofx", "2.0.0")
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert ofx.bundle_path() == meipass / "ofx" / ofx.BUNDLE_NAME
    assert ofx.bundle_version(ofx.bundle_path()) == "2.0.0"


def test_install_dir_per_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(ofx.sys, "platform", "win32")
    monkeypatch.setenv("CommonProgramFiles", str(tmp_path / "Common Files"))
    assert ofx.install_dir() == tmp_path / "Common Files" / "OFX" / "Plugins"
    monkeypatch.setattr(ofx.sys, "platform", "linux")
    assert ofx.install_dir() == Path("/usr/OFX/Plugins")
    monkeypatch.setattr(ofx.sys, "platform", "darwin")
    assert ofx.install_dir() == Path("/Library/OFX/Plugins")


def test_elevated_command_asks_for_admin(monkeypatch, tmp_path):
    src, dest = tmp_path / "a b" / ofx.BUNDLE_NAME, tmp_path / "O'FX"
    monkeypatch.setattr(ofx.sys, "platform", "win32")
    cmd = ofx.elevated_command(src, dest)
    assert cmd[0] == "powershell.exe" and "-Verb RunAs" in cmd[-1] and "O''FX" in cmd[-1]
    monkeypatch.setattr(ofx.sys, "platform", "linux")
    cmd = ofx.elevated_command(src, dest)
    assert cmd[0] == "pkexec" and str(dest) in cmd[-1]


def test_build_script_flags_keep_precise_math():
    assert "/fp:precise" in BUILD.MSVC_FLAGS and not any("fast" in f for f in BUILD.MSVC_FLAGS)
    assert "-O2" in BUILD.GCC_FLAGS and "-shared" in BUILD.GCC_FLAGS and "-fPIC" in BUILD.GCC_FLAGS
    assert not any("fast-math" in f for f in BUILD.GCC_FLAGS)
    assert BUILD.app_version() == __version__


# ------------------------------------------------------------------ binário
def test_ofx_entry_points(core):
    lib = core.lib
    assert lib.OfxGetNumberOfPlugins() == 1
    p = lib.OfxGetPlugin(0).contents
    assert p.pluginApi == b"OfxImageEffectPluginAPI" and p.apiVersion == 1
    assert p.pluginIdentifier.decode() == ofx.PLUGIN_ID
    major, minor = (int(x) for x in __version__.split(".")[:2])
    assert (p.pluginVersionMajor, p.pluginVersionMinor) == (major, minor)
    assert p.setHost and p.mainEntry
    assert lib.pc_ui_size() == ofx.ui_size()


def test_presets_in_the_binary_are_the_app_presets(core):
    buf = np.zeros(ofx.ui_size(), np.float32)
    for i, p in enumerate(presets.BUILTIN):
        assert core.lib.pc_preset_ui(i, core._p(buf)) == 1
        np.testing.assert_allclose(buf, ofx.ui_values(presets.builtin_values(p["id"])), rtol=1e-6, atol=1e-6)
    assert core.lib.pc_preset_ui(len(presets.BUILTIN), core._p(buf)) == 0


def _load(core, text: str):
    buf = np.zeros(ofx.ui_size(), np.float32)
    err = ctypes.create_string_buffer(256)
    ok = core.lib.pc_load_look(text.encode("utf-8"), core._p(buf), err, 256)
    return ok, buf, err.value.decode("utf-8")


def test_reads_looks_exported_by_the_app(core, tmp_path):
    v = presets.builtin_values("lab_technicolor_hue_split")
    v["exposicao"] = 0.75
    path = tmp_path / "meu look.json"
    presets.export_file(str(path), "Meu look ç", v)
    ok, buf, err = _load(core, path.read_text(encoding="utf-8"))
    assert ok == 1, err
    np.testing.assert_allclose(buf, ofx.ui_values(v), atol=1e-5)
    # projeto .plc (mesma chave "valores"), chaves desconhecidas e tipos errados ficam no padrão do app
    proj = {"versao": 3, "valores": {"lab_on": True, "lab_negativo": "ecn2_5297", "iso": 500, "grao_forca": "x",
                                     "chave_nova": 1, "hal_cor": [1.0, 0.5, 0.25]}}
    ok, buf, err = _load(core, json.dumps(proj))
    want = params.sanitize(dict(params.defaults(), lab_on=True, lab_negativo="ecn2_5297", iso="500",
                                hal_cor=(1.0, 0.5, 0.25)))
    assert ok == 1, err
    np.testing.assert_allclose(buf, ofx.ui_values(want), atol=1e-5)
    ok, _b, err = _load(core, '{"nome": "sem valores"}')
    assert ok == 0 and "valores" in err
    ok, _b, err = _load(core, "{ quebrado")
    assert ok == 0 and err


# ------------------------------------------------------------------ paridade com o app (GPU)
@pytest.mark.gpu
@pytest.mark.parametrize("pid", [p["id"] for p in presets.BUILTIN])
def test_color_matches_the_app_for_every_preset(core, gl_engine, pid):
    assert _color_diff(core, gl_engine, presets.builtin_values(pid)) < 1e-4


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", [c[0] for c in params.PARAMS["entrada"].choices])
def test_color_matches_the_app_for_every_input_profile(core, gl_engine, entrada):
    v = presets.builtin_values("vision3_500t")
    v["entrada"] = entrada
    assert _color_diff(core, gl_engine, v) < 1e-4


@pytest.mark.gpu
def test_color_matches_the_app_for_every_lab_combination(core, gl_engine):
    base = params.defaults()
    worst = 0.0
    cases = [(0.0, 1.0, 0.3, 1.0, 0.0), (-2.0, 0.0, 1.0, 0.4, 6.0), (3.0, 2.0, 0.0, 0.7, -12.0)]
    for neg, cop, proc in itertools.product([k for k, _ in params.NEGATIVOS], [k for k, _ in params.COPIAS_LAB],
                                            [k for k, _ in params.PROCESSOS]):
        for push, xt, ch, fo, lr in cases:
            v = dict(base, lab_on=True, lab_negativo=neg, lab_copia=cop, lab_processo=proc, lab_revelacao=push,
                     lab_diafonia=xt, lab_chave=ch, lab_processo_forca=fo, lab_luz_r=lr, lab_luz_b=-lr / 2,
                     lab_densidade=lr / 3, cor_on=True, pele_matiz=12.0, pele_luz=-0.5, pele_sat=0.3)
            worst = max(worst, _color_diff(core, gl_engine, v, n=9))
    # mediana ~1e-6; nos ombros mais íngremes (R e B no máximo) a precisão do float da GPU pesa um pouco
    assert worst < 1e-3


NEW_LAB_CASES = [
    dict(lab_separacao=0.69),
    dict(lab_separacao=1.0, lab_separacao_eixo=200.0, lab_saturacao_filme=1.6),
    dict(lab_dens_r=1.8, lab_dens_g=0.4, lab_dens_b=2.0, lab_saturacao=1.7),
    dict(lab_pe=0.8, lab_luzes_rolagem=0.7, lab_sombras_rolagem=0.4, lab_pele_matiz=-20.0, lab_pele_sat=0.8),
    dict(lab_bypass_negativo=1.0, lab_bypass_copia=0.6, lab_neutro_negativo=1.0, lab_neutro_copia=0.7),
    dict(lab_separacao=0.69, lab_saturacao_filme=1.3, lab_processo="tech3", lab_neutro_copia=0.5, lab_pe=0.3),
]


@pytest.mark.gpu
@pytest.mark.parametrize("over", NEW_LAB_CASES, ids=[str(i) for i in range(len(NEW_LAB_CASES))])
@pytest.mark.parametrize("neg, cop", [("vision3_250d", "2383"), ("ecn2_5297", "e5386"), ("double_x", "2302")])
def test_color_matches_the_app_for_the_new_lab_controls(core, gl_engine, neg, cop, over):
    v = dict(params.defaults(), lab_on=True, lab_negativo=neg, lab_copia=cop, lab_luz_r=3.0, lab_luz_b=-2.0, **over)
    assert _color_diff(core, gl_engine, params.sanitize(v), n=9) < 1e-4


def test_fast_color_lut_stays_close_to_the_exact_math(core):
    rng = np.random.default_rng(7)
    sat = rng.random((20000, 3), dtype=np.float32)
    sat[np.arange(20000), rng.integers(0, 3, 20000)] = 0.0       # cores no limite do gamut
    pts = np.concatenate([_grid(17).reshape(-1, 3), rng.random((40000, 3), dtype=np.float32), sat])
    for pid in ("vision3_250d", "lab_teal_orange_5201", "super8_kodachrome", "blockbuster"):
        v = presets.builtin_values(pid)
        a = np.clip(core.color(v, pts, exact=True), 0, 1)
        b = np.clip(core.color(v, pts, exact=False), 0, 1)
        d = np.abs(a - b).max(axis=1)
        assert d.max() < 1e-2 and np.percentile(d, 99) < 2.5e-3, pid
        assert 0.0 <= core.lib.pc_lut_exact_fraction(core._p(core.ui(v))) < 0.5


def _neutral(**kw) -> dict:
    v = params.defaults()
    v["bitola"] = "nenhuma"
    v.update(kw)
    return v


def _app(gl_engine, img, vals, frame, fps=24.0):
    h, w = img.shape[:2]
    gl_engine.set_input(img)
    out = gl_engine.render(look.build_plan(vals, w, h, frame, fps, None, dither=False), 8)
    return out.astype(np.float32) / 255.0


def _scene(pid: str) -> dict:
    v = presets.builtin_values(pid)
    v["scan_on"] = False  # o scan da película (furos, borda) não existe no plugin
    return v


RENDER_CASES = [
    ("neutro", _neutral()),
    ("grao", _neutral(grao_on=True, grao_forca=1.5)),
    ("grao_35", _neutral(bitola="35mm", bitola_desfoque_on=False, bitola_vinheta=0.0, grao_on=True, iso="500",
                         grao_cor=0.6, grao_aspereza=0.5)),
    ("grao_s8", _neutral(bitola="super8", bitola_desfoque_on=False, bitola_vinheta=0.0, grao_on=True)),
    ("vinheta", _neutral(lente_on=True, vinheta=0.6)),
    ("maciez", _neutral(bitola="16mm", bitola_vinheta=0.0)),
    ("mtf", _neutral(mtf="close", mtf_forca=0.8)),
    ("nitidez", _neutral(lente_on=True, nitidez=1.0)),
    ("lente", _neutral(lente_on=True, aberracao=4.0, distorcao=0.1)),
    ("tremor", _neutral(proj_on=True, tremor_x=3, tremor_y=2, tremor_rot=0.2, cintilacao=0.1)),
    ("poeira", _neutral(desg_on=True, poeira=1.0, riscos=0.8, vazamento_on=False, poeira_tipo="mista")),
    ("eventos", _neutral(desg_on=True, poeira_on=False, riscos_on=False, vazamento_on=False, cabelo_on=True,
                         cabelo=1.0, manchas_on=True, manchas=1.0, marcas_on=True, emenda_on=True, emenda=1.0)),
    ("luz", _neutral(desg_on=True, poeira_on=False, riscos_on=False, vazamento=0.7, cor_instavel_on=True,
                     queima_on=True, queima=1.0)),
    ("moldura", _neutral(mold_on=True, proporcao="2.39", cantos=0.05, borda_irregular=0.5)),
    ("halacao", _neutral(hal_on=True, hal_forca=1.0, hal_limiar=1.0)),
    ("bloom", _neutral(bloom_on=True, bloom_forca=0.5, bloom_limiar=1.0)),
    ("nevoa", _neutral(bloom_on=True, bloom_forca=0.0, nevoa_forca=0.6)),
    ("super8_kodachrome", _scene("super8_kodachrome")),
    ("vision3_500t", _scene("vision3_500t")),
    ("lab_teal_orange", _scene("lab_teal_orange_5201")),
]


@pytest.mark.gpu
@pytest.mark.parametrize("name, vals", RENDER_CASES, ids=[c[0] for c in RENDER_CASES])
def test_full_frame_matches_the_app(core, gl_engine, test_rgb, name, vals):
    """Todas as passadas (desfoques de verdade, mipmaps, grão em grade, defeitos): ~1 nível de 8 bits do app.

    O app grava a luz linear em meio float (f2) e sai em 8 bits; o plugin é float32 do começo ao fim.
    """
    for frame in (0, 7, 61):
        want = _app(gl_engine, test_rgb, vals, frame)
        got = core.render(vals, test_rgb, frame)
        d = np.abs(want - got).max(axis=2) * 255
        assert np.percentile(d, 99) < 1.0 and d.mean() < 0.5, f"{name} quadro {frame}"
        limit = 4.0 if name in ("nitidez", "halacao") else 2.0
        assert (d > limit).mean() < 5e-4, f"{name} quadro {frame}: {d.max():.2f}"


@pytest.mark.gpu
def test_frame_rate_drives_the_projector_like_the_app(core, gl_engine, test_rgb):
    v = _neutral(proj_on=True, tremor_x=3, tremor_y=2, cintilacao=0.1)
    want = _app(gl_engine, test_rgb, v, 33, fps=30.0)
    got = core.render(v, test_rgb, 33, fps=30.0)
    assert np.abs(want - got).max() * 255 < 2.0


def test_render_is_deterministic_and_grain_follows_the_frame(core, test_rgb):
    v = _neutral(grao_on=True, desg_on=True, poeira=1.0)
    a, b = core.render(v, test_rgb, 3), core.render(v, test_rgb, 4)
    assert np.abs(a - b).mean() > 1e-3
    np.testing.assert_array_equal(a, core.render(v, test_rgb, 3))
    v["grao_animado"] = False
    v["desg_on"] = False
    np.testing.assert_array_equal(core.render(v, test_rgb, 3), core.render(v, test_rgb, 9))


def test_global_strength_zero_returns_the_input(core, test_rgb):
    v = _scene("super8_kodachrome")
    v.update(mix_geral=0.0, mold_on=False)
    np.testing.assert_allclose(core.render(v, test_rgb, 5), test_rgb.astype(np.float32) / 255.0, atol=1e-6)


def test_px1080_scaling_keeps_the_look_at_any_size(core, test_rgb):
    """Distâncias em px@1080: a mesma cena em 2x tem os mesmos brilhos e maciez (só mais pixels)."""
    v = _neutral(hal_on=True, hal_forca=1.0, hal_limiar=0.5, bloom_on=True, bloom_forca=0.6, lente_on=True,
                 maciez=0.6)
    small = core.render(v, test_rgb, 0)
    big_in = np.repeat(np.repeat(test_rgb, 2, axis=0), 2, axis=1)
    big = core.render(v, big_in, 0)
    down = big.reshape(small.shape[0], 2, small.shape[1], 2, 3).mean(axis=(1, 3))
    assert np.abs(down - small).mean() * 255 < 1.0


def test_show_curve_draws_over_the_image(core):
    img = np.full((108, 192, 3), 0.2, dtype=np.float32)
    v = dict(presets.builtin_values("lab_v3_250d_2383"), mix_geral=1.0)
    for k in ("grao_on", "hal_on", "bloom_on", "proj_on", "desg_on", "mold_on", "lente_on"):
        v[k] = False
    plain = core.render(v, img)
    ui = core.ui(v)
    slot = next(s for s in ofx.slots() if s.field == "mostrar_curva")  # controle só do plugin (sem chave)
    ui[slot.offset] = 1.0
    out = np.zeros_like(img)
    core.lib.pc_render(core._p(ui), core._p(img), core._p(out), 192, 108, 0, 24.0, 1)
    changed = np.abs(out - plain).max(axis=2) > 0.05
    assert changed.any() and changed.mean() < 0.2           # só as linhas, a imagem continua lá
    rows = np.nonzero(changed[:, 96])[0]                    # meio da largura = 0 stops = cinza médio
    assert rows.size and np.abs(rows - (1.0 - 0.45) * 108).min() < 3


# ------------------------------------------------------------------ o efeito num host OpenFX (tests/ofxhost.py)
@pytest.fixture(scope="session")
def host(core):
    """Um host para a sessão: o binário fica carregado e guarda o host (como num editor de verdade)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ofxhost
    h = ofxhost.Host(core.path)
    h.describe()
    yield h
    h.action("kOfxActionUnload")


def test_describe_declares_every_parameter_in_the_app_groups(host):
    K = __import__("ofxhost").K
    d = host.descriptor
    props = d["props"]
    assert props[K["kOfxPropLabel"]] == ["PeliculaConverter"]
    assert props[K["kOfxImageEffectPluginPropGrouping"]] == ["PeliculaConverter"]
    assert props[K["kOfxImageEffectPropSupportedContexts"]] == [K["kOfxImageEffectContextFilter"]]
    assert props[K["kOfxImageEffectPropSupportsTiles"]] == [0]
    assert sorted(d["clips"]) == ["Output", "Source"]
    defs = d["params"]["defs"]
    for s in ofx.slots():
        p = defs[s.field]
        label = p.props[K["kOfxPropLabel"]][0]
        assert label == ofx.label_of(s.ctl)
        parent = p.props[K["kOfxParamPropParent"]][0]
        assert defs[parent].props[K["kOfxPropLabel"]][0] == ofx.group_title(s.group)
    preset = defs["pc_preset"]
    assert len(preset.props[K["kOfxParamPropChoiceOption"]]) == len(presets.BUILTIN)
    assert preset.props[K["kOfxParamPropDefault"]] == [[p["id"] for p in presets.BUILTIN].index(presets.DEFAULT_ID)]
    assert defs["pc_arquivo"].props[K["kOfxParamPropStringMode"]] == [K["kOfxParamStringIsFilePath"]]
    # o efeito novo já sai com o preset padrão do app
    start = ofx.ui_values(presets.builtin_values(presets.DEFAULT_ID))
    for s in ofx.slots():
        dv = defs[s.field].props[K["kOfxParamPropDefault"]]
        want = start[s.offset:s.offset + s.size]
        assert [float(x) for x in dv] == pytest.approx(want, abs=1e-6), s.field


def _set_values(host, values: dict) -> None:
    ui = ofx.ui_values(values)
    for s in ofx.slots():
        v = ui[s.offset:s.offset + s.size]
        if s.ctl.kind == "float":
            host.set_param(s.field, float(v[0]))
        elif s.ctl.kind == "color":
            host.set_param(s.field, *[float(x) for x in v])
        else:
            host.set_param(s.field, int(round(v[0])))


def test_host_render_flips_rows_and_matches_the_core(host, core, test_rgb):
    v = _scene("super8_kodachrome")
    host.create_instance(test_rgb.shape[1], test_rgb.shape[0])
    _set_values(host, v)
    img = test_rgb.astype(np.float32) / 255.0
    got = host.render(img, time=12.0)
    np.testing.assert_allclose(got, core.render(v, img, 12, fps=24.0), atol=1e-6)
    assert not host.messages


def test_choosing_a_preset_sets_every_parameter(host):
    host.create_instance(64, 36)
    idx = [p["id"] for p in presets.BUILTIN].index("lab_teal_orange_5201")
    host.set_param("pc_preset", idx)
    assert host.change("pc_preset") in (0, 14)  # a biblioteca de apoio responde "padrão"
    want = ofx.ui_values(presets.builtin_values("lab_teal_orange_5201"))
    for s in ofx.slots():
        got = [float(x) for x in host.param(s.field).value]
        assert got == pytest.approx(want[s.offset:s.offset + s.size], abs=1e-5), s.field
    # abrir um projeto (o host trocando valores) não reaplica o preset
    host.set_param("exposicao", 1.25)
    host.change("pc_preset", reason="kOfxChangePluginEdited")
    assert host.param("exposicao").value == [1.25]


def test_loading_a_look_json_from_the_app(host, tmp_path):
    host.create_instance(64, 36)
    v = presets.builtin_values("vision3_500t")
    v.update(exposicao=-0.5, grao_forca=1.7, lab_on=True, lab_separacao=0.4)
    path = tmp_path / "pasta com 100% acento é" / "look.json"
    path.parent.mkdir()
    presets.export_file(str(path), "Look", v)
    host.set_param("pc_arquivo", str(path))
    assert host.change("pc_arquivo") in (0, 14)
    want = ofx.ui_values(params.sanitize(v))
    for s in ofx.slots():
        got = [float(x) for x in host.param(s.field).value]
        assert got == pytest.approx(want[s.offset:s.offset + s.size], abs=1e-5), s.field
    host.set_param("pc_arquivo", str(tmp_path / "nao existe 50%.json"))
    host.change("pc_arquivo")
    assert host.messages and host.messages[-1][0] == __import__("ofxhost").K["kOfxMessageError"]
    assert "50%%" in host.messages[-1][1]


def test_global_strength_zero_is_an_identity(host):
    host.create_instance(64, 36)
    host.set_param("mix_geral", 0.0)
    st, clip = host.is_identity()
    assert st == 0 and clip == "Source"
    host.set_param("mix_geral", 100.0)
    st, _clip = host.is_identity()
    assert st == __import__("ofxhost").REPLY_DEFAULT


def test_resolve_dialog_shows_the_openfx_section(tmp_path):
    """A janela (num processo à parte, offscreen) mostra o estado do plugin OpenFX e o botão certo."""
    import os
    import subprocess
    code = r"""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula import ofx, resolve
tmp = Path(sys.argv[1])
bundle = tmp / "app" / ofx.BUNDLE_NAME
(bundle / "Contents" / ofx.arch_dir()).mkdir(parents=True)
(bundle / "Contents" / ofx.arch_dir() / ofx.BINARY_NAME).write_bytes(b"x")
(bundle / "Contents" / "Resources").mkdir()
(bundle / "Contents" / "Resources" / ofx.VERSION_FILE).write_text("versao=2.0.0\n", encoding="utf-8")
plugins = tmp / "OFX" / "Plugins"
ofx.bundle_path = lambda: bundle
ofx.install_dir = lambda: plugins
resolve.lut_dirs = lambda: [tmp / "lut"]
from pelicula.ui.resolve_dialog import ResolveDialog
d = ResolveDialog(None)
assert d.btn_ofx_install.isEnabled(), "deveria poder instalar o OpenFX"
assert "OpenFX" in d.btn_ofx_install.text() and "ainda" in d.ofx_status.text(), d.ofx_status.text()
ofx.install(plugins, bundle=bundle, elevate=False)
d.refresh()
assert "2.0.0" in d.ofx_status.text(), d.ofx_status.text()
(plugins / ofx.BUNDLE_NAME / "Contents" / "Resources" / ofx.VERSION_FILE).write_text("versao=1.0.0\n")
d.refresh()
assert "1.0.0" in d.ofx_status.text() and "2.0.0" in d.ofx_status.text(), d.ofx_status.text()
ofx.bundle_path = lambda: None
d.refresh()
assert not d.btn_ofx_install.isEnabled()
assert "build_windows.bat" in d.ofx_status.text(), d.ofx_status.text()
print("OK")
app.exit(0)
"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PELICULA_SETTINGS_DIR=str(tmp_path / "cfg"),
               APPDATA=str(tmp_path / "appdata"), PELICULA_LANG="pt_BR")
    res = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=str(ROOT), env=env,
                         capture_output=True, timeout=120)
    assert res.returncode == 0 and b"OK" in res.stdout, res.stderr.decode("utf-8", "replace")[-2000:]
