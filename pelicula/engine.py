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
        self._clip_tex: dict[int | str, moderngl.Texture] = {}
        # 1.7, tela montada de cada clipe de sequência: {caminho: (camadas, sequência, parâmetros, textura)}; veja
        # `_nested_texture`.
        self._nested_tex: dict[str, tuple] = {}

    # ------------------------------------------------------------ recursos
    # Uniforms do FINAL que o plano só grava com o efeito ligado (os planos de sempre não mudam): o valor neutro
    # entra antes do plano, para que um quadro anterior com o efeito não deixe o valor no programa.
    FINAL_NEUTRAL = {"u_breath": (1.0, 1.0, 1.0),  # 1.6: respiração por camada (grao.breathing)
                     "u_streak_on": 0}  # 1.6: risco do anamórfico (`anamorfico.streak`)

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
        """Envia a imagem do look (h × w × 3; ou × 4, RGBA de cor direta: o alfa vai à parte, veja `render`).
        float32: a leitura de log com super-brancos (`media.float_input`), valores fora de 0–1 inclusive."""
        h, w = frame.shape[:2]
        dtype = "f1" if frame.dtype == np.uint8 else "f4" if frame.dtype == np.float32 else "nu2"
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
        self._run(self._base_program(U), lin, {"t_in": self.input_tex, "t_text": self._text_tex},
                  {**look.SPARSE_UNIFORMS, **U})

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
            # 1.6: o risco do anamórfico lê o nível 0 só (alvo sem mipmaps: um alvo com mipmaps não montados
            # não é amostrável)
            hi = self._target("streak_hi", (w, h)) if ch.name == "streak" else self._target("hi", (w, h), mip=True)
            self._run("extract", hi, {"t_src": lin[0]},
                      {"u_thr": float(ch.threshold), "u_limit": float(ch.limit), "u_lum_only": int(ch.lum_only),
                       "u_use_alpha": int(ch.alpha_mask)})
            if ch.name == "streak":  # 1.6: risco horizontal do anamórfico (só na horizontal)
                glow[ch.name] = self._streak(hi[0], w, h, ch.sigma)
                continue
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
            "t_streak": glow.get("streak", lin[0]),
            "t_noise": noise[0] if noise else lin[0],
            "t_lut": self._lut_texture(plan.lut_path),
        }
        self._run(self._final_program(U), out, textures, {**self.FINAL_NEUTRAL, **U})
        return out

    def _final_program(self, U: dict) -> str:
        """O FINAL de sempre, ou (1.6) o FINAL com o grão físico no negativo (`u_grain_on = 3`, `grao_fisico`), com
        véu, pré-exposição e scanner de luz branca (`labx`) ou com os dois (a `labPathX` copia a `labPath` já com o
        grão físico)."""
        if U.get("u_grain_on") != 3:
            if "u_gs_amt" in U:  # 1.6: estrutura pela densidade (grao_estrutura.py)
                from . import grao_estrutura
                name = "final_gs_lx" if "u_lx_on" in U else "final_gs"
                self._lazy_program(name, grao_estrutura.program(name))
                return name
            return self._lab_program("final", U)
        from . import grao_fisico
        if "u_pg_var" in U:  # 1.6 (fase 3): variação do tamanho do grão físico (raios variáveis)
            name = "final_pgv_lx" if "u_lx_on" in U else "final_pgv"
            self._lazy_program(name, grao_fisico.program(name))
            return name
        if "u_lx_on" not in U:
            self._lazy_program("final_pg", grao_fisico.FINAL_PG)
            return "final_pg"
        return self._lab_program("final_pg", U)

    def _lab_program(self, name: str, U: dict) -> str:
        """O FINAL/BAKE de sempre, ou (1.6) a variante com véu, pré-exposição e scanner de luz branca (labx.py)."""
        if "u_lx_on" not in U:
            return name
        from . import labx
        self._lazy_program(name + "_lx", labx.program(name + "_lx"))
        return name + "_lx"

    def _streak(self, src, w: int, h: int, sigma: float):
        """(1.6) Desfoque só na horizontal, longo (`sigma` px): reduz a largura pela metade a cada passo (altura
        inteira, nada vaza para cima ou para baixo) e termina com uma gaussiana na largura reduzida."""
        sw, lvl = w, 0
        while sigma / (2 ** lvl) > 6.0 and lvl < 9 and (w >> (lvl + 1)) >= 4:
            lvl += 1
            nw = max(1, w >> lvl)
            dst = self._target(f"streak_d{lvl}", (nw, h))
            self._blur(src, dst, (1.0 / sw, 0.0), 1.0, 0)
            src, sw = dst[0], nw
        out = self._target("streak_b", (sw, h))
        self._blur(src, out, (1.0 / sw, 0.0), max(sigma / (2 ** lvl), 0.5), 0)
        return out[0]

    def _base_program(self, U: dict) -> str:
        """O BASE de sempre, ou (1.6) o BASE com a Cor por planos quando o plano traz os uniforms dela e/ou com a tira
        do scan deitada (`scanformatos.rotated`, o plano traz `u_scan_rot`)."""
        cp = "u_cp_on" in U
        rot = bool(U.get("u_scan_rot"))
        if not cp and not rot:
            return "base"
        from . import planes, scanformatos
        name = ("base_cp" if cp else "base") + ("_rot" if rot else "")
        if name not in self.progs:
            src = planes.BASE_CP if cp else shaders.BASE
            self._lazy_program(name, scanformatos.rotated(src) if rot else src)
        return name

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
        (`exposure.py`); só para a tela, a exportação nunca chama isto."""
        if self.input_tex is None:
            raise RuntimeError("Nenhuma imagem carregada no motor.")
        w, h = self.input_tex.size
        U = dict(plan.uniforms)
        if U.get("u_scan_on"):
            U["u_text_aspect"] = self._edge_text(plan.edge_text)
        light = self._target("scene_light", (w, h), dtype="f4")
        self._run(self._base_program(U), light, {"t_in": self.input_tex, "t_text": self._text_tex},
                  {**look.SPARSE_UNIFORMS, **U})
        data = light[1].read(components=4, alignment=1, dtype="f4")
        return np.frombuffer(data, dtype=np.float32).reshape(h, w, 4).copy()

    def _plane_view(self, U: dict, w: int, h: int) -> np.ndarray:
        vig = U.get("u_vig", (0.0, 0.5, 0.5, 0.0))
        U["u_vig"] = (0.0,) + tuple(vig[1:])
        if U.get("u_scan_on"):
            U["u_text_aspect"] = 0.0
        view = self._target("cp_view", (w, h), dtype="f4")
        self._run(self._base_program(U), view, {"t_in": self.input_tex, "t_text": self._text_tex},
                  {**look.SPARSE_UNIFORMS, **U})
        data = view[1].read(components=4, alignment=1, dtype="f4")
        return np.frombuffer(data, dtype=np.float32).reshape(h, w, 4).copy()

    def _alpha_out(self, plan: look.Plan, depth: int, out) -> np.ndarray:
        """O quadro do look (`out`, já desenhado) com o alfa: o BASE desenha a transparência da entrada com a
        geometria do look (`alphashaders.ALPHA_GEOMETRY`) e o `ALPHA` junta cor e alfa. (h, w, 4) cor direta."""
        from . import alphashaders
        w, h = self.input_tex.size
        geo = self._target("alpha_geo", (w, h), dtype="f4")
        self._run(self._base_program({"u_scan_rot": plan.uniforms.get("u_scan_rot", 0)}), geo,
                  {"t_in": self.input_alpha, "t_text": self._text_tex},
                  {**look.SPARSE_UNIFORMS, **plan.uniforms, **alphashaders.ALPHA_GEOMETRY})
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
        self._run(self._lab_program("bake", plan.uniforms), out,
                  {"t_grid": grid, "t_lut": self._lut_texture(plan.lut_path)},
                  {**look.SPARSE_UNIFORMS, **plan.uniforms})
        data = out[1].read(components=3, alignment=1, dtype="f4")
        grid.release()
        return np.frombuffer(data, dtype=np.float32).reshape(-1, 3).copy()

    # ------------------------------------------------------------ 1.6: obturador (tempo_camera)
    def temporal_blend(self, images: list[np.ndarray], weights: list[float], curve: int, cv: bool) -> np.ndarray:
        """Média ponderada de quadros do mesmo tamanho na luz linear da curva `curve` (`look.input_id`; `cv`: código
        de 10 bits numa fonte de faixa legal), devolvida no valor da mesma curva em float32 (h × w × 3; × 4 com RGBA
        pré-multiplicado, misturado pela cobertura). `tempo_camera.ACC` soma 4 quadros por passo; `ENC` volta à
        curva. O obturador do look (`frame.Recipe.montage`)."""
        from . import tempo_camera as tc
        self._lazy_program("shutter_acc", tc.ACC)
        self._lazy_program("shutter_enc", tc.ENC)
        h, w = images[0].shape[:2]
        alpha = images[0].ndim == 3 and images[0].shape[2] == 4
        size = (int(w), int(h))
        accs = (self._target("shutter_a", size, dtype="f4"), self._target("shutter_b", size, dtype="f4"))
        common = {"u_curve": int(curve), "u_cv": int(bool(cv)), "u_alpha": int(alpha)}
        prev = None
        for n, i in enumerate(range(0, len(images), 4)):
            chunk = images[i:i + 4]
            ws = [float(x) for x in weights[i:i + 4]] + [0.0] * (4 - len(chunk))
            texs = {f"t_f{j}": self._clip_texture(1000 + j, img) for j, img in enumerate(chunk)}
            for j in range(len(chunk), 4):
                texs[f"t_f{j}"] = texs["t_f0"]
            texs["t_prev"] = prev[0] if prev is not None else texs["t_f0"]
            dst = accs[n % 2]
            self._run("shutter_acc", dst, texs, {**common, "u_prev": int(prev is not None), "u_n": len(chunk),
                                                 "u_w": tuple(ws)})
            prev = dst
        out = self._target("shutter_out", size, dtype="f4")
        self._run("shutter_enc", out, {"t_acc": prev[0]}, common)
        comps = 4 if alpha else 3
        data = out[1].read(components=comps, alignment=1, dtype="f4")
        return np.frombuffer(data, dtype=np.float32).reshape(h, w, comps).copy()

    # ------------------------------------------------------------ modo Edição
    def _clip_texture(self, slot: int | str, img: np.ndarray) -> moderngl.Texture:
        h, w = img.shape[:2]
        comps = 4 if img.ndim == 3 and img.shape[2] == 4 else 3  # 4 = RGBA pré-multiplicado (transparência)
        dtype = "f1" if img.dtype == np.uint8 else ("f4" if img.dtype == np.float32 else "nu2")  # f4: log (1.6)
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
                light: tuple[int, bool] | None = None, alpha: bool = False, camera=None,
                float_out: bool = False) -> np.ndarray:
        """Monta um quadro da sequência (modo Edição) e devolve (h, w, 3) uint8 ou uint16.

        `frame_layers` é um `sequence.FrameLayers` (imagens já decodificadas, de baixo para cima).
        Cada camada é desenhada por `editshaders.CLIP` com os valores de `compositor.clip_uniforms`
        sobre uma tela RGBA de 32 bits (alterna entre dois alvos). Só na thread dona do contexto.
        `crop` (x, y, largura, altura) devolve só esse recorte da tela (exportação com "cortar", `fit.py`).
        `light`: em que luz as transições da 1.5 misturam (`transitions.light_of`; None = rec709); as camadas
        com uma delas são desenhadas por `editshaders.CLIP_TR`.
        `alpha`: (h, w, 4) RGBA de cor direta; com o "Fundo transparente" da sequência a tela começa transparente
        (`_canvas_alpha`). Sem `alpha`, a tela é sempre opaca, exatamente como antes.
        A janela útil da sequência (1.7, `Sequence.window`) limita tudo: fora dela a tela é preta e opaca.
        `camera` (1.6, `camera.Target`, a entrada do look): os clipes com perfil de câmera próprio passam antes pelo
        `editshaders.CAMERA` (`_camera_pass`). `float_out`: devolve a tela em float32 (h, w, 3), sem cortar em 0–1
        nem arredondar (a montagem com perfis de clipe vai assim ao look). Sem os dois, tudo como antes.
        Um clipe de sequência (1.7, `LayerImage.nested`) é a tela dela, montada do mesmo jeito (`_nested_texture`).
        """
        size = (int(canvas_w), int(canvas_h))
        src = self._canvas(frame_layers, seq, size, "", 0.0 if alpha and getattr(seq, "transparent", False) else 1.0,
                           neutral, light, camera)
        out_dtype = "u1" if depth == 8 else "u2"
        osize, offset = size, (0, 0)
        if crop is not None:
            osize, offset = (int(crop[2]), int(crop[3])), (int(crop[0]), int(crop[1]))
        if alpha:
            return self._canvas_alpha(src, size, osize, offset, depth)
        if float_out:  # 1.6: perfis de câmera por clipe: a tela vai ao look em float32, sem cortar
            self._lazy_program("canvas_outf", editshaders.OUT_FLOAT)
            out = self._target("canvas_outf", osize, dtype="f4")
            self._run("canvas_outf", out, {"t_canvas": src[0]}, {"u_offset": offset})
            data = out[1].read(components=3, alignment=1, dtype="f4")
            return np.frombuffer(data, dtype=np.float32).reshape(osize[1], osize[0], 3)
        out = self._target("canvas_out8" if depth == 8 else "canvas_out16", osize, dtype=out_dtype)
        self._run("canvas_out", out, {"t_canvas": src[0]},
                  {"u_max": 255.0 if depth == 8 else 65535.0, "u_offset": offset})
        data = out[1].read(components=3, alignment=1, dtype=out_dtype)
        arr = np.frombuffer(data, dtype=np.uint8 if depth == 8 else np.uint16)
        return arr.reshape(osize[1], osize[0], 3)

    def _canvas(self, frame_layers, seq, size: tuple[int, int], path: str, start_alpha: float, neutral: bool, light,
                camera):
        """A tela de uma sequência com as camadas desenhadas e as faixas da janela útil: o alvo (textura, framebuffer)
        em f4, cor direta e cobertura. `path` é o lugar desta tela na montagem ("" = a de cima; "/2" = o clipe de
        sequência na camada 2; "/2/0" = o da camada 0 dele): os alvos e as texturas levam esse nome, então uma tela de
        dentro nunca escreve na de fora nem na de outro clipe, e são reaproveitados entre quadros."""
        from . import compositor
        a = self._target("canvas_a" + path, size, dtype="f4")
        b = self._target("canvas_b" + path, size, dtype="f4")
        bg = tuple(float(c) for c in seq.background)
        a[1].use()
        a[1].clear(bg[0], bg[1], bg[2], start_alpha)
        src, dst = a, b
        for slot, li in enumerate(frame_layers.layers):
            key = f"{path}:{slot}" if path else slot
            if li.nested is not None:
                tex = self._nested_texture(li.nested, f"{path}/{slot}", neutral, light, camera)
                tw, th, tex_alpha = li.nested.size[0], li.nested.size[1], bool(li.nested.seq.transparent)
            else:
                tex = self._clip_texture(key, li.image)
                tw, th, tex_alpha = li.image.shape[1], li.image.shape[0], tex.components == 4
            U, mip = compositor.clip_uniforms(seq, li.layer, tw, th, size[0], size[1], neutral, tex_alpha=tex_alpha,
                                              light=light)
            if li.nested is not None and U["u_exact"] and "u_tr_kind" not in U:
                # A tela inteira pixel a pixel não tem borda a suavizar. Na última coluna, o erro de 32 bits do uv vira
                # cobertura de 0,99998: de fora vazaria 0,002% do que está embaixo, e a tela não sairia bit a bit.
                U["u_px_per_uv"] = (compositor.EXACT_PX_PER_UV, compositor.EXACT_PX_PER_UV)
            if camera is not None:  # 1.6: clipe com perfil de câmera próprio → espaço da entrada do look
                tex = self._camera_pass(key, tex, seq, li.layer, camera)
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
        if seq.window:  # 1.7, "Faixas pretas no quadro": camadas e fundo só dentro da janela útil
            self._window_bars(src, seq.window_rect(*size), size)
        return src

    def _nested_texture(self, nested, path: str, neutral: bool, light, camera) -> moderngl.Texture:
        """A imagem de um clipe de sequência (`sequence.Nested`): a tela dela, em f4 e sem arredondar nada, por isso um
        clipe sem ajustes sai bit a bit como os clipes de dentro fora dele. Opaca, a tela começa no fundo da sequência;
        com "Fundo transparente", começa transparente e passa por `editshaders.NEST_PREMUL`.

        Uma câmera lenta mostra o mesmo quadro de dentro em vários de fora: as mesmas camadas (o mesmo objeto, que
        `_NestedStream` repete; o registro segura a referência, então o `is` não confunde objetos) da mesma sequência
        com os mesmos parâmetros reaproveitam a textura. Quem escreve nesses alvos é só este caminho, e sempre troca o
        registro."""
        size = (int(nested.size[0]), int(nested.size[1]))
        params = (bool(neutral), light, camera, size)
        hit = self._nested_tex.get(path)
        if hit is not None and hit[0] is nested.layers and hit[1] is nested.seq and hit[2] == params:
            return hit[3]
        inner = nested.seq
        canvas = self._canvas(nested.layers, inner, size, path, 0.0 if inner.transparent else 1.0, neutral, light, camera)
        tex = canvas[0]
        if inner.transparent:
            self._lazy_program("nest_premul", editshaders.NEST_PREMUL)
            pm = self._target("nest_pm" + path, size, dtype="f4")
            self._run("nest_premul", pm, {"t_canvas": tex}, {})
            tex = pm[0]
        self._nested_tex[path] = (nested.layers, inner, params, tex)
        return tex

    def _window_bars(self, canvas, rect: tuple[int, int, int, int], size: tuple[int, int]) -> None:
        """Fora da janela útil a tela fica preta e opaca (também com o "Fundo transparente": as faixas são imagem)."""
        x, y, w, h = rect
        for box in ((0, 0, size[0], y), (0, y + h, size[0], size[1] - y - h), (0, y, x, h),
                    (x + w, y, size[0] - x - w, h)):
            if box[2] > 0 and box[3] > 0:
                canvas[1].clear(0.0, 0.0, 0.0, 1.0, viewport=box)

    def _camera_pass(self, slot: int | str, tex, seq, layer, target):
        """1.6: a imagem de um clipe com perfil de câmera próprio convertida para a entrada do look (textura f4 do
        mesmo tamanho, `editshaders.CAMERA`); um clipe que segue o look volta como está."""
        from . import camera
        clip = layer.clip
        U = camera.uniforms(clip.values, seq.sources.get(clip.src), target)
        if U is None:
            return tex
        self._lazy_program("clip_cam", editshaders.CAMERA)
        out = self._target(f"clip_cam{slot}", tex.size, dtype="f4", mip=True)
        U["u_tex_alpha"] = 1 if tex.components == 4 else 0
        self._run("clip_cam", out, {"t_clip": tex}, U)
        return out[0]

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
        self._nested_tex.clear()
        for tex, fbo in self._targets.values():
            fbo.release()
            tex.release()
        self._targets.clear()
        try:
            self.ctx.release()
        except Exception:
            pass
