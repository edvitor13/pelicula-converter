"""Interface das transições de película da 1.5 (módulo "transicoes", `pelicula/transitions.py`).

Três ganchos pequenos ligam isto ao resto da janela:

- **Inspetor do clipe** (`ClipInspector.transitions = InspectorTransitions(...)`): ícones e dicas nos tipos de
  "Entrada" e "Saída", e só os ajustes que o tipo escolhido usa (`transitions.params_for`). Com o módulo
  desligado os tipos novos somem da lista (o do clipe, se for um deles, continua lá).
- **Menu do corte** (`add_menu`, no menu de contexto da linha do tempo): "Transição ▸" com os tipos; escolher
  um troca o tipo e a duração (a que já havia, ou a última usada, 1 s no começo) num passo só do desfazer
  (`TimelineModel.set_transition`). Some com o módulo desligado.
- **Linha do tempo** (`paint`, chamado no `paintEvent`): a faixa da transição sobre o corte, com o ícone e o
  nome quando cabem. Continua aparecendo com o módulo desligado: o projeto não muda.

O som não muda: a transição de som continua sendo a de sempre (menu "Transição de som").
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu

from .. import editparams, transitions
from ..i18n import N_, _
from ..timeline import VIDEO
from . import theme

MODULE_ID = "transicoes"
SIDES = ("entrada", "saida")

# Dica de cada tipo (na lista do inspetor e no menu do corte).
TIPS: dict[tuple[str, str], str] = {
    ("entrada", "fusao"): N_("As duas imagens se somam na luz, como na copiadora ótica: as altas luzes "
                             "atravessam primeiro."),
    ("entrada", "exposicao"): N_("A luz sobe do preto como na copiadora: os tons seguem a curva da película."),
    ("entrada", "queima"): N_("A película queima no projetor: um furo com a borda branca e laranja abre e mostra "
                              "o próximo plano."),
    ("entrada", "emenda"): N_("Corte com a emenda à vista: de um a três quadros estouram de luz, com a linha da "
                              "emenda e um pulo da imagem."),
    ("entrada", "ponta"): N_("Alguns quadros de ponta (preta ou clara) com poeira, riscos e o furo de perfuração "
                             "antes do plano."),
    ("entrada", "iris"): N_("Um círculo abre a partir do centro escolhido, como nos filmes mudos (com anel preto, "
                            "se quiser)."),
    ("entrada", "empurrar"): N_("O clipe novo empurra o anterior para fora do quadro."),
    ("entrada", "cortina"): N_("Uma borda atravessa o quadro e troca um plano pelo outro."),
    ("entrada", "zoom"): N_("O plano anterior amplia até a troca e o novo chega ampliado e volta ao tamanho."),
    ("saida", "exposicao"): N_("A luz desce até o preto como na copiadora: os tons seguem a curva da película."),
    ("saida", "queima"): N_("A película queima no projetor e mostra o que está na faixa de baixo."),
    ("saida", "iris"): N_("O círculo fecha no centro escolhido; fora dele aparece a faixa de baixo."),
}
# Nome curto desenhado na linha do tempo.
SHORT = {"fusao": N_("Fusão"), "exposicao": N_("Exposição"), "queima": N_("Queima"), "emenda": N_("Emenda"),
         "ponta": N_("Ponta"), "iris": N_("Íris"), "empurrar": N_("Empurrar"), "cortina": N_("Cortina"),
         "zoom": N_("Zoom")}


def is_extra(side: str, kind: str) -> bool:
    """Tipo da 1.5 (do módulo) neste lado."""
    return kind in (editparams.EXTRA_IN if side == "entrada" else editparams.EXTRA_OUT)


# ------------------------------------------------------------------ ícones
def draw_glyph(p: QPainter, kind: str, r: QRectF, color: QColor) -> None:
    """Desenho simples de cada tipo de transição (antigos e novos) dentro de `r`."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, max(1.0, r.width() / 12.0))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    c = r.center()
    s = min(r.width(), r.height())
    box = QRectF(c.x() - s * 0.42, c.y() - s * 0.32, s * 0.84, s * 0.64)
    fill = QColor(color)
    fill.setAlpha(150)
    if kind == "corte":
        p.drawLine(QPointF(c.x(), box.top()), QPointF(c.x(), box.bottom()))
        p.drawRect(box)
    elif kind in ("dissolver", "fusao"):
        rad = s * 0.24
        if kind == "fusao":
            p.setBrush(fill)
        p.drawEllipse(QPointF(c.x() - rad * 0.55, c.y()), rad, rad)
        p.drawEllipse(QPointF(c.x() + rad * 0.55, c.y()), rad, rad)
    elif kind in ("preto", "branco", "exposicao"):
        p.drawRect(box)
        p.setPen(Qt.PenStyle.NoPen)
        half = QRectF(box.left(), box.top(), box.width() / 2, box.height())
        p.setBrush(QColor(0, 0, 0, 220) if kind != "branco" else QColor(255, 255, 255, 220))
        p.drawRect(half)
        if kind == "exposicao":
            p.setBrush(fill)
            p.drawRect(QRectF(box.center().x(), box.top() + box.height() * 0.45, box.width() / 2, box.height() * 0.55))
    elif kind == "transparente":
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(box)
    elif kind == "queima":
        p.setBrush(QColor(255, 150, 40, 220))
        path = QPainterPath()
        n = 14
        for i in range(n + 1):
            a = i / n * 2 * math.pi
            rr = s * (0.26 + 0.07 * math.sin(a * 3) + 0.04 * math.cos(a * 5))
            pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "emenda":
        p.drawRect(box)
        p.setPen(QPen(QColor(255, 255, 255, 230), max(1.0, s / 10.0)))
        p.drawLine(QPointF(box.left(), c.y()), QPointF(box.right(), c.y()))
    elif kind == "ponta":
        p.drawRect(box)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        hole = s * 0.07
        for i in range(4):
            x = box.left() + box.width() * (0.15 + 0.233 * i)
            p.drawRect(QRectF(x - hole / 2, box.top() + hole, hole, hole))
            p.drawRect(QRectF(x - hole / 2, box.bottom() - 2 * hole, hole, hole))
    elif kind == "iris":
        p.drawRect(box)
        p.setBrush(fill)
        p.drawEllipse(c, s * 0.2, s * 0.2)
    elif kind == "empurrar":
        y = c.y()
        p.drawLine(QPointF(box.left(), y), QPointF(box.right(), y))
        p.drawLine(QPointF(box.right() - s * 0.18, y - s * 0.18), QPointF(box.right(), y))
        p.drawLine(QPointF(box.right() - s * 0.18, y + s * 0.18), QPointF(box.right(), y))
    elif kind == "cortina":
        p.drawRect(box)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRect(QRectF(box.left(), box.top(), box.width() * 0.6, box.height()))
    elif kind == "zoom":
        p.drawRect(box)
        p.drawRect(QRectF(c.x() - box.width() * 0.22, c.y() - box.height() * 0.22, box.width() * 0.44,
                          box.height() * 0.44))
    p.restore()


