"""Recuperação automática na janela: cópias de segurança, fila guardada e o aviso depois de um travamento.

`pelicula/recovery.py` cuida dos arquivos (sem Qt); aqui fica o que depende da janela:

- `Guard`: a sessão desta execução (`recovery.Session`, o marcador com pid e hora de início) e o registro de
  travamentos (`crashlog.CrashLog`), ligados pelo `app.main()` logo depois da QApplication (antes da janela,
  para pegar um travamento ao iniciar o OpenGL) e fechados quando `app.exec()` termina. Testes e automações
  (`PELICULA_SCREENSHOT`) que só criam a janela não ligam nada disso nem gravam na pasta do app.
- `RecoveryController` (`attach`): criado depois da `MainWindow`. Grava uma cópia a cada
  `recuperacao/intervalo` minutos **só quando há mudanças não salvas** (e antes de exportar e de importar:
  `MainWindow._recovery_point`), guarda a fila de exportação sempre que ela muda e renova o sinal de vida
  da sessão. Tudo na thread principal: o projeto em JSON é pequeno (sem miniatura) e a gravação é atômica,
  sem travar a tela.
- `RecoveryDialog`: "O PeliculaConverter fechou inesperadamente", com **Recuperar** / **Abrir o salvo**
  (só se havia um .plc) / **Descartar**, a hora da cópia, o nome do projeto, as exportações interrompidas
  e o relatório do travamento (copiar).

Recuperar abre o projeto da cópia com o estado da tela (modo, quadro, seleção, zoom da linha do tempo),
marcado como modificado: "Salvar" grava no .plc original (ou pede um nome, se ele nunca foi salvo).
Com o módulo `recuperacao` desligado nada é copiado nem perguntado (o registro de travamentos continua).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from .. import APP_NAME, crashlog, export, modules, recovery
from ..i18n import _
from . import icons, theme
from .crash_dialog import CrashUi

MODULE = "recuperacao"
RECOVER, OPEN_SAVED, DISCARD, LATER = "recuperar", "abrir_salvo", "descartar", ""


def when_text(ts: float) -> str:
    """Data e hora no formato do idioma do app (o mesmo da lista de projetos recentes)."""
    from .welcome import short_datetime
    return short_datetime(ts) or "?"


def ui_state(win) -> dict:
    """Estado da tela que vale a pena voltar: modo, quadro, comparação, seleção e vista da linha do tempo."""
    st = {"modo": win.mode, "quadro": int(win.frame_idx), "comparacao": getattr(win.viewer, "mode", "split"),
          "selecao": [str(i) for i in getattr(win.model, "selection", [])]}
    canvas = getattr(getattr(win, "tl_editor", None), "canvas", None)
    if canvas is not None:
        st["linha_zoom"] = float(getattr(canvas, "ppf", 0.0) or 0.0)
        st["linha_rolagem"] = float(getattr(canvas, "scroll", 0.0) or 0.0)
    return st


def restore_ui_state(win, ui: dict) -> None:
    sel = [i for i in ui.get("selecao") or [] if isinstance(i, str)]
    if sel:
        win.model.select(sel)
    canvas = getattr(getattr(win, "tl_editor", None), "canvas", None)
    try:
        if canvas is not None and float(ui.get("linha_zoom") or 0) > 0:
            canvas.set_ppf(float(ui["linha_zoom"]))
            canvas.set_scroll(float(ui.get("linha_rolagem") or 0.0))
    except (TypeError, ValueError):
        pass


def project_name(data: dict) -> str:
    original = str(data.get("projeto_original") or "")
    return Path(original).stem if original else (str(data.get("nome") or "") or _("Edição sem título"))


class RecoveryController(QObject):
    """Cópias automáticas e fila guardada da janela (veja o topo do arquivo)."""

    def __init__(self, window, settings, session: recovery.Session, logs: Path | None = None):
        super().__init__(window)
        self.window = window
        self.settings = settings
        self.session = session
        self.logs = logs
        self.saves = 0
        self._last_key: str | None = None
        self._queue_sig: tuple | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.autosave)
        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(1000)
        self.queue_timer.timeout.connect(self.persist_queue)
        self.beat_timer = QTimer(self)
        self.beat_timer.setInterval(recovery.BEAT_INTERVAL * 1000)
        self.beat_timer.timeout.connect(session.beat)
        self.beat_timer.start()
        window.recovery = self
        window.settings_changed.connect(self._settings_changed)
        self.apply_settings()

    # ------------------------------------------------------------ preferências
    def enabled(self) -> bool:
        return modules.is_enabled(self.settings, MODULE)

    def apply_settings(self) -> None:
        self.timer.setInterval(recovery.interval_minutes(self.settings) * 60_000)
        if self.enabled():
            if not self.timer.isActive():
                self.timer.start()
            if not self.queue_timer.isActive():
                self.queue_timer.start()
        else:
            self.timer.stop()
            self.queue_timer.stop()
            self.session.clear_copies()
            self.session.save_queue([])
            self._last_key = None
            self._queue_sig = None

    def _settings_changed(self, key: str) -> None:
        if key in ("modulos", MODULE):
            self.apply_settings()

    # ------------------------------------------------------------ cópias
    def payload(self) -> dict:
        w = self.window
        p = w._make_project(backup=True)  # sem miniatura e sem fechar o passo de desfazer em andamento
        p.thumbnail_jpeg = b""
        p.path = ""  # caminhos absolutos: a cópia não mora ao lado do projeto
        p.media_path = os.path.abspath(p.media_path) if p.media_path else ""
        original = str(w.project_path or "")
        if original:
            name = Path(original).stem
        elif getattr(w, "file_info", None) is not None and w._seq_json() is None:
            name = Path(w.file_info.path).name
        else:
            name = _("Edição sem título")
        return recovery.make_payload(p.to_json(), original, ui_state(w), name, self.session.id)

    def autosave(self, force: bool = False) -> Path | None:
        """Grava uma cópia se há mudanças não salvas e algo mudou desde a última cópia. Devolve o arquivo.

        Sem mudanças não salvas (salvou, descartou ou voltou ao estado salvo) as cópias desta janela saem:
        não há nada a recuperar, e uma cópia velha não pode parecer mais nova que o .plc."""
        if not self.enabled():
            return None
        w = self.window
        if w.info is None or (not force and not w.is_dirty()):
            if self._last_key is not None:
                self.session.clear_copies()
                self._last_key = None
            return None
        try:
            data = self.payload()
            proj = {k: v for k, v in data["projeto"].items() if k != "salvo_em"}
            key = json.dumps([proj, data["interface"], data["projeto_original"]], sort_keys=True)
        except Exception:  # noqa: BLE001 — uma cópia que não deu certo nunca atrapalha a edição
            return None
        if not force and key == self._last_key:
            return None
        try:
            path = self.session.autosave(data, recovery.versions(self.settings))
        except OSError:
            return None
        self._last_key = key
        self.saves += 1
        return path

    def checkpoint(self) -> None:
        """Antes de exportar e de importar e depois de salvar: a cópia agora (ou nenhuma, sem mudanças) e a
        fila."""
        if self.enabled():
            self.autosave()
            self.persist_queue()

    def delete_copies(self) -> int:
        """Botão "Apagar cópias" (Configurações › Recuperação): as desta janela e as de sessões que travaram.
        A próxima mudança volta a ser copiada."""
        n = recovery.delete_copies(self.session.root, self.session.id)
        self._last_key = None
        return n

    # ------------------------------------------------------------ fila de exportação
    def persist_queue(self) -> bool:
        """Guarda as exportações esperando ou rodando quando a fila muda. True se gravou."""
        if not self.enabled():
            return False
        active = [j for j in list(self.window.queue.jobs) if j.status in ("aguardando", "exportando")]
        sig = tuple((j.id, j.status) for j in active)
        if sig == self._queue_sig:
            return False
        try:
            self.session.save_queue([j.to_dict() for j in active])
        except (OSError, TypeError, ValueError):
            return False
        self._queue_sig = sig
        return True

    def requeue(self, items: list[dict]) -> tuple[int, int]:
        """Põe de volta na fila as exportações interrompidas (recomeçam do início). (postas, puladas)"""
        done = skipped = 0
        for d in items:
            try:
                job = export.ExportJob.from_dict(d)
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue
            if any(not os.path.exists(p) for p in export.job_inputs(job.info, job.sequence)):
                skipped += 1
                continue
            self.window.queue.add(job)
            done += 1
        if done:
            self.window.show_queue()
        return done, skipped

    @staticmethod
    def discard_partials(items: list[dict]) -> int:
        """Apaga os parciais que sobraram das exportações interrompidas — só os desta fila guardada (o nome do
        parcial sai do destino de cada uma); nenhuma pasta é varrida."""
        n = 0
        for d in items:
            try:
                s = export.ExportSettings.from_dict(d.get("config") or {})
                out = str(d.get("saida") or "")
                if out and os.path.exists(export.partial_output(out, s)):
                    export._discard_output(out, s)
                    n += 1
            except (OSError, TypeError, ValueError):
                continue
        return n

    # ------------------------------------------------------------ depois de um travamento
    def startup(self) -> str:
        """Ao abrir: trata a sessão que travou. Devolve a escolha ("recuperar", "abrir_salvo", "descartar"
        ou "" quando não havia nada a perguntar ou a pessoa deixou para depois)."""
        try:
            crashed = recovery.scan(self.session.root, self.session.id, self.logs)
            crashlog.prune(self.logs if self.logs is not None else crashlog.logs_dir(),
                           recovery.live_sessions(self.session.root))
        except OSError:
            return LATER
        for c in crashed:
            if not c.has_content:
                recovery.forget(c)  # nada a recuperar (o relatório do travamento fica na pasta de logs)
        pending = [c for c in crashed if c.has_content]
        if not pending or not self.enabled():
            return LATER
        return self.resolve(pending[0])

    def resolve(self, c: recovery.Crashed) -> str:
        data = c.latest()
        choice, requeue = self.ask(c, data)
        if choice == LATER:
            return LATER
        if choice == RECOVER and data is not None and not self.restore(data):
            return LATER  # a cópia fica para a próxima vez
        self.discard_partials(c.queue)
        if choice == OPEN_SAVED and data is not None and data.get("projeto_original"):
            self.window.open_project(str(data["projeto_original"]))
        if requeue and c.queue:
            self.requeue(c.queue)
        recovery.forget(c)
        return choice

    def ask(self, c: recovery.Crashed, data: dict | None) -> tuple[str, bool]:
        """O aviso (substituível nos testes). (escolha, pôr as exportações de volta na fila)"""
        dlg = RecoveryDialog(self.window, c, data)
        dlg.exec()
        return dlg.choice, dlg.requeue

    def restore(self, data: dict) -> bool:
        """Abre o projeto de uma cópia, marcado como modificado ("Salvar" vai para o .plc original)."""
        w = self.window
        try:
            p, original, ui = recovery.project_from_copy(data)
            w.show_project(p, remember=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(w, APP_NAME, _("Não foi possível recuperar a cópia de segurança. Ela continua guardada "
                                               "para uma nova tentativa.\n\n{erro}").format(erro=exc))
            return False
        w.project_path = original or None
        w._saved_state = {}  # modificado: "Salvar" grava no .plc original (ou pede um nome)
        restore_ui_state(w, ui)
        w._update_title()
        w.statusBar().showMessage(_("Projeto recuperado da cópia de {hora}. Salve para guardar no arquivo.").format(
            hora=when_text(float(data.get("salvo_em") or 0))), 12000)
        self.autosave(force=True)  # a sessão nova já guarda o trabalho recuperado
        return True

    def stop(self) -> None:
        for t in (self.timer, self.queue_timer, self.beat_timer):
            t.stop()

    def close(self) -> None:
        """Fechamento normal do app: a sessão some com as cópias (só servem depois de um travamento)."""
        self.stop()
        self.session.close()


class Guard:
    """Sessão + registro de travamentos de uma execução do app (veja o topo do arquivo)."""

    def __init__(self, session: recovery.Session, crash: crashlog.CrashLog):
        self.session = session
        self.crash = crash
        self.controller: RecoveryController | None = None
        self.crash_ui: CrashUi | None = None

    @classmethod
    def start(cls, root: Path | None = None, logs: Path | None = None) -> "Guard":
        session = recovery.Session(root).start()
        return cls(session, crashlog.CrashLog(logs, session.id).install())

    def close(self) -> None:
        """Fechamento normal: marcador, cópias, fila guardada e o falha-*.log vazio somem."""
        try:
            if self.controller is not None:
                self.controller.stop()
        except RuntimeError:
            pass  # a janela (e o controlador, filho dela) já foi destruída
        self.session.close()
        self.crash.close()


def attach(window, settings, guard: Guard) -> RecoveryController:
    """Liga a janela recém-criada à sessão: cópias automáticas, fila guardada e o aviso de erro inesperado."""
    try:
        guard.crash.gpu = str(window.engine.renderer)
    except Exception:  # noqa: BLE001
        pass
    guard.crash_ui = CrashUi(guard.crash, lambda: window, window)
    guard.controller = RecoveryController(window, settings, guard.session, guard.crash.folder)
    return guard.controller


class RecoveryDialog(QDialog):
    """O aviso depois de um travamento. `choice` e `requeue` dizem o que a pessoa escolheu."""

    def __init__(self, parent, crashed: recovery.Crashed, data: dict | None):
        super().__init__(parent)
        self.crashed = crashed
        self.data = data
        self.choice = LATER
        self.requeue = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        head = QLabel(_("O PeliculaConverter fechou inesperadamente"))
        head.setObjectName("PanelTitle")
        head.setStyleSheet("font-size: 13pt;")
        head.setWordWrap(True)
        lay.addWidget(head)

        original = str((data or {}).get("projeto_original") or "")
        if data is not None:
            text = _("Há uma cópia de segurança de \"{nome}\" de {hora}, com o trabalho que ainda não estava salvo."
                     ).format(nome=project_name(data), hora=when_text(float(data.get("salvo_em") or 0)))
            if original and os.path.isfile(original):
                text += " " + _("O projeto salvo continua como estava em {caminho}.").format(caminho=original)
        else:
            text = _("Não havia mudanças sem salvar para recuperar.")
        self.info = QLabel(text)
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info)

        self.chk_queue = None
        if crashed.queue:
            self.chk_queue = QCheckBox(_("Pôr de volta na fila as {n} exportações interrompidas (elas recomeçam do "
                                         "início)").format(n=len(crashed.queue)))
            self.chk_queue.setChecked(True)
            lay.addWidget(self.chk_queue)

        self.report_box = None
        if crashed.report:
            box = QFrame()
            box.setObjectName("ReportBox")
            box.setStyleSheet(f"QFrame#ReportBox {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
                              f" border-radius: 10px; }}")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 10, 12, 10)
            row = QHBoxLayout()
            lbl = QLabel(_("Relatório do travamento (fica só neste computador)"))
            lbl.setObjectName("Muted")
            row.addWidget(lbl, 1)
            self.btn_copy = QPushButton(_("Copiar relatório"))
            self.btn_copy.clicked.connect(self.copy_report)
            row.addWidget(self.btn_copy)
            bl.addLayout(row)
            self.report_box = QPlainTextEdit(crashed.report)
            self.report_box.setReadOnly(True)
            self.report_box.setFont(theme.mono_font(8.5))
            self.report_box.setFixedHeight(140)
            bl.addWidget(self.report_box)
            lay.addWidget(box)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_discard = QPushButton(_("Descartar"))
        self.btn_discard.setToolTip(_("Apaga a cópia de segurança"))
        self.btn_discard.clicked.connect(lambda: self._done(DISCARD))
        buttons.addWidget(self.btn_discard)
        self.btn_saved = QPushButton(_("Abrir o salvo"))
        self.btn_saved.setToolTip(_("Abre o projeto como foi salvo pela última vez e apaga a cópia de segurança"))
        self.btn_saved.clicked.connect(lambda: self._done(OPEN_SAVED))
        self.btn_saved.setVisible(bool(original) and os.path.isfile(original))
        buttons.addWidget(self.btn_saved)
        self.btn_recover = QPushButton(_("Recuperar"))
        self.btn_recover.setObjectName("Primary")
        self.btn_recover.clicked.connect(lambda: self._done(RECOVER))
        self.btn_recover.setVisible(data is not None)
        buttons.addWidget(self.btn_recover)
        if data is None:
            self.btn_discard.setText(_("Continuar"))
        lay.addLayout(buttons)
        (self.btn_recover if data is not None else self.btn_discard).setDefault(True)

    def copy_report(self) -> None:
        QGuiApplication.clipboard().setText(self.crashed.report)
        self.btn_copy.setText(_("Copiado"))

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.requeue = bool(self.chk_queue is not None and self.chk_queue.isChecked())
        self.accept()
