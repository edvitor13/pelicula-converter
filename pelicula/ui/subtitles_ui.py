"""Legendas na interface: o controle comum do painel e da faixa "Legendas" e a ligação com a janela principal.

- `SubtitleController` (sem a janela): as legendas da montagem como aparecem na tela (`subedit.items`), a
  legenda escolhida e as mudanças, sempre por `TimelineModel.edit_subtitles` (um passo de desfazer cada).
  O painel (`subtitles_panel.py`) e a faixa da linha do tempo (`subtitle_lane.py`) usam o mesmo controle,
  então escolher numa escolhe na outra.
- `SubtitlesUI`: o botão "Legendas" da barra de cima (menu), o painel numa área encaixável da janela, a faixa
  na linha do tempo, "Gerar legendas…" (módulo Beta `legendas_auto`), "Remover silêncios…" (módulo
  `silencios`) e a receita do quadro com as legendas gravadas (`burn`, que a janela passa a `frame.Recipe`).

Nada aqui entra na renderização: o desenho das legendas gravadas é de `subtitles.Burn`, pelo `frame.Recipe`.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
                               QFileDialog, QLabel, QMenu, QMessageBox, QToolButton, QVBoxLayout)

from .. import subedit, subtitles as sb
from ..i18n import _, fmt_int
from .edit_model import TimelineModel


class SubtitleController(QObject):
    """As legendas como a interface vê: itens na tela (tempo da sequência), seleção e mudanças com desfazer."""

    changed = Signal()            # legendas ou montagem mudaram (redesenhar a lista e a faixa)
    selectionChanged = Signal()
    seekRequested = Signal(int)   # levar o cursor a este quadro
    textRequested = Signal()      # dois cliques numa legenda: editar o texto no painel

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.clock = lambda: 0                  # quadro do cursor (a janela troca por um que lê o dela)
        self.selection: list[subedit.Ref] = []
        self._picked: list[tuple[str | None, sb.Cue]] = []
        self._items: list[subedit.Item] | None = None
        model.changed.connect(self._model_changed)

    # ------------------------------------------------------------ leitura
    @property
    def seq(self):
        return self.model.seq

    @property
    def fps(self) -> float:
        return self.model.seq.fps

    @property
    def playhead(self) -> int:
        return int(self.clock())

    def doc(self) -> sb.Subtitles:
        return self.model.subtitles()

    def items(self) -> list[subedit.Item]:
        if self._items is None:
            self._items = subedit.items(self.model.seq, self.model.seq.subtitles)
        return self._items

    def cues(self) -> list[sb.Cue]:
        """As legendas na tela, em segundos da sequência (o que vai para o .srt e para o vídeo)."""
        return [it.cue for it in self.items()]

    def selected_items(self) -> list[subedit.Item]:
        refs = set(self.selection)
        return [it for it in self.items() if it.ref in refs]

    def current(self) -> subedit.Item | None:
        sel = self.selected_items()
        return sel[0] if sel else None

    def source_cue(self, item: subedit.Item | None) -> sb.Cue | None:
        if item is None or self.model.seq.subtitles is None:
            return None
        return subedit.source(self.model.seq.subtitles, item.ref)

    def item_at(self, t: float) -> subedit.Item | None:
        """A legenda na tela no instante t (s da sequência); a escolhida tem preferência."""
        hits = [it for it in self.items() if it.cue.start - 1e-6 <= t < it.cue.end - 1e-6]
        sel = set(self.selection)
        return next((it for it in hits if it.ref in sel), hits[0] if hits else None)

    def frame_of(self, t: float) -> int:
        return max(0, int(round(t * self.fps)))

    # ------------------------------------------------------------ seleção
    def select(self, refs, seek: bool = False) -> None:
        subs = self.model.seq.subtitles
        refs = [r for r in refs if r is not None and subs is not None and subedit.source(subs, r) is not None]
        # a legenda escolhida (não só a posição): depois de desfazer, a escolha acha a mesma legenda ou some
        self._picked = [(r.path, subedit.source(subs, r)) for r in refs]
        if refs != self.selection:
            self.selection = refs
            self.selectionChanged.emit()
        if seek and refs:
            it = subedit.item_for(self.items(), refs[0])
            if it is not None:
                self.seekRequested.emit(self.frame_of(it.cue.start))

    def _model_changed(self, _kind: str) -> None:
        self._items = None
        subs = self.model.seq.subtitles
        found = [subedit.find(subs, cue, path) for path, cue in self._picked] if subs else []
        keep = [r for r in found if r is not None]
        if keep != self.selection:
            self.selection = keep
            self.selectionChanged.emit()
        self.changed.emit()

    # ------------------------------------------------------------ mudanças (um passo de desfazer cada)
    def apply(self, fn) -> bool:
        """`fn(subs)` muda as legendas e devolve [(caminho, legenda guardada)] para escolher depois (ou None para
        manter a escolha, False para desistir)."""
        picked: list[tuple[str | None, sb.Cue]] | None = None

        def run(subs):
            nonlocal picked
            got = fn(subs)
            if got is False:
                return False
            if got is not None:
                picked = list(got)
            return None

        if not self.model.edit_subtitles(run):
            return False
        subs = self.model.seq.subtitles
        if picked is not None and subs is not None:  # senão a escolha já foi refeita em `_model_changed`
            self.select([subedit.find(subs, cue, path) for path, cue in picked])
        return True

    def add_at(self, frame: int | None = None, text: str | None = None, dur: float = subedit.NEW_DUR) -> bool:
        """Legenda nova no cursor (ou no quadro dado), presa ao arquivo que toca ali; vai até a próxima legenda se
        ela começa antes de `dur`."""
        frame = self.playhead if frame is None else int(frame)
        t = frame / self.fps
        nxt = [it.cue.start for it in self.items() if it.cue.start > t + 1e-6]
        end = min([t + dur] + [s for s in nxt if s >= t + 0.5])
        path, mapping = subedit.anchor_at(self.model.seq, frame)
        body = text if text is not None else _("Nova legenda")

        def fn(subs):
            cue = subedit.add(subs, t, end, body, mapping, path)
            return False if cue is None else [(path if mapping is not None else None, cue)]

        return self.apply(fn)

    def delete_selected(self) -> int:
        refs = list(self.selection)
        if not refs:
            return 0
        count = []

        def fn(subs):
            count.append(subedit.delete(subs, refs))
            return [] if count[0] else False

        self.apply(fn)
        return count[0] if count else 0

    def set_text(self, item: subedit.Item, text: str) -> bool:
        def fn(subs):
            cue = subedit.set_text(subs, item.ref, text)
            return [] if cue is None else [(item.ref.path, cue)]
        return self.apply(fn)

    def set_flags(self, item: subedit.Item, italic: bool | None = None, bold: bool | None = None) -> bool:
        def fn(subs):
            cue = subedit.set_style(subs, item.ref, italic, bold)
            return False if cue is None else [(item.ref.path, cue)]
        return self.apply(fn)

    def set_times(self, item: subedit.Item, start: float | None = None, end: float | None = None) -> bool:
        def fn(subs):
            cue = subedit.set_times(subs, item, start, end)
            return False if cue is None else [(item.ref.path, cue)]
        return self.apply(fn)

    def move(self, item: subedit.Item, dt: float) -> bool:
        if abs(dt) < 1e-9:
            return False

        def fn(subs):
            cue = subedit.move(subs, item, dt)
            return False if cue is None else [(item.ref.path, cue)]
        return self.apply(fn)

    def split(self, item: subedit.Item | None = None, frame: int | None = None) -> bool:
        t = (self.playhead if frame is None else frame) / self.fps
        item = item or self.item_at(t)
        if item is None:
            return False

        def fn(subs):
            got = subedit.split(subs, item, t)
            return False if got is None else [(item.ref.path, got[1])]
        return self.apply(fn)

    def merge_next(self, item: subedit.Item | None = None) -> bool:
        item = item or self.current()
        if item is None:
            return False
        nxt = subedit.neighbor(self.items(), item, 1)
        if nxt is None or nxt.ref.path != item.ref.path:
            return False

        def fn(subs):
            cue = subedit.merge(subs, [item.ref, nxt.ref])
            return False if cue is None else [(item.ref.path, cue)]
        return self.apply(fn)

    def replace_all(self, query: str, repl: str, case: bool = False) -> int:
        count = []

        def fn(subs):
            count.append(subedit.replace_all(subs, query, repl, case))
            return None if count[0] else False

        self.apply(fn)
        return count[0] if count else 0

    def set_options(self, **kw) -> bool:
        """Estilo (`style`), gravar no vídeo (`burn`), faixa no arquivo (`embed`) e idioma (`language`)."""
        def fn(subs):
            for k, v in kw.items():
                setattr(subs, k, v)
            return None
        return self.apply(fn)

    def import_cues(self, cues, path: str | None = None, replace: bool = False) -> int:
        cues = list(cues)
        if not cues:
            return 0

        def fn(subs):
            subedit.import_cues(subs, cues, path, replace)
            return None
        return len(cues) if self.apply(fn) else 0


# ====================================================================== janela principal
def anchor_choices(seq) -> list[tuple[str | None, str]]:
    """Onde legendas importadas ficam presas: a sequência (tempo da montagem) ou um arquivo da montagem (o .srt
    veio com aquele vídeo: tempo do arquivo, acompanha os cortes)."""
    out: list[tuple[str | None, str]] = [(None, _("A montagem (o tempo do .srt é o da sequência)"))]
    for path in sorted({c.src for c in seq.clips}):
        src = seq.sources.get(path)
        if src is not None and src.is_file and not src.is_image and sb.clips_for(seq, path):
            out.append((path, _("O arquivo {arquivo} (acompanha os cortes)").format(arquivo=os.path.basename(path))))
    return out


def default_anchor(seq) -> str | None:
    """Arquivo aberto sem montagem (modo Película): o .srt é dele; numa montagem, o tempo é o da sequência."""
    return seq.is_trivial() or None


def icon(name: str):
    from . import icons, theme
    return icons.icon(name, theme.TEXT, 16)


class ImportDialog(QDialog):
    """Pergunta onde prender as legendas importadas e se elas trocam as que já existem."""

    def __init__(self, parent, seq, path: str, count: int, has_cues: bool):
        super().__init__(parent)
        self.setWindowTitle(_("Importar legendas"))
        v = QVBoxLayout(self)
        v.addWidget(QLabel(_("{n} legendas em {arquivo}.").format(n=fmt_int(count), arquivo=os.path.basename(path))))
        v.addWidget(QLabel(_("Prender ao tempo de:")))
        self.anchor = QComboBox()
        for key, label in anchor_choices(seq):
            self.anchor.addItem(label, key)
        self.anchor.setCurrentIndex(max(0, self.anchor.findData(default_anchor(seq))))
        v.addWidget(self.anchor)
        self.replace = QCheckBox(_("Trocar as legendas que já existem nesse tempo"))
        self.replace.setVisible(has_cues)
        v.addWidget(self.replace)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(_("Importar"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class SubtitlesUI(QObject):
    """Legendas na janela principal: botão e menu "Legendas", painel encaixável e faixa da linha do tempo.

    A janela cria um (logo depois de montar a interface) e chama `apply_modules` com os módulos ligados.
    """

    def __init__(self, win):
        super().__init__(win)
        from .subtitle_lane import SubtitleLane
        from .subtitles_panel import SubtitlesPanel
        self.win = win
        self.enabled = True          # módulo "legendas"
        self.auto = False            # módulo Beta "legendas_auto"
        self.ctl = SubtitleController(win.model, self)
        self.ctl.clock = lambda: win.frame_idx
        self.ctl.seekRequested.connect(win.seek)
        self.panel = SubtitlesPanel(self.ctl)
        self.panel.importRequested.connect(self.import_dialog)
        self.panel.exportRequested.connect(self.export_dialog)
        self.panel.generateRequested.connect(self.generate_dialog)
        self.panel.previewToggled.connect(lambda _on: self._preview_toggled())
        self._burn_key: tuple | None = None
        self._burn = None
        self.dock = QDockWidget(_("Legendas"), win)
        self.dock.setObjectName("SubtitlesDock")
        self.dock.setWidget(self.panel)
        self.dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
                                  | Qt.DockWidgetArea.BottomDockWidgetArea)
        win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self.dock.visibilityChanged.connect(lambda _v: self._sync())
        self.lane = SubtitleLane(win.tl_editor.canvas, self.ctl)
        self.ctl.changed.connect(self._sync)

        self.menu = QMenu(win)
        self.act_panel = self.menu.addAction(icon("captions"), _("Painel de legendas"), self.toggle_panel)
        self.act_panel.setCheckable(True)
        self.act_panel.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.act_panel.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)  # o atalho é o `shortcut` abaixo
        self.menu.addSeparator()
        self.menu.addAction(icon("open"), _("Importar .srt ou .vtt…"), self.import_dialog)
        self.act_export = self.menu.addAction(icon("export"), _("Exportar .srt ou .vtt…"), self.export_dialog)
        self.act_generate = self.menu.addAction(icon("wand"), _("Gerar legendas pela fala…"), self.generate_dialog)
        self.act_generate.setVisible(False)
        self.menu.aboutToShow.connect(self._sync_menu)
        win.btn_subs.setMenu(self.menu)
        win.btn_subs.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), win)
        self.shortcut.activated.connect(self.toggle_panel)
        self._sync()

    # ------------------------------------------------------------ estado
    def _sync_menu(self) -> None:
        self.act_panel.setChecked(self.dock.isVisible())
        self.act_export.setEnabled(bool(self.ctl.items()))

    def _sync(self) -> None:
        """Faixa na linha do tempo: com o módulo ligado, quando há legendas ou o painel está aberto."""
        doc = self.win.model.seq.subtitles
        want = self.enabled and (self.dock.isVisible() or (doc is not None and not doc.is_empty()))
        if want != self.lane.visible:
            self.lane.set_visible(want)

    def toggle_panel(self) -> None:
        if self.enabled:
            self.show_panel(self.dock.isHidden())

    def show_panel(self, on: bool = True) -> None:
        self.dock.setVisible(bool(on) and self.enabled)
        if on and self.enabled:
            self.dock.raise_()
            self.panel.table.setFocus()

    def burn(self, full: bool = False):
        """As legendas gravadas da receita do quadro da janela (`frame.Recipe.burn`): as do projeto no modo que ele
        pede (o mesmo da exportação; `full` = "Salvar quadro"). Na prévia, sem gravar no vídeo e com "Ver na
        prévia" ligado, elas aparecem por cima do resultado (como num player)."""
        doc = self.win.model.seq.subtitles
        if doc is None or doc.is_empty():
            return None
        mode = doc.burn
        if mode == "nao" and not full and self.enabled and self.panel.chk_preview.isChecked():
            mode = "digital"
        items = self.ctl.items()   # a mesma lista enquanto a montagem e as legendas não mudam
        key = self._burn_key
        if key is None or key[0] is not items or key[1:] != (mode, doc.style):
            self._burn_key = (items, mode, doc.style)
            self._burn = sb.Burn.make(mode, doc.style, [it.cue for it in items])
        return self._burn

    def _preview_toggled(self) -> None:
        self.win._uploaded = None  # a imagem enviada à GPU pode ter a legenda gravada na cópia
        self.win.render_now()

    def owns_focus(self) -> bool:
        """O foco está no painel: Ctrl+Z / Ctrl+Y desfazem nas legendas (também no modo Película)."""
        w = QApplication.focusWidget()
        return w is not None and not self.dock.isHidden() and (w is self.dock or self.dock.isAncestorOf(w))

    def apply_modules(self, on) -> None:
        self.enabled = "legendas" in on
        self.auto = "legendas_auto" in on
        self.win.btn_subs.setVisible(self.enabled)
        self.shortcut.setEnabled(self.enabled)
        if not self.enabled:
            self.dock.hide()
        self.panel.btn_generate.setVisible(self.enabled and self.auto)
        self.act_generate.setVisible(self.enabled and self.auto)
        dlg = getattr(self.win, "_transcribe_dialog", None)
        if dlg is not None and not (self.enabled and self.auto):
            dlg.hide()            # o trabalho que já está na fila continua e põe as legendas ao terminar
        self._sync()

    def generate_dialog(self):
        """"Gerar legendas pela fala…" (módulo Beta `legendas_auto`): janela não modal, trabalho na fila."""
        if not (self.enabled and self.auto):
            return None
        from .transcribe_dialog import open_for
        return open_for(self.win)

    # ------------------------------------------------------------ arquivos
    def _dir(self) -> str:
        s = self.win.settings
        return str(s.value("last_sub_dir", s.value("last_dir", "")) or "")

    def import_dialog(self) -> None:
        win = self.win
        path, _f = QFileDialog.getOpenFileName(win, _("Importar legendas"), self._dir(),
                                               _("Legendas") + " (*.srt *.vtt);;" + _("Todos os arquivos") + " (*)")
        if not path:
            return
        try:
            cues = sb.load(path)
        except ValueError as exc:
            QMessageBox.warning(win, _("Importar legendas"), str(exc))
            return
        self.import_file(path, cues)

    def import_file(self, path: str, cues, ask: bool = True) -> int:
        """Põe as legendas lidas de `path`; `ask` pergunta onde prender (sem: o padrão de `default_anchor`)."""
        win = self.win
        win.settings.setValue("last_sub_dir", os.path.dirname(path))
        seq = win.model.seq
        anchor, replace = default_anchor(seq), False
        if ask:
            dlg = ImportDialog(win, seq, path, len(cues), bool(self.ctl.items()))
            if not dlg.exec():
                return 0
            anchor, replace = dlg.anchor.currentData(), dlg.replace.isChecked()
        n = self.ctl.import_cues(cues, anchor, replace)
        if n:
            self.show_panel(True)
            win.statusBar().showMessage(_("{n} legendas importadas.").format(n=fmt_int(n)), 5000)
        return n

    def default_name(self, ext: str) -> str:
        win = self.win
        base = win.project_path or (win.file_info.path if win.file_info is not None else "")
        name = os.path.splitext(os.path.basename(base))[0] if base else _("legendas")
        return os.path.join(self._dir() or os.path.dirname(base), name + ext)

    def export_dialog(self) -> None:
        win = self.win
        cues = self.ctl.cues()
        if not cues:
            QMessageBox.information(win, _("Exportar legendas"), _("Não há legendas para exportar."))
            return
        path, filt = QFileDialog.getSaveFileName(win, _("Exportar legendas"), self.default_name(".srt"),
                                                 "SubRip (*.srt);;WebVTT (*.vtt)")
        if path:
            self.export_file(path if os.path.splitext(path)[1] else path + (".vtt" if "vtt" in filt else ".srt"))

    def export_file(self, path: str) -> bool:
        win = self.win
        try:
            sb.save(path, self.ctl.cues())
        except OSError as exc:
            QMessageBox.warning(win, _("Exportar legendas"), _("Não foi possível gravar {arquivo}: {erro}").format(
                arquivo=os.path.basename(path), erro=exc))
            return False
        win.settings.setValue("last_sub_dir", os.path.dirname(path))
        win.statusBar().showMessage(_("Legendas exportadas: {arquivo}").format(arquivo=os.path.basename(path)), 6000)
        return True
