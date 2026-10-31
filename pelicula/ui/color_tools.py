"""Cor simples no inspetor do modo Edição (1.6, módulo "cor_simples"): a barra de ferramentas da cor do clipe.

- **Neutro** (conta-gotas do balanço): um clique num neutro da prévia acerta a temperatura e a tonalidade do clipe
  (`colorsimple.white_balance_from`, com a cor do arquivo no ponto: `colorsimple.clip_point` + `sample`).
- **Cor** (conta-gotas): o matiz clicado vira o centro da "Cor escolhida" e o HSL mostra a faixa mais perto.
- **Igualar**: a outro clipe (o quadro do meio dele, com os ajustes dele somados) ou a uma imagem, protegendo a
  pele (`colorsimple.match_adjust`).
- **Grupo**: agrupar os clipes selecionados (a cor muda junto, `TimelineModel.set_clip_values`), selecionar o
  grupo e tirar do grupo.
- O "Automático" analisa o clipe inteiro (`auto_whole_clip`); o menu dele tem "Só o quadro atual".

Tudo vira ajuste comum do clipe, um passo do desfazer. Desligar o módulo só esconde a barra e os cartões.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from .. import colorsimple, media, timeline
from ..i18n import _
from . import icons, sem_efeitos_ui, theme
from .flow import flow_widget

NEW_CARDS = ("pele", "alvo", "degrade")
GRAB_W = 480


def _array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return buf[:, :w * 3].reshape(h, w, 3).copy()


class ColorTools:
    """A barra "Cor simples" do inspetor e o "Automático" do clipe inteiro."""

    def __init__(self, win):
        self.win = win
        self.insp = win.inspector
        self.model = win.model
        self._picking = ""
        self.protect_skin = True
        self._build()
        win.viewer.picked.connect(self._picked)
        win.viewer.pickCanceled.connect(self._pick_done)
        self.model.selectionChanged.connect(self.refresh)
        self.model.changed.connect(lambda _k: self.refresh())
        self.refresh()

    # ------------------------------------------------------------ barra
    def _button(self, text: str, icon: str, tip: str, checkable: bool = False) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        if icon:
            b.setIcon(icons.icon(icon, theme.ACCENT_HI, 14))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _build(self) -> None:
        self.bar = QWidget()
        self.bar.setObjectName("ColorTools")
        vl = QVBoxLayout(self.bar)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(4)
        lab = QLabel(_("Cor simples"))
        lab.setObjectName("Muted")
        vl.addWidget(lab)
        self.btn_wb = self._button(_("Neutro"), "eyedropper",
                                   _("Conta-gotas do balanço: clique em algo que deveria ser branco ou cinza na prévia "
                                     "(Esc cancela)"), True)
        self.btn_wb.toggled.connect(lambda on: self._toggle("wb", on))
        self.btn_color = self._button(_("Cor"), "eyedropper",
                                      _("Clique numa cor da prévia para mudar só ela (Cor escolhida; Esc cancela)"),
                                      True)
        self.btn_color.toggled.connect(lambda on: self._toggle("cor", on))
        self.btn_match = self._button(_("Igualar"), "",
                                      _("Deixa a cor e a luz deste clipe parecidas com as de outro clipe ou de uma "
                                        "imagem"))
        self.btn_match.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.match_menu = QMenu(self.btn_match)
        self.clips_menu = self.match_menu.addMenu(_("A outro clipe"))
        self.clips_menu.aboutToShow.connect(self._fill_clips)
        self.match_menu.addAction(_("A uma imagem…"), self.match_image)
        self.match_menu.addSeparator()
        self.act_protect = QAction(_("Proteger a pele"), self.match_menu)
        self.act_protect.setCheckable(True)
        self.act_protect.setChecked(True)
        self.act_protect.setToolTip(_("A pele fica fora das contas e liga a \"Pele natural\" do clipe"))
        self.act_protect.toggled.connect(lambda on: setattr(self, "protect_skin", bool(on)))
        self.match_menu.addAction(self.act_protect)
        self.btn_match.setMenu(self.match_menu)
        self.tips = {b: b.toolTip() for b in (self.btn_wb, self.btn_color, self.btn_match)}
        self.btn_group = self._button(_("Grupo"), "link", _("Clipes do mesmo grupo mudam a cor juntos"))
        self.btn_group.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        gm = QMenu(self.btn_group)
        self.act_group = gm.addAction(_("Agrupar os selecionados"), self.group_selected)
        self.act_select_group = gm.addAction(_("Selecionar o grupo"), self.select_group)
        self.act_ungroup = gm.addAction(_("Tirar do grupo"), self.ungroup)
        gm.aboutToShow.connect(self._sync_group_menu)
        self.btn_group.setMenu(gm)
        vl.addWidget(flow_widget([self.btn_wb, self.btn_color, self.btn_match, self.btn_group], 4, 4))
        self.group_label = QLabel()
        self.group_label.setObjectName("Faint")
        vl.addWidget(self.group_label)
        lay = self.insp.video_page.layout()
        lay.insertWidget(lay.count() - 1, self.bar)  # antes da lista de cartões
        # "Automático": o clique analisa o clipe inteiro; o menu guarda o de antes (só o quadro atual).
        chip = self.insp.chip_auto
        chip.setToolTip(_("Corrige a exposição, os níveis e o balanço de branco olhando o clipe inteiro "
                          "({n} quadros); o menu tem \"Só o quadro atual\"").format(n=colorsimple.N_AUTO))
        menu = QMenu(chip)
        menu.addAction(_("Só o quadro atual"), self._auto_frame)
        chip.setMenu(menu)
        chip.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

    def cards(self) -> list:
        return [c for c in self.insp.vcards if c.section.key in NEW_CARDS]

    def module_tools(self) -> list:
        return [self.bar, *self.cards()]

    def apply_module(self, on: bool) -> None:
        if not on and self._picking:
            self.win.viewer.cancel_pick()

    def refresh(self) -> None:
        c = self.insp.current_clip()
        video = c is not None and c.kind == timeline.VIDEO
        nested = video and self.is_nested(c)
        for b in (self.btn_wb, self.btn_color, self.btn_match):
            b.setEnabled(video and not nested)  # a imagem de uma sequência não é um arquivo para amostrar
            b.setToolTip(self.tips[b] if not nested else _("Não vale para um clipe de sequência: use nos clipes de "
                                                           "dentro dela."))
        if nested and self._picking:
            self.win.viewer.cancel_pick()
        n = len(self.model.color_group_of(c.id)) if video and c.color_group else 0
        self.group_label.setText(_("Grupo de cor: {n} clipes").format(n=n) if n else "")
        self.group_label.setVisible(bool(n))

    # ------------------------------------------------------------ conta-gotas
    def _toggle(self, kind: str, on: bool) -> None:
        viewer = self.win.viewer
        other = self.btn_color if kind == "wb" else self.btn_wb
        if on and sem_efeitos_ui.refuses_tool(self.win):
            self._pick_done()
            return
        if on:
            if other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
            self._picking = kind
            viewer.start_pick()
            msg = (_("Clique em algo branco ou cinza na prévia (Esc cancela).") if kind == "wb"
                   else _("Clique na cor que você quer mudar (Esc cancela)."))
            self.win.statusBar().showMessage(msg, 6000)
        elif self._picking == kind:
            self._picking = ""
            viewer.cancel_pick()

    def _pick_done(self) -> None:
        self._picking = ""
        for b in (self.btn_wb, self.btn_color):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)

    def is_nested(self, clip) -> bool:
        """O clipe mostra outra sequência do projeto (1.7)? A imagem dele não é a de um arquivo."""
        src = self.model.seq.sources.get(clip.src)
        return src is not None and src.is_nested

    def clip_color_at(self, fx: float, fy: float):
        """(clipe, cor do arquivo no ponto) do clipe selecionado sob o clique, ou (clipe, None)."""
        win = self.win
        c = self.insp.current_clip()
        if c is None or c.kind != timeline.VIDEO or win.cur_layers is None or win.cur is None or self.is_nested(c):
            return c, None
        li = next((x for x in win.cur_layers.layers if x.layer.clip.id == c.id and not x.layer.extension), None)
        if li is None:
            return c, None
        layer = li.layer
        clip = self.model.seq.find(c.id) or c
        import dataclasses
        layer = dataclasses.replace(layer, clip=clip, values=self.model.seq.values_at(clip, win.cur_layers.frame))
        h, w = win.cur.shape[:2]
        uv = colorsimple.clip_point(self.model.seq, layer, w, h, fx, fy)
        if uv is None:
            return c, None
        return c, colorsimple.sample(li.image, *uv)

    def _picked(self, fx: float, fy: float) -> None:
        kind = self._picking
        if not kind:
            return
        self._pick_done()
        status = self.win.statusBar()
        c, rgb = self.clip_color_at(fx, fy)
        if rgb is None:
            status.showMessage(_("Clique dentro do clipe selecionado, no quadro do cursor."), 6000)
            return
        vals = dict(c.values)
        if kind == "wb":
            wb = colorsimple.white_balance_from(rgb)
            if wb is None:
                status.showMessage(_("Essa parte é escura ou clara demais: clique num cinza ou num branco que não "
                                     "esteja estourado."), 6000)
                return
            vals.update(wb)
            self.model.set_clip_values(c.id, vals)
            status.showMessage(_("Balanço acertado: temperatura {t}, tonalidade {ti}.").format(
                t=f"{wb['temperatura']:g}", ti=f"{wb['tonalidade']:g}"), 5000)
            return
        t = colorsimple.pick_target(rgb)
        if t is None:
            status.showMessage(_("Essa cor é quase cinza: clique numa cor com mais saturação."), 6000)
            return
        vals["alvo_matiz"] = t["alvo_matiz"]
        self.model.set_clip_values(c.id, vals)
        cards = {card.section.key: card for card in self.insp.vcards}
        if "alvo" in cards:
            cards["alvo"].set_expanded(True)
        if "hsl" in cards:
            cards["hsl"].set_hsl_color(t["band"])
        status.showMessage(_("Cor escolhida: mude o matiz, a saturação ou a luminância em \"Cor escolhida\"."), 6000)

    # ------------------------------------------------------------ quadros do arquivo
    def grab(self, clip, frame: int):
        """Um quadro do arquivo do clipe (sem ajustes), em `GRAB_W` de largura; None se não der."""
        seq = self.model.seq
        src = seq.sources.get(clip.src)
        if src is None or not src.is_file:
            return None
        try:
            h = max(2, int(round(GRAB_W * src.height / max(1, src.width))))
            return media.grab_frame(src.to_info(), seq.src_frame(clip, frame), GRAB_W, h, 8)
        except Exception:  # noqa: BLE001
            return None

    def current_frame_of(self, clip):
        """O quadro do arquivo do clipe: o da prévia, se o cursor está nele; senão, o do meio. Um clipe de sequência não
        tem quadro de arquivo (None)."""
        win = self.win
        if self.is_nested(clip):
            return None
        if win.cur_layers is not None:
            li = next((x for x in win.cur_layers.layers if x.layer.clip.id == clip.id and not x.layer.extension),
                      None)
            if li is not None:
                return li.image
        return self.grab(clip, clip.start + clip.dur // 2)

    def auto_whole_clip(self, cid: str) -> bool:
        """"Automático" com `colorsimple.N_AUTO` quadros do clipe; False = fica com o quadro atual (imagem parada,
        clipe gerado ou sem leitura)."""
        seq = self.model.seq
        clip = seq.find(cid)
        if clip is None or clip.kind != timeline.VIDEO:
            return False
        src = seq.sources.get(clip.src)
        if src is None or not src.is_file or src.is_image or clip.frozen:
            return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            imgs = [self.grab(clip, f) for f in colorsimple.sample_frames(clip)]
        finally:
            QApplication.restoreOverrideCursor()
        imgs = [i for i in imgs if i is not None]
        if not imgs:
            return False
        vals = dict(clip.values)
        vals.update(colorsimple.auto_adjust_frames(imgs))
        self.model.set_clip_values(cid, vals)
        self.win.statusBar().showMessage(_("Cor automática do clipe inteiro ({n} quadros) aplicada em {nome}.").format(
            n=len(imgs), nome=clip.name or src.name), 4000)
        return True

    def _auto_frame(self) -> None:
        c = self.insp.current_clip()
        if c is not None and c.kind == timeline.VIDEO:
            self.insp.autoFrameRequested.emit(c.id)

    # ------------------------------------------------------------ igualar
    def _fill_clips(self) -> None:
        self.clips_menu.clear()
        c = self.insp.current_clip()
        seq = self.model.seq
        others = [x for x in seq.clips if x.kind == timeline.VIDEO and (c is None or x.id != c.id)
                  and seq.sources.get(x.src) is not None and seq.sources[x.src].is_file]
        if not others:
            a = self.clips_menu.addAction(_("Nenhum outro clipe de vídeo"))
            a.setEnabled(False)
            return
        from .widgets import timecode
        for x in sorted(others, key=lambda k: (k.start, k.track)):
            name = x.name or seq.sources[x.src].name
            self.clips_menu.addAction(f"{name}  •  {timecode(x.start, seq.fps)}",
                                      lambda cid=x.id: self.match_clip(cid))

    def _apply_match(self, ref, ref_values, label: str) -> bool:
        c = self.insp.current_clip()
        status = self.win.statusBar()
        if c is None or c.kind != timeline.VIDEO:
            return False
        src = self.current_frame_of(c)
        if src is None or ref is None:
            status.showMessage(_("Não foi possível ler os quadros para igualar."), 6000)
            return False
        delta = colorsimple.match_adjust(src, ref, self.protect_skin, float(c.values.get("pele_centro", 64.5)))
        if not delta:
            status.showMessage(_("Não deu para igualar: as imagens são escuras, claras ou lisas demais."), 6000)
            return False
        self.model.set_clip_values(c.id, colorsimple.match_values(c.values, delta, ref_values))
        status.showMessage(_("Cor igualada a {nome}. Os valores ficam nos ajustes do clipe.").format(nome=label), 5000)
        return True

    def match_clip(self, cid: str) -> bool:
        other = self.model.seq.find(cid)
        if other is None or sem_efeitos_ui.refuses_tool(self.win):
            return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ref = self.grab(other, other.start + other.dur // 2)
        finally:
            QApplication.restoreOverrideCursor()
        src = self.model.seq.sources.get(other.src)
        return self._apply_match(ref, other.values, other.name or (src.name if src else "-"))

    def match_image(self, path: str | None = None) -> bool:
        if sem_efeitos_ui.refuses_tool(self.win):
            return False
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self.win, _("Igualar a uma imagem"), "",
                                                   _("Imagens") + " (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)")
            if not path:
                return False
        img = QImage(path)
        if img.isNull():
            self.win.statusBar().showMessage(_("Não foi possível abrir a imagem."), 6000)
            return False
        if img.width() > 960:
            img = img.scaledToWidth(960, Qt.TransformationMode.SmoothTransformation)
        from pathlib import Path
        return self._apply_match(_array(img), None, Path(path).name)

    # ------------------------------------------------------------ grupos
    def _sync_group_menu(self) -> None:
        sel = [c for c in self.model.selected_clips() if c.kind == timeline.VIDEO]
        c = self.insp.current_clip()
        self.act_group.setEnabled(len(sel) >= 2)
        grouped = c is not None and bool(getattr(c, "color_group", ""))
        self.act_select_group.setEnabled(grouped)
        self.act_ungroup.setEnabled(any(x.color_group for x in sel))

    def group_selected(self) -> str:
        gid = self.model.group_selected()
        if gid:
            n = len(self.model.color_group_of(next(c.id for c in self.model.selected_clips()
                                                     if c.color_group == gid)))
            self.win.statusBar().showMessage(_("{n} clipes no grupo: a cor de um muda a dos outros.").format(n=n),
                                             5000)
        else:
            self.win.statusBar().showMessage(_("Selecione dois ou mais clipes de vídeo para agrupar."), 5000)
        self.refresh()
        return gid

    def select_group(self) -> None:
        c = self.insp.current_clip()
        if c is not None:
            self.model.select_color_group(c.id)

    def ungroup(self) -> None:
        self.model.ungroup_selected()
        self.refresh()
