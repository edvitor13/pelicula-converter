"""Filtro de ajustes: o campo "Filtrar ajustes…" no alto do painel de ajustes (Película) e do inspetor (Edição).

A busca em si é de `busca_ajustes.py` (sem Qt, em qualquer idioma). Aqui o campo mostra o resultado nos
cartões (`SectionCard.set_filter`): os cartões sem relação somem, os que ficam abrem e destacam os controles que
bateram, e os avançados escondidos aparecem se foram eles. Apagar o texto devolve tudo como estava (cartões
abertos, avançados escondidos, faixa de cor e posição da rolagem). O filtro só muda a interface: não altera
valores, não vai para o projeto e não é lembrado entre sessões.

Cartão de módulo desligado continua escondido; se a busca só bate neles, a mensagem diz em qual módulo estão.

Ligação nos painéis (uma linha em cada): `filtro_ajustes.install(layout, painel, [cartões...])`.
Atalhos: Ctrl+F com o foco no painel e `/` fora de campos de texto (`focus_current`, chamado pela janela).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QScrollArea,
                               QTextEdit, QVBoxLayout, QWidget)

from .. import busca_ajustes, modules
from ..i18n import _
from .module_notice import module_names


class _Campo(QLineEdit):
    """O campo de texto: Esc apaga o filtro (e, com ele já vazio, devolve o foco)."""

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.text():
                self.clear()
            else:
                self.clearFocus()
            e.accept()
            return
        super().keyPressEvent(e)


class _Painel:
    """Os cartões de uma página (todos da mesma lista de seções) e o estado de antes do filtro."""

    def __init__(self, cards: list):
        self.cards = cards
        self.sections = [c.section for c in cards]
        self.natural: dict = {}
        self.scroll_value = 0
        inner = cards[0].parentWidget() if cards else None
        view = inner.parentWidget() if inner is not None else None
        scroll = view.parentWidget() if view is not None else None
        self.scroll: QScrollArea | None = scroll if isinstance(scroll, QScrollArea) else None
        self.label = QLabel()
        self.label.setObjectName("Muted")
        self.label.setWordWrap(True)
        self.label.setVisible(False)
        if inner is not None and inner.layout() is not None:
            inner.layout().insertWidget(0, self.label)


class FiltroAjustes(QWidget):
    """Campo + resultado nos cartões de uma ou mais páginas de ajustes."""

    def __init__(self, panels: list[list], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.field = _Campo()
        self.field.setObjectName("FiltroAjustes")
        self.field.setPlaceholderText(_("Filtrar ajustes…"))
        self.field.setToolTip(_("Procura nos ajustes, em qualquer idioma e sem diferença de acentos "
                                "(Ctrl+F ou /; Esc limpa)"))
        self.field.setClearButtonEnabled(True)
        self.field.textChanged.connect(self._changed)
        lay.addWidget(self.field)
        self.panels = [_Painel(cards) for cards in panels]
        self._active = False

    # ------------------------------------------------------------ uso
    def text(self) -> str:
        return self.field.text()

    def set_text(self, text: str) -> None:
        self.field.setText(text)

    def focus_field(self) -> bool:
        if not self.isVisible():
            return False
        self.field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.field.selectAll()
        return True

    def reapply(self) -> None:
        """Refaz o resultado (módulos ligados ou desligados mudam a visibilidade dos cartões)."""
        if self._active:
            self._apply()

    # ------------------------------------------------------------ módulos
    def _blocked(self) -> dict:
        """widget → módulo das ferramentas de módulos desligados na janela; vazio fora da janela principal."""
        win = self.window()
        tools = getattr(win, "_module_tools", None)
        settings = getattr(win, "settings", None)
        if tools is None or settings is None:
            return {}
        on = modules.enabled_ids(settings)
        out = {}
        for module_id, items in tools().items():
            if module_id not in on:
                for it in items:
                    out[it] = module_id
        lights = getattr(win, "lights_card", None)  # cartão "Luz da copiadora" do inspetor: módulo do Laboratório
        if lights is not None and "laboratorio" not in on:
            out[lights] = "laboratorio"
        return out

    # ------------------------------------------------------------ resultado
    def _changed(self, _text: str) -> None:
        self._apply()

    def _apply(self) -> None:
        query = self.field.text()
        if not query.strip():
            self._clear()
            return
        blocked = self._blocked()
        if not self._active:
            self._active = True
            for p in self.panels:
                p.natural = {c: c.isVisibleTo(c.parentWidget()) or c in blocked for c in p.cards}
                p.scroll_value = p.scroll.verticalScrollBar().value() if p.scroll is not None else 0
        for p in self.panels:
            self._apply_panel(p, query, blocked)

    def _apply_panel(self, p: _Painel, query: str, blocked: dict) -> None:
        found = busca_ajustes.search(query, p.sections)
        shown = 0
        off_modules: set[str] = set()
        for card in p.cards:
            m = found.get(card.section.key)
            gone = {r.param.key: blocked[r] for r in card.rows if r in blocked}
            if m is None or not p.natural.get(card, True):
                card.setVisible(False)
                card.set_filter(None)
                continue
            if card in blocked:
                off_modules.add(blocked[card])
                card.setVisible(False)
                card.set_filter(None)
                continue
            keys = set(m.keys) - set(gone)
            if not m.section and m.keys and not keys:  # só bateu em controles de módulo desligado
                off_modules |= {gone[k] for k in m.keys if k in gone}
                card.setVisible(False)
                card.set_filter(None)
                continue
            card.setVisible(True)
            card.set_filter(keys)
            shown += 1
        if shown:
            p.label.setVisible(False)
            return
        if off_modules:
            p.label.setText(_("Está no módulo {nome}: ligue em Configurações › Recursos").format(
                nome=module_names(off_modules)))
        else:
            p.label.setText(_("Nenhum ajuste encontrado"))
        p.label.setVisible(True)

    def _clear(self) -> None:
        if not self._active:
            return
        self._active = False
        blocked = self._blocked()
        for p in self.panels:
            p.label.setVisible(False)
            for card in p.cards:
                card.set_filter(None)
                card.setVisible(p.natural.get(card, True) and card not in blocked)
            if p.scroll is not None:
                bar = p.scroll.verticalScrollBar()
                bar.setValue(p.scroll_value)
                QTimer.singleShot(0, lambda b=bar, v=p.scroll_value: b.setValue(v))  # depois de o layout assentar


def install(layout: QVBoxLayout, scope: QWidget, panels: list[list], index: int | None = None) -> FiltroAjustes:
    """Põe o campo no `layout` (na posição `index`, ou no fim) e liga Ctrl+F ao `scope` (o painel inteiro).

    `panels` = uma lista de `SectionCard` por página de ajustes (o look; o inspetor tem a de imagem e a de som)."""
    filtro = FiltroAjustes(panels, scope)
    if index is None:
        layout.addWidget(filtro)
    else:
        layout.insertWidget(index, filtro)
    sc = QShortcut(QKeySequence("Ctrl+F"), scope)
    sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    sc.activated.connect(filtro.focus_field)
    filtro.shortcut = sc
    return filtro


_TEXT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


def typing_in_text(widget) -> bool:
    """O foco está num campo onde a pessoa digita (a tecla `/` é dela)."""
    if isinstance(widget, QComboBox):
        return widget.isEditable()
    return isinstance(widget, _TEXT_WIDGETS)


def focus_current(win, focus_widget=None) -> bool:
    """Tecla `/`: leva o foco ao filtro do painel do modo atual, se a tecla não for de um campo de texto."""
    if typing_in_text(focus_widget):
        return False
    filtro = win.inspector.filtro if win.mode == "edicao" else getattr(win, "look_filter", None)
    return filtro is not None and filtro.focus_field()


__all__ = ["FiltroAjustes", "install", "focus_current", "typing_in_text"]
