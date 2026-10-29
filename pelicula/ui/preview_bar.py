"""Botões da prévia da 1.6 (módulo "scopes"): zebra, falsa cor e quadro de referência, nos dois modos.

Zebra e falsa cor são camadas de `preview_tools.PreviewTools` (a exposição de `exposure.py`, medida na luz da cena
que o look decodifica); a referência é um quadro fixado ou uma imagem que o `Viewer` mostra no lugar do original
na comparação (Dividido ou Lado a lado). Tudo só na tela: a receita do quadro e a exportação não mudam.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QActionGroup, QImage
from PySide6.QtWidgets import QFileDialog, QMenu, QToolButton, QWidget

from .. import exposure
from ..i18n import _, decimal_sep


def _stops_text(x: float) -> str:
    return (f"{x:+g}").replace(".", decimal_sep())


class PreviewBar:
    """Os botões na barra da prévia e as duas camadas (falsa cor por baixo, zebra por cima)."""

    def __init__(self, win, tools):
        self.win = win
        self.tools = tools
        self.zebra_level = exposure.ZEBRA_DEFAULT
        self._build()
        tools.add("falsa_cor", self.false_color_layer)
        tools.add("zebra", self.zebra_layer)

    def _build(self) -> None:
        win = self.win
        self.btn_false = win._flat("meter", self._false_tip(), _("Falsa cor"), checkable=True)
        self.btn_false.toggled.connect(lambda _on: self.tools.refresh())
        self.btn_zebra = win._flat("zebra", "", _("Zebra"), checkable=True)
        self.btn_zebra.toggled.connect(lambda _on: self.tools.refresh())
        menu = QMenu(self.btn_zebra)
        group = QActionGroup(menu)
        self.zebra_actions: dict[float, QAction] = {}
        for level in exposure.ZEBRA_LEVELS:
            a = menu.addAction(_("A partir de {n} stops").format(n=_stops_text(level)))
            a.setCheckable(True)
            a.setChecked(level == self.zebra_level)
            a.triggered.connect(lambda _c=False, lv=level: self.set_zebra_level(lv))
            group.addAction(a)
            self.zebra_actions[level] = a
        self.btn_zebra.setMenu(menu)
        self.btn_zebra.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._sync_zebra_tip()
        self.btn_ref = win._flat("reference", _("Comparar com um quadro de referência: fixe o quadro atual ou abra "
                                                "uma imagem; Dividido ou Lado a lado mostram a referência no lugar "
                                                "do original"), _("Referência"))
        self.btn_ref.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        rm = QMenu(self.btn_ref)
        rm.addAction(_("Fixar este quadro"), self.pin_frame)
        rm.addAction(_("Abrir imagem…"), lambda: self.open_image())
        rm.addSeparator()
        self.act_compare = rm.addAction(_("Comparar com a referência"))
        self.act_compare.setCheckable(True)
        self.act_compare.toggled.connect(self.set_compare)
        self.act_clear = rm.addAction(_("Tirar a referência"), self.clear_reference)
        rm.aboutToShow.connect(self._sync_ref_menu)
        self.btn_ref.setMenu(rm)
        bar = win.findChild(QWidget, "ViewerBar")
        if bar is not None and bar.layout() is not None:
            for b in self.buttons():
                bar.layout().addWidget(b)

    def buttons(self) -> list:
        return [self.btn_false, self.btn_zebra, self.btn_ref]

    @staticmethod
    def _false_tip() -> str:
        names = "; ".join(_(name) for _lo, _hi, _c, name in exposure.BANDS)
        return _("Falsa cor em stops em relação ao cinza de 18% da luz da cena (só na tela): {faixas}; o resto em "
                 "cinza").format(faixas=names)

    def _sync_zebra_tip(self) -> None:
        self.btn_zebra.setToolTip(_("Zebra: listras onde a exposição passa de {n} stops acima do cinza de 18% (só "
                                    "na tela). A setinha escolhe o limite.").format(n=_stops_text(self.zebra_level)))

    def set_zebra_level(self, level: float) -> None:
        self.zebra_level = float(level)
        if level in self.zebra_actions:
            self.zebra_actions[level].setChecked(True)
        self._sync_zebra_tip()
        if not self.btn_zebra.isChecked():
            self.btn_zebra.setChecked(True)  # escolher o limite liga a zebra (e redesenha)
        else:
            self.tools.refresh()

    # ------------------------------------------------------------ camadas
    def false_color_layer(self, ctx):
        if not self.btn_false.isChecked() or self.btn_false.isHidden():
            return None
        light = ctx.light()
        return exposure.false_color(exposure.stops(light[..., :3]), light[..., 3])

    def zebra_layer(self, ctx):
        if not self.btn_zebra.isChecked() or self.btn_zebra.isHidden():
            return None
        light = ctx.light()
        return exposure.zebra(exposure.stops(light[..., :3]), self.zebra_level, light[..., 3])

    # ------------------------------------------------------------ referência
    def _sync_ref_menu(self) -> None:
        has = self.win.viewer.reference is not None
        self.act_compare.setEnabled(has)
        self.act_clear.setEnabled(has)
        self.act_compare.blockSignals(True)
        self.act_compare.setChecked(self.win.viewer.compare_reference)
        self.act_compare.blockSignals(False)

    def set_reference(self, img: QImage | None) -> None:
        viewer = self.win.viewer
        viewer.set_reference(img)
        self.set_compare(img is not None)

    def set_compare(self, on: bool) -> None:
        win = self.win
        win.viewer.set_compare_reference(on)
        if win.viewer.compare_reference and win.viewer.mode in ("proc", "orig"):
            win.compare.set_current("split")
            win.viewer.set_mode("split")  # sem gravar a preferência da comparação

    def pin_frame(self) -> bool:
        img = self.win.viewer.proc
        if img is None or img.isNull():
            self.win.statusBar().showMessage(_("Abra um vídeo para fixar um quadro."), 5000)
            return False
        self.set_reference(img.copy())
        self.win.statusBar().showMessage(_("Quadro fixado como referência: compare em Dividido ou Lado a lado."),
                                         5000)
        return True

    def open_image(self, path: str | None = None) -> bool:
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self.win, _("Imagem de referência"), "",
                                                   _("Imagens") + " (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
            if not path:
                return False
        img = QImage(path)
        if img.isNull():
            self.win.statusBar().showMessage(_("Não foi possível abrir a imagem."), 6000)
            return False
        self.set_reference(img.convertToFormat(QImage.Format.Format_RGB32))
        return True

    def clear_reference(self) -> None:
        self.win.viewer.set_reference(None)

    def apply_module(self, on: bool) -> None:
        """Módulo "scopes" desligado: os botões somem, as camadas param e a referência sai da comparação."""
        for b in self.buttons():
            b.setVisible(on)
        if not on:
            for b in (self.btn_false, self.btn_zebra):
                if b.isChecked():
                    b.setChecked(False)
            if self.win.viewer.compare_reference:
                self.win.viewer.set_compare_reference(False)
