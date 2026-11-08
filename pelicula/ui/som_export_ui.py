""""O que exportar" na janela Exportar (1.8, ARQUITETURA §43.6): vídeo e som (como sempre), só o som ou uma faixa por
arquivo (stems), com o formato do som. A gravação é de `somexport.py`, pela mesma fila (`ExportJob` + `run_job`).

É o ponto de ligação com `ExportDialog` (que só instala e repassa quatro ganchos): no modo de som, as partes do vídeo
(plataforma e prévia, qualidade, desempenho, capítulos, legendas, transparência e as linhas de vídeo dos ajustes do
arquivo) somem e voltam como estavam; ficam o destino, o volume alvo e o pico real (só em "Só o som") e o trecho.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QMessageBox, QVBoxLayout

from .. import export, somexport
from ..i18n import _
from .widgets import compact

KEEP_ROWS = ("loud", "peak")   # linhas dos "Ajustes do arquivo" que valem para o som


class SoundChoice(QObject):
    def __init__(self, dlg, lay, after):
        super().__init__(dlg)
        self.dlg = dlg
        g = QGroupBox(_("O que exportar"))
        form = QFormLayout(g)
        form.setHorizontalSpacing(14)
        self.what = compact(QComboBox())
        for key, label in somexport.MODES:
            self.what.addItem(_(label), key)
        self.fmt = compact(QComboBox())
        for key, label in somexport.FORMATS:
            self.fmt.addItem(_(label), key)
        self.note = QLabel()
        self.note.setObjectName("Faint")
        self.note.setWordWrap(True)
        form.addRow(_("Exportar"), self.what)
        form.addRow(_("Formato do som"), self.fmt)
        form.addRow("", self.note)
        self.form = form
        self.group = g
        lay.insertWidget(lay.indexOf(after) + 1, g)
        info = dlg.info
        model = self.what.model()
        if not info.has_audio:
            for i in (1, 2):
                model.item(i).setEnabled(False)
            self.what.setToolTip(_("Este vídeo não tem som."))
        elif dlg.sequence is None:
            item = model.item(2)
            item.setEnabled(False)
            item.setToolTip(_("Stems (uma faixa por arquivo) só existem numa montagem do modo Edição; aqui o som é o "
                              "do próprio arquivo, numa faixa só."))
        g.setVisible(not info.is_image)
        self._hidden_rows: dict = {}
        self.what.currentIndexChanged.connect(self._changed)
        self.fmt.currentIndexChanged.connect(self._changed)
        self._sync()

    # ------------------------------------------------------------ estado
    @property
    def mode(self) -> str:
        return self.what.currentData() or ""

    @property
    def active(self) -> bool:
        return self.mode in ("som", "stems")

    def ext(self) -> str:
        return somexport.EXT[self.fmt.currentData() or "pcm24"]

    def apply(self, s: export.ExportSettings) -> None:
        """`ExportDialog.settings`: o modo e o formato; nos stems, sem volume alvo."""
        if not self.active:
            return
        s.sound_only = self.mode
        s.audio = self.fmt.currentData() or "pcm24"
        if self.mode == "stems":
            s.loudness = 0.0

    # ------------------------------------------------------------ a janela
    def _video_parts(self):
        d = self.dlg
        return [d.platform_group, d.quality.parentWidget(), d.perf_box, d.chapters_box, d.subs_row]

    def _changed(self, *_args) -> None:
        self._sync()
        self.dlg._fix_ext()
        self.dlg._summary()

    def _sync(self) -> None:
        d = self.dlg
        on = self.active
        self.fmt.setEnabled(on)
        self.form.setRowVisible(self.fmt, on)
        if self.mode == "stems":
            self.note.setText(_("Um arquivo por faixa de som, todos do mesmo tamanho e no mesmo começo (somados dão a "
                                "mixagem). Sem o volume alvo: cada faixa sai no nível que tem na mixagem. Os tons das "
                                "barras de cor vão na faixa de vídeo deles."))
        elif self.mode == "som":
            self.note.setText(_("Só o som do trecho, sem vídeo (a mixagem da montagem ou o som do arquivo). O volume "
                                "alvo vale."))
        else:
            self.note.setText("")
        self.form.setRowVisible(self.note, on)
        if d.info.is_image:
            return
        for w in self._video_parts():
            if on:
                if w not in self._hidden_rows:
                    self._hidden_rows[w] = w.isHidden()
                w.setVisible(False)
            elif w in self._hidden_rows:
                w.setVisible(not self._hidden_rows.pop(w))
        keep = {getattr(d, k) for k in KEEP_ROWS}
        for i in range(d.form.rowCount()):
            item = d.form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            w = item.widget() if item is not None else None
            if w is None or w in keep:
                continue
            key = ("row", w)
            if on:
                if key not in self._hidden_rows:
                    self._hidden_rows[key] = d.form.isRowVisible(i)
                d.form.setRowVisible(i, False)
            elif key in self._hidden_rows:
                d.form.setRowVisible(i, self._hidden_rows.pop(key))
        loud_row = not (on and self.mode == "stems")
        for k in KEEP_ROWS:
            d.form.setRowVisible(getattr(d, k), loud_row)
        if on:
            d.loud.setEnabled(True)
            d.peak.setEnabled(True)

    def summary(self) -> None:
        """`ExportDialog._summary` no modo de som: duração, formato e os arquivos (sem medir velocidade nem prévia)."""
        d = self.dlg
        dur = d._duration()
        mins = int(dur // 60)
        lab = self.fmt.currentText()
        if self.mode == "stems" and d.sequence is not None:
            n = len(somexport.stem_paths(d.sequence, d.path.text().strip() or "x.wav"))
            text = _("Saída: só o som • {formato} • {duracao} • até {n} arquivos (um por faixa)").format(
                formato=lab, duracao=f"{mins}min{dur - mins * 60:04.1f}s", n=n)
        else:
            text = _("Saída: só o som • {formato} • {duracao}").format(
                formato=lab, duracao=f"{mins}min{dur - mins * 60:04.1f}s")
        d.summary.setText(text)
        d.est_label.setText("")
        d.warn.setVisible(False)
        d._cancel_estimate()

    def confirm_overwrite(self, path: str, s: export.ExportSettings) -> bool:
        """`ExportDialog._accept`: pergunta antes de substituir o arquivo (ou os stems) que já existe."""
        if s.sound_only == "stems" and self.dlg.sequence is not None:
            dests = somexport.stem_paths(self.dlg.sequence, path, s.audio)
        else:
            dests = [path]
        existing = [p for p in dests if Path(p).exists()]
        if not existing:
            return True
        r = QMessageBox.question(self.dlg, _("Exportar"), _(
            "Já existe:\n{caminho}\n\nSubstituir? Os arquivos antigos só são trocados quando a exportação "
            "terminar.").format(caminho="\n".join(existing[:6]) + ("\n…" if len(existing) > 6 else "")))
        return r == QMessageBox.StandardButton.Yes


def install(dlg, lay, after) -> SoundChoice:
    return SoundChoice(dlg, lay, after)
