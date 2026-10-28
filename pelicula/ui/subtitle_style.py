"""Aba "Estilo" do painel de legendas: o estilo pronto (YouTube, Reels e Shorts, Cinema) e os ajustes dele.

Fonte (do catálogo embutido, `textrender.FAMILIES`), peso, tamanho em px@1080, maiúsculas, cores, contorno,
caixa de fundo, sombra, posição e margem de segurança, largura, palavras por tela e a cor do destaque da
palavra falada. Cada mudança é um passo de desfazer (`SubtitleController.set_options(style=...)`) e aparece na
prévia na hora (a janela redesenha o quadro quando as legendas mudam). O aviso de caracteres que a fonte não
tem fica embaixo do painel (`missing_text`).
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFormLayout, QHBoxLayout, QPushButton, QSpinBox,
                               QWidget)

from .. import subtitles as sb, textrender as tr
from ..i18n import N_, _
from .subtitles_ui import SubtitleController
from .widgets import ColorButton

POSITION_LABELS = {"baixo": N_("Embaixo"), "meio": N_("No meio"), "cima": N_("Em cima")}
WEIGHT_LABELS = ((400, N_("Normal")), (700, N_("Negrito")), (900, N_("Extranegrito")))
HIGHLIGHT_COLOR = (1.0, 0.84, 0.0)


def qcolor(c) -> QColor:
    return QColor.fromRgbF(*c)


def from_qcolor(q: QColor):
    return tr.parse_color(q.name())


def missing_text(subs: sb.Subtitles | None, cues) -> str:
    """Caracteres das legendas que a fonte do estilo não tem (com itálico e negrito de cada legenda)."""
    if subs is None:
        return ""
    st = subs.style.text
    found: set[str] = set()
    groups: dict[tuple[int, bool], list[str]] = {}
    for c in cues:
        text = c.text.upper() if st.uppercase else c.text
        weight = max(st.weight, 700) if c.bold else st.weight
        groups.setdefault((weight, c.italic or st.italic), []).append(text)
    for (weight, italic), texts in groups.items():
        found.update(tr.missing_chars("".join(texts), st.family, weight, italic))
    found.discard("\n")
    return "".join(sorted(found))


class _Color(ColorButton):
    """Botão de cor: abre o seletor e avisa com `picked`."""
    picked = Signal(QColor)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.clicked.connect(self._pick)

    def _pick(self) -> None:
        c = QColorDialog.getColor(self.color, self, self.title)
        if c.isValid():
            self.set(c)
            self.picked.emit(c)

    def set(self, c: QColor) -> None:
        self.color = QColor(c)
        self.update()


class StyleEditor(QWidget):
    def __init__(self, ctl: SubtitleController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self._filling = False
        form = QFormLayout(self)
        form.setContentsMargins(0, 8, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        row = QHBoxLayout()
        self.preset = QComboBox()
        for sid, st in sb.STYLES.items():
            self.preset.addItem(_(st.name), sid)
        self.preset.setToolTip(_("Estilos prontos: YouTube (caixa escura embaixo), Reels e Shorts (grande, no meio, "
                                 "poucas palavras e a palavra falada em destaque) e Cinema (discreto, com sombra)."))
        self.preset.activated.connect(self._preset_chosen)
        row.addWidget(self.preset, 1)
        self.btn_reset = QPushButton(_("Restaurar"))
        self.btn_reset.setToolTip(_("Volta ao estilo pronto, sem os seus ajustes"))
        self.btn_reset.clicked.connect(self._preset_chosen)
        row.addWidget(self.btn_reset)
        form.addRow(_("Estilo"), row)

        self.family = QComboBox()
        for fam in tr.FAMILIES:
            self.family.addItem(fam.name, fam.id)
            self.family.setItemData(self.family.count() - 1, _(tr.CATEGORIES.get(fam.category, "")),
                                    Qt.ItemDataRole.ToolTipRole)
        self.family.activated.connect(lambda _i: self._text(family=self.family.currentData()))
        form.addRow(_("Fonte"), self.family)
        row = QHBoxLayout()
        self.weight = QComboBox()
        for w, label in WEIGHT_LABELS:
            self.weight.addItem(_(label), w)
        self.weight.activated.connect(lambda _i: self._text(weight=int(self.weight.currentData())))
        row.addWidget(self.weight, 1)
        self.upper = QCheckBox(_("Maiúsculas"))
        self.upper.toggled.connect(lambda on: self._text(uppercase=bool(on)))
        row.addWidget(self.upper)
        form.addRow(_("Peso"), row)
        self.size = self._spin(8, 300, " px", _("Tamanho da letra num quadro de 1080 linhas (em outras resoluções, "
                                                 "na mesma proporção)"))
        self.size.valueChanged.connect(lambda v: self._text(size=float(v)))
        form.addRow(_("Tamanho"), self.size)

        self.color = _Color(_("Cor do texto"))
        self.color.picked.connect(lambda c: self._text(color=from_qcolor(c)))
        form.addRow(_("Cor"), self.color)
        row = QHBoxLayout()
        self.outline = self._spin(0, 30, " px", _("Espessura do contorno (0 = sem contorno)"))
        self.outline.valueChanged.connect(lambda v: self._text(outline=float(v)))
        self.outline_color = _Color(_("Cor do contorno"))
        self.outline_color.picked.connect(lambda c: self._text(outline_color=from_qcolor(c)))
        row.addWidget(self.outline)
        row.addWidget(self.outline_color)
        row.addStretch(1)
        form.addRow(_("Contorno"), row)
        row = QHBoxLayout()
        self.box = self._spin(0, 100, " %", _("Opacidade da caixa atrás do texto (0 = sem caixa)"))
        self.box.valueChanged.connect(lambda v: self._text(box=v / 100.0))
        self.box_color = _Color(_("Cor da caixa"))
        self.box_color.picked.connect(lambda c: self._text(box_color=from_qcolor(c)))
        row.addWidget(self.box)
        row.addWidget(self.box_color)
        row.addStretch(1)
        form.addRow(_("Caixa"), row)
        self.shadow = self._spin(0, 100, " %", _("Opacidade da sombra (0 = sem sombra)"))
        self.shadow.valueChanged.connect(lambda v: self._text(shadow=v / 100.0))
        form.addRow(_("Sombra"), self.shadow)

        row = QHBoxLayout()
        self.position = QComboBox()
        for key in sb.POSITIONS:
            self.position.addItem(_(POSITION_LABELS[key]), key)
        self.position.activated.connect(lambda _i: self._style(position=self.position.currentData()))
        row.addWidget(self.position, 1)
        self.margin = self._spin(-1000, 1000, " px", _("Margem de segurança: distância da borda de baixo (ou de "
                                                       "cima). No meio, quanto desce (negativo: sobe)."))
        self.margin.valueChanged.connect(lambda v: self._style(margin=float(v)))
        row.addWidget(self.margin)
        form.addRow(_("Posição"), row)
        self.width = self._spin(10, 100, " %", _("Largura máxima do texto, em porcentagem da largura do quadro"))
        self.width.valueChanged.connect(lambda v: self._style(width=v / 100.0))
        form.addRow(_("Largura"), self.width)
        self.max_words = self._spin(0, 50, "", _("Quantas palavras aparecem de cada vez (0 = a legenda inteira). "
                                                 "Precisa do tempo de cada palavra (legendas geradas pela fala)."))
        self.max_words.setSpecialValueText(_("Todas"))
        self.max_words.valueChanged.connect(lambda v: self._style(max_words=int(v)))
        form.addRow(_("Palavras por tela"), self.max_words)
        row = QHBoxLayout()
        self.highlight = QCheckBox(_("Destacar a palavra falada"))
        self.highlight.setToolTip(_("Pinta a palavra que está sendo dita (precisa do tempo de cada palavra)"))
        self.highlight.toggled.connect(self._highlight_toggled)
        self.highlight_color = _Color(_("Cor do destaque"))
        self.highlight_color.picked.connect(lambda c: self._set_highlight(color=from_qcolor(c)))
        row.addWidget(self.highlight)
        row.addWidget(self.highlight_color)
        row.addStretch(1)
        form.addRow("", row)

        ctl.changed.connect(self.refresh)
        self.refresh()

    def _spin(self, lo: int, hi: int, suffix: str, tip: str) -> QSpinBox:
        b = QSpinBox()
        b.setRange(lo, hi)
        b.setSuffix(suffix)
        b.setToolTip(tip)
        b.setKeyboardTracking(False)
        return b

    # ------------------------------------------------------------ mostrar
    def refresh(self) -> None:
        st = self.ctl.doc().style
        t = st.text
        self._filling = True
        try:
            self.preset.setCurrentIndex(max(0, self.preset.findData(st.id)))
            self.btn_reset.setEnabled(st != sb.STYLES.get(st.id))
            self.family.setCurrentIndex(max(0, self.family.findData(tr.family(t.family).id)))
            self.weight.setCurrentIndex(min(range(len(WEIGHT_LABELS)), key=lambda i: abs(WEIGHT_LABELS[i][0] - t.weight)))
            self.upper.setChecked(t.uppercase)
            self.size.setValue(int(round(t.size)))
            self.color.set(qcolor(t.color))
            self.outline.setValue(int(round(t.outline)))
            self.outline_color.set(qcolor(t.outline_color))
            self.box.setValue(int(round(t.box * 100)))
            self.box_color.set(qcolor(t.box_color))
            self.shadow.setValue(int(round(t.shadow * 100)))
            self.position.setCurrentIndex(max(0, self.position.findData(st.position)))
            self.margin.setValue(int(round(st.margin)))
            self.width.setValue(int(round(st.width * 100)))
            self.max_words.setValue(st.max_words)
            on = st.highlight is not None and st.highlight.color is not None
            self.highlight.setChecked(on)
            self.highlight_color.setEnabled(on)
            self.highlight_color.set(qcolor(st.highlight.color if on else HIGHLIGHT_COLOR))
        finally:
            self._filling = False

    # ------------------------------------------------------------ mudar
    def _apply(self, style: sb.SubStyle) -> None:
        if self._filling:
            return
        # pelo JSON: o estilo guardado é o mesmo que volta do projeto (cores em #rrggbb, limites conferidos)
        style = sb.SubStyle.from_json(style.to_json())
        if style != self.ctl.doc().style:
            self.ctl.set_options(style=style)

    def _style(self, **kw) -> None:
        if not self._filling:
            self._apply(replace(self.ctl.doc().style, **kw))

    def _text(self, **kw) -> None:
        if not self._filling:
            st = self.ctl.doc().style
            self._apply(replace(st, text=replace(st.text, **kw)))

    def _preset_chosen(self, *_a) -> None:
        if self._filling:
            return
        sid = self.preset.currentData()
        if sid in sb.STYLES and sb.STYLES[sid] != self.ctl.doc().style:
            self.ctl.set_options(style=sb.STYLES[sid])

    def _highlight_toggled(self, on: bool) -> None:
        if self._filling:
            return
        st = self.ctl.doc().style
        if on:
            base = sb.STYLES.get(st.id)
            h = base.highlight if base is not None and base.highlight is not None else \
                tr.WordOverride(color=HIGHLIGHT_COLOR)
            self._apply(replace(st, highlight=h))
        else:
            self._apply(replace(st, highlight=None))

    def _set_highlight(self, **kw) -> None:
        st = self.ctl.doc().style
        h = st.highlight or tr.WordOverride(color=HIGHLIGHT_COLOR)
        self._apply(replace(st, highlight=replace(h, **kw)))
