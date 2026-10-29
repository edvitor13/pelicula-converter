"""Referência da entrada da câmera gravada pela BASE da 1.6 (575c6f5), antes da frente "entrada".

A 1.6 mexe na leitura dos arquivos (super-brancos, 16 bits exatos), acrescenta perfis de câmera, a proteção de
cores saturadas e o perfil por clipe no modo Edição. Nada disso pode mudar um bit do que já existia com os
ajustes padrão. Este módulo calcula, com o código atual:

- os uniforms do plano do look (`look.build_plan`) de cada perfil antigo, com faixa legal e cheia (sem GPU);
- os quadros do look na GPU (todos os presets no perfil padrão; cada perfil antigo em dois presets; 8 e 16 bits);
- os LUTs exportados (`Engine.bake_lut`) de cada perfil antigo;
- a montagem do modo Edição (`tests/transicoes_base.scenario`) com e sem a película por cima (8 e 16 bits);
- o nó Cor do plugin do Resolve (o kernel do DCTL em GLSL) de cada perfil antigo;
- a leitura de arquivos Rec.709 em 8 bits (`media.FrameReader`, profundidade 8) de vídeo de 8 e 10 bits.

e compara com `tests/data/entrada_base.json`, gravado pela BASE:

    python tests/entrada_base.py        # regrava a referência (só faz sentido no código da BASE)

Os uniforms valem em qualquer computador; os hashes dos quadros dependem da placa e do driver (e a leitura, da
versão do ffmpeg), então `tests/test_entrada_base.py` só os confere quando o `GL_RENDERER` (ou o ffmpeg) é o
mesmo da gravação.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "entrada_base.json"
W, H = 160, 90
OLD_INPUTS = ["rec709", "linear", "nlog", "slog3", "logc3", "vlog", "log3g10", "dwg", "cineon", "bmd_gen5",
              "logc4", "applelog", "hlg", "pq"]
PROFILE_PRESETS = ["vision3_500t", "lab_v3_250d_2383"]
MONTAGE_FRAMES = [0, 12, 30, 47, 50, 60, 70, 100, 115]


def _num(v):
    if isinstance(v, (tuple, list)):
        return [_num(x) for x in v]
    if isinstance(v, np.ndarray):
        return [_num(x) for x in v.tolist()]
    if isinstance(v, (bool, np.bool_)):
        return int(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        v = float(v)
        return v if math.isfinite(v) else str(v)
    return v


def _sha(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def image(depth: int) -> np.ndarray:
    """A cena de teste do app (8 bits) e, em 16 bits, a mesma cena com uma rampa fina por cima."""
    from pelicula import testimage
    img = testimage.make(W, H)
    if depth == 8:
        return img
    y, x = np.mgrid[0:H, 0:W]
    fine = ((x * 37 + y * 11) % 257).astype(np.uint16)[..., None]
    return img.astype(np.uint16) * np.uint16(257) - np.minimum(fine, img.astype(np.uint16) * 257)


def value_sets() -> dict[str, dict]:
    """Os ajustes de cada caso: padrão, todos os presets e cada perfil antigo em dois presets."""
    from pelicula import params, presets
    out = {"padrao": params.defaults()}
    for p in presets.BUILTIN:
        out[f"preset:{p['id']}"] = presets.builtin_values(p["id"])
    for pid in PROFILE_PRESETS:
        for ent in OLD_INPUTS:
            out[f"perfil:{pid}:{ent}"] = dict(presets.builtin_values(pid), entrada=ent)
    for ent in ("nlog", "slog3", "vlog"):
        out[f"reescalado:{ent}"] = dict(presets.builtin_values("vision3_500t"), entrada=ent, log_reescalado=True)
    return out


def plans() -> dict:
    """Uniforms do plano do look de cada caso, com a fonte em faixa legal e cheia (sem GPU)."""
    from pelicula import look
    out = {}
    for name, v in value_sets().items():
        for legal in (True, False):
            p = look.build_plan(v, W, H, 7, 24.0, None, dither=True, legal=legal)
            out[f"{name}|{int(legal)}"] = {
                "u": {k: _num(val) for k, val in sorted(p.uniforms.items())},
                "soft_sigma": _num(p.soft_sigma), "grain_size": _num(p.grain_size), "grain_seed": int(p.grain_seed),
                "chains": len(p.chains)}
    return out


def renders(engine) -> dict:
    """sha256 do quadro do look (o caminho de `frame.Recipe`) de cada caso, em 8 e 16 bits."""
    from pelicula.frame import Recipe
    out = {}
    imgs = {8: image(8), 16: image(16)}
    for name, v in value_sets().items():
        legals = (True, False) if name.startswith(("perfil:", "reescalado:")) else (True,)
        for legal in legals:
            for depth in (8, 16):
                r = Recipe.for_source(v, 24.0, depth, legal=legal, dither=depth == 8)
                out[f"{name}|{int(legal)}|{depth}"] = _sha(r.render(engine, imgs[depth], 7))
    return out


def luts(engine) -> dict:
    """sha256 do LUT exportado (17³, float32) de cada perfil antigo, com faixa legal e cheia."""
    from pelicula import presets
    out = {}
    for pid in ("original", "vision3_500t", "lab_v3_250d_2383"):
        for ent in OLD_INPUTS:
            v = dict(presets.builtin_values(pid), entrada=ent)
            for legal in (True, False):
                out[f"{pid}:{ent}|{int(legal)}"] = _sha(engine.bake_lut(v, 17, legal=legal).astype(np.float32))
    return out


def montages(engine) -> dict:
    """sha256 da montagem do modo Edição (8 e 16 bits), sem e com a película por cima."""
    sys.path.insert(0, str(HERE))
    import transicoes_base as tb

    from pelicula import presets
    from pelicula.frame import Recipe
    seq = tb.scenario()
    out = {}
    looks = {"sem": None, "rec709": presets.builtin_values("vision3_500t"),
             "slog3": dict(presets.builtin_values("vision3_500t"), entrada="slog3")}
    for depth in (8, 16):
        for name, v in looks.items():
            r = Recipe.for_source(v, 24.0, depth, legal=True, seq=seq, size=(tb.W, tb.H), dither=False)
            for t in MONTAGE_FRAMES:
                out[f"{name}|{depth}|{t}"] = _sha(r.render(engine, tb.frame_layers(seq, t, depth), t))
    return out


def plugin(engine) -> dict:
    """sha256 do nó Cor do plugin (o kernel do DCTL em GLSL) numa grade 9³, para cada perfil antigo."""
    sys.path.insert(0, str(HERE))
    import test_resolve as tr

    from pelicula import presets
    h = tr.Harness(engine)
    out = {}
    for ent in OLD_INPUTS:
        for pid in ("original", "vision3_500t"):
            v = dict(presets.builtin_values(pid), entrada=ent, proj_on=False, lut_on=False)
            out[f"{pid}:{ent}"] = _sha(h.run("cor", v, tr._grid(9)))
    return out


def _ffmpeg_version() -> str:
    from pelicula import media
    try:
        res = subprocess.run([media.ffmpeg(), "-version"], capture_output=True)
        return res.stdout.decode("utf-8", "replace").splitlines()[0]
    except (OSError, IndexError):
        return ""


def synthetic_video(path: Path, pix: str, codes: np.ndarray) -> None:
    """Vídeo FFV1 (sem perda) marcado como Rec.709 em faixa legal, com os códigos YUV dados (h × w × 3, 4:4:4
    já com o croma; em 4:2:0 o croma é a média de 2 × 2). 2 quadros iguais."""
    from pelicula import media
    h, w = codes.shape[:2]
    y, u, v = (codes[..., i] for i in range(3))
    if pix.startswith("yuv420"):
        u = u.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3)).round().astype(codes.dtype)
        v = v.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3)).round().astype(codes.dtype)
    dt = "<u2" if "10" in pix else "u1"
    raw = np.concatenate([y.ravel(), u.ravel(), v.ravel()]).astype(dt).tobytes() * 2
    # A faixa vai também na entrada: sem ela, o ffmpeg 8+ converte o rawvideo "sem faixa" para a faixa legal e
    # corta os códigos abaixo de 64 e acima de 943 (os super-brancos que os testes querem ver).
    tags = ["-color_range", "tv", "-colorspace", "bt709"]
    subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix, "-s", f"{w}x{h}",
                    "-r", "24", *tags, "-i", "pipe:0", "-c:v", "ffv1", *tags, "-color_primaries", "bt709",
                    "-color_trc", "bt709", str(path)], input=raw, check=True)


def synthetic_codes(bits: int, w: int = 64, h: int = 16) -> np.ndarray:
    """Códigos YUV determinísticos (rampa de luma de ponta a ponta e croma variado, inclusive fora da faixa)."""
    top = (1 << bits) - 1
    yy, xx = np.mgrid[0:h, 0:w]
    y = np.round(xx / (w - 1) * top).astype(np.int64)
    u = (np.round((yy * 7 + xx * 3) % (top + 1))).astype(np.int64)
    v = (np.round((yy * 13 + xx * 5 + top // 2) % (top + 1))).astype(np.int64)
    u = (u + (1 << (bits - 1))) % (top + 1)
    return np.stack([y, u, v], -1).astype(np.uint16)


def decodes(tmp: Path) -> dict:
    """sha256 da leitura (8 bits) de vídeos Rec.709 de 8 e 10 bits em faixa legal; e a de 16 bits, só para ver."""
    from pelicula import media
    out = {}
    for pix, bits in (("yuv420p", 8), ("yuv444p10le", 10), ("yuv420p10le", 10)):
        path = tmp / f"ref_{pix}.mkv"
        synthetic_video(path, pix, synthetic_codes(bits))
        info = media.probe(str(path))
        for size in ((64, 16), (32, 8), (96, 24)):
            for hq in (False, True):
                for depth in (8, 16):
                    img = media.grab_frame(info, 0, size[0], size[1], depth, hq=hq)
                    out[f"{pix}|{size[0]}x{size[1]}|{int(hq)}|{depth}"] = _sha(img)
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT))
    import tempfile

    import moderngl

    from pelicula.engine import Engine
    eng = Engine(moderngl.create_standalone_context(require=330))
    with tempfile.TemporaryDirectory() as tmp:
        ref = {"renderer": eng.renderer, "ffmpeg": _ffmpeg_version(), "planos": plans(), "quadros": renders(eng),
               "luts": luts(eng), "montagens": montages(eng), "plugin": plugin(eng), "leitura": decodes(Path(tmp))}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    print(f"gravado {DATA} ({eng.renderer}; {ref['ffmpeg']})")
    eng.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
