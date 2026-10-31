"""Geometria do clipe e da sequência na janela (1.7, ARQUITETURA §37): o que o cartão "Enquadrar e posicionar" tem além
das linhas do esquema, e a janela útil na área segura da prévia.

- A linha "Taxa manual" só aparece com o desespremer em "Taxa manual".
- O aviso quando o clipe é desespremido e a Lente anamórfica do look também está comprimindo: os dois valem (nada é
  bloqueado) e a pessoa fica sabendo. O aviso é só da tela: quem desenha é `compositor.fit_box` e `anamorfico.py`.
- A área segura das plataformas fica dentro da janela útil (`sync_safe_window`, só na tela).

Três ganchos pequenos: `ClipInspector` cria o `InspectorGeometry`, a janela chama `install` para ele enxergar o look
e `MainWindow._refresh_source` chama `sync_safe_window`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QLabel

from .. import anamorfico, compositor
from ..i18n import _, fmt_decimal


class InspectorGeometry:
    """Liga as linhas do desespremer do cartão "Enquadrar e posicionar" ao clipe e ao look."""

    def __init__(self, store, cards, look_values: Callable[[], dict | None] = lambda: None):
        self.store = store
        self.look_values = look_values
        self.card = next((c for c in cards if c.section.key == "transformar"), None)
        self.rows = {r.param.key: r for r in self.card.rows} if self.card is not None else {}
        self.warning = QLabel()
        self.warning.setObjectName("Muted")
        self.warning.setWordWrap(True)
        self.warning.hide()
        row = self.rows.get("desespremer_taxa")
        if row is not None:
            body = self.card.body.layout()
            body.insertWidget(body.indexOf(row) + 1, self.warning)
        store.changed.connect(self._changed)
        self.update()

    def _changed(self, key: str) -> None:
        if key in ("*", "desespremer", "desespremer_taxa"):
            self.update()

    def warning_text(self) -> str:
        """O aviso do clipe no store: "" sem desespremer no clipe ou sem compressão na lente do look."""
        look = anamorfico.squeeze(self.look_values() or {})
        if compositor.desqueeze(self.store.values) <= 1.0 or look <= 1.0:
            return ""
        return _("A Lente anamórfica do look também está desespremendo ({taxa}×). As duas compressões valem neste "
                 "clipe: a imagem pode sair larga demais.").format(taxa=fmt_decimal(look, 2))

    def update(self) -> None:
        row = self.rows.get("desespremer_taxa")
        if row is not None:
            row.setVisible(self.store.get("desespremer") == "manual")
        text = self.warning_text()
        self.warning.setText(text)
        self.warning.setVisible(bool(text))


def safe_window(seq) -> tuple[float, float, float, float] | None:
    """A janela útil da sequência em frações do quadro; None sem sequência ou sem janela."""
    if seq is None or not seq.window:
        return None
    x, y, w, h = seq.window_rect(seq.width, seq.height)
    return x / seq.width, y / seq.height, w / seq.width, h / seq.height


def sync_safe_window(win) -> None:
    """A prévia mostra a montagem (`src_seq`): a área segura segue a janela útil dela."""
    win.viewer.set_safe_window(safe_window(win.src_seq))


def install(win) -> None:
    """A janela mostra o look ao inspetor: o aviso acompanha a Lente anamórfica."""
    geo = getattr(getattr(win, "inspector", None), "geometry", None)
    if geo is None:
        return
    geo.look_values = lambda: win.store.values
    win.store.changed.connect(lambda _k: geo.update())
    geo.update()
