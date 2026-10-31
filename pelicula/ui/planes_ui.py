"""Cor por planos na janela (1.6, módulo Beta "cor_planos"): o cartão da seção com Frente, Fundo e Pele.

O cartão é o `SectionCard` gerado de `params.SECTIONS` ("planos"); aqui as linhas são reagrupadas em três
blocos (Frente, Fundo, Pele, com os cinco ajustes de cada plano) e ganham uma barra com os prontos, o
conta-gotas da pele e "Ver planos". "Ver planos" é uma camada da prévia (`preview_tools`): frente em laranja,
fundo em azul e o contorno da pele, calculados pelo mesmo shader do look (`Engine.plane_view`); só na tela.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from .. import masks, planes
from ..i18n import N_, _
from . import icons, sem_efeitos_ui, theme

FRONT_RGB = (0.94, 0.65, 0.23)   # laranja: frente
BACK_RGB = (0.30, 0.55, 0.95)    # azul: fundo
TINT = 0.42                      # quanto da cor do plano vai por cima

GROUPS = (
    ("frente", N_("Frente"), N_("O que fica perto: o assunto ou o chão.")),
    ("fundo", N_("Fundo"), N_("O que fica longe: o céu, a paisagem ou a parede de trás.")),
    ("pele", N_("Pele"), N_("Os tons de pele, achados pela cor (a textura nunca muda).")),
)


def view_rgba(masks_img: np.ndarray) -> np.ndarray:
    """A camada de "Ver planos" (RGBA float) das máscaras (frente, fundo, pele, cobertura)."""
    m = np.asarray(masks_img, dtype=np.float64)
    front, back, skin, cover = m[..., 0], m[..., 1], m[..., 2], np.clip(m[..., 3], 0.0, 1.0)
    rgb = (np.asarray(FRONT_RGB) * front[..., None] + np.asarray(BACK_RGB) * back[..., None])
    a = np.clip((front + back) * TINT, 0.0, 1.0)
    rgb = rgb / np.maximum(front + back, 1e-6)[..., None]
    edge = np.zeros_like(skin, dtype=bool)
    hard = skin >= 0.5
    edge[:, 1:] |= hard[:, 1:] != hard[:, :-1]
    edge[1:, :] |= hard[1:, :] != hard[:-1, :]
    rgb = np.where(edge[..., None], 1.0, rgb)
    a = np.where(edge, 0.95, a) * cover
    return np.concatenate([rgb, a[..., None]], axis=-1)


class PlanesUI:
    """Liga o cartão "planos" da janela: blocos, prontos, conta-gotas e "Ver planos"."""

    def __init__(self, win, card):
        self.win = win
        self.card = card
        self.view_on = False
        self._picking = False
        self.groups: dict[str, QFrame] = {}
        self._build()
        win.preview_tools.add("planos", self.provider)
        win.viewer.picked.connect(self._picked)
        win.viewer.pickCanceled.connect(self._pick_done)

    # ------------------------------------------------------------ cartão
    def _build(self) -> None:
        body = self.card.body
        lay = body.layout()
        rows = {r.param.key: r for r in self.card.rows}
        for r in self.card.rows:
            lay.removeWidget(r)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 4)
        bl.setSpacing(4)
        self.btn_prontos = QToolButton()
        self.btn_prontos.setText(_("Prontos"))
        self.btn_prontos.setToolTip(_("Preenche os ajustes de frente, fundo e pele com um ponto de partida"))
        self.btn_prontos.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_prontos)
        for pid, name, _v in planes.PRONTOS:
            menu.addAction(_(name), lambda p=pid: self.apply_pronto(p))
        self.btn_prontos.setMenu(menu)
        bl.addWidget(self.btn_prontos)
        self.btn_pick = QToolButton()
        self.btn_pick.setObjectName("Flat")
        self.btn_pick.setIcon(icons.icon("eyedropper", theme.TEXT, 16))
        self.btn_pick.setText(_("Pele"))
        self.btn_pick.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip(_("Conta-gotas: clique na pele da prévia para a máscara procurar essa cor "
                                   "(Esc cancela)"))
        self.btn_pick.toggled.connect(self._toggle_pick)
        bl.addWidget(self.btn_pick)
        bl.addStretch(1)
        self.btn_view = QToolButton()
        self.btn_view.setText(_("Ver planos"))
        self.btn_view.setCheckable(True)
        self.btn_view.setToolTip(_("Mostra por cima da prévia a frente (laranja), o fundo (azul) e o contorno da "
                                   "pele. Só na tela: não vai para a exportação."))
        self.btn_view.toggled.connect(self.set_view)
        bl.addWidget(self.btn_view)
        lay.addWidget(bar)
        for key in planes.GEOMETRY_KEYS:
            if key in rows:
                lay.addWidget(rows[key])
        plane_rows = {"frente": planes.plane_keys("frente"), "fundo": planes.plane_keys("fundo"),
                      "pele": ["planos_proteger_pele"] + planes.skin_keys() + list(planes.SKIN_WINDOW_KEYS)}
        for gid, title, tip in GROUPS:
            box = QFrame()
            box.setObjectName("PlaneGroup")
            color = {"frente": FRONT_RGB, "fundo": BACK_RGB}.get(gid, (0.85, 0.85, 0.85))
            css = "rgb({}, {}, {})".format(*(int(c * 255) for c in color))
            box.setStyleSheet(f"QFrame#PlaneGroup {{ border: 1px solid {theme.BORDER}; border-left: 3px solid {css};"
                              f" border-radius: 8px; }}")
            bx = QVBoxLayout(box)
            bx.setContentsMargins(8, 4, 8, 6)
            bx.setSpacing(2)
            head = QLabel(_(title))
            head.setObjectName("PanelTitle")
            head.setToolTip(_(tip))
            bx.addWidget(head)
            for key in plane_rows[gid]:
                if key in rows:
                    bx.addWidget(rows[key])
            self.groups[gid] = box
            lay.addWidget(box)
        self.card.set_advanced(self.win.adv.isChecked() if hasattr(self.win, "adv") else False)

    def apply_pronto(self, pid: str) -> None:
        store = self.win.store
        store.set_all(planes.apply_pronto(store.values, pid), keys=None)

    # ------------------------------------------------------------ conta-gotas
    def _toggle_pick(self, on: bool) -> None:
        viewer = self.win.viewer
        if on and sem_efeitos_ui.refuses_tool(self.win):
            self._pick_done()
            return
        if on:
            self._picking = True
            viewer.start_pick()
            self.win.statusBar().showMessage(_("Clique na pele da prévia (Esc cancela)."), 6000)
        elif self._picking:
            self._picking = False
            viewer.cancel_pick()

    def _pick_done(self) -> None:
        self._picking = False
        self.btn_pick.blockSignals(True)
        self.btn_pick.setChecked(False)
        self.btn_pick.blockSignals(False)

    def _picked(self, fx: float, fy: float) -> None:
        if not self._picking:
            return
        self._pick_done()
        hue = self.skin_hue_at(fx, fy)
        if hue is None:
            self.win.statusBar().showMessage(_("Essa cor é quase cinza: clique numa parte da pele com cor."), 6000)
            return
        store = self.win.store
        store.set("planos_pele_centro", round(hue * 2.0) / 2.0)
        store.commit()

    def skin_hue_at(self, fx: float, fy: float) -> float | None:
        """O matiz da pele (OkLCh) num ponto da prévia: a luz da cena do look, como a máscara a vê."""
        from .preview_tools import Context
        win = self.win
        if win.cur is None:
            return None
        ctx = Context(win, win.frame_recipe())
        if ctx.values is None:
            return None
        lin = ctx.light()[..., :3].astype(np.float64)
        return masks.skin_hue_of(planes._display(area(lin, fx, fy)))

    # ------------------------------------------------------------ "Ver planos"
    def set_view(self, on: bool) -> None:
        self.view_on = bool(on)
        if self.btn_view.isChecked() != self.view_on:
            self.btn_view.blockSignals(True)
            self.btn_view.setChecked(self.view_on)
            self.btn_view.blockSignals(False)
        self.win.preview_tools.refresh()

    def provider(self, ctx) -> np.ndarray | None:
        if not self.view_on or self.card.isHidden():
            return None
        values = ctx.values
        if values is None:
            return None
        ctx.ensure_input()
        return view_rgba(ctx.engine.plane_view(ctx.plan(), values))

    def apply_module(self, on: bool) -> None:
        """Módulo desligado: o cartão some (`_module_tools`) e "Ver planos" e o conta-gotas param."""
        if not on:
            if self.view_on:
                self.set_view(False)
            if self._picking:
                self.btn_pick.setChecked(False)


def area(img: np.ndarray, fx: float, fy: float, r: int = 2) -> np.ndarray:
    """Os pixels (… × 3) de um quadrado de (2r + 1)² em volta do ponto (fração da imagem)."""
    h, w = img.shape[:2]
    x = min(max(int(fx * w), 0), w - 1)
    y = min(max(int(fy * h), 0), h - 1)
    return img[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, img.shape[2])
