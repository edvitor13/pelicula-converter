"""Ferramentas da prévia da 1.6: o que é desenhado por cima do quadro na tela (nunca na exportação).

`PreviewTools` junta as camadas de cima da prévia — "Ver planos" (`planes_ui`), zebra e falsa cor (`meter.py`) —
numa imagem RGBA que o `Viewer` desenha sobre o quadro processado (`Viewer.set_overlay`). Cada ferramenta é um
"provedor": uma função que recebe o `Context` do quadro atual e devolve (h × w × 4, float 0 a 1, alfa direto) ou
None. A janela chama `refresh()` depois de cada `render_now`.

O `Context` dá a luz da cena do quadro (`Engine.scene_light`): no modo Película e no modo Edição com película, o
plano do look da prévia (a entrada decodificada pelo perfil do look, exposição, balanço, Cor por planos); no modo
Edição sem película, a montagem lida pelo perfil escolhido no look, sem os efeitos (`meter.decode_values`). Nada
disso entra na receita do quadro: `frame.Recipe` e a exportação não sabem que estas ferramentas existem.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from PySide6.QtGui import QImage


class Context:
    """O quadro da prévia que as ferramentas leem (preguiçoso: a luz só é calculada se alguém pedir)."""

    def __init__(self, win, recipe):
        self.win = win
        self.recipe = recipe
        self.engine = win.engine
        self.img = win.cur
        self.frame = int(getattr(win, "cur_frame", 0) or 0)
        h, w = self.img.shape[:2]
        self.size = (w, h)
        self._light = None
        self._plan = None

    @property
    def values(self) -> dict | None:
        """Os ajustes do look neste quadro (None = modo Edição sem película)."""
        return None if self.recipe.values is None else self.recipe.look_values(self.frame)

    def plan(self):
        """O plano da luz medida: o do look da prévia ou, sem película, só a leitura da entrada."""
        if self._plan is None:
            w, h = self.size
            if self.recipe.values is not None:
                self._plan = self.recipe.plan(w, h, self.frame)
            else:
                from .. import look, meter
                v = meter.decode_values(self.win.store.values)
                self._plan = look.build_plan(v, w, h, self.frame, self.recipe.fps or 24.0, dither=False,
                                             legal=self.recipe.legal)
        return self._plan

    def ensure_input(self) -> None:
        """O quadro da prévia na entrada do motor (sem película, a prévia não o envia)."""
        if self.recipe.values is None or getattr(self.win, "_uploaded", None) is not self.img:
            self.engine.set_input(self.img)
            self.win._uploaded = self.img

    def light(self) -> np.ndarray:
        """(h, w, 4) float32: a luz da cena (RGB) e quanto do pixel é imagem."""
        if self._light is None:
            self.ensure_input()
            self._light = self.engine.scene_light(self.plan())
        return self._light


Provider = Callable[[Context], "np.ndarray | None"]


def over(dst: np.ndarray | None, src: np.ndarray | None) -> np.ndarray | None:
    """`src` sobre `dst` (RGBA float, alfa direto)."""
    if src is None:
        return dst
    if dst is None:
        return src
    sa = src[..., 3:4]
    da = dst[..., 3:4] * (1.0 - sa)
    a = sa + da
    rgb = (src[..., :3] * sa + dst[..., :3] * da) / np.maximum(a, 1e-6)
    return np.concatenate([rgb, a], axis=-1)


def to_qimage(rgba: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(np.clip(np.rint(rgba * 255.0), 0, 255).astype(np.uint8))
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()


class PreviewTools:
    """As camadas de cima da prévia. `add(nome, provedor)` registra; `refresh(receita)` redesenha."""

    def __init__(self, win):
        self.win = win
        self.providers: list[tuple[str, Provider]] = []
        self.last_error = ""

    def add(self, name: str, provider: Provider) -> None:
        self.providers.append((name, provider))

    def refresh(self, recipe=None) -> None:
        win = self.win
        if getattr(win, "cur", None) is None or not self.providers:
            win.viewer.set_overlay(None)
            return
        recipe = recipe if recipe is not None else win.frame_recipe()
        ctx = Context(win, recipe)
        out = None
        self.last_error = ""
        for _name, fn in self.providers:
            try:
                out = over(out, fn(ctx))
            except Exception as exc:  # noqa: BLE001  (uma ferramenta da tela nunca derruba a prévia)
                self.last_error = str(exc)
        win.viewer.set_overlay(None if out is None else to_qimage(out))
