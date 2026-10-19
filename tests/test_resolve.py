"""Plugin do DaVinci Resolve: DCTLs gerados, paridade com o app na GPU, pacote e instalação.

A paridade roda o MESMO kernel do DCTL em GLSL (dialeto `resolve.GLSL`, macros no lugar das funções
do Resolve) e compara com o próprio app: `Engine.bake_lut` para o nó Cor e `Engine.render` para a
Textura e o Projetor. Nada é instalado no Resolve de verdade: todas as pastas são temporárias.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pelicula import __version__, look, params, presets, resolve, shaders

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {k: resolve.source(k) for k in resolve.KINDS}


def _strip_comments(src: str) -> str:
    src = re.sub(r"//[^\n]*", "", src)
    return re.sub(r"/\*.*?\*/", "", src, flags=re.S)


def _code_lines(src: str) -> list[str]:
    """Linhas de código (sem comentários nem as definições de interface, que seguem o exemplo oficial)."""
    out = []
    for ln in _strip_comments(src).splitlines():
        if ln.startswith(("DEFINE_UI_PARAMS", "DEFINE_UI_TOOLTIP")):
            continue
        out.append(ln)
    return out


# ------------------------------------------------------------------ fonte do DCTL
@pytest.mark.parametrize("kind", resolve.KINDS)
def test_dctl_is_ascii_with_balanced_brackets(kind):
    src = SOURCES[kind]
    src.encode("ascii")
    code = re.sub(r'"[^"\n]*"', '""', _strip_comments(src))
    for a, b in ("()", "{}", "[]"):
        assert code.count(a) == code.count(b), f"{kind}: {a}{b} desbalanceados"


@pytest.mark.parametrize("kind", resolve.KINDS)
def test_entry_point_is_exactly_the_documented_signature(kind):
    src = SOURCES[kind]
    if kind == "cor":
        sig = ("__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, "
               "float p_B)")
    else:
        sig = ("__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, __TEXTURE__ p_TexR, "
               "__TEXTURE__ p_TexG, __TEXTURE__ p_TexB)")
    assert src.count("transform(") == 1 and sig in src


@pytest.mark.parametrize("kind", resolve.KINDS)
def test_control_limits_of_the_resolve_ui(kind):
    counts = resolve.control_counts(kind)
    for typ, n in counts.items():
        assert n <= (5 if typ == "color" else 64), f"{kind}: {n} controles {typ}"
    src = SOURCES[kind]
    assert src.count("DCTLUI_COLOR_PICKER") == counts.get("color", 0) <= 5
    assert src.count("DEFINE_UI_PARAMS") == sum(counts.values())


@pytest.mark.parametrize("kind", resolve.KINDS)
def test_labels_are_safe_and_unique(kind):
    ctls = resolve.spec(kind).controls
    labels = [c.label for c in ctls]
    assert len(set(labels)) == len(labels), "rótulos repetidos quebram o DEFINE_UI_TOOLTIP"
    names = [c.name for c in ctls]
    assert len(set(names)) == len(names)
    for c in ctls:
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .\-]*", c.label), c.label
        assert re.fullmatch(r"ui_[a-z0-9_]+", c.name), c.name
        assert '"' not in c.tip and "\n" not in c.tip
        for _v, lab in c.choices:
            assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .\-]*", lab), lab
    enums = [e for c in ctls for e in c.enums()]
    assert len(set(enums)) == len(enums), "enums de combos diferentes não podem ter o mesmo nome"


@pytest.mark.parametrize("kind", resolve.KINDS)
def test_float_literals_have_the_f_suffix(kind):
    bad = []
    for ln in _code_lines(SOURCES[kind]):
        for m in re.finditer(r"(?<![\w.])(\d+\.\d*(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+)(f?)(?![\w.])", ln):
            if not m.group(2):
                bad.append(ln.strip())
    assert not bad, bad[:5]


@pytest.mark.parametrize("kind", resolve.KINDS)
def test_no_glsl_leftovers_swizzles_or_overloads(kind):
    code = "\n".join(_code_lines(SOURCES[kind]))
    for word in ("vec2", "vec3", "vec4", "uniform", "texture", "texelFetch", "mix", "smoothstep", "clamp", "fract",
                 "mod", "dot", "length", "PC_DEVICE", "gl_FragCoord"):
        assert not re.search(rf"\b{word}\b", code), f"{kind}: '{word}' não existe no DCTL"
    assert not re.search(r"\.[xyzwrgb]{2,}\b", code), "swizzle não existe no DCTL"
    names = re.findall(r"__DEVICE__\s+\w+\s+(\w+)\s*\(", code)
    assert len(names) == len(set(names)), "sobrecarga de funções não compila no OpenCL"
    assert all(n.startswith("pc_") or n == "transform" for n in names)


def test_frame_index_is_version_guarded():
    for kind in ("textura", "projetor"):
        src = SOURCES[kind]
        assert "TIMELINE_FRAME_INDEX" in src and "__RESOLVE_VER_MAJOR__" in src
        assert "#define PC_FRAME (1)" in src
    assert "TIMELINE_FRAME_INDEX" not in SOURCES["cor"]


def test_tables_come_from_the_app_tables():
    src = SOURCES["cor"]
    m = re.search(r"PC_GAM\[\d+\] = \{([^}]*)\}", src)
    vals = [float(x.strip().rstrip("f")) for x in m.group(1).split(",")]
    entradas = [c[0] for c in params.PARAMS["entrada"].choices]
    want = np.concatenate([look.gamut_to_709(look.INPUT_GAMUT[e]).flatten() for e in entradas])
    np.testing.assert_allclose(vals, want, rtol=1e-6, atol=1e-7)
    m = re.search(r"PC_NEG\[(\d+)\]", src)
    assert int(m.group(1)) == resolve.NEG_FIELDS * len(params.NEGATIVOS)


def test_ascii_helpers():
    assert resolve.ascii_text("Exposição (EV), força") == "Exposicao EV forca"
    assert resolve.safe_file_name('Super 8 • Kodachrome: "40"') == "Super 8 - Kodachrome 40"
    assert resolve.flt(1) == "1.0f" and resolve.flt(-0.5) == "-0.5f" and resolve.flt(1e-7) == "1.0e-7f"
    assert resolve.flt(0.155) == "0.155f"


@pytest.mark.parametrize("pid", ["vision3_500t", "super8_kodachrome", "double_x", "lab_technicolor3"])
def test_preset_dctl_defaults_are_the_preset_values(pid):
    vals = presets.builtin_values(pid)
    for kind in resolve.KINDS:
        src = resolve.source(kind, values=vals)
        for c in resolve.spec(kind).controls:
            if not c.key:
                continue
            m = re.search(rf"DEFINE_UI_PARAMS\({c.name}, [^,]+, (\w+), ([^,)]+)", src)
            assert m, c.name
            want = c.ui_value(vals[c.key])
            if c.kind == "float":
                assert float(m.group(2)) == pytest.approx(want, abs=1e-5), c.name
            elif c.kind in ("int", "check", "combo"):
                assert int(m.group(2)) == want, c.name


def test_preset_files_follow_what_the_preset_uses():
    assert resolve.preset_files(presets.BY_ID["vision3_250d"]) == ["cor", "textura"]
    assert resolve.preset_files(presets.BY_ID["8mm_caseiro"]) == ["cor", "textura", "projetor"]


# ------------------------------------------------------------------ pacote e instalação
def test_build_package_without_luts(tmp_path):
    files = resolve.build_package(tmp_path, luts=False)
    root = tmp_path / resolve.PACKAGE_NAME
    for kind in resolve.KINDS:
        assert (root / resolve.FILE_NAMES[kind]).is_file()
    items = [p for p in presets.BUILTIN if p["valores"] is not None]
    n_presets = sum(len(resolve.preset_files(p)) for p in items)
    assert len(list((root / "Presets").glob("*.dctl"))) == n_presets
    assert not (root / "LUTs").exists()
    assert "PeliculaConverter" in (root / "LEIA-ME.txt").read_text(encoding="utf-8")
    assert resolve.installed_version(tmp_path) == __version__
    assert all(f.exists() for f in files)
    for f in root.rglob("*.dctl"):
        f.read_text(encoding="ascii")


@pytest.mark.gpu
def test_build_package_with_luts(tmp_path, gl_engine):
    resolve.build_package(tmp_path, presets=False, engine=gl_engine, lut_size=9)
    cubes = sorted((tmp_path / resolve.PACKAGE_NAME / "LUTs").glob("*.cube"))
    assert len(cubes) == len([p for p in presets.BUILTIN if p["valores"] is not None])
    from pelicula import luts
    lut = luts.load_cube(str(cubes[0]))
    assert lut.size == 9 and lut.data.shape == (729, 3)


def test_install_into_folder_updates_and_protects_foreign_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(resolve, "_bake_luts", lambda items, size, engine=None: {})
    dest = resolve.install(tmp_path)
    assert dest == tmp_path / resolve.PACKAGE_NAME and resolve.is_installed(tmp_path)
    (dest / "VERSAO.txt").write_text("PeliculaConverter\nversao=0.0.1\n", encoding="utf-8")
    (dest / "lixo_antigo.dctl").write_text("x", encoding="ascii")
    assert resolve.installed_version(tmp_path) == "0.0.1"
    resolve.install(tmp_path)
    assert resolve.installed_version(tmp_path) == __version__
    assert not (dest / "lixo_antigo.dctl").exists(), "a atualização troca a pasta inteira"
    assert not any(p.name.endswith((".novo", ".antigo")) for p in tmp_path.iterdir())
    other = tmp_path / "outro"
    (other / resolve.PACKAGE_NAME).mkdir(parents=True)
    (other / resolve.PACKAGE_NAME / "meu.cube").write_text("x", encoding="ascii")
    with pytest.raises(resolve.ResolveError):
        resolve.install(other)
    assert (other / resolve.PACKAGE_NAME / "meu.cube").exists()


def test_install_without_resolve_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(resolve, "lut_dirs", lambda: [tmp_path / "nao_existe"])
    assert resolve.default_install_dir() is None
    assert not resolve.is_installed()
    with pytest.raises(resolve.ResolveError):
        resolve.install()


def test_lut_dirs_per_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(resolve.sys, "platform", "win32")
    monkeypatch.setenv("ProgramData", str(tmp_path))
    d = tmp_path / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT"
    assert resolve.lut_dirs() == [d]
    assert resolve.default_install_dir() is None
    d.mkdir(parents=True)
    assert resolve.default_install_dir() == d
    monkeypatch.setattr(resolve.sys, "platform", "linux")
    dirs = resolve.lut_dirs()
    assert Path("/opt/resolve/LUT") in dirs and any(".local" in str(p) for p in dirs)
    monkeypatch.setattr(resolve.sys, "platform", "darwin")
    assert any("Library" in str(p) for p in resolve.lut_dirs())


# ------------------------------------------------------------------ paridade na GPU (dialeto GLSL)
class Harness:
    """Roda os kernels do DCTL em GLSL com o moderngl, no mesmo contexto do Engine dos testes."""

    def __init__(self, engine):
        import moderngl
        self.mgl = moderngl
        self.eng = engine
        self.ctx = engine.ctx
        self.progs = {}

    def prog(self, kind: str):
        if kind not in self.progs:
            p = self.ctx.program(vertex_shader=shaders.VERT, fragment_shader=resolve.source(kind, resolve.GLSL))
            self.progs[kind] = (p, self.ctx.vertex_array(p, [(self.eng.vbo, "2f", "in_pos")]))
        return self.progs[kind]

    def run(self, kind: str, values: dict, img: np.ndarray, frame: int = 0, **ui) -> np.ndarray:
        p, vao = self.prog(kind)
        h, w = img.shape[:2]
        dtype = "f4" if img.dtype == np.float32 else "f1"
        tex = self.ctx.texture((w, h), 3, data=np.ascontiguousarray(img).tobytes(), dtype=dtype, alignment=1)
        out = self.ctx.texture((w, h), 4, dtype="f4")
        fbo = self.ctx.framebuffer([out])
        try:
            vals = resolve.ui_uniforms(kind, values)
            vals.update(ui)
            for k, v in vals.items():
                m = p.get(k, None)
                if m is not None:
                    m.value = v
            m = p.get("u_frame", None)
            if m is not None:
                m.value = int(frame)
            tex.use(0)
            p["t_img"].value = 0
            fbo.use()
            vao.render(self.mgl.TRIANGLE_STRIP)
            data = fbo.read(components=3, dtype="f4")
        finally:
            fbo.release()
            out.release()
            tex.release()
        return np.frombuffer(data, np.float32).reshape(h, w, 3)


@pytest.fixture(scope="module")
def harness(gl_engine):
    return Harness(gl_engine)


def _grid(n: int) -> np.ndarray:
    """A mesma grade do Engine.bake_lut (R mais rápido, depois G, depois B)."""
    axis = np.linspace(0.0, 1.0, n, dtype=np.float32)
    img = np.zeros((n, n * n, 3), dtype=np.float32)
    for g in range(n):
        img[:, g * n:(g + 1) * n, 0] = axis[None, :]
        img[:, g * n:(g + 1) * n, 1] = axis[g]
    img[:, :, 2] = axis[:, None]
    return img


def _cor_diff(harness, gl_engine, values: dict, n: int = 17) -> float:
    vals = dict(values, proj_on=False, lut_on=False)
    want = np.clip(gl_engine.bake_lut(vals, n), 0.0, 1.0)
    got = harness.run("cor", vals, _grid(n)).reshape(-1, 3)
    return float(np.abs(want - got).max())


@pytest.mark.gpu
@pytest.mark.parametrize("kind", resolve.KINDS)
def test_glsl_dialect_compiles(harness, kind):
    harness.prog(kind)


@pytest.mark.gpu
@pytest.mark.parametrize("pid", [p["id"] for p in presets.BUILTIN])
def test_cor_node_matches_the_app_for_every_preset(harness, gl_engine, pid):
    assert _cor_diff(harness, gl_engine, presets.builtin_values(pid)) < 2e-3


@pytest.mark.gpu
@pytest.mark.parametrize("entrada", [c[0] for c in params.PARAMS["entrada"].choices])
def test_cor_node_matches_the_app_for_every_input_profile(harness, gl_engine, entrada):
    v = presets.builtin_values("vision3_500t")
    v["entrada"] = entrada
    assert _cor_diff(harness, gl_engine, v) < 2e-3


@pytest.mark.gpu
def test_cor_node_matches_the_app_for_every_lab_combination(harness, gl_engine):
    base = params.defaults()
    worst = 0.0
    cases = [(0.0, 1.0, 0.3, 1.0, 0.0), (-2.0, 0.0, 1.0, 0.4, 6.0), (3.0, 2.0, 0.0, 0.7, -12.0)]
    for neg, cop, proc in itertools.product([k for k, _ in params.NEGATIVOS], [k for k, _ in params.COPIAS_LAB],
                                            [k for k, _ in params.PROCESSOS]):
        for push, xt, ch, fo, lr in cases:
            v = dict(base, lab_on=True, lab_negativo=neg, lab_copia=cop, lab_processo=proc, lab_revelacao=push,
                     lab_diafonia=xt, lab_chave=ch, lab_processo_forca=fo, lab_luz_r=lr, lab_luz_b=-lr / 2,
                     lab_densidade=lr / 3, cor_on=True, pele_matiz=12.0, pele_luz=-0.5, pele_sat=0.3)
            worst = max(worst, _cor_diff(harness, gl_engine, v, n=9))
    assert worst < 2e-3


@pytest.mark.gpu
def test_cor_node_neutral_and_global_mix(harness):
    v = params.defaults()
    img = _grid(9)
    # a curva neutra vai e volta (a menos do limite de -12 stops perto do preto, como no app)
    np.testing.assert_allclose(harness.run("cor", v, img), np.clip(img, 0, 1), atol=2e-3)
    v.update(cor_on=True, contraste=1.4, saturacao=1.6, mix_geral=0.0)
    np.testing.assert_allclose(harness.run("cor", v, img), img, atol=1e-6)


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


EXACT = [
    ("grao", "textura", _neutral(grao_on=True, grao_forca=1.5)),
    ("grao_35", "textura", _neutral(bitola="35mm", bitola_desfoque_on=False, bitola_vinheta=0.0, grao_on=True,
                                    iso="500", grao_cor=0.6, grao_aspereza=0.5)),
    ("grao_s8", "textura", _neutral(bitola="super8", bitola_desfoque_on=False, bitola_vinheta=0.0, grao_on=True)),
    ("vinheta", "textura", _neutral(lente_on=True, vinheta=0.6)),
    ("maciez", "textura", _neutral(bitola="16mm", bitola_vinheta=0.0)),
    ("nitidez", "textura", _neutral(lente_on=True, nitidez=1.0)),
    ("lente", "textura", _neutral(lente_on=True, aberracao=4.0, distorcao=0.1)),
    ("tremor", "projetor", _neutral(proj_on=True, tremor_x=3, tremor_y=2, tremor_rot=0.2, cintilacao=0.1)),
    ("poeira", "projetor", _neutral(desg_on=True, poeira=1.0, riscos=0.8, vazamento_on=False, poeira_tipo="mista")),
    ("eventos", "projetor", _neutral(desg_on=True, poeira_on=False, riscos_on=False, vazamento_on=False,
                                     cabelo_on=True, cabelo=1.0, manchas_on=True, manchas=1.0, marcas_on=True,
                                     emenda_on=True, emenda=1.0)),
    ("luz", "projetor", _neutral(desg_on=True, poeira_on=False, riscos_on=False, vazamento=0.7,
                                 cor_instavel_on=True, queima_on=True, queima=1.0)),
    ("moldura", "projetor", _neutral(mold_on=True, proporcao="2.39", cantos=0.05, borda_irregular=0.5)),
]


@pytest.mark.gpu
@pytest.mark.parametrize("name, kind, vals", EXACT, ids=[e[0] for e in EXACT])
def test_texture_and_projector_match_the_app(harness, gl_engine, test_rgb, name, kind, vals):
    """Grão, lente, maciez, vinheta, tremor, cintilação e defeitos: a menos de ~1/255 do app."""
    for frame in (0, 7, 61):
        want = _app(gl_engine, test_rgb, vals, frame)
        got = harness.run(kind, vals, test_rgb, frame)
        d = np.abs(want - got)
        # o app guarda a luz linear em meio float (f2); a nitidez amplifica essa diferença
        limit = 4.0 if name == "nitidez" else 2.5
        assert d.max() * 255 < limit and d.mean() * 255 < 0.5, f"{name} quadro {frame}"


@pytest.mark.gpu
@pytest.mark.parametrize("vals", [_neutral(hal_on=True, hal_forca=1.0, hal_limiar=1.0),
                                  _neutral(bloom_on=True, bloom_forca=0.5, bloom_limiar=1.0)], ids=["hal", "bloom"])
def test_glows_are_a_close_single_pass_approximation(harness, gl_engine, test_rgb, vals):
    """Halação e bloom numa passada: sem viés (média em blocos) e ruído pequeno."""
    want = _app(gl_engine, test_rgb, vals, 0)
    got = harness.run("textura", vals, test_rgb, 0)
    h, w = test_rgb.shape[:2]
    bias = (want - got)[: h // 8 * 8, : w // 8 * 8].reshape(h // 8, 8, w // 8, 8, 3).mean(axis=(1, 3))
    assert np.abs(bias).max() * 255 < 4.0
    assert np.percentile(np.abs(want - got), 99) * 255 < 8.0


@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["textura", "projetor"])
def test_texture_nodes_pass_through_when_off(harness, test_rgb, kind):
    v = params.defaults()
    v.update(bitola="nenhuma", grao_on=False, hal_on=False, bloom_on=False, lente_on=False, proj_on=False,
             desg_on=False, mold_on=False)
    got = harness.run(kind, v, test_rgb, 5)
    np.testing.assert_allclose(got, test_rgb.astype(np.float32) / 255.0, atol=1e-6)


@pytest.mark.gpu
def test_grain_animates_with_the_timeline_frame(harness, test_rgb):
    v = _neutral(grao_on=True)
    a, b = harness.run("textura", v, test_rgb, 3), harness.run("textura", v, test_rgb, 4)
    assert np.abs(a - b).mean() > 1e-3
    np.testing.assert_array_equal(a, harness.run("textura", v, test_rgb, 3))
    v["grao_animado"] = False
    np.testing.assert_array_equal(harness.run("textura", v, test_rgb, 3), harness.run("textura", v, test_rgb, 9))


@pytest.mark.gpu
def test_projector_fps_choice_follows_the_timeline_rate(harness, gl_engine, test_rgb):
    v = _neutral(proj_on=True, tremor_x=3, tremor_y=2, cintilacao=0.1)
    fps_idx = [k for k, _l in resolve.FPS_CHOICES].index("30")
    want = _app(gl_engine, test_rgb, v, 33, fps=30.0)
    got = harness.run("projetor", v, test_rgb, 33, ui_fps=fps_idx)
    assert np.abs(want - got).max() * 255 < 2.5


# ------------------------------------------------------------------ janela
def test_resolve_dialog_opens_offscreen(tmp_path):
    """A janela abre (num processo à parte, com QApplication própria) e mostra o estado da instalação."""
    code = r"""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pelicula import resolve
target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
resolve.lut_dirs = lambda: [target]
from pelicula.ui.resolve_dialog import ResolveDialog
d = ResolveDialog(None)
assert d.btn_install.isEnabled(), "deveria poder instalar"
assert "ainda" in d.status.text(), d.status.text()
(target / resolve.PACKAGE_NAME).mkdir()
(target / resolve.PACKAGE_NAME / resolve.MARKER).write_text("versao=0.0.1\n", encoding="utf-8")
d.refresh()
assert "0.0.1" in d.status.text(), d.status.text()
print("OK")
app.exit(0)
"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PELICULA_SETTINGS_DIR=str(tmp_path / "cfg"),
               APPDATA=str(tmp_path / "appdata"))
    res = subprocess.run([sys.executable, "-c", code, str(tmp_path / "lut")], cwd=str(ROOT), env=env,
                         capture_output=True, timeout=120)
    assert res.returncode == 0 and b"OK" in res.stdout, res.stderr.decode("utf-8", "replace")[-2000:]
