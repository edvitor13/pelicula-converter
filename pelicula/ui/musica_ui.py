"""Música na linha do tempo (1.8, ARQUITETURA §46): batidas, ímã nas batidas, encaixar a música na duração do vídeo e
abaixar a música sob a voz.

- **Batidas** (`batidas.py`): "Detectar batidas" no menu do botão direito de um clipe de som, ou sozinho quando um
  clipe de um arquivo só de som (música) com mais de `AUTO_MIN_S` entra na montagem (preferência `PREF_AUTO`,
  ligada por padrão). A análise roda na fila de tarefas (`jobs.CPU`, chave `DETECT_KEY`), com Cancelar na barra de
  status; o resultado fica no cache de `batidas` (pelo carimbo do arquivo), então reabrir o projeto mostra as batidas
  sem analisar de novo.
- **Marcas e ímã**: as batidas aparecem no pé do clipe (`paint_beats`); o botão "Ímã nas batidas" (`snap_button`,
  preferência `PREF_SNAP`) junta as batidas das outras músicas aos pontos do ímã (`snap_points`).
- **Correção à mão** (`MusicUI.set_fix`): "Andamento ×2", "Andamento ÷2", "Compasso de 3/4" e "Voltar ao detectado" no
  menu do clipe. A correção fica na fonte (`timeline.Source.beats_fix`, salva no projeto) e `beats_for` devolve as
  batidas já corrigidas (`batidas.corrected_by`): marcas, ímã, encaixe e a descrição usam a mesma. Um passo do desfazer.
- **Encaixar** (`MusicUI.fit`): `musica.fit_plan` + `musica.apply_fit` num passo do desfazer.
- **Abaixar sob a voz** (`MusicUI.duck`): diálogo (profundidade, descida, volta, faixas com voz; preferências
  `PREF_DUCK_*`), mixagem só das faixas de voz e detecção de fala numa thread de trabalho (chave `DUCK_KEY`), e as
  chaves de volume (`musica.apply_duck`) num passo do desfazer.

Ganchos: a janela chama `install` (`MainWindow.musica`); o menu da linha do tempo chama `add_clip_actions`. Sem a
janela (testes da linha do tempo sozinha), `controller_for` prende um controlador à linha do tempo.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from PySide6.QtCore import QObject, QPointF, QRectF, Signal
from PySide6.QtGui import QActionGroup, QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QMenu, QMessageBox, QProgressBar, QToolButton, QVBoxLayout, QWidget)

from .. import audiomix, batidas, jobs, musica
from ..i18n import _, fmt_decimal
from ..timeline import AUDIO
from . import prefs
from .job_bridge import bridge

DETECT_KEY = "detectar_batidas"
DUCK_KEY = "abaixar_musica"
PREF_AUTO = "musica/batidas_auto"        # "true"/"false"; sem valor = ligado
PREF_SNAP = "musica/ima_batidas"         # "true"/"false"; sem valor = ligado (só vale com o ímã ligado)
PREF_DUCK_DB = "musica/ducking_db"       # quanto abaixar (dB, negativo); sem valor = musica.DUCK_DB
PREF_DUCK_ATTACK = "musica/ducking_ataque"      # segundos; sem valor = musica.ATTACK_S
PREF_DUCK_RELEASE = "musica/ducking_liberacao"  # segundos; sem valor = musica.RELEASE_S
AUTO_MIN_S = 20.0                        # clipe de música mais longo que isto é analisado sozinho
TICK_PX, TICK_DOWN_PX = 4, 8             # altura das marcas das batidas e dos começos de compasso
TICK_MIN_PX = 4                          # marcas mais juntas que isto não são desenhadas


def music_path(seq, clip) -> str | None:
    """O arquivo de som do clipe, se as batidas dele podem ser achadas (clipe de som de um arquivo com som)."""
    if clip is None or clip.kind != AUDIO:
        return None
    src = seq.sources.get(clip.src)
    if src is None or not src.is_file or not src.has_audio:
        return None
    return clip.src


def is_music(seq, clip) -> bool:
    """Clipe de som de um arquivo só de som (sem imagem): o que a análise automática olha."""
    src = seq.sources.get(clip.src) if clip is not None else None
    return music_path(seq, clip) is not None and not src.has_video and not src.is_image


class MusicUI(QObject):
    """As batidas conhecidas de cada arquivo (`beats`), a análise em segundo plano e as ações da música."""

    message = Signal(str)
    beatsChanged = Signal()

    def __init__(self, model, canvas, parent=None, auto: bool = True):
        super().__init__(parent)
        self.model = model
        self.auto_allowed = auto          # sem a janela (testes da linha do tempo sozinha) nada é analisado sozinho
        self.canvas = canvas
        self.beats: dict[str, batidas.Beats] = {}      # o resultado cru do detector, por arquivo
        self._fixed: dict[str, tuple] = {}             # arquivo -> (cru, correção, batidas corrigidas)
        self.jobs: dict[str, jobs.Job] = {}
        self.duck_job: jobs.Job | None = None
        self._looked: set[str] = set()      # arquivos já procurados no cache (para não ler o disco a cada mudança)
        self._refused: set[str] = set()     # análise automática que falhou: não tenta de novo sozinha
        self.bar = QWidget()
        hl = QHBoxLayout(self.bar)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        self.label = QLabel(_("Procurando as batidas…"))
        self.progress = QProgressBar()
        self.progress.setFixedWidth(80)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.btn_cancel = QToolButton()
        self.btn_cancel.setObjectName("beats_cancel")
        self.btn_cancel.setText(_("Cancelar"))
        self.btn_cancel.clicked.connect(self.cancel)
        for w in (self.label, self.progress, self.btn_cancel):
            hl.addWidget(w)
        self.bar.hide()
        model.changed.connect(self._model_changed)
        self.beatsChanged.connect(canvas.update)
        self.scan()

    # ------------------------------------------------------------ batidas
    @property
    def auto(self) -> bool:
        return self.auto_allowed and str(prefs.settings().value(PREF_AUTO, "true")) != "false"

    def raw_beats(self, path: str | None) -> batidas.Beats | None:
        """As batidas como o detector achou (do cache), sem a correção à mão."""
        if not path:
            return None
        hit = self.beats.get(path)
        if hit is None and path not in self._looked:
            self._looked.add(path)
            hit = batidas.cached(path)
            if hit is not None:
                self.beats[path] = hit
        return hit

    def fix_of(self, path: str | None) -> dict:
        """A correção à mão das batidas do arquivo na montagem aberta (`Source.beats_fix`; vazio = como detectado)."""
        src = self.model.seq.sources.get(path) if path else None
        return dict(src.beats_fix) if src is not None else {}

    def beats_for(self, path: str | None) -> batidas.Beats | None:
        """As batidas do arquivo já com a correção à mão: é o que marcas, ímã, encaixe e descrição usam."""
        raw = self.raw_beats(path)
        if raw is None:
            return None
        fix = self.fix_of(path)
        hit = self._fixed.get(path)
        if hit is None or hit[0] is not raw or hit[1] != fix:
            hit = self._fixed[path] = (raw, fix, batidas.corrected_by(raw, fix))
        return hit[2]

    def set_fix(self, path: str, factor: float | None = None, bar: int | None = None, reset: bool = False) -> bool:
        """Muda a correção das batidas do arquivo num passo do desfazer. `factor`: multiplica o andamento (2 ou 0.5; de
        volta ao detectado ao passar por 1); `bar`: batidas por compasso (3 ou 4); `reset`: volta ao detectado."""
        raw = self.raw_beats(path)
        if raw is None or path not in self.model.seq.sources:
            return False
        fix = self.fix_of(path)
        cur = float(fix.get("fator", 1.0))
        if reset:
            fix = {}
        else:
            if factor is not None:
                cur = min(2.0, max(0.5, cur * float(factor)))
            meter = int(bar) if bar is not None else int(fix.get("compasso", batidas.BAR))
            fix = {}
            if cur != 1.0:
                fix["fator"] = cur
            if meter != batidas.BAR:
                fix["compasso"] = meter
        if not self.model.apply_edit(lambda s: setattr(s.sources[path], "beats_fix", dict(fix)), "values"):
            return False
        self.beatsChanged.emit()
        self.message.emit(self.describe(self.beats_for(path)))
        return True

    def busy(self, path: str | None = None) -> bool:
        if path is None:
            return any(j.active for j in self.jobs.values())
        job = self.jobs.get(path)
        return job is not None and job.active

    def _model_changed(self, kind: str) -> None:
        if kind in ("structure", "*", "settings"):
            self.scan()

    def scan(self) -> None:
        """Lê do cache as batidas dos clipes de som e manda analisar as músicas longas novas (preferência)."""
        seq = self.model.seq
        auto = self.auto
        for c in seq.clips:
            path = music_path(seq, c)
            if path is None or self.beats_for(path) is not None or self.busy(path):
                continue
            if auto and path not in self._refused and is_music(seq, c) and c.dur >= AUTO_MIN_S * seq.fps:
                self.detect(path, auto=True)

    def detect(self, path: str, auto: bool = False, then=None) -> jobs.Job | None:
        """Acha as batidas do arquivo numa thread de trabalho; `then(beats)` roda no fim (thread principal)."""
        if self.busy(path):
            return None
        hit = self.beats_for(path)
        if hit is not None:
            if then is not None:
                then(hit)
            return None

        def run(job: jobs.Job):
            job.report(_("Procurando as batidas…"))
            return batidas.analyze_file(path, job.cancel_event)

        job = bridge().submit(run, _("Detectar batidas"), kind=jobs.CPU, key=DETECT_KEY,
                              on_finished=lambda j: self._detected(j, path, auto, then))
        self.jobs[path] = job
        self.bar.show()
        return job

    def cancel(self) -> None:
        for job in list(self.jobs.values()) + [j for j in (self.duck_job,) if j is not None]:
            job.cancel()

    def _detected(self, job: jobs.Job, path: str, auto: bool, then) -> None:
        if self.jobs.get(path) is job:
            del self.jobs[path]
        self.bar.setVisible(self.busy() or self.busy_duck())
        if job.state == jobs.ERRO:
            self._refused.add(path)
            if not auto:
                self.message.emit(job.error)
            return
        if job.state != jobs.CONCLUIDO:
            if auto:
                self._refused.add(path)   # cancelada: não volta sozinha a cada mudança
            return
        self.beats[path] = job.result
        b = self.beats_for(path)
        self.beatsChanged.emit()
        self.message.emit(self.describe(b))
        if then is not None:
            then(b)

    # ------------------------------------------------------------ encaixar na duração do vídeo
    def fit(self, cid: str) -> None:
        """"Encaixar a música na duração do vídeo": acha as batidas (se preciso) e troca o clipe pelos pedaços do
        plano (`musica.fit_plan`) num passo do desfazer. Recusa com a mensagem do motivo; quando só os compassos não
        servem e a música é mais longa que o alvo, oferece a saída simples (acabar no alvo com "diminuir no fim")."""
        seq = self.model.seq
        clip = seq.find(cid)
        path = music_path(seq, clip)
        if path is None:
            return
        span = musica.fit_target(seq, clip, getattr(self.canvas, "inp", None), getattr(self.canvas, "outp", None))
        if span is None:
            self.inform(_("Não há imagem na montagem para a música acompanhar. Marque um trecho (In e Out) para "
                          "dizer onde ela deve acabar."))
            return
        why = musica.fit_blockers(seq, clip, *span)
        if why:
            self.inform(why)
            return
        b = self.beats_for(path)
        if b is None:
            self.detect(path, then=lambda _b: self.fit(cid))
            return
        start, end = span
        plan = musica.fit_plan(b, clip, end - start, seq.fps, start)
        if not plan.ok:
            fade = musica.fade_plan(clip, end - start, seq.fps, start) if plan.can_fade else None
            if fade is None or not fade.ok:
                self.inform(plan.reason)
                return
            if not self.ask(plan.reason + "\n\n" + _("Acabar a música no ponto pedido com uma saída suave "
                                                     "(\"Diminuir no fim\")?")):
                return
            plan = fade
        if self.model.apply_edit(lambda s: musica.apply_fit(s, cid, plan)):
            self.message.emit(self.describe_fit(plan, seq.fps))

    @staticmethod
    def describe_fit(plan: musica.Plan, fps: float) -> str:
        secs = fmt_decimal((plan.end - plan.pieces[0].start) / fps, 1)
        if plan.removed:
            return _("Música encaixada em {s} s: {n} compassos tirados do meio.").format(s=secs, n=plan.removed)
        if plan.added:
            return _("Música encaixada em {s} s: {n} compassos repetidos no meio.").format(s=secs, n=plan.added)
        return _("Música encaixada em {s} s, com saída suave.").format(s=secs)

    # ------------------------------------------------------------ abaixar a música sob a voz
    def music_clips(self, clip) -> list:
        """Os clipes de música da ação: os clipes de som selecionados (se `clip` está entre eles) ou só `clip`."""
        seq = self.model.seq
        sel = set(self.model.selection)
        if clip.id in sel:
            chosen = [c for c in seq.clips if c.id in sel and c.kind == AUDIO]
        else:
            chosen = [clip]
        return [c for c in chosen if not seq.locked(c)]

    def duck(self, cid: str):
        """"Abaixar a música sob a voz": pergunta as medidas e as faixas com voz, acha as falas numa thread de trabalho
        e escreve as chaves de volume. Devolve o trabalho (ou None se nada foi feito)."""
        seq = self.model.seq
        clip = seq.find(cid)
        if clip is None or clip.kind != AUDIO or self.busy_duck():
            return None
        music = self.music_clips(clip)
        if not music:
            self.inform(_("A faixa da música está travada."))
            return None
        own = {c.track for c in music}
        tracks = [i for i in range(len(seq.kind_tracks(AUDIO))) if i not in own]
        if not tracks:
            self.inform(_("Não há outra faixa de som com voz: ponha a narração ou o diálogo numa faixa separada da "
                          "música."))
            return None
        got = self.duck_dialog(tracks, musica.voice_tracks_for(seq, music))
        if got is None:
            return None
        depth, attack, release, voice = got
        if not voice:
            return None
        ids = [c.id for c in music]
        a, b = min(c.start for c in music), max(c.end for c in music)
        mix = musica.voice_mix(seq, voice, ids)
        fps = seq.fps

        def run(job: jobs.Job):
            job.report(_("Procurando a voz…"))
            work = tempfile.mkdtemp(prefix="pelicula_voz_")
            try:
                wav = os.path.join(work, "voz.wav")
                ok = audiomix.render_mix(mix, wav, a, b, job.cancel_event)
                if job.cancel_event.is_set():
                    raise jobs.Cancelled()
                if not ok:
                    return []
                r = audiomix.WavReader(wav)
                regions = musica.speech_regions(r.read(0, r.frames), r.rate)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            return [(a / fps + t0, a / fps + t1) for t0, t1 in regions]

        self.duck_job = bridge().submit(run, _("Abaixar a música sob a voz"), kind=jobs.CPU, key=DUCK_KEY,
                                        on_finished=lambda j: self._ducked(j, ids, depth, attack, release))
        self.label.setText(_("Procurando a voz…"))
        self.bar.show()
        return self.duck_job

    def busy_duck(self) -> bool:
        return self.duck_job is not None and self.duck_job.active

    def _ducked(self, job: jobs.Job, ids: list[str], depth: float, attack: float, release: float) -> None:
        self.duck_job = None
        self.label.setText(_("Procurando as batidas…"))
        self.bar.setVisible(self.busy())
        if job.state == jobs.ERRO:
            self.inform(job.error)
            return
        if job.state != jobs.CONCLUIDO:
            return
        regions = job.result
        if not regions:
            self.inform(_("Nenhuma fala encontrada nas faixas de voz escolhidas."))
            return
        seq = self.model.seq
        plans = []
        clash = 0
        for cid in ids:
            c = seq.find(cid)
            if c is None or seq.locked(c):
                continue
            ducks = musica.duck_spans(c, regions, seq.fps, attack, release)
            if ducks:
                plans.append((cid, ducks))
                clash += len(musica.duck_conflicts(seq, c, ducks))
        if not plans:
            self.inform(_("Nenhuma fala encontrada sob a música."))
            return
        if clash and not self.ask(_("A música já tem {n} chave(s) de volume onde ela vai abaixar. Substituir essas "
                                    "chaves?").format(n=clash)):
            return
        n = sum(len(d) for _cid, d in plans)
        if self.model.apply_edit(lambda s: [musica.apply_duck(s, cid, d, depth) for cid, d in plans], "values"):
            self.message.emit(_("Música abaixada {db} dB em {n} trecho(s) com voz.").format(
                db=fmt_decimal(-abs(depth), 1), n=n))

    def duck_dialog(self, tracks: list[int], checked: list[int]):
        """(profundidade em dB, descida s, volta s, faixas com voz) ou None (cancelado). Lembra as três medidas."""
        st = prefs.settings()

        def num(key, default):
            try:
                return float(st.value(key, default))
            except (TypeError, ValueError):
                return default

        dlg = QDialog(self.canvas.window())
        dlg.setWindowTitle(_("Abaixar a música sob a voz"))
        lay = QVBoxLayout(dlg)
        form = QFormLayout()
        depth = QDoubleSpinBox()
        depth.setRange(-40.0, -1.0)
        depth.setDecimals(1)
        depth.setSuffix(" dB")
        depth.setValue(-abs(num(PREF_DUCK_DB, musica.DUCK_DB)))
        attack = QDoubleSpinBox()
        attack.setRange(0.0, 3.0)
        attack.setDecimals(2)
        attack.setSingleStep(0.05)
        attack.setSuffix(" s")
        attack.setValue(num(PREF_DUCK_ATTACK, musica.ATTACK_S))
        release = QDoubleSpinBox()
        release.setRange(0.0, 5.0)
        release.setDecimals(2)
        release.setSingleStep(0.05)
        release.setSuffix(" s")
        release.setValue(num(PREF_DUCK_RELEASE, musica.RELEASE_S))
        form.addRow(_("Abaixar"), depth)
        form.addRow(_("Descida antes da voz"), attack)
        form.addRow(_("Volta depois da voz"), release)
        lay.addLayout(form)
        lay.addWidget(QLabel(_("Faixas com voz:")))
        boxes = {}
        for i in tracks:
            tr = self.model.seq.track(AUDIO, i)
            name = (tr.name if tr is not None and tr.name else "") or f"A{i + 1}"
            box = QCheckBox(name)
            box.setChecked(i in checked)
            lay.addWidget(box)
            boxes[i] = box
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        st.setValue(PREF_DUCK_DB, depth.value())
        st.setValue(PREF_DUCK_ATTACK, attack.value())
        st.setValue(PREF_DUCK_RELEASE, release.value())
        return depth.value(), attack.value(), release.value(), [i for i, b in boxes.items() if b.isChecked()]

    # ------------------------------------------------------------ perguntas (os testes trocam)
    def inform(self, text: str) -> None:
        QMessageBox.information(self.canvas.window(), _("Música"), text)

    def ask(self, text: str) -> bool:
        box = QMessageBox.question(self.canvas.window(), _("Música"), text)
        return box == QMessageBox.StandardButton.Yes

    @staticmethod
    def describe(b: batidas.Beats) -> str:
        if not b.times:
            return _("Nenhuma batida encontrada neste som.")
        text = _("{bpm} BPM, {n} batidas").format(bpm=fmt_decimal(b.bpm, 1), n=len(b.times))
        if not b.confident:
            return text + " — " + _("ritmo irregular: as batidas são só uma ajuda visual")
        if b.bar == 3:
            return text + " — " + _("compassos de 3 estimados")
        return text + " — " + _("compassos de 4 estimados")


# ------------------------------------------------------------------ marcas das batidas e ímã
def tick_marks(canvas, clip) -> list[tuple[float, bool]]:
    """[(x, começo de compasso)] das marcas que o clipe mostra agora: todas as batidas, só os compassos se as batidas
    ficariam a menos de `TICK_MIN_PX` uma da outra, nenhuma se nem os compassos cabem."""
    ctl = controller_for(canvas)
    b = ctl.beats_for(music_path(canvas.model.seq, clip))
    if b is None or b.bpm <= 0:
        return []
    seq = canvas.model.seq
    px_beat = 60.0 / b.bpm * seq.fps / max(clip.speed, 1e-9) * canvas.ppf
    if px_beat * b.bar < TICK_MIN_PX:
        return []
    only_downs = px_beat < TICK_MIN_PX
    return [(canvas.frame_to_x(f), down) for f, down in musica.beat_frames(seq, clip, b) if down or not only_downs]


def paint_beats(canvas, p: QPainter, clip, r: QRectF) -> None:
    """Marcas das batidas no pé do clipe de som (o começo do compasso mais alto e mais claro). Gancho de
    `TimelineCanvas._paint_clip`, já recortado no retângulo do clipe."""
    marks = tick_marks(canvas, clip)
    if not marks:
        return
    beat = QPen(QColor(255, 246, 232, 95), 1)
    down = QPen(QColor(255, 246, 232, 210), 1.4)
    bottom = r.bottom() - 2
    for x, is_down in marks:
        if x < r.left() or x > r.right():
            continue
        p.setPen(down if is_down else beat)
        p.drawLine(QPointF(x, bottom - (TICK_DOWN_PX if is_down else TICK_PX)), QPointF(x, bottom))


def beat_snap_on(canvas) -> bool:
    return bool(getattr(canvas, "beat_snap", True))


def snap_points(canvas, exclude) -> set[int]:
    """Gancho de `TimelineCanvas.snap_points`: os quadros das batidas das músicas (menos as que estão sendo
    arrastadas), com "Ímã nas batidas" ligado."""
    if not beat_snap_on(canvas):
        return set()
    ctl = controller_for(canvas)
    return musica.snap_frames(canvas.model.seq, ctl.beats_for, exclude)


def snap_button(editor) -> QToolButton:
    """O botão "Ímã nas batidas", ao lado do ímã da barra da linha do tempo (preferência `PREF_SNAP`; só vale com o
    ímã ligado)."""
    b = editor._btn("beats", _("Ímã nas batidas: com o ímã ligado, gruda também nas batidas das músicas "
                               "(\"Detectar batidas\" no menu do clipe de som)"), checkable=True)
    b.setObjectName("beat_snap")
    canvas = editor.canvas
    canvas.beat_snap = str(prefs.settings().value(PREF_SNAP, "true")) != "false"
    b.setChecked(canvas.beat_snap)
    b.setEnabled(canvas.snap)

    def toggled(on: bool) -> None:
        canvas.beat_snap = on
        prefs.settings().setValue(PREF_SNAP, "true" if on else "false")

    b.toggled.connect(toggled)
    editor.btn_snap.toggled.connect(b.setEnabled)
    return b


def controller_for(canvas) -> MusicUI:
    """O controlador da janela (`install`) ou, sem ela (testes), um preso à linha do tempo."""
    ctl = getattr(canvas.window(), "musica", None)
    if ctl is None:
        ctl = getattr(canvas, "_musica", None)
        if ctl is None:
            ctl = canvas._musica = MusicUI(canvas.model, canvas, canvas, auto=False)
    return ctl


def add_clip_actions(menu: QMenu, canvas, clip) -> None:
    """Itens da música no menu do botão direito de um clipe de som."""
    path = music_path(canvas.model.seq, clip)
    if path is None:
        return
    ctl = controller_for(canvas)
    b = ctl.beats_for(path)
    if b is None:
        act = menu.addAction(_("Detectar batidas"), lambda: ctl.detect(path))
        act.setObjectName("detect_beats")
        act.setEnabled(not ctl.busy(path))
    else:
        act = menu.addAction(ctl.describe(b))
        act.setObjectName("beats_info")
        act.setEnabled(False)
        add_fix_actions(menu, ctl, path)
    act = menu.addAction(_("Encaixar a música na duração do vídeo"), lambda: ctl.fit(clip.id))
    act.setObjectName("fit_music")
    act.setToolTip(_("Tira ou repete compassos inteiros no meio da música para ela acabar junto com a imagem (ou no "
                     "Out do trecho marcado), com uma transição de som em cada emenda."))
    act.setEnabled(not ctl.busy(path) and not canvas.model.seq.locked(clip))
    act = menu.addAction(_("Abaixar a música sob a voz…"), lambda: ctl.duck(clip.id))
    act.setObjectName("duck_music")
    act.setToolTip(_("Acha as falas nas outras faixas de som e abaixa o volume da música enquanto alguém fala, com "
                     "chaves de volume comuns (dá para ajustar depois)."))
    act.setEnabled(not ctl.busy_duck() and not canvas.model.seq.locked(clip))


def add_fix_actions(menu: QMenu, ctl: MusicUI, path: str) -> None:
    """A correção à mão das batidas (§46.5): o detector às vezes acha a metade ou o dobro do andamento e só conhece o
    compasso de 4. "Andamento ×2" e "÷2" andam entre metade, detectado e dobro; o compasso é de 3 ou de 4 (marcado);
    "Voltar ao detectado" só aparece com correção."""
    fix = ctl.fix_of(path)
    factor, meter = float(fix.get("fator", 1.0)), int(fix.get("compasso", batidas.BAR))
    act = menu.addAction(_("Andamento ×2"), lambda: ctl.set_fix(path, factor=2.0))
    act.setObjectName("beats_x2")
    act.setToolTip(_("O detector achou a metade do andamento: põe uma batida no meio de cada par."))
    act.setEnabled(factor < 2.0)
    act = menu.addAction(_("Andamento ÷2"), lambda: ctl.set_fix(path, factor=0.5))
    act.setObjectName("beats_div2")
    act.setToolTip(_("O detector achou o dobro do andamento: fica uma batida sim, outra não."))
    act.setEnabled(factor > 0.5)
    group = QActionGroup(menu)
    for n in (3, batidas.BAR):
        act = menu.addAction(_("Compasso de {n}").format(n=n), lambda _checked=False, n=n: ctl.set_fix(path, bar=n))
        act.setObjectName(f"beats_bar{n}")
        act.setCheckable(True)
        act.setChecked(meter == n)
        group.addAction(act)
        act.setToolTip(_("Quantas batidas tem cada compasso: os compassos são refeitos pelo acento."))
    if fix:
        act = menu.addAction(_("Voltar ao detectado"), lambda: ctl.set_fix(path, reset=True))
        act.setObjectName("beats_reset")


def install(win) -> MusicUI:
    """O controlador da janela, com o progresso na barra de status e as mensagens nela."""
    ctl = MusicUI(win.model, win.tl_editor.canvas, win)
    win.statusBar().addPermanentWidget(ctl.bar)
    ctl.message.connect(lambda text: win.statusBar().showMessage(text, 10000))
    return ctl


__all__ = ["MusicUI", "add_clip_actions", "controller_for", "install", "music_path", "is_music"]
