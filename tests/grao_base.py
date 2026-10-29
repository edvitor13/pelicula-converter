"""Referência do look gravada pela BASE da 1.6 (575c6f5), antes do grão e da textura da 1.6 (frente "grão").

Os ajustes novos de grão e textura (maciez pelo grão, nitidez por camada, grão no negativo, estrutura pela
densidade, halação física, respiração por camada) começam num padrão neutro: com eles no padrão, nada pode mudar
um bit. Este módulo calcula, para um conjunto de looks (todos os presets e alguns looks com tudo ligado):

- os uniforms e as cadeias do plano (`look.build_plan`) — sem GPU, valem em qualquer computador;
- os hashes dos quadros do look (8 e 16 bits, modo Película e uma montagem do modo Edição), dos LUTs exportados
  (`Engine.bake_lut`) e dos nós do plugin do DaVinci (dialeto GLSL de `resolve.py`) na GPU;
- os hashes do quadro do plugin OpenFX (`pc_render`, se houver o binário compilado das fontes atuais);

e compara com `tests/data/grao_base.json`:

    python tests/grao_base.py        # regrava a referência (só faz sentido no código da BASE)

Os hashes da GPU dependem da placa e do driver (`GL_RENDERER`) e os do OpenFX do compilador: `tests/test_grao.py`
só os confere quando são os mesmos da gravação. Os uniforms são conferidos em todo lugar (com tolerância: a
calibração do Laboratório usa mínimos quadrados, que podem diferir no último dígito de uma CPU para outra), e só as
chaves que a BASE tinha (uma frente nova pode acrescentar uniforms).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data" / "grao_base.json"
W, H = 320, 180
FRAMES = (0, 7, 61)


def _neutral(**kw) -> dict:
    from pelicula import params
    v = params.defaults()
    v["bitola"] = "nenhuma"
    v.update(kw)
    return params.sanitize(v)


def looks() -> dict[str, dict]:
    """Looks conferidos: todos os presets e looks com o grão, a halação, a maciez e o Laboratório ligados."""
    from pelicula import params, presets
    out = {"padrao": params.defaults()}
    for p in presets.BUILTIN:
        out["preset_" + p["id"]] = presets.builtin_values(p["id"])
    grain = dict(grao_on=True, grao_forca=1.4, grao_aspereza=0.5, grao_cor=0.6)
    out["grao"] = _neutral(**grain)
    out["grao_35_500"] = params.sanitize(dict(params.defaults(), bitola="35mm", iso="500", **grain))
    out["grao_s8_parado"] = params.sanitize(dict(params.defaults(), bitola="super8", grao_animado=False, **grain))
    out["grao_lab"] = params.sanitize(dict(params.defaults(), lab_on=True, lab_revelacao=1.0, **grain))
    out["maciez_mtf"] = params.sanitize(dict(params.defaults(), bitola="16mm", mtf="close", mtf_forca=0.8,
                                             lente_on=True, maciez=0.4, nitidez=0.6))
    out["halacao"] = _neutral(hal_on=True, hal_forca=1.2, hal_limiar=1.0, hal_raio=20.0)
    out["halacao_scan"] = params.sanitize(dict(params.defaults(), hal_on=True, hal_forca=1.0, hal_limiar=0.5,
                                               scan_on=True))
    out["brilhos"] = _neutral(hal_on=True, bloom_on=True, bloom_forca=0.6, nevoa_forca=0.4)
    out["lab_tudo"] = params.sanitize(dict(params.defaults(), lab_on=True, lab_negativo="vision3_500t",
                                           lab_copia="2393", lab_separacao=0.6, lab_luz_r=3.0, lab_pe=0.3,
                                           lab_saturacao=1.2, grao_on=True, hal_on=True, bitola="16mm"))
    out["lab_scan"] = params.sanitize(dict(params.defaults(), lab_on=True, lab_copia="nenhuma", grao_on=True))
    out["slog3"] = params.sanitize(dict(presets.builtin_values("vision3_250d"), entrada="slog3"))
    return out


def _num(v):
    if isinstance(v, (tuple, list)):
        return [_num(x) for x in v]
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    return v


def plan_data(v: dict, w: int, h: int, frame: int) -> dict:
    from pelicula import look
    p = look.build_plan(v, w, h, frame, 24.0, None, dither=True)
    return {"uniforms": {k: _num(x) for k, x in sorted(p.uniforms.items())}, "soft_sigma": p.soft_sigma,
            "chains": [[c.name, c.threshold, c.sigma, c.limit, int(c.lum_only), int(c.alpha_mask)] for c in p.chains],
            "grain_size": p.grain_size, "grain_seed": p.grain_seed, "lut_path": p.lut_path, "edge_text": p.edge_text}


def plans() -> dict:
    """Planos de cada look em 1920 × 1080 (quadro 7) e, nos looks de textura, também 320 × 180 e quadro 61."""
    out = {}
    for name, v in looks().items():
        out[f"{name}@1920x1080#7"] = plan_data(v, 1920, 1080, 7)
        if not name.startswith("preset_"):
            out[f"{name}@{W}x{H}#61"] = plan_data(v, W, H, 61)
    return out


def image16(img8: np.ndarray) -> np.ndarray:
    """A cena de teste em 16 bits, com um degradê fino somado (usa os bits a mais)."""
    h, w = img8.shape[:2]
    ramp = (np.arange(w, dtype=np.int64)[None, :, None] * 37 + np.arange(h, dtype=np.int64)[:, None, None] * 11) % 257
    return np.clip(img8.astype(np.int64) * 257 + ramp - 128, 0, 65535).astype(np.uint16)


def _sha(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def film_hashes(engine) -> dict:
    """Quadros do look (modo Película) em 8 e 16 bits pela receita única (`frame.Recipe`)."""
    from pelicula import frame, testimage
    img8 = testimage.make(W, H)
    img16 = image16(img8)
    out = {}
    for name, v in looks().items():
        for depth, img in ((8, img8), (16, img16)):
            r = frame.Recipe.for_source(v, 24.0, depth, legal=name != "slog3", dither=depth == 8)
            for f in FRAMES:
                out[f"{name}/{depth}/{f}"] = _sha(r.render(engine, img, f))
    return out


def montage():
    """Montagem 320 × 180 de dois clipes com ajustes de cor e um título por cima (modo Edição)."""
    from pelicula import timeline as tl
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")
    a, = seq.insert_media(tl.Source("a.mp4", W, H, 24.0, "24/1", 96, 4.0, has_audio=False), at=0)
    seq.trim_end(a.id, 48)
    b, = seq.insert_media(tl.Source("b.mp4", W, H, 24.0, "24/1", 96, 4.0, has_audio=False), at=48)
    seq.set_values(b.id, {**b.values, "exposicao": 0.4, "saturacao": 0.3, "temperatura": 15.0})
    c, = seq.insert_media(tl.Source("c.mp4", 160, 90, 24.0, "24/1", 96, 4.0, has_audio=False), at=20, vtrack=1)
    seq.set_values(c.id, {**c.values, "escala": 0.6, "opacidade": 0.7, "pos_x": 0.2})
    return seq


def edit_layers(seq, t: int, depth: int):
    from pelicula import sequence
    out = []
    for layer in seq.layers_at(t):
        src = seq.sources[layer.clip.src]
        dw, dh = sequence.decode_size(seq, layer.clip, W, H)
        seed = sum(src.path.encode())
        y, x = np.mgrid[0:dh, 0:dw]
        base = x * 3 + y * 5 + layer.src_frame * 7 + seed * 41
        rgb = np.stack([base % 256, (base * 3 + 17) % 256, (x * 2 + y + seed * 13) % 256], axis=-1) / 255.0
        mx = 255 if depth == 8 else 65535
        img = np.rint(rgb * mx).astype(np.uint8 if depth == 8 else np.uint16)
        out.append(sequence.LayerImage(layer, img))
    return sequence.FrameLayers(t, out)


def edit_hashes(engine) -> dict:
    """Quadros da montagem com o look por cima (modo Edição com película), 8 e 16 bits."""
    from pelicula import frame, presets
    seq = montage()
    out = {}
    for pid in ("vision3_500t", "lab_v3_250d_2383", "super8_kodachrome"):
        v = presets.builtin_values(pid)
        for depth in (8, 16):
            r = frame.Recipe.for_source(v, 24.0, depth, legal=True, seq=seq, dither=False)
            for t in (5, 30, 60):
                out[f"{pid}/{depth}/{t}"] = _sha(r.render(engine, edit_layers(seq, t, depth), t))
    return out


def lut_hashes(engine) -> dict:
    out = {}
    for name, v in looks().items():
        vals = dict(v, lut_on=False)
        out[name] = _sha(engine.bake_lut(vals, 17))
        if name in ("slog3", "lab_tudo", "padrao"):
            out[name + "/legal"] = _sha(engine.bake_lut(vals, 17, legal=True))
    return out


def plugin_hashes(engine) -> dict:
    """Nós do plugin do DaVinci (dialeto GLSL, como `tests/test_resolve.py`) com os controles do app."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_resolve import Harness, _grid

    from pelicula import params, testimage
    hn = Harness(engine)
    img = testimage.make(W, H)
    grid = _grid(9)
    out = {}
    for name, v in looks().items():
        vals = dict(v, proj_on=False, lut_on=False)
        out[f"cor/{name}"] = _sha(hn.run("cor", vals, grid))
        lab = dict(vals, lab_on=True, cor_on=False, copia="nenhuma", envelhecimento=0.0)
        out[f"laboratorio/{name}"] = _sha(hn.run("laboratorio", lab, grid))
        for f in (0, 7):
            out[f"textura/{name}/{f}"] = _sha(hn.run("textura", v, img, f))
    del params
    return out


