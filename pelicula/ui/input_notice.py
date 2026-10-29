"""Aviso discreto da janela (1.6): os metadados do arquivo aberto indicam outro perfil de entrada para o look.

`media.suggest_input` dá o perfil; a faixa só sugere ("Usar este perfil" troca o Perfil do vídeo, com desfazer) e
some ao fechar, ao abrir outro arquivo ou projeto e quando o perfil do look já é o sugerido. Nunca muda o look
sozinha, e um projeto reaberto não mostra a faixa.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton

from .. import params
from ..i18n import _
from . import icons, theme


def profile_name(prof: str) -> str:
    """Nome traduzido de um perfil de entrada (`params.ENTRADAS`)."""
    return _(dict(params.PARAMS["entrada"].choices).get(prof, prof))


class InputNotice(QFrame):
    """Faixa abaixo da barra do topo. `offer(None)` esconde; "Usar este perfil" emite o perfil sugerido."""

    accepted = Signal(str)  # trocar o Perfil do vídeo do look por este

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InputNotice")
        self.setStyleSheet(f"QFrame#InputNotice {{ background: {theme.PANEL2}; border: none;"
                           f" border-bottom: 1px solid {theme.BORDER}; }}")
        self.profile: str | None = None
        self._suppressed = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 5, 10, 5)
        lay.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.icon("camera", theme.ACCENT, 16).pixmap(16, 16))
        lay.addWidget(icon)
        self.text = QLabel()
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.btn_use = QPushButton(_("Usar este perfil"))
        self.btn_use.setToolTip(_("Troca o Perfil do vídeo do look (Película › Entrada e exposição); dá para "
                                  "desfazer com Ctrl+Z"))
        self.btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_use.setStyleSheet("QPushButton { padding: 3px 14px; }")
        self.btn_use.clicked.connect(self._accept)
        lay.addWidget(self.btn_use)
        self.btn_close = QToolButton()
        self.btn_close.setObjectName("Flat")
        self.btn_close.setIcon(icons.icon("close", theme.MUTED, 14))
        self.btn_close.setIconSize(QSize(14, 14))
        self.btn_close.setToolTip(_("Manter o perfil atual"))
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(lambda: self.offer(None))
        lay.addWidget(self.btn_close)
        self.setVisible(False)

    def offer(self, prof: str | None, current: str = "") -> None:
        """Sugere `prof` (o perfil do look agora é `current`); None esconde."""
        self.profile = prof or None
        if self.profile is not None:
            main = _("Pelos metadados, este arquivo parece gravado em {perfil}.").format(
                perfil=f"<b>{html.escape(profile_name(self.profile))}</b>")
            detail = _("O look continua em {atual} até você escolher.").format(
                atual=html.escape(profile_name(current or "rec709")))
            self.text.setText(f"{main} <span style='color:{theme.MUTED}'>{detail}</span>")
        self._sync_visible()

    def sync(self, current: str) -> None:
        """O perfil do look mudou: a faixa some se ele já é o sugerido."""
        if self.profile is not None and current == self.profile:
            self.offer(None)

    def set_suppressed(self, on: bool) -> None:
        """Esconde a faixa sem esquecer a sugestão (prévia em tela cheia)."""
        self._suppressed = bool(on)
        self._sync_visible()

    def _sync_visible(self) -> None:
        self.setVisible(self.profile is not None and not self._suppressed)

    def _accept(self) -> None:
        prof = self.profile
        self.offer(None)
        if prof:
            self.accepted.emit(prof)
