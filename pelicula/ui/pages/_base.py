"""Peças comuns das páginas de Configurações: cabeçalho e rolagem."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget


class PageBase(QWidget):
    """Página com título, subtítulo e um corpo rolável (`self.body`, um QVBoxLayout)."""

    def __init__(self, dialog, title: str, subtitle: str = ""):
        super().__init__()
        self.dialog = dialog
        self.settings = dialog.settings
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        head = QLabel(title)
        head.setObjectName("PanelTitle")
        outer.addWidget(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            outer.addWidget(sub)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 8, 6, 8)
        self.body.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

    def finish(self) -> None:
        """Empurra o conteúdo para cima (chame no fim do construtor)."""
        self.body.addStretch(1)

    def kicker(self, text: str) -> QLabel:
        k = QLabel(text.upper())
        k.setObjectName("Kicker")
        self.body.addWidget(k)
        return k
