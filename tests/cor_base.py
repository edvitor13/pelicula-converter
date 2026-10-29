"""Referência da cor da 1.5 gravada pela BASE da 1.6 (575c6f5), antes das ferramentas de cor novas.

A frente de cor da 1.6 (máscaras, "Cor por planos", cor simples na Edição, zebra, falsa cor e referência) não
pode mudar um bit do que já existia com os padrões. Este módulo calcula, numa imagem e numa montagem
determinísticas:

- os quadros do look de todos os presets embutidos (8 e 16 bits, faixa legal e cheia) e os uniforms dos planos;
- o LUT exportado (`Engine.bake_lut`) de todos os presets;
- os quadros compostos do modo Edição com os ajustes de cor dos clipes (8 e 16 bits, com e sem a cor) e os
  uniforms de cada camada;
- o texto dos kernels do plugin do DaVinci (DCTL, GLSL e C++ do OpenFX) com os ajustes padrão;

e compara com `tests/data/cor_base.json`, gravado pela BASE:

    python tests/cor_base.py        # regrava a referência (só faz sentido no código da BASE)

Para regravar depois: uma cópia de `pelicula/` da BASE (575c6f5) com este arquivo em `tests/` ao lado.
O texto do plugin (`plugin_sources`) é a exceção: as frentes de grão e de entrada mudam o plugin de propósito,
então ele foi regravado na integração com o código já juntado.

Os uniforms e os textos valem em qualquer computador; os hashes dos quadros e dos LUTs dependem da placa e do
driver, então `tests/test_cor_base.py` só os confere quando o `GL_RENDERER` é o mesmo da gravação.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data" / "cor_base.json"
W, H = 320, 180
FPS = 24.0
INDEX = 7
LUT_SIZE = 9
EDIT_FRAMES = [0, 6, 20, 30, 41, 52, 60, 70]


# ------------------------------------------------------------------ imagens
def image(depth: int) -> np.ndarray:
    """A imagem de teste do app (céu, pele, sombras, rampas) com uma rampa fina por cima (16 bits usa os bits
    de baixo)."""
    from pelicula import testimage
    rgb = testimage.make(W, H).astype(np.float64) / 255.0
    y, x = np.mgrid[0:H, 0:W]
    rgb = np.clip(rgb + ((x * 7 + y * 3) % 64)[..., None] / 64.0 / 255.0, 0.0, 1.0)
    mx = 255 if depth == 8 else 65535
    return np.rint(rgb * mx).astype(np.uint8 if depth == 8 else np.uint16)


def look_cases() -> list[tuple[str, dict]]:
    """Os ajustes padrão e todos os presets embutidos. O texto da borda do scan sai (ele é desenhado pelo Qt com
    a fonte do sistema e só existe com uma QGuiApplication: mudaria o hash conforme a ordem dos testes)."""
    from pelicula import params, presets
    out = [("padrao", params.defaults())]
    out += [(p["id"], presets.builtin_values(p["id"])) for p in presets.BUILTIN]
    return [(name, {**values, "scan_texto": "nenhum"}) for name, values in out]


def _num(v):
    if isinstance(v, dict):
        return {str(k): _num(x) for k, x in sorted(v.items())}
    if isinstance(v, np.ndarray):
        return _num(v.tolist())
    if isinstance(v, (tuple, list)):
        return [_num(x) for x in v]
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (np.floating, float)):
        v = float(v)
        return v if math.isfinite(v) else str(v)
    if isinstance(v, np.integer):
        return int(v)
    return v


def plan_uniforms() -> dict:
    """O plano de cada preset (uniforms, cadeias de desfoque, grão; sem GPU)."""
    import dataclasses

    from pelicula import look
    out = {}
    for name, values in look_cases():
        for legal in (True, False):
            plan = dataclasses.asdict(look.build_plan(values, W, H, INDEX, FPS, legal=legal))
            out[f"{name}/{int(legal)}"] = _num(plan)
    return out


def look_hashes(engine) -> dict:
    from pelicula import frame
    out = {}
    for depth in (8, 16):
        img = image(depth)
        for legal in (True, False):
            for name, values in look_cases():
                r = frame.Recipe.for_source(values, FPS, depth, legal=legal)
                out[f"{name}/{depth}/{int(legal)}"] = hashlib.sha256(r.render(engine, img, INDEX).tobytes()).hexdigest()
    return out


def lut_hashes(engine) -> dict:
    out = {}
    for name, values in look_cases():
        for legal in (False, True):
            lut = engine.bake_lut(values, LUT_SIZE, legal)
            out[f"{name}/{int(legal)}"] = hashlib.sha256(np.ascontiguousarray(lut, dtype=np.float32).tobytes()).hexdigest()
    return out


# ------------------------------------------------------------------ modo Edição
def _src(path: str, frames: int = 96, w: int = W, h: int = H):
    from pelicula import timeline as tl
    return tl.Source(path, w, h, 24.0, "24/1", frames, frames / 24.0, has_audio=False)


def scenario():
    """Montagem 320 × 180 com os ajustes de cor dos clipes da 1.5 (todas as seções de cor)."""
    from pelicula import timeline as tl
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")

    def put(path, at, end, vtrack=0, **values):
        c, = seq.insert_media(_src(path), at=at, vtrack=vtrack)
        seq.trim_end(c.id, end)
        if values:
            seq.set_values(c.id, {**c.values, **values})
        return c

    from pelicula import editparams
    put("a.mp4", 0, 12)
    put("b.mp4", 12, 24, exposicao=0.4, contraste=0.2, realces=-0.3, sombras=0.25, brancos=0.1, pretos=-0.1,
        brilho=0.15)
    put("c.mp4", 24, 36, temperatura=25.0, tonalidade=-12.0, vibracao=0.3, saturacao=-0.2, matiz=8.0)
    put("d.mp4", 36, 48, roda_sombras=(0.2, -0.3), roda_sombras_luz=0.1, roda_meios=(-0.1, 0.2),
        roda_luzes=(0.3, 0.1), roda_luzes_luz=-0.1, curva_realces=-0.2, curva_claros=0.1, curva_escuros=0.15,
        curva_sombras=-0.1)
    put("e.mp4", 48, 56, hsl_laranja_matiz=0.3, hsl_laranja_sat=-0.2, hsl_azul_luz=-0.3, hsl_verde_sat=0.4,
        hsl_vermelho_matiz=-0.2)
    put("f.mp4", 56, 64, nitidez=0.5, clareza=0.3, vinheta=0.4, desbotar=0.3)
    g = put("g.mp4", 64, 72)
    seq.set_values(g.id, editparams.apply_quick_look(g.values, "antigo"))
    put("h.mp4", 4, 40, vtrack=1, escala=0.5, pos_x=0.2, opacidade=0.8, exposicao=-0.3, temperatura=-20.0)
    return seq


def frame_layers(seq, t: int, depth: int):
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
        out.append(sequence.LayerImage(layer, np.rint(rgb * mx).astype(np.uint8 if depth == 8 else np.uint16)))
    return sequence.FrameLayers(t, out)


def clip_uniforms(seq) -> dict:
    from pelicula import compositor, sequence
    out = {}
    for t in EDIT_FRAMES:
        rows = []
        for layer in seq.layers_at(t):
            dw, dh = sequence.decode_size(seq, layer.clip, W, H)
            for neutral in (False, True):
                u, mip = compositor.clip_uniforms(seq, layer, dw, dh, W, H, neutral=neutral)
                rows.append({"mip": int(mip), "u": {k: _num(v) for k, v in sorted(u.items())}})
        out[str(t)] = rows
    return out


def edit_hashes(engine, seq) -> dict:
    out = {}
    for depth in (8, 16):
        for neutral in (False, True):
            key = f"{depth}{'n' if neutral else ''}"
            out[key] = {str(t): hashlib.sha256(engine.compose(frame_layers(seq, t, depth), seq, W, H, depth,
                                                              neutral=neutral).tobytes()).hexdigest()
                        for t in EDIT_FRAMES}
    return out


# ------------------------------------------------------------------ plugin do DaVinci
def plugin_sources() -> dict:
    from pelicula import resolve
    out = {}
    for kind in resolve.KINDS:
        for dialect in (resolve.DCTL, resolve.GLSL, resolve.CPP):
            try:
                text = resolve.source(kind, dialect)
            except Exception as exc:  # noqa: BLE001  (um nó que não existe num dialeto)
                text = f"erro: {type(exc).__name__}"
            out[f"{kind}/{dialect}"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return out


def cpu_reference() -> dict:
    return {"planos": plan_uniforms(), "clipes": clip_uniforms(scenario()), "plugin": plugin_sources()}


def gpu_reference(engine) -> dict:
    return {"renderer": engine.renderer, "look": look_hashes(engine), "lut": lut_hashes(engine),
            "edicao": edit_hashes(engine, scenario())}


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import moderngl

    from pelicula.engine import Engine
    eng = Engine(moderngl.create_standalone_context(require=330))
    ref = {**cpu_reference(), **gpu_reference(eng)}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    print(f"gravado {DATA} ({eng.renderer})")
    eng.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
