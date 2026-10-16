"""Motor de renderização na GPU (OpenGL 3.3 via moderngl).

Cada quadro passa por: base (geometria, perfil de entrada, exposição, vinheta) ->
desfoques (maciez, halação, bloom, névoa) -> ruído do grão -> passo final
(cor da película, cópia, LUT, grão, desgaste, moldura).
"""

from __future__ import annotations

import math
import os
import threading

import moderngl
import numpy as np

from . import look, luts, shaders

_LUT_CACHE: dict[str, tuple[float, luts.Lut3D]] = {}
_LUT_LOCK = threading.Lock()


def cached_lut(path: str) -> luts.Lut3D | None:
    """LUT lido do disco, guardado em memória enquanto o arquivo não mudar."""
    if not path or not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    with _LUT_LOCK:
        hit = _LUT_CACHE.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    lut = luts.load_cube(path)
    with _LUT_LOCK:
        _LUT_CACHE[path] = (mtime, lut)
    return lut


def lut_info(path: str):
    try:
        lut = cached_lut(path)
    except Exception:
        return None
    return (lut.size, lut.dmin, lut.dmax) if lut else None


class Engine:
    def __init__(self, ctx: moderngl.Context | None = None):
        self.ctx = ctx or moderngl.create_standalone_context(require=330)
        self.renderer = self.ctx.info.get("GL_RENDERER", "GPU")
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.vbo = self.ctx.buffer(quad.tobytes())
        self.progs: dict[str, moderngl.Program] = {}
        self.vaos: dict[str, moderngl.VertexArray] = {}
        for name, src in (("base", shaders.BASE), ("extract", shaders.EXTRACT), ("blur", shaders.BLUR),
                          ("noise", shaders.NOISE), ("final", shaders.FINAL), ("bake", shaders.BAKE)):
            prog = self.ctx.program(vertex_shader=shaders.VERT, fragment_shader=src)
            self.progs[name] = prog
            self.vaos[name] = self.ctx.vertex_array(prog, [(self.vbo, "2f", "in_pos")])
        self._targets: dict[str, tuple[moderngl.Texture, moderngl.Framebuffer]] = {}
        self.input_tex: moderngl.Texture | None = None
        self._lut_tex: moderngl.Texture3D | None = None
        self._lut_key = None
        self._dummy3d = self.ctx.texture3d((2, 2, 2), 3, data=np.zeros(24, "f4").tobytes(), dtype="f4")
        self._text_tex = self.ctx.texture((1, 1), 1, data=b"\x00", dtype="f1")
        self._text_key = None
        self._text_aspect = 0.0

    # ------------------------------------------------------------ recursos
    def _target(self, name: str, size: tuple[int, int], dtype: str = "f2", mip: bool = False):
        cur = self._targets.get(name)
        if cur and cur[0].size == size and cur[0].dtype == dtype:
            return cur
        if cur:
            cur[1].release()
            cur[0].release()
        tex = self.ctx.texture(size, 4, dtype=dtype)
        tex.repeat_x = False
        tex.repeat_y = False
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR) if mip else (moderngl.LINEAR, moderngl.LINEAR)
        fbo = self.ctx.framebuffer(color_attachments=[tex])
        self._targets[name] = (tex, fbo)
        return tex, fbo

    def set_input(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        dtype = "f1" if frame.dtype == np.uint8 else "nu2"
        t = self.input_tex
        if t is None or t.size != (w, h) or t.dtype != dtype:
            if t is not None:
                t.release()
            t = self.ctx.texture((w, h), 3, dtype=dtype, alignment=1)
            t.repeat_x = False
            t.repeat_y = False
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.input_tex = t
        t.write(np.ascontiguousarray(frame))

    def _lut_texture(self, path: str):
        if not path:
            return self._dummy3d
        lut = cached_lut(path)
        if lut is None:
            return self._dummy3d
        key = (path, id(lut))
        if self._lut_key != key:
            if self._lut_tex is not None:
                self._lut_tex.release()
            n = lut.size
            tex = self.ctx.texture3d((n, n, n), 3, data=lut.data.astype("f4").tobytes(), dtype="f4")
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = tex.repeat_z = False
            self._lut_tex = tex
            self._lut_key = key
        return self._lut_tex

    def _edge_text(self, text: str) -> float:
        """Prepara a textura do texto da borda; devolve a proporção (0 = sem texto)."""
        if text == self._text_key:
            return self._text_aspect
        from . import edgetext
        arr = edgetext.render(text) if text else None
        self._text_tex.release()
        if arr is None:
            self._text_tex = self.ctx.texture((1, 1), 1, data=b"\x00", dtype="f1")
            self._text_aspect = 0.0
        else:
            h, w = arr.shape
            self._text_tex = self.ctx.texture((w, h), 1, data=arr.tobytes(), dtype="f1", alignment=1)
            self._text_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._text_tex.repeat_x = self._text_tex.repeat_y = False
            self._text_aspect = w / h
        self._text_key = text
        return self._text_aspect

    # ------------------------------------------------------------ passos
    def _run(self, name: str, target, textures: dict, uniforms: dict) -> None:
        prog = self.progs[name]
        target[1].use()
        unit = 0
        for uname, tex in textures.items():
            member = prog.get(uname, None)
            if member is None:
                continue
            tex.use(location=unit)
            member.value = unit
            unit += 1
        for key, val in uniforms.items():
            member = prog.get(key, None)
            if member is not None:
                member.value = val
        self.vaos[name].render(moderngl.TRIANGLE_STRIP)

    def _blur(self, src, dst, direction, sigma, lod) -> None:
        self._run("blur", dst, {"t_src": src}, {"u_dir": direction, "u_sigma": float(sigma), "u_lod": float(lod)})

    def render(self, plan: look.Plan, depth: int = 8) -> np.ndarray:
        """Renderiza a imagem de entrada atual e devolve (h, w, 3) uint8 ou uint16."""
        if self.input_tex is None:
            raise RuntimeError("Nenhuma imagem carregada no motor.")
        w, h = self.input_tex.size
        U = plan.uniforms
        lin = self._target("lin", (w, h))
        if U.get("u_scan_on"):
            U["u_text_aspect"] = self._edge_text(plan.edge_text)
        self._run("base", lin, {"t_in": self.input_tex, "t_text": self._text_tex}, U)

        soft = lin
        if plan.soft_sigma > 0:
            tmp = self._target("tmp", (w, h))
            soft = self._target("soft", (w, h))
            self._blur(lin[0], tmp, (1.0 / w, 0.0), plan.soft_sigma, 0)
            self._blur(tmp[0], soft, (0.0, 1.0 / h), plan.soft_sigma, 0)

        glow = {}
        for ch in plan.chains:
            hi = self._target("hi", (w, h), mip=True)
            self._run("extract", hi, {"t_src": lin[0]},
                      {"u_thr": float(ch.threshold), "u_limit": float(ch.limit), "u_lum_only": int(ch.lum_only),
                       "u_use_alpha": int(ch.alpha_mask)})
            hi[0].build_mipmaps()
            lvl = 0
            while ch.sigma / (2 ** lvl) > 6.0 and lvl < 8 and (w >> (lvl + 1)) >= 4 and (h >> (lvl + 1)) >= 4:
                lvl += 1
            sw, sh = max(1, w >> lvl), max(1, h >> lvl)
            sig = max(ch.sigma / (2 ** lvl), 0.5)
            a = self._target(ch.name + "_a", (sw, sh))
            b = self._target(ch.name + "_b", (sw, sh))
            self._blur(hi[0], a, (1.0 / sw, 0.0), sig, lvl)
            self._blur(a[0], b, (0.0, 1.0 / sh), sig, 0)
            glow[ch.name] = b[0]

        noise = None
        if plan.grain_size > 0:
            gw = max(2, int(math.ceil(w / plan.grain_size)))
            gh = max(2, int(math.ceil(h / plan.grain_size)))
            noise = self._target("noise", (gw, gh))
            self._run("noise", noise, {}, {"u_seed": int(plan.grain_seed % 2147483647)})

        out_dtype = "f1" if depth == 8 else "nu2"
        out = self._target("out8" if depth == 8 else "out16", (w, h), dtype=out_dtype)
        textures = {
            "t_in": self.input_tex,
            "t_lin": lin[0],
            "t_soft": soft[0],
            "t_hal": glow.get("hal", lin[0]),
            "t_bloom": glow.get("bloom", lin[0]),
            "t_mist": glow.get("mist", lin[0]),
            "t_noise": noise[0] if noise else lin[0],
            "t_lut": self._lut_texture(plan.lut_path),
        }
        self._run("final", out, textures, U)
        data = out[1].read(components=3, alignment=1, dtype=out_dtype)
        arr = np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16)
        return arr.reshape(h, w, 3)

    def bake_lut(self, values: dict, size: int = 33) -> np.ndarray:
        """Grava só a parte de cor do look num LUT 3D (ordem .cube)."""
        n = size
        axis = np.linspace(0.0, 1.0, n, dtype=np.float32)
        img = np.zeros((n, n * n, 3), dtype=np.float32)
        for g in range(n):
            img[:, g * n:(g + 1) * n, 0] = axis[None, :]
            img[:, g * n:(g + 1) * n, 1] = axis[g]
        img[:, :, 2] = axis[:, None]
        grid = self.ctx.texture((n * n, n), 3, data=img.tobytes(), dtype="f4", alignment=1)
        grid.filter = (moderngl.NEAREST, moderngl.NEAREST)
        vals = dict(values)
        vals["proj_on"] = False
        info = lut_info(vals.get("lut_arquivo", "")) if vals.get("lut_on") else None
        plan = look.build_plan(vals, n * n, n, 0, 24.0, info, dither=False)
        out = self._target("bake", (n * n, n), dtype="f4")
        self._run("bake", out, {"t_grid": grid, "t_lut": self._lut_texture(plan.lut_path)}, plan.uniforms)
        data = out[1].read(components=3, alignment=1, dtype="f4")
        grid.release()
        return np.frombuffer(data, dtype=np.float32).reshape(-1, 3).copy()

    def release(self) -> None:
        for tex, fbo in self._targets.values():
            fbo.release()
            tex.release()
        self._targets.clear()
        try:
            self.ctx.release()
        except Exception:
            pass
