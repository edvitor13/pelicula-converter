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

from . import alphashaders, editshaders, look, luts, shaders

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
                          ("noise", shaders.NOISE), ("final", shaders.FINAL), ("bake", shaders.BAKE),
                          ("clip", editshaders.CLIP), ("canvas_out", editshaders.OUT),
                          ("copy", shaders.COPY), ("fit", shaders.FIT),
                          ("alpha", alphashaders.ALPHA), ("canvas_alpha", alphashaders.CANVAS_OUT),
                          ("premul", alphashaders.PREMUL)):
            prog = self.ctx.program(vertex_shader=shaders.VERT, fragment_shader=src)
            self.progs[name] = prog
            self.vaos[name] = self.ctx.vertex_array(prog, [(self.vbo, "2f", "in_pos")])
        self._targets: dict[str, tuple[moderngl.Texture, moderngl.Framebuffer]] = {}
        self.input_tex: moderngl.Texture | None = None
        # Transparência (1 − alfa) da entrada RGBA (`set_input` com 4 canais); None = entrada opaca.
        self.input_alpha: moderngl.Texture | None = None
        self._lut_tex: moderngl.Texture3D | None = None
        self._lut_key = None
        self._dummy3d = self.ctx.texture3d((2, 2, 2), 3, data=np.zeros(24, "f4").tobytes(), dtype="f4")
        self._text_tex = self.ctx.texture((1, 1), 1, data=b"\x00", dtype="f1")
        self._text_key = None
        self._text_aspect = 0.0
        self._clip_tex: dict[int, moderngl.Texture] = {}

    # ------------------------------------------------------------ recursos
    # Uniforms do FINAL que o plano só grava com o efeito ligado (os planos de sempre não mudam): o valor neutro
    # entra antes do plano, para que um quadro anterior com o efeito não deixe o valor no programa.
    FINAL_NEUTRAL = {"u_breath": (1.0, 1.0, 1.0)}  # 1.6: respiração por camada (grao.breathing)

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
        """Envia a imagem do look (h × w × 3; ou × 4, RGBA de cor direta: o alfa vai à parte, veja `render`)."""
        h, w = frame.shape[:2]
        dtype = "f1" if frame.dtype == np.uint8 else "nu2"
        if frame.ndim == 3 and frame.shape[2] == 4:
            self._set_alpha(frame[..., 3], dtype)
            frame = frame[..., :3]
        elif self.input_alpha is not None:
            self.input_alpha.release()
            self.input_alpha = None
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

    def _set_alpha(self, alpha: np.ndarray, dtype: str) -> None:
        h, w = alpha.shape[:2]
        t = self.input_alpha
        if t is None or t.size != (w, h) or t.dtype != dtype:
            if t is not None:
                t.release()
            t = self.ctx.texture((w, h), 1, dtype=dtype, alignment=1)
            t.repeat_x = False
            t.repeat_y = False
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.input_alpha = t
        mx = np.iinfo(alpha.dtype).max
        t.write(np.ascontiguousarray(mx - alpha))  # transparência: o que o BASE desenha fora da imagem é opaco

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

    def _blur3(self, src, dst, direction, sigma3) -> None:
        """BLUR com um sigma por canal (`shaders.BLUR3`, compilado no primeiro uso)."""
        self._lazy_program("blur3", shaders.BLUR3)
        self._run("blur3", dst, {"t_src": src}, {"u_dir": direction, "u_sigma3": tuple(float(x) for x in sigma3)})

    def render(self, plan: look.Plan, depth: int = 8, alpha: bool = False) -> np.ndarray:
        """Renderiza a imagem de entrada atual e devolve (h, w, 3) uint8 ou uint16. `alpha` com uma entrada RGBA:
        (h, w, 4) de cor direta, a mesma cor de sempre e o alfa com a geometria do look (`_alpha_out`)."""
        out = self._render_look(plan, depth)
        if alpha and self.input_alpha is not None:
            return self._alpha_out(plan, depth, out)
        w, h = out[0].size
        out_dtype = "f1" if depth == 8 else "nu2"
        data = out[1].read(components=3, alignment=1, dtype=out_dtype)
        arr = np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16)
        return arr.reshape(h, w, 3)

    def _render_look(self, plan: look.Plan, depth: int):
        """Todos os passos do look; devolve o alvo `out8`/`out16` (textura, framebuffer) já desenhado."""
        if self.input_tex is None:
            raise RuntimeError("Nenhuma imagem carregada no motor.")
        w, h = self.input_tex.size
        U = plan.uniforms
        lin = self._target("lin", (w, h))
        if U.get("u_scan_on"):
            U["u_text_aspect"] = self._edge_text(plan.edge_text)
        self._run(self._base_program(U), lin, {"t_in": self.input_tex, "t_text": self._text_tex}, U)

        soft = lin
        if plan.soft_sigma > 0:
            tmp = self._target("tmp", (w, h))
            soft = self._target("soft", (w, h))
            if plan.soft_sigma3 is not None:  # 1.6: nitidez por camada (um sigma por canal)
                self._blur3(lin[0], tmp, (1.0 / w, 0.0), plan.soft_sigma3)
                self._blur3(tmp[0], soft, (0.0, 1.0 / h), plan.soft_sigma3)
            else:
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
        self._run("final", out, textures, {**self.FINAL_NEUTRAL, **U})
        return out

    def _base_program(self, U: dict) -> str:
        """O BASE de sempre, ou (1.6) o BASE com a Cor por planos quando o plano traz os uniforms dela."""
        if "u_cp_on" not in U:
            return "base"
        from . import planes
        self._lazy_program("base_cp", planes.BASE_CP)
        return "base_cp"

    def plane_view(self, plan: look.Plan, values: dict) -> np.ndarray:
        """"Ver planos" (1.6): (h, w, 4) float32 com frente, fundo e pele da imagem de entrada atual, no mesmo
        enquadramento da prévia (a quarta coluna é quanto do pixel é imagem: o scan da película tem bordas). As
        máscaras aparecem mesmo com os ajustes da seção em zero. Só para a tela: a exportação nunca chama isto."""
        if self.input_tex is None:
            raise RuntimeError("Nenhuma imagem carregada no motor.")
        from . import planes
        w, h = self.input_tex.size
        U = {**plan.uniforms, **planes.uniforms(values, view=True)}
        return self._plane_view(U, w, h)

    def scene_light(self, plan: look.Plan) -> np.ndarray:
        """(1.6) A luz da cena do passo BASE para a imagem de entrada atual: (h, w, 4) float32 com a entrada
        decodificada pelo perfil do look (`toLinear`), o gamut, a exposição, o balanço, a Cor por planos e a vinheta,
        no enquadramento da prévia (a quarta coluna é quanto do pixel é imagem). Zebra e falsa cor medem aqui
        (`meter.py`); só para a tela, a exportação nunca chama isto."""
        if self.input_tex is None:
            raise RuntimeError("Nenhuma imagem carregada no motor.")
        w, h = self.input_tex.size
        U = dict(plan.uniforms)
        if U.get("u_scan_on"):
            U["u_text_aspect"] = self._edge_text(plan.edge_text)
        light = self._target("scene_light", (w, h), dtype="f4")
        self._run(self._base_program(U), light, {"t_in": self.input_tex, "t_text": self._text_tex}, U)
        data = light[1].read(components=4, alignment=1, dtype="f4")
        return np.frombuffer(data, dtype=np.float32).reshape(h, w, 4).copy()

    def _plane_view(self, U: dict, w: int, h: int) -> np.ndarray:
        vig = U.get("u_vig", (0.0, 0.5, 0.5, 0.0))
        U["u_vig"] = (0.0,) + tuple(vig[1:])
        if U.get("u_scan_on"):
            U["u_text_aspect"] = 0.0
        view = self._target("cp_view", (w, h), dtype="f4")
        self._run(self._base_program(U), view, {"t_in": self.input_tex, "t_text": self._text_tex}, U)
        data = view[1].read(components=4, alignment=1, dtype="f4")
        return np.frombuffer(data, dtype=np.float32).reshape(h, w, 4).copy()

    def _alpha_out(self, plan: look.Plan, depth: int, out) -> np.ndarray:
        """O quadro do look (`out`, já desenhado) com o alfa: o BASE desenha a transparência da entrada com a
        geometria do look (`alphashaders.ALPHA_GEOMETRY`) e o `ALPHA` junta cor e alfa. (h, w, 4) cor direta."""
        from . import alphashaders
        w, h = self.input_tex.size
        geo = self._target("alpha_geo", (w, h), dtype="f4")
        self._run("base", geo, {"t_in": self.input_alpha, "t_text": self._text_tex},
                  {**plan.uniforms, **alphashaders.ALPHA_GEOMETRY})
        out_dtype = "f1" if depth == 8 else "nu2"
        res = self._target("alpha_out8" if depth == 8 else "alpha_out16", (w, h), dtype=out_dtype)
        self._run("alpha", res, {"t_rgb": out[0], "t_geo": geo[0], "t_ain": self.input_alpha}, plan.uniforms)
        data = res[1].read(components=4, alignment=1, dtype=out_dtype)
        return np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16).reshape(h, w, 4)

    def render_fit(self, plan: look.Plan, depth: int, fit, alpha: bool = False) -> np.ndarray:
        """Look na imagem de entrada (o tamanho de `fit.box`) e encaixe num quadro `fit.out_w` × `fit.out_h`.

        `fit` é um `fit.Fit` com modo `bordas` (fundo preto) ou `desfocado` (a própria imagem com o look,
        ampliada para cobrir o quadro, desfocada — `fit.BLUR_PX` em px@1080 — e escurecida por `fit.DIM`).
        Dentro da caixa o quadro é exatamente o que `render()` devolveria. Devolve (h, w, 3) uint8 ou uint16.
        `alpha` com uma entrada RGBA: (h, w, 4); fora da caixa, transparente nas bordas e opaco no desfocado.
        """
        from . import fit as fitmod
        look_out = self._render_look(plan, depth)
        img = look_out[0]
        inner = self._alpha_out(plan, depth, look_out)[..., 3] if alpha and self.input_alpha is not None else None
        cw, ch = img.size
        ow, oh = int(fit.out_w), int(fit.out_h)
        x, y = int(fit.box[0]), int(fit.box[1])
        U = {"u_box": (x, y, cw, ch), "u_bg_mode": 0, "u_cover": (0.0, 0.0, 1.0, 1.0), "u_dim": fitmod.DIM,
             "u_max": 255.0 if depth == 8 else 65535.0, "u_dither": int(plan.uniforms.get("u_dither", 0)),
             "u_frame": int(plan.uniforms.get("u_frame", 0))}
        bg = img
        if fit.mode == fitmod.DESFOCADO:
            src = self._target("fit_src", (cw, ch), mip=True)
            self._run("copy", src, {"t_src": img}, {})
            src[0].build_mipmaps()
            cover = max(ow / cw, oh / ch)
            sigma = fit.blur_sigma() / cover  # em px da imagem (o fundo é ela ampliada `cover` vezes)
            lvl = 0
            while sigma / (2 ** lvl) > 6.0 and lvl < 8 and (cw >> (lvl + 1)) >= 4 and (ch >> (lvl + 1)) >= 4:
                lvl += 1
            sw, sh = max(1, cw >> lvl), max(1, ch >> lvl)
            sig = max(sigma / (2 ** lvl), 0.5)
            a = self._target("fit_a", (sw, sh))
            b = self._target("fit_b", (sw, sh))
            self._blur(src[0], a, (1.0 / sw, 0.0), sig, lvl)
            self._blur(a[0], b, (0.0, 1.0 / sh), sig, 0)
            bg = b[0]
            U["u_bg_mode"] = 1
            U["u_cover"] = ((ow - cw * cover) / 2.0, (oh - ch * cover) / 2.0, 1.0 / (cw * cover), 1.0 / (ch * cover))
        out_dtype = "u1" if depth == 8 else "u2"
        out = self._target("fit_out8" if depth == 8 else "fit_out16", (ow, oh), dtype=out_dtype)
        self._run("fit", out, {"t_img": img, "t_bg": bg}, U)
        data = out[1].read(components=3, alignment=1, dtype=out_dtype)
        arr = np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16)
        arr = arr.reshape(oh, ow, 3)
        if inner is None:
            return arr
        mx = 255 if depth == 8 else 65535
        a = np.full((oh, ow), mx if fit.mode == fitmod.DESFOCADO else 0, dtype=arr.dtype)
        a[y:y + ch, x:x + cw] = inner
        return np.dstack([arr, a])

    def bake_lut(self, values: dict, size: int = 33, legal: bool = False) -> np.ndarray:
        """Grava só a parte de cor do look num LUT 3D (ordem .cube).

        A entrada do LUT é o valor no perfil escolhido. Padrão (`legal=False`): o domínio da própria curva,
        a convenção dos LUTs .cube (no S-Log3, V-Log e N-Log, o código de 10 bits, como os LUTs "Full" dos
        fabricantes). `legal=True` trata a entrada como vídeo de faixa legal já expandido (um clipe em
        "Video levels" no Resolve: é o padrão do plugin; também a curva do gráfico para um arquivo comum).
        """
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
        plan = look.build_plan(vals, n * n, n, 0, 24.0, info, dither=False, legal=legal)
        out = self._target("bake", (n * n, n), dtype="f4")
        self._run("bake", out, {"t_grid": grid, "t_lut": self._lut_texture(plan.lut_path)}, plan.uniforms)
        data = out[1].read(components=3, alignment=1, dtype="f4")
        grid.release()
        return np.frombuffer(data, dtype=np.float32).reshape(-1, 3).copy()

    # ------------------------------------------------------------ modo Edição
    def _clip_texture(self, slot: int, img: np.ndarray) -> moderngl.Texture:
        h, w = img.shape[:2]
        comps = 4 if img.ndim == 3 and img.shape[2] == 4 else 3  # 4 = RGBA pré-multiplicado (transparência)
        dtype = "f1" if img.dtype == np.uint8 else "nu2"
        t = self._clip_tex.get(slot)
        if t is None or t.size != (w, h) or t.dtype != dtype or t.components != comps:
            if t is not None:
                t.release()
            t = self.ctx.texture((w, h), comps, dtype=dtype, alignment=1)
            t.repeat_x = False
            t.repeat_y = False
            self._clip_tex[slot] = t
        t.write(np.ascontiguousarray(img))
        return t

    def _lazy_program(self, name: str, src: str) -> None:
        """Compila um programa só na primeira vez que ele é usado (os das transições da 1.5)."""
        if name not in self.progs:
            prog = self.ctx.program(vertex_shader=shaders.VERT, fragment_shader=src)
            self.progs[name] = prog
            self.vaos[name] = self.ctx.vertex_array(prog, [(self.vbo, "2f", "in_pos")])

    def compose(self, frame_layers, seq, canvas_w: int, canvas_h: int, depth: int = 8,
                neutral: bool = False, crop: tuple[int, int, int, int] | None = None,
                light: tuple[int, bool] | None = None, alpha: bool = False) -> np.ndarray:
        """Monta um quadro da sequência (modo Edição) e devolve (h, w, 3) uint8 ou uint16.

        `frame_layers` é um `sequence.FrameLayers` (imagens já decodificadas, de baixo para cima).
        Cada camada é desenhada por `editshaders.CLIP` com os valores de `compositor.clip_uniforms`
        sobre uma tela RGBA de 32 bits (alterna entre dois alvos). Só na thread dona do contexto.
        `crop` (x, y, largura, altura) devolve só esse recorte da tela (exportação com "cortar", `fit.py`).
        `light`: em que luz as transições da 1.5 misturam (`transitions.light_of`; None = rec709); as camadas
        com uma delas são desenhadas por `editshaders.CLIP_TR`.
        `alpha`: (h, w, 4) RGBA de cor direta; com o "Fundo transparente" da sequência a tela começa transparente
        (`_canvas_alpha`). Sem `alpha`, a tela é sempre opaca, exatamente como antes.
        """
        from . import compositor
        size = (int(canvas_w), int(canvas_h))
        a = self._target("canvas_a", size, dtype="f4")
        b = self._target("canvas_b", size, dtype="f4")
        bg = tuple(float(c) for c in seq.background)
        a[1].use()
        a[1].clear(bg[0], bg[1], bg[2], 0.0 if alpha and getattr(seq, "transparent", False) else 1.0)
        src, dst = a, b
        for slot, li in enumerate(frame_layers.layers):
            img = li.image
            tex = self._clip_texture(slot, img)
            U, mip = compositor.clip_uniforms(seq, li.layer, img.shape[1], img.shape[0], size[0], size[1], neutral,
                                              tex_alpha=tex.components == 4, light=light)
            if mip:
                tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                tex.build_mipmaps()
            else:
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            program = "clip"
            if "u_tr_kind" in U:  # 1.5: transição de película nesta camada
                program = "clip_tr"
                self._lazy_program(program, editshaders.CLIP_TR)
            if "u_cs_on" in U:  # 1.6: cor simples do clipe (`colorsimple.py`)
                program += "_cs"
                self._lazy_program(program, editshaders.CLIP_TR_CS if "u_tr_kind" in U else editshaders.CLIP_CS)
            self._run(program, dst, {"t_clip": tex, "t_dst": src[0]}, U)
            src, dst = dst, src
        out_dtype = "u1" if depth == 8 else "u2"
        osize, offset = size, (0, 0)
        if crop is not None:
            osize, offset = (int(crop[2]), int(crop[3])), (int(crop[0]), int(crop[1]))
        if alpha:
            return self._canvas_alpha(src, size, osize, offset, depth)
        out = self._target("canvas_out8" if depth == 8 else "canvas_out16", osize, dtype=out_dtype)
        self._run("canvas_out", out, {"t_canvas": src[0]},
                  {"u_max": 255.0 if depth == 8 else 65535.0, "u_offset": offset})
        data = out[1].read(components=3, alignment=1, dtype=out_dtype)
        arr = np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16)
        return arr.reshape(osize[1], osize[0], 3)

    def _canvas_alpha(self, canvas, size, osize, offset, depth: int) -> np.ndarray:
        """A tela da montagem em RGBA de cor direta; pixels transparentes com a cor dos vizinhos (mipmap)."""
        pm = self._target("canvas_pm", size, dtype="f4", mip=True)
        self._run("premul", pm, {"t_canvas": canvas[0]}, {})
        pm[0].build_mipmaps()
        levels = float(max(1, int(math.floor(math.log2(max(size))))))
        out_dtype = "u1" if depth == 8 else "u2"
        out = self._target("canvas_alpha8" if depth == 8 else "canvas_alpha16", osize, dtype=out_dtype)
        self._run("canvas_alpha", out, {"t_canvas": canvas[0], "t_pm": pm[0]},
                  {"u_max": 255.0 if depth == 8 else 65535.0, "u_offset": offset,
                   "u_size": (float(size[0]), float(size[1])), "u_levels": levels})
        data = out[1].read(components=4, alignment=1, dtype=out_dtype)
        arr = np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16)
        return arr.reshape(osize[1], osize[0], 4)

    def release(self) -> None:
        if self.input_alpha is not None:
            self.input_alpha.release()
            self.input_alpha = None
        for t in self._clip_tex.values():
            t.release()
        self._clip_tex.clear()
        for tex, fbo in self._targets.values():
            fbo.release()
            tex.release()
        self._targets.clear()
        try:
            self.ctx.release()
        except Exception:
            pass