def kind_icon(kind: str, color: str | None = None, size: int = 16) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_glyph(p, kind, QRectF(0, 0, size, size), QColor(color or theme.TEXT))
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------------ inspetor
class InspectorTransitions:
    """Liga a seção "Transições" do inspetor do clipe ao tipo escolhido em cada lado."""

    def __init__(self, store, cards, model=None):
        self.store = store
        self.model = model
        self.card = next((c for c in cards if c.section.key == "transicao"), None)
        self.enabled = True
        self.rows = {r.param.key: r for r in self.card.rows} if self.card is not None else {}
        for side in SIDES:
            row = self.rows.get(f"{side}_tipo")
            combo = getattr(row, "combo", None)
            if combo is None:
                continue
            for i in range(combo.count()):
                kind = combo.itemData(i)
                combo.setItemIcon(i, kind_icon(kind))
                tip = TIPS.get((side, kind))
                if tip:
                    combo.setItemData(i, _(tip), Qt.ItemDataRole.ToolTipRole)
        store.changed.connect(self._changed)
        self.update()

    def _changed(self, key: str) -> None:
        if key == "*" or key in ("entrada_tipo", "saida_tipo"):
            self.update()
        elif key in ("entrada_dur", "saida_dur") and self.model is not None:
            side = key.split("_")[0]
            if self.store.get(f"{side}_tipo") != "corte":  # a última duração usada vira a do menu do corte
                self.model.last_transition_s = float(self.store.get(key))

    def set_enabled(self, on: bool) -> None:
        """Módulo ligado ou desligado: os tipos novos aparecem ou somem das listas."""
        self.enabled = bool(on)
        self.update()

    def update(self) -> None:
        for side in SIDES:
            kind = self.store.get(f"{side}_tipo")
            self._filter(side, kind)
            for key in transitions.EXTRA_KEYS:
                if key.startswith(side + "_") and key in self.rows:
                    self.rows[key].setVisible(key in transitions.params_for(side, kind))
            dur = self.rows.get(f"{side}_dur")
            if dur is not None:
                dur.setVisible(not (side == "entrada" and kind == "emenda"))

    def _filter(self, side: str, current: str) -> None:
        row = self.rows.get(f"{side}_tipo")
        combo = getattr(row, "combo", None)
        if combo is None:
            return
        view, model = combo.view(), combo.model()
        for i in range(combo.count()):
            kind = combo.itemData(i)
            hide = not self.enabled and is_extra(side, kind) and kind != current
            view.setRowHidden(i, hide)
            item = model.item(i) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(not hide)

    def visible_choices(self, side: str) -> list[str]:
        """Tipos que a lista do lado mostra agora (para os testes e para a ajuda)."""
        combo = self.rows[f"{side}_tipo"].combo
        return [combo.itemData(i) for i in range(combo.count()) if not combo.view().isRowHidden(i)]


