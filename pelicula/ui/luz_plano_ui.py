"""Marcação de luz por plano na janela (1.6, `luz_plano.py`): o cartão "Luz da copiadora" do inspetor e os atalhos.

O cartão é o de sempre do esquema (`editparams`, seção "luz_copiadora": quatro sliders em pontos); aqui entra, no
alto dele, o `LightsPanel`:

- o mostrador clássico do marcador de luz: as luzes do plano no TAPE do LAD (25-25-25) mais as do Laboratório do
  look e as deste clipe (`luz_plano.classic`), e o que vem só do clipe;
- o aviso quando as luzes não valem (Laboratório do look desligado, ou a prévia da Edição sem película);
- botões de ±1 ponto por cor e na densidade, "Zerar" e "Copiar luzes para os clipes selecionados".

Atalhos (modo Edição; nos clipes de vídeo selecionados ou, sem seleção, no plano da V1 sob o cursor): Ctrl+Alt+R /
G / B / D somam 1 ponto de luz vermelha / verde / azul / densidade; com Shift, tiram 1 ponto.

Toda mudança passa pelo `TimelineModel` (`update_clip_values`: um passo do desfazer). O cartão e os atalhos somem
com o módulo "laboratorio" desligado; a renderização nunca consulta `modules`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import editparams, luz_plano
from ..i18n import _, decimal_sep
from ..timeline import VIDEO

CHANNELS = (("luz_r", "R"), ("luz_g", "G"), ("luz_b", "B"), ("luz_densidade", "D"))
SHORTCUTS = {"luz_r": "R", "luz_g": "G", "luz_b": "B", "luz_densidade": "D"}


def _num(x: float) -> str:
    """Pontos no mostrador: inteiro quando é inteiro, senão uma casa (vírgula do idioma)."""
    x = float(x)
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.1f}".replace(".", decimal_sep())


def _signed(x: float) -> str:
    x = float(x)
    if abs(x) < 1e-6:
        return "0"
    return ("+" if x > 0 else "−") + _num(abs(x))


def clamp(key: str, value: float) -> float:
    p = editparams.VIDEO.params[key]
    return min(max(float(value), float(p.min)), float(p.max))


def trimmed(values: dict, key: str, delta: float) -> dict:
    """{chave: novo valor} com `delta` pontos somados (dentro da faixa do ajuste)."""
    return {key: clamp(key, float(values.get(key, 0.0)) + float(delta))}


class LightsPanel(QWidget):
    """O mostrador e os botões do cartão "Luz da copiadora" para o clipe `clip_id()`."""

    def __init__(self, model, clip_id: Callable[[], str | None], look_values: Callable[[], dict | None],
                 film_on: Callable[[], bool] = lambda: True, parent=None):
        super().__init__(parent)
        self.model = model
        self.clip_id = clip_id
        self.look_values = look_values
        self.film_on = film_on
        self.setObjectName("LightsPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 6)
        lay.setSpacing(4)
        self.display = QLabel()
        self.display.setObjectName("PanelTitle")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setToolTip(_("Luzes vermelha, verde e azul da copiadora neste plano: o TAPE padrão 25-25-25 "
                                  "(as luzes no alvo do LAD) mais as do Laboratório do look e as deste clipe. 1 "
                                  "ponto = 0,025 log E; 12 pontos = 1 stop da cópia; cerca de 7 pontos = 1 stop da "
                                  "câmera."))
        lay.addWidget(self.display)
        self.detail = QLabel()
        self.detail.setObjectName("Faint")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)
        self.warning = QLabel()
        self.warning.setObjectName("Muted")
        self.warning.setWordWrap(True)
        lay.addWidget(self.warning)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        names = {"luz_r": _("Vermelho"), "luz_g": _("Verde"), "luz_b": _("Azul"), "luz_densidade": _("Densidade")}
        self.buttons: dict[tuple[str, int], QPushButton] = {}
        for col, (key, letter) in enumerate(CHANNELS):
            head = QLabel(letter)
            head.setObjectName("Muted")
            head.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.setToolTip(names[key])
            grid.addWidget(head, 0, col)
            for row, delta in ((1, 1), (2, -1)):
                b = QPushButton(("+1" if delta > 0 else "−1"))
                b.setObjectName(f"trim_{key}_{'mais' if delta > 0 else 'menos'}")
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                sc = ("Ctrl+Alt+Shift+" if delta < 0 else "Ctrl+Alt+") + SHORTCUTS[key]
                b.setToolTip(_("{cor}: {sinal}1 ponto neste plano ({atalho})").format(
                    cor=names[key], sinal="+" if delta > 0 else "−", atalho=sc))
                b.clicked.connect(lambda _c=False, k=key, d=delta: self.trim(k, d))
                grid.addWidget(b, row, col)
                self.buttons[(key, delta)] = b
        lay.addLayout(grid)
        self.btn_zero = QPushButton(_("Zerar"))
        self.btn_zero.setToolTip(_("Este plano volta às luzes do look"))
        self.btn_zero.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_zero.clicked.connect(self.reset)
        self.btn_copy = QPushButton(_("Copiar luzes para os clipes selecionados"))
        self.btn_copy.setToolTip(_("As quatro luzes deste plano nos outros clipes de vídeo selecionados (um passo de "
                                   "desfazer)"))
        self.btn_copy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_copy.clicked.connect(self.copy_to_selected)
        lay.addWidget(self.btn_zero)
        lay.addWidget(self.btn_copy)
        model.changed.connect(lambda _k: self.refresh())
        model.selectionChanged.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------ estado
    def clip(self):
        cid = self.clip_id()
        c = self.model.seq.find(cid) if cid else None
        return c if c is not None and c.kind == VIDEO else None

    def warning_text(self) -> str:
        look = self.look_values() or {}
        if not look.get("lab_on"):
            return _("O Laboratório do look está desligado: as luzes por plano só valem com ele ligado (modo Película "
                     "› Laboratório).")
        if not self.film_on():
            return _("A prévia está sem película: ligue a película na barra da prévia para ver as luzes (a "
                     "exportação com o look já usa).")
        return ""

    def refresh(self) -> None:
        c = self.clip()
        vals = c.values if c is not None else {}
        r, g, b = luz_plano.classic(self.look_values(), vals)
        self.display.setText(f"{_num(r)} · {_num(g)} · {_num(b)}")
        own = luz_plano.points(vals)
        self.detail.setText(_("Este plano: R {r} · G {g} · B {b}").format(
            r=_signed(own[0]), g=_signed(own[1]), b=_signed(own[2])))
        text = self.warning_text()
        self.warning.setText(text)
        self.warning.setVisible(bool(text))
        sel = [x for x in self.model.selected_clips() if x.kind == VIDEO and (c is None or x.id != c.id)]
        self.btn_copy.setEnabled(c is not None and bool(sel))
        self.btn_zero.setEnabled(c is not None and luz_plano.has_lights(vals))
        for b_ in self.buttons.values():
            b_.setEnabled(c is not None)

    # ------------------------------------------------------------ ações (um passo do desfazer cada)
    def trim(self, key: str, delta: float) -> bool:
        c = self.clip()
        if c is None:
            return False
        return self.model.update_clip_values({c.id: trimmed(c.values, key, delta)}) > 0

    def reset(self) -> bool:
        c = self.clip()
        if c is None:
            return False
        return self.model.update_clip_values({c.id: {k: 0.0 for k, _l in CHANNELS}}) > 0

    def copy_to_selected(self) -> int:
        c = self.clip()
        if c is None:
            return 0
        lights = {k: float(c.values.get(k, 0.0)) for k, _l in CHANNELS}
        ids = [x.id for x in self.model.selected_clips() if x.kind == VIDEO and x.id != c.id]
        return self.model.update_clip_values({cid: dict(lights) for cid in ids})


# ---------------------------------------------------------------- ligação com a janela
def targets(win) -> list:
    """Clipes que os atalhos mudam: os de vídeo selecionados ou, sem seleção, o plano da V1 sob o cursor."""
    model = win.model
    sel = [c for c in model.selected_clips() if c.kind == VIDEO]
    if sel:
        return sel
    t = int(getattr(win, "frame_idx", 0) or 0)
    shot = luz_plano.shot_at(model.seq, t) if model.seq.clips else []
    return [shot[-1][0]] if shot else []


def trim_targets(win, key: str, delta: float) -> int:
    """Atalho: ±`delta` pontos em `key` nos clipes de `targets` (um passo do desfazer)."""
    if getattr(win, "mode", "") != "edicao":
        return 0
    clips = targets(win)
    n = win.model.update_clip_values({c.id: trimmed(c.values, key, delta) for c in clips})
    if n and clips:
        r, g, b = luz_plano.classic(win.store.values, clips[-1].values)
        win.statusBar().showMessage(_("Luzes do plano: {r} · {g} · {b}").format(r=_num(r), g=_num(g), b=_num(b)),
                                    3000)
    return n


def install(win) -> None:
    """O painel no cartão "Luz da copiadora" do inspetor e os atalhos Ctrl+Alt+R/G/B/D (Shift: menos)."""
    insp = getattr(win, "inspector", None)
    card = next((c for c in getattr(insp, "vcards", []) if c.section.key == "luz_copiadora"), None)
    win.lights_panel = None
    if card is not None:
        panel = LightsPanel(win.model, lambda: insp.clip_id, lambda: win.store.values,
                            lambda: bool(getattr(win, "edit_film", True)))
        card.body.layout().insertWidget(0, panel)
        win.store.changed.connect(lambda _k: panel.refresh())
        btn_film = getattr(win, "btn_edit_film", None)
        if btn_film is not None:
            btn_film.toggled.connect(lambda _on: panel.refresh())
        win.lights_panel = panel
        win.lights_card = card
    win.lights_shortcuts = []
    for key, letter in SHORTCUTS.items():
        for prefix, delta in (("Ctrl+Alt+", 1.0), ("Ctrl+Alt+Shift+", -1.0)):
            s = QShortcut(QKeySequence(prefix + letter), win)
            s.activated.connect(lambda k=key, d=delta: trim_targets(win, k, d))
            win.lights_shortcuts.append(s)


def apply_modules(win, on: set[str]) -> None:
    """O cartão e os atalhos são do Laboratório: somem com o módulo "laboratorio" desligado."""
    lab = "laboratorio" in on
    card = getattr(win, "lights_card", None)
    if card is not None:
        card.setVisible(lab)
    for s in getattr(win, "lights_shortcuts", []):
        s.setEnabled(lab)
