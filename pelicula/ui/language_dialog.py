"""Escolha do idioma (primeiro acesso ou Configurações > Idioma)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import i18n
from . import icons, theme

# Textos desta janela nos três idiomas (ela aparece antes de existir um idioma escolhido).
TEXTS = {
    "pt_BR": ("Escolha o idioma", "Você pode trocar depois em Configurações > Idioma.", "Continuar"),
    "en": ("Choose your language", "You can change it later in Settings > Language.", "Continue"),
    "es": ("Elige tu idioma", "Puedes cambiarlo después en Configuración > Idioma.", "Continuar"),
}
CAPTIONS = {"pt_BR": "Brasil", "en": "English (US)", "es": "Español (Latinoamérica y España)"}


class LangCard(QAbstractButton):
    def __init__(self, code: str, parent=None):
        super().__init__(parent)
        self.code = code
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(QSize(200, 92))
        self._hover = False

    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(QPen(QColor(theme.ACCENT if on else (theme.ACCENT_DIM if self._hover else theme.BORDER)), 2 if on else 1))
        p.setBrush(QColor(theme.PANEL3 if on else theme.PANEL2))
        p.drawRoundedRect(r, 12, 12)
        p.setPen(QColor(theme.ACCENT_HI if on else theme.TEXT))
        p.setFont(theme.font(13, theme.QFont.Weight.DemiBold, title=True))
        p.drawText(r.adjusted(16, 14, -40, -36), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   i18n.LANGUAGES[self.code])
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(8.5))
        p.drawText(r.adjusted(16, 48, -12, -10), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                   CAPTIONS[self.code])
        if on:
            p.drawPixmap(int(r.right()) - 30, int(r.top()) + 12, icons.icon("check", theme.ACCENT, 18).pixmap(18, 18))
        p.end()


class LanguageDialog(QDialog):
    def __init__(self, parent=None, current: str | None = None):
        super().__init__(parent)
        self.selected = current or i18n.system_language()
        self.setWindowTitle("PeliculaConverter")
        self.setWindowIcon(icons.app_icon())
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(14)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.app_icon().pixmap(48, 48))
        top.addWidget(logo)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("PanelTitle")
        self.title.setStyleSheet("font-size: 16pt;")
        tl.addWidget(self.title)
        self.sub = QLabel()
        self.sub.setObjectName("Muted")
        tl.addWidget(self.sub)
        top.addLayout(tl, 1)
        lay.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.group = QButtonGroup(self)
        self.cards = {}
        for code in i18n.LANGUAGES:
            card = LangCard(code)
            self.group.addButton(card)
            row.addWidget(card)
            self.cards[code] = card
            card.clicked.connect(lambda _=False, c=code: self._pick(c))
        lay.addLayout(row)
        bl = QHBoxLayout()
        bl.addStretch(1)
        self.ok = QPushButton()
        self.ok.setObjectName("Primary")
        self.ok.setMinimumWidth(140)
        self.ok.clicked.connect(self.accept)
        bl.addWidget(self.ok)
        lay.addLayout(bl)
        self._pick(self.selected if self.selected in self.cards else "en")

    def _pick(self, code: str) -> None:
        self.selected = code
        self.cards[code].setChecked(True)
        title, sub, ok = TEXTS[code]
        self.title.setText(title)
        self.sub.setText(sub)
        self.ok.setText(ok)
        for c in self.cards.values():
            c.update()