# ------------------------------------------------------------------ menu do corte
def cut_near(canvas, clip, x: float) -> tuple:
    """(clipe, lado) da transição no corte mais perto do clique `x` dentro de `clip`: na metade da esquerda, a
    entrada do próprio clipe; na da direita, a entrada do próximo clipe colado na faixa ou, sem ele, a saída do
    próprio clipe."""
    r = canvas.clip_rect(clip)
    left = r is None or x < r.center().x()
    if left:
        return clip, "entrada"
    nxt = canvas.seq.next_on_track(clip)
    if nxt is not None:
        return nxt, "entrada"
    return clip, "saida"


def add_menu(canvas, menu: QMenu, clip, x: float):
    """"Transição ▸" no menu de contexto de um clipe de vídeo (só com o módulo ligado). Devolve o submenu."""
    if clip.kind != VIDEO or not getattr(canvas, "film_transitions", True):
        return None
    target, side = cut_near(canvas, clip, x)
    sub = menu.addMenu(kind_icon("fusao"), _("Transição"))
    sub.setObjectName("TransitionMenu")
    src = canvas.seq.sources.get(target.src)
    name = target.name or (src.name if src is not None else "")
    where = _("No começo de “{nome}”") if side == "entrada" else _("No fim de “{nome}”")
    info = sub.addAction(where.format(nome=name))
    info.setEnabled(False)
    sub.addSeparator()
    current = target.values.get(f"{side}_tipo", "corte")
    for val, label in editparams.VIDEO.params[f"{side}_tipo"].choices:
        act = sub.addAction(kind_icon(val), _(label))
        act.setCheckable(True)
        act.setChecked(val == current)
        act.setData((target.id, side, val))
        tip = TIPS.get((side, val))
        if tip:
            act.setToolTip(_(tip))
        act.triggered.connect(lambda _on=False, cid=target.id, s=side, v=val: canvas.model.set_transition(cid, s, v))
    sub.setToolTipsVisible(True)
    sub.setEnabled(not canvas.seq.locked(target))
    return sub


# ------------------------------------------------------------------ linha do tempo
def paint(canvas, p: QPainter, x_min: float, x_max: float) -> None:
    """A faixa de cada transição da 1.5 sobre o corte, com o ícone e o nome quando cabem."""
    seq = canvas.seq
    fm = QFontMetrics(theme.font(7.6))
    for c in seq.clips:
        if c.kind != VIDEO:
            continue
        r = None
        for side in SIDES:
            kind = c.values.get(f"{side}_tipo", "corte")
            if not is_extra(side, kind):
                continue
            if r is None:
                r = canvas.clip_rect(c)
            if r is None:
                break
            n = seq.transition_frames(c, side)
            wpx = min(r.width(), n * canvas.ppf)
            x0 = r.left() if side == "entrada" else r.right() - wpx
            if x0 + wpx < x_min or x0 > x_max:
                continue
            band = QRectF(x0, r.top() + 2, max(wpx, 3.0), r.height() - 4)
            p.save()
            p.setClipRect(r.adjusted(1, 1, -1, -1))
            p.setPen(QPen(QColor(theme.ACCENT_HI), 1))
            fill = QColor(theme.ACCENT)
            fill.setAlpha(48)
            p.setBrush(fill)
            p.drawRoundedRect(band, 3, 3)
            if band.width() >= 14:
                icon_r = QRectF(band.left() + 2, band.center().y() - 6.5, 13, 13)  # entre o nome e o tempo
                draw_glyph(p, kind, icon_r, QColor("#fff6e8"))
                text = _(SHORT.get(kind, kind))
                if band.width() >= fm.horizontalAdvance(text) + 22:
                    p.setFont(theme.font(7.6))
                    p.setPen(QColor(255, 246, 232, 200))
                    p.drawText(QRectF(icon_r.right() + 3, icon_r.top() - 1, band.width() - 20, 14),
                               Qt.AlignmentFlag.AlignVCenter, text)
            p.restore()


def apply_module(window, on: bool) -> None:
    """Módulo ligado/desligado na janela (`MainWindow.apply_modules`): listas do inspetor e menu do corte."""
    inspector = getattr(window, "inspector", None)
    if inspector is not None and getattr(inspector, "transitions", None) is not None:
        inspector.transitions.set_enabled(on)
    editor = getattr(window, "tl_editor", None)
    if editor is not None:
        editor.canvas.film_transitions = bool(on)