def ofx_core():
    """O binário do OpenFX compilado das fontes atuais (o mesmo do `tests/test_ofx.py`), ou None."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_ofx
    shipped = test_ofx._dist_binary()
    if shipped is not None:
        return test_ofx.Core(shipped)
    if test_ofx.BUILD.find_compiler() is None:
        return None
    out = ROOT / "plugins" / "ofx" / "build" / ("teste-" + test_ofx.BUILD.source_hash())
    binary = out / test_ofx.BUILD.BUNDLE / "Contents" / test_ofx.BUILD.ARCH.get(sys.platform, "Linux-x86-64") \
        / test_ofx.BUILD.BINARY
    if not binary.is_file():
        test_ofx.BUILD.build(out, out / "obj")
    return test_ofx.Core(binary)


def ofx_hashes(core) -> dict:
    from pelicula import testimage
    img = testimage.make(W, H)
    out = {}
    for name, v in looks().items():
        vals = dict(v, scan_on=False)
        for f in (0, 7):
            out[f"{name}/{f}"] = _sha(core.render(vals, img, f))
        out[f"{name}/cor"] = _sha(core.color(vals, img.astype(np.float32) / 255.0))
    return out


def compiler() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_ofx
    c = test_ofx.BUILD.find_compiler()
    return f"{sys.platform}:{str(c).split(' (')[0]}" if c else ""


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import moderngl

    from pelicula.engine import Engine
    eng = Engine(moderngl.create_standalone_context(require=330))
    ref = {"renderer": eng.renderer, "planos": plans(), "pelicula": film_hashes(eng), "edicao": edit_hashes(eng),
           "luts": lut_hashes(eng), "plugin": plugin_hashes(eng)}
    core = ofx_core()
    if core is not None:
        ref["ofx_compilador"] = compiler()
        ref["ofx"] = ofx_hashes(core)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    print(f"gravado {DATA} ({eng.renderer}; OpenFX: {ref.get('ofx_compilador') or 'sem compilador'})")
    eng.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
