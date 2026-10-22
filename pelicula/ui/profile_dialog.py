"""Perfil de recursos: o que aparece na janela (Simples, Criador, Cinema ou Tudo).

`ProfileDialog` aparece uma vez, no primeiro acesso, logo depois da escolha do idioma
(`app.choose_profile`). Depois o perfil muda em Configurações › Recursos, que usa os mesmos
cartões (`ProfileCard`). Desligar um recurso só o esconde: a imagem e a exportação não mudam.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from .. import APP_NAME, modules
from ..i18n import _
from . import icons, theme

DEFAULT_PROFILE = "tudo"


def profile_info(profile_id: str) -> tuple[str, str, str, frozenset[str]]:
    """(id, nome, descrição, módulos) do perfil; nome e descrição ainda sem tradução."""
    return next(p for p in modules.PROFILES if p[0] == profile_id)


class ProfileCard(QAbstractButton):
    """Cartão de um perfil: nome, descrição e quantos recursos ele liga. Marcado = escolhido."""

    def __init__(self, profile_id: str, parent=None):
        super().__init__(parent)
        pid, name, desc, ids = profile_info(profile_id)
        self.profile_id = pid
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(180)
        self.setAccessibleName(_(name))
        self._hover = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 13, 14, 12)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel(_(name))
        self.title.setObjectName("PanelTitle")
        head.addWidget(self.title, 1)
        self.mark = QLabel()
        self.mark.setPixmap(icons.icon("check", theme.ACCENT, 18).pixmap(18, 18))
        sp = self.mark.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.mark.setSizePolicy(sp)
        head.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self.desc = QLabel(_(desc))
        self.desc.setObjectName("Muted")
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("font-size: 8.8pt;")
        lay.addWidget(self.desc)
        lay.addStretch(1)
        total = sum(1 for m in modules.MODULES if m.status == modules.ESTAVEL)
        self.count = QLabel(_("{n} de {total} recursos").format(n=len(ids), total=total))
        self.count.setObjectName("Faint")
        lay.addWidget(self.count)
        for lbl in (self.title, self.mark, self.desc, self.count):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(self._sync)
        self._sync()

    def nextCheckState(self) -> None:  # noqa: N802 (Qt)
        """Clicar num cartão marcado não o desmarca (como um botão de opção)."""
        self.setChecked(True)

    def _sync(self, _on: bool = False) -> None:
        on = self.isChecked()
        self.mark.setVisible(on)
        self.title.setStyleSheet(f"font-size: 12pt; color: {theme.ACCENT_HI if on else theme.TEXT};")
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        border = theme.ACCENT if on else (theme.ACCENT_DIM if self._hover else theme.BORDER)
        p.setPen(QPen(QColor(border), 2 if on else 1))
        p.setBrush(QColor(theme.PANEL3 if on else theme.PANEL2))
        p.drawRoundedRect(r, 12, 12)
        p.end()


class ProfileDialog(QDialog):
    """Primeiro acesso: escolha do perfil de recursos. `selected` guarda o id escolhido."""

    def __init__(self, parent=None, current: str = DEFAULT_PROFILE):
        super().__init__(parent)
        ids = [p[0] for p in modules.PROFILES]
        self.selected = current if current in ids else DEFAULT_PROFILE
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(48, 48))
        top.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        title = QLabel(_("Como você vai usar o PeliculaConverter?"))
        title.setObjectName("PanelTitle")
        title.setStyleSheet("font-size: 16pt;")
        tl.addWidget(title)
        sub = QLabel(_("Escolha o que aparece na janela. Dá para mudar quando quiser em Configurações › Recursos."))
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        tl.addWidget(sub)
        top.addLayout(tl, 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.cards: dict[str, ProfileCard] = {}
        for pid in ids:
            card = ProfileCard(pid)
            card.setMinimumHeight(132)
            card.clicked.connect(lambda _c=False, p=pid: self.pick(p))
            row.addWidget(card)
            self.cards[pid] = card
        lay.addLayout(row)
        note = QLabel(_("Recursos desligados só ficam escondidos: nada muda na imagem nem na exportação."))
        note.setObjectName("Faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        bl = QHBoxLayout()
        bl.addStretch(1)
        self.ok = QPushButton(_("Continuar"))
        self.ok.setObjectName("Primary")
        self.ok.setMinimumWidth(140)
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        bl.addWidget(self.ok)
        lay.addLayout(bl)
        self.pick(self.selected)

    def pick(self, profile_id: str) -> None:
        self.selected = profile_id
        for pid, card in self.cards.items():
            card.setChecked(pid == profile_id)
