"""Configurações › Recursos: escolher um perfil e ligar ou desligar cada módulo.

Desligar um módulo só esconde a ferramenta na janela (veja `modules.py`): projetos e presets que
o usam continuam saindo iguais. Toda mudança é gravada com `modules.set_enabled`/`apply_profile`
e avisada com `dialog.settings_changed.emit("modulos")`; a janela principal reage em
`MainWindow.apply_modules()`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ... import modules
from ...i18n import _
from .. import theme
from ..profile_dialog import ProfileCard
from ..widgets import ToggleSwitch
from ._base import PageBase

# Cor do selo de cada estado: (texto, borda).
_BADGE_COLORS = {
    modules.ESTAVEL: (theme.OK, "#2f5a41"),
    modules.BETA: (theme.ACCENT, theme.ACCENT_DIM),
    modules.EXPERIMENTAL: (theme.DANGER, "#6e2d29"),
}


class StatusBadge(QLabel):
    """Selo "Estável", "Beta" ou "Experimental"."""

    def __init__(self, status: str, parent=None):
        super().__init__(_(modules.STATUS_LABELS[status]), parent)
        self.status = status
        fg, border = _BADGE_COLORS[status]
        self.setStyleSheet(f"color: {fg}; border: 1px solid {border}; border-radius: 8px; padding: 0px 7px;"
                           f" font-size: 7.8pt; font-weight: 600;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class ModuleRow(QFrame):
    """Um módulo: nome, selo de estado, descrição e a chave liga/desliga (clicar na linha também troca)."""

    def __init__(self, module: modules.Module, parent=None):
        super().__init__(parent)
        self.module = module
        self.setObjectName("ModuleRow")
        self.setStyleSheet(f"QFrame#ModuleRow {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
                           f" border-radius: 10px; }}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.name = QLabel(_(module.name))
        head.addWidget(self.name)
        self.badge = StatusBadge(module.status)
        head.addWidget(self.badge)
        head.addStretch(1)
        text.addLayout(head)
        self.desc = QLabel(_(module.description))
        self.desc.setObjectName("Muted")
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("font-size: 8.8pt;")
        text.addWidget(self.desc)
        lay.addLayout(text, 1)
        self.switch = ToggleSwitch()
        self.switch.setToolTip(_("Ligar ou desligar este recurso"))
        self.switch.setAccessibleName(_(module.name))
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        self.switch.toggled.connect(self._paint_state)
        self._paint_state(self.switch.isChecked())

    def set_on(self, on: bool) -> None:
        """Mostra o estado gravado sem avisar ninguém."""
        self.switch.blockSignals(True)
        self.switch.setChecked(bool(on))
        self.switch.blockSignals(False)
        self.switch.update()
        self._paint_state(bool(on))

    def _paint_state(self, on: bool) -> None:
        self.name.setStyleSheet(f"font-weight: 600; color: {theme.TEXT if on else theme.MUTED};")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.switch.toggle()
            e.accept()
            return
        super().mousePressEvent(e)


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Recursos"),
                         _("Ligue só o que você usa. Desligar um recurso só esconde a ferramenta: projetos e presets "
                           "que o usam continuam saindo iguais."))
        self.kicker(_("Perfil"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards: dict[str, ProfileCard] = {}
        for i, (pid, *_rest) in enumerate(modules.PROFILES):
            card = ProfileCard(pid)
            card.setMinimumHeight(112)
            card.clicked.connect(lambda _c=False, p=pid: self.choose_profile(p))
            grid.addWidget(card, i // 2, i % 2)
            self.cards[pid] = card
        self.body.addLayout(grid)
        self.custom = QLabel(_("Personalizado: você escolheu os recursos um a um. "
                               "Clique num perfil para voltar a ele."))
        self.custom.setObjectName("Muted")
        self.custom.setWordWrap(True)
        self.body.addWidget(self.custom)

        self.rows: dict[str, ModuleRow] = {}
        self.group_heads: dict[str, QLabel] = {}
        for gid, gname in modules.GROUPS:
            items = [m for m in modules.MODULES if m.group == gid]
            if not items:
                continue
            self.body.addSpacing(4)
            self.group_heads[gid] = self.kicker(_(gname))
            for m in items:
                row = ModuleRow(m)
                row.switch.toggled.connect(lambda on, mid=m.id: self.set_module(mid, on))
                self.body.addWidget(row)
                self.rows[m.id] = row

        self.body.addSpacing(6)
        self.chk_tests = QCheckBox(_("Mostrar recursos em teste (Beta e Experimental)"))
        self.chk_tests.setToolTip(_("Recursos em teste começam desligados e podem mudar numa versão futura."))
        self.chk_tests.setChecked(modules.show_tests(self.settings))
        self.chk_tests.toggled.connect(self._set_show_tests)
        self.body.addWidget(self.chk_tests)
        self.no_tests = QLabel(_("Nenhum recurso em teste nesta versão."))
        self.no_tests.setObjectName("Faint")
        self.body.addWidget(self.no_tests)
        self.finish()
        self.refresh()

    # ------------------------------------------------------------ estado
    def refresh(self) -> None:
        """Cartões, chaves e lista conforme o que está gravado (sem emitir sinais)."""
        current = modules.current_profile(self.settings)
        for pid, card in self.cards.items():
            card.setChecked(pid == current)
        self.custom.setVisible(current is None)
        shown = {m.id for m in modules.visible(self.settings)}
        for mid, row in self.rows.items():
            row.set_on(modules.is_enabled(self.settings, mid))
            row.setVisible(mid in shown)
        for gid, head in self.group_heads.items():
            head.setVisible(any(m.id in shown for m in modules.MODULES if m.group == gid))
        tests = modules.show_tests(self.settings)
        self.no_tests.setVisible(tests and all(m.status == modules.ESTAVEL for m in modules.MODULES))

    def _changed(self) -> None:
        self.refresh()
        self.dialog.settings_changed.emit("modulos")

    # ------------------------------------------------------------ ações
    def choose_profile(self, profile_id: str) -> None:
        modules.apply_profile(self.settings, profile_id)
        self._changed()

    def set_module(self, module_id: str, on: bool) -> None:
        modules.set_enabled(self.settings, module_id, bool(on))
        self._changed()

    def _set_show_tests(self, on: bool) -> None:
        self.settings.setValue(modules.KEY_SHOW_TESTS, "1" if on else "0")
        self._changed()
