"""Referência das transições da 1.4 (corte, dissolver, preto, branco, transparente) gravada pela BASE da 1.5.

As transições novas (`pelicula/transitions.py`) não podem mudar um bit das antigas. Este módulo monta uma
montagem só com os tipos antigos (com transparência, cor, enquadramento, mesclagem e transições sobrepostas),
calcula as camadas, os uniforms de cada camada e os quadros compostos na GPU (8 e 16 bits) e compara com
`tests/data/transicoes_base.json`, gravado pela BASE (59a434d, antes das transições novas):

    python tests/transicoes_base.py        # regrava a referência (só faz sentido no código da BASE)

Os uniforms e as camadas valem em qualquer computador; os hashes dos quadros dependem da placa e do driver,
então `tests/test_transitions.py` só os confere quando o `GL_RENDERER` é o mesmo da gravação.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data" / "transicoes_base.json"
W, H = 320, 180
FRAMES = [0, 5, 10, 11, 12, 13, 15, 30, 37, 38, 39, 47, 48, 49, 50, 52, 55, 58, 59, 60, 61, 63, 70, 85, 87, 88,
          89, 95, 96, 97, 100, 105, 110, 114, 115, 120, 125]


def _src(path: str, frames: int = 96, alpha: bool = False, w: int = W, h: int = H):
    from pelicula import timeline as tl
    return tl.Source(path, w, h, 24.0, "24/1", frames, frames / 24.0, has_audio=False, has_alpha=alpha,
                     pix_fmt="yuva444p10le" if alpha else "yuv420p")


def scenario():
    """Montagem 320 × 180 a 24 quadros/s só com os tipos de transição da 1.4."""
    from pelicula import timeline as tl
    seq = tl.Sequence(width=W, height=H, fps_str="24/1")

    def put(path, at, end, vtrack=0, alpha=False, w=W, h=H, **values):
        c, = seq.insert_media(_src(path, alpha=alpha, w=w, h=h), at=at, vtrack=vtrack)
        seq.trim_end(c.id, end)
        if values:
            seq.set_values(c.id, {**c.values, **values})
        return c

    put("a.mp4", 0, 48)
    put("b.mp4", 48, 96, entrada_tipo="dissolver", entrada_dur=0.5, exposicao=0.4, saturacao=0.2,
        saida_tipo="branco", saida_dur=0.25)
    put("e.mp4", 96, 126, entrada_tipo="preto", entrada_dur=0.75, saida_tipo="preto", saida_dur=0.75,
        temperatura=20.0)
    put("c.mov", 10, 40, vtrack=1, alpha=True, entrada_tipo="branco", entrada_dur=0.25, saida_tipo="transparente",
        saida_dur=0.5, escala=0.5, pos_x=0.1)
    put("d.mp4", 60, 90, vtrack=1, w=160, h=90, entrada_tipo="preto", entrada_dur=0.25, saida_tipo="branco",
        saida_dur=0.25, opacidade=0.7, mesclagem="tela", rotacao=10.0)
    return seq


def image(path: str, f: int, w: int, h: int, depth: int, alpha: bool) -> np.ndarray:
    """Imagem determinística de um clipe (rampas diferentes por arquivo e por quadro)."""
    seed = sum(path.encode())
    y, x = np.mgrid[0:h, 0:w]
    base = x * 3 + y * 5 + f * 7 + seed * 41
    rgb = np.stack([base % 256, (base * 3 + 17) % 256, (x * 2 + y + seed * 13) % 256], axis=-1) / 255.0
    if alpha:
        a = ((x + y + f) % 64) / 63.0
        rgb = np.concatenate([rgb * a[..., None], a[..., None]], axis=-1)
    mx = 255 if depth == 8 else 65535
    return np.rint(rgb * mx).astype(np.uint8 if depth == 8 else np.uint16)


def frame_layers(seq, t: int, depth: int):
    from pelicula import sequence
    out = []
    for layer in seq.layers_at(t):
        src = seq.sources[layer.clip.src]
        dw, dh = sequence.decode_size(seq, layer.clip, W, H)
        out.append(sequence.LayerImage(layer, image(src.path, layer.src_frame, dw, dh, depth, src.has_alpha)))
    return sequence.FrameLayers(t, out)


def _num(v):
    if isinstance(v, (tuple, list)):
        return [_num(x) for x in v]
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    return v


def layers_and_uniforms(seq) -> dict:
    """Camadas e uniforms de cada quadro de `FRAMES` (sem GPU: vale em qualquer computador)."""
    from pelicula import compositor, sequence
    frames = {}
    table: list[dict] = []   # uniforms distintos (quadros parecidos repetem os mesmos)
    index: dict[str, int] = {}

    def ref_of(u: dict) -> int:
        d = {k: _num(v) for k, v in sorted(u.items())}
        key = json.dumps(d, sort_keys=True)
        if key not in index:
            index[key] = len(table)
            table.append(d)
        return index[key]

    for t in FRAMES:
        rows = []
        for layer in seq.layers_at(t):
            dw, dh = sequence.decode_size(seq, layer.clip, W, H)
            alpha = seq.sources[layer.clip.src].has_alpha
            u, mip = compositor.clip_uniforms(seq, layer, dw, dh, W, H, tex_alpha=alpha)
            un, _mip = compositor.clip_uniforms(seq, layer, dw, dh, W, H, neutral=True, tex_alpha=alpha)
            rows.append({"src": layer.clip.src, "src_frame": layer.src_frame, "alpha": layer.alpha,
                         "fade_color": list(layer.fade_color), "fade": layer.fade, "extension": layer.extension,
                         "mip": int(mip), "uniforms": ref_of(u), "neutral": ref_of(un)})
        frames[str(t)] = rows
    return {"quadros": frames, "uniforms": table}


def frame_hashes(engine, seq) -> dict:
    """sha256 de cada quadro composto (8 e 16 bits, com e sem a cor dos clipes)."""
    out = {}
    for depth in (8, 16):
        for neutral in (False, True):
            key = f"{depth}{'n' if neutral else ''}"
            out[key] = {str(t): hashlib.sha256(engine.compose(frame_layers(seq, t, depth), seq, W, H, depth,
                                                              neutral=neutral).tobytes()).hexdigest()
                        for t in FRAMES}
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import moderngl

    from pelicula.engine import Engine
    eng = Engine(moderngl.create_standalone_context(require=330))
    from pelicula import editshaders
    seq = scenario()
    ref = {"renderer": eng.renderer, "camadas": layers_and_uniforms(seq), "quadros": frame_hashes(eng, seq),
           "shader_clip": hashlib.sha256(editshaders.CLIP.encode("utf-8")).hexdigest(),
           "shader_out": hashlib.sha256(editshaders.OUT.encode("utf-8")).hexdigest()}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    print(f"gravado {DATA} ({eng.renderer})")
    eng.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
