"""Casos da recuperação automática na interface (rodados por test_recovery_ui.py num subprocesso offscreen).

A pasta do app (`LOCALAPPDATA`/`XDG_DATA_HOME`) e as preferências apontam para pastas temporárias; nada abre
o gerenciador de arquivos de verdade (`system` substituído). Os casos com a `MainWindow` pulam sem
OpenGL 3.3 (CI) ou sem ffprobe (a cena de teste é aberta como um arquivo de verdade).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_recovery_ui_")
_DATA = Path(tempfile.mkdtemp(prefix="pelicula_recovery_data_"))
os.environ["LOCALAPPDATA"] = str(_DATA / "local")
os.environ["XDG_DATA_HOME"] = str(_DATA / "local")
os.environ["APPDATA"] = str(_DATA / "roaming")

import pytest  # noqa: E402
from PySide6.QtCore import Signal  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import APP_NAME, crashlog, export, i18n, modules, project, recovery, system  # noqa: E402
from pelicula.ui import crash_dialog, prefs, recovery_ui  # noqa: E402
from pelicula.ui.pages import recuperacao  # noqa: E402
from pelicula.ui.settings_dialog import SettingsDialog  # noqa: E402

i18n.set_language("pt_BR")
OPENED: list[tuple[str, str]] = []
FAKE_SYSTEM = types.SimpleNamespace(reveal=lambda p: OPENED.append(("reveal", str(p))),
                                    open_path=lambda p: OPENED.append(("open", str(p))))
crash_dialog.system = FAKE_SYSTEM
recuperacao.system = FAKE_SYSTEM


def pump(cond=lambda: False, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def clean_settings():
    s = prefs.settings()
    for key in list(s.allKeys()):
        if key.startswith(("recuperacao/", "modulos/")):
            s.remove(key)
    return s


def tmpdir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=_DATA))


def write_marker(root: Path, sid: str, pid: int = 0):
    """Marcador de uma sessão que não fechou direito (pid 0 = processo que não existe)."""
    m = root / recovery.SESSIONS / f"{sid}.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"app": APP_NAME, "sessao": sid, "pid": pid, "inicio": time.time() - 60,
                             "versao_app": "1.3.1"}), encoding="utf-8")
    return m


def job_dict(tmp: Path, status="exportando", codec="x264", name="saida.mp4", source=None) -> dict:
    src = source or tmp / "fonte.mp4"
    Path(src).write_bytes(b"x")
    info = dict(path=str(src), width=320, height=180, fps=24.0, fps_str="24/1", frames=24, duration=1.0,
                pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="", bitrate=0, color_space="bt709",
                color_range="tv", color_transfer="bt709", color_primaries="bt709", has_audio=False,
                audio_codec="", container="mp4", is_image=False)
    s = export.ExportSettings(codec=codec, container="png" if codec == "png_seq" else "mp4")
    return {"id": "j", "nome": name, "status": status, "saida": str(tmp / name), "inicio": 0, "fim": -1,
            "valores": {}, "config": s.to_dict(), "midia": info, "edicao": None}


class FakeQueue:
    def __init__(self):
        self.jobs: list = []

    def add(self, job):
        self.jobs.append(job)


class FakeWindow(QWidget):
    """O que o RecoveryController usa da janela, sem OpenGL."""

    settings_changed = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.queue = FakeQueue()
        self.info = None
        self.queue_shown = 0
        self.opened: list[str] = []

    def show_queue(self):
        self.queue_shown += 1

    def open_project(self, path):
        self.opened.append(path)


def controller(window=None, root=None, logs=None):
    s = clean_settings()
    w = window or FakeWindow(s)
    session = recovery.Session(root or tmpdir("rec_")).start()
    ctl = recovery_ui.RecoveryController(w, s, session, logs or tmpdir("logs_"))
    return ctl, w, s


# ------------------------------------------------------------------ fila guardada
def test_queue_is_persisted_only_when_it_changes():
    ctl, w, s = controller()
    tmp = tmpdir("fila_")
    job = export.ExportJob.from_dict(job_dict(tmp, "aguardando"))
    w.queue.jobs.append(job)
    assert ctl.persist_queue() is True
    assert ctl.persist_queue() is False  # nada mudou: não grava de novo
    saved = recovery.read_queue(ctl.session.folder)
    assert [d["saida"] for d in saved] == [job.out_path] and saved[0]["status"] == "aguardando"
    job.status = "exportando"
    assert ctl.persist_queue() is True
    job.status = "concluido"
    assert ctl.persist_queue() is True
    assert recovery.read_queue(ctl.session.folder) == [] and not (ctl.session.folder / recovery.QUEUE_FILE).exists()
    modules.set_enabled(s, "recuperacao", False)
    w.settings_changed.emit("modulos")
    job.status = "aguardando"
    assert ctl.persist_queue() is False and not ctl.queue_timer.isActive() and not ctl.timer.isActive()
    ctl.close()


def test_requeue_restarts_jobs_whose_files_still_exist():
    ctl, w, _s = controller()
    tmp = tmpdir("requeue_")
    ok = job_dict(tmp, name="a.mp4")
    gone = job_dict(tmp, name="b.mp4", source=tmp / "sumiu.mp4")
    os.remove(gone["midia"]["path"])
    assert ctl.requeue([ok, gone, {"lixo": 1}]) == (1, 2)
    assert len(w.queue.jobs) == 1 and w.queue.jobs[0].status == "aguardando" and w.queue_shown == 1
    assert w.queue.jobs[0].out_path == ok["saida"]
    ctl.close()


def test_discard_partials_only_of_the_saved_queue():
    tmp = tmpdir("parciais_")
    video = job_dict(tmp, name="filme.mp4")
    part = Path(system.partial_path(video["saida"]))
    part.write_bytes(b"meio arquivo")
    final = Path(video["saida"])
    final.write_bytes(b"antigo")  # o arquivo antigo com o nome final fica
    seq = job_dict(tmp, codec="png_seq", name="quadros.png")
    folder = Path(export.partial_output(seq["saida"], export.ExportSettings.from_dict(seq["config"])))
    folder.mkdir()
    (folder / "quadros_000001.png").write_bytes(b"x")
    other = tmp / f"outro.{system.PARTIAL}.mp4"
    other.write_bytes(b"de outra exportacao")
    assert recovery_ui.RecoveryController.discard_partials([video, seq, {"saida": ""}]) == 2
    assert not part.exists() and not folder.exists() and final.read_bytes() == b"antigo" and other.exists()


# ------------------------------------------------------------------ ao abrir depois de um travamento
def crashed_session(root: Path, logs: Path, sid="20260101000000dead0001", with_copy=True, queue=None,
                    original="") -> recovery.Session:
    s = recovery.Session(root, sid)
    if with_copy:
        data = project.Project(media_path=str(root / "v.mp4"), frame=5).to_json()
        s.autosave(recovery.make_payload(data, original, {"modo": "pelicula"}, "v.mp4", sid))
    if queue:
        s.save_queue(queue)
    write_marker(root, sid)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"falha-{sid}.log").write_text("Fatal Python error: Segmentation fault\n", encoding="utf-8")
    return s


def test_startup_discard_removes_the_copies_and_partials():
    root, logs = tmpdir("rec_"), tmpdir("logs_")
    tmp = tmpdir("job_")
    item = job_dict(tmp)
    part = Path(system.partial_path(item["saida"]))
    part.write_bytes(b"x")
    dead = crashed_session(root, logs, queue=[item])
    ctl, w, _s = controller(root=root, logs=logs)
    asked = []
    ctl.ask = lambda c, data: asked.append((c, data)) or (recovery_ui.DISCARD, False)
    assert ctl.startup() == recovery_ui.DISCARD
    c, data = asked[0]
    assert c.session == dead.id and data["nome"] == "v.mp4" and "Segmentation fault" in c.report
    assert not dead.folder.exists() and not part.exists() and w.queue.jobs == []
    assert recovery.scan(root, ctl.session.id, logs) == []
    assert ctl.startup() == recovery_ui.LATER and len(asked) == 1  # nada mais a perguntar
    ctl.close()


def test_startup_can_requeue_and_open_the_saved_project():
    root, logs = tmpdir("rec_"), tmpdir("logs_")
    tmp = tmpdir("job_")
    plc = tmp / "salvo.plc"
    plc.write_text("{}", encoding="utf-8")
    crashed_session(root, logs, queue=[job_dict(tmp)], original=str(plc))
    ctl, w, _s = controller(root=root, logs=logs)
    ctl.ask = lambda c, data: (recovery_ui.OPEN_SAVED, True)
    assert ctl.startup() == recovery_ui.OPEN_SAVED
    assert w.opened == [str(plc)] and len(w.queue.jobs) == 1 and w.queue.jobs[0].status == "aguardando"
    ctl.close()


def test_startup_later_keeps_everything_and_module_off_does_not_ask():
    root, logs = tmpdir("rec_"), tmpdir("logs_")
    dead = crashed_session(root, logs)
    ctl, _w, s = controller(root=root, logs=logs)
    ctl.ask = lambda c, data: (recovery_ui.LATER, False)
    assert ctl.startup() == recovery_ui.LATER and dead.folder.exists()
    modules.set_enabled(s, "recuperacao", False)
    ctl.ask = lambda c, data: pytest.fail("não devia perguntar com o módulo desligado")
    assert ctl.startup() == recovery_ui.LATER and dead.folder.exists()
    ctl.close()


def test_startup_forgets_crashes_without_anything_to_recover():
    root, logs = tmpdir("rec_"), tmpdir("logs_")
    dead = crashed_session(root, logs, with_copy=False)
    ctl, _w, _s = controller(root=root, logs=logs)
    ctl.ask = lambda c, data: pytest.fail("nada a recuperar: sem pergunta")
    assert ctl.startup() == recovery_ui.LATER
    assert not (root / recovery.SESSIONS / f"{dead.id}.json").exists()
    assert (logs / f"falha-{dead.id}.log").exists()  # o relatório do travamento fica (Configurações › Recuperação)
    ctl.close()


# ------------------------------------------------------------------ aviso depois do travamento
def crashed_with(tmp: Path, original="", queue=None, report="") -> tuple[recovery.Crashed, dict]:
    data = recovery.make_payload(project.Project().to_json(), original, {}, "clipe.mp4", "x")
    data["salvo_em"] = time.mktime((2026, 10, 22, 14, 30, 0, 0, 0, -1))
    c = recovery.Crashed(session="x", folder=tmp, queue=list(queue or []), report=report)
    return c, data


def test_dialog_offers_the_three_choices():
    tmp = tmpdir("dlg_")
    plc = tmp / "meu projeto.plc"
    plc.write_text("{}", encoding="utf-8")
    c, data = crashed_with(tmp, str(plc), queue=[{"id": 1}, {"id": 2}], report="Fatal Python error: abort")
    dlg = recovery_ui.RecoveryDialog(None, c, data)
    assert dlg.windowTitle() == APP_NAME
    assert "meu projeto" in dlg.info.text() and "14:30" in dlg.info.text()
    assert not dlg.btn_recover.isHidden() and not dlg.btn_saved.isHidden() and dlg.btn_discard.text() == "Descartar"
    assert "2 exportações interrompidas" in dlg.chk_queue.text() and "recomeçam do início" in dlg.chk_queue.text()
    assert dlg.report_box is not None and "abort" in dlg.report_box.toPlainText()
    dlg.copy_report()
    assert QGuiApplication.clipboard().text() == "Fatal Python error: abort" and dlg.btn_copy.text() == "Copiado"
    dlg.btn_recover.click()
    assert (dlg.choice, dlg.requeue) == (recovery_ui.RECOVER, True)


def test_dialog_without_saved_file_or_copy():
    tmp = tmpdir("dlg_")
    c, data = crashed_with(tmp, str(tmp / "apagado.plc"))
    dlg = recovery_ui.RecoveryDialog(None, c, data)
    assert dlg.btn_saved.isHidden() and dlg.chk_queue is None and dlg.report_box is None
    assert "apagado" in dlg.info.text() and "continua como estava" not in dlg.info.text()
    dlg.btn_discard.click()
    assert (dlg.choice, dlg.requeue) == (recovery_ui.DISCARD, False)
    c, _data = crashed_with(tmp, queue=[{"id": 1}])
    dlg = recovery_ui.RecoveryDialog(None, c, None)
    assert dlg.btn_recover.isHidden() and dlg.btn_discard.text() == "Continuar"
    dlg.chk_queue.setChecked(False)
    dlg.btn_discard.click()
    assert (dlg.choice, dlg.requeue) == (recovery_ui.DISCARD, False)
    assert recovery_ui.project_name({"nome": ""}) == "Edição sem título"


# ------------------------------------------------------------------ erro inesperado
class FakeDialog:
    def __init__(self, log, text):
        self.log, self.text = log, text

    def exec(self):
        self.log.append((self.text, threading.current_thread() is threading.main_thread()))
        return 0


def boom():
    raise RuntimeError("falha de teste")


def test_unhandled_errors_show_a_dialog_on_the_main_thread():
    crash = crashlog.CrashLog(tmpdir("logs_"), "s1")
    win = QWidget()
    ui = crash_dialog.CrashUi(crash, lambda: win)
    shown = []
    ui.make_dialog = lambda text, path: FakeDialog(shown, text)

    def worker():
        try:
            boom()
        except RuntimeError as exc:
            crash.handle(type(exc), exc, exc.__traceback__, where="thread x", main_thread=False)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert pump(lambda: shown)
    assert shown[0][1] is True and "falha de teste" in shown[0][0]
    for _i in range(5):
        crash.handle(RuntimeError, RuntimeError("de novo"), None)
    pump(timeout=0.3)
    assert len(shown) == crash_dialog.MAX_DIALOGS  # os outros ficam só no arquivo
    assert len(list(crash.folder.iterdir())) == 6


def test_error_dialog_copies_and_opens_the_folder():
    folder = tmpdir("logs_")
    report = folder / "erro-1-s.txt"
    report.write_text("relatório", encoding="utf-8")
    dlg = crash_dialog.ErrorDialog(None, "Traceback: x", str(report))
    assert dlg.details.toPlainText() == "Traceback: x"
    dlg.copy()
    assert QGuiApplication.clipboard().text() == "Traceback: x"
    OPENED.clear()
    dlg.open_folder()
    assert OPENED == [("reveal", str(report))]
    crash_dialog.ErrorDialog(None, "x", "").open_folder()
    assert OPENED[-1] == ("open", str(crashlog.logs_dir()))


def test_guard_start_and_clean_close():
    root, logs = tmpdir("rec_"), tmpdir("logs_")
    guard = recovery_ui.Guard.start(root, logs)
    try:
        assert guard.session.marker.exists() and guard.crash.fault_file.exists()
    finally:
        guard.close()
    assert not guard.session.marker.exists() and not guard.crash.fault_file.exists()
    assert recovery.scan(root, logs=logs) == []


# ------------------------------------------------------------------ Configurações › Recuperação
def page(main=None):
    dlg = SettingsDialog(None, prefs.settings(), "recuperacao", main=main)
    seen: list[str] = []
    dlg.settings_changed.connect(seen.append)
    return dlg, dlg.page("recuperacao"), seen


def test_page_writes_interval_and_versions():
    s = clean_settings()
    _dlg, p, seen = page()
    assert p.cmb_interval.currentData() == 1 and p.spin_versions.value() == 5
    p.cmb_interval.setCurrentIndex(p.cmb_interval.findData(5))
    p.spin_versions.setValue(9)
    assert recovery.interval_minutes(s) == 5 and recovery.versions(s) == 9
    assert seen == ["recuperacao", "recuperacao"]


def test_page_with_the_window_controller_deletes_copies_and_shows_the_report():
    ctl, w, s = controller()
    w.recovery = ctl
    ctl.session.autosave(recovery.make_payload({"app": APP_NAME}, "", {}, "", ctl.session.id))
    other = recovery.Session(ctl.session.root, "outra")
    other.autosave(recovery.make_payload({"app": APP_NAME}, "", {}, "", "outra"))
    write_marker(ctl.session.root, "outra")  # sessão que travou
    report = ctl.logs / "falha-outra.log"
    report.write_text("Windows fatal exception: access violation", encoding="utf-8")
    _dlg, p, _seen = page(w)
    assert p.root == ctl.session.root and "2 cópia(s)" in p.usage.text()
    assert "access violation" in p.report.toPlainText() and not p.report.isHidden()
    p.copy_report()
    assert "access violation" in QGuiApplication.clipboard().text()
    OPENED.clear()
    p.open_logs()
    assert OPENED == [("reveal", str(report))]
    p.open_folder()
    assert OPENED[-1] == ("open", str(ctl.session.root))
    p._confirm = lambda title, text: False
    assert p.delete_copies() == 0 and recovery.usage(ctl.session.root)[0] == 2
    p._confirm = lambda title, text: True
    assert p.delete_copies() == 2 and recovery.usage(ctl.session.root)[0] == 0
    assert "Nenhuma cópia" in p.usage.text() and not p.btn_delete.isEnabled()
    assert ctl.session.marker.exists()
    ctl.close()


def test_page_explains_when_the_module_is_off():
    s = clean_settings()
    modules.set_enabled(s, "recuperacao", False)
    _dlg, p, seen = page()
    assert not p.off_box.isHidden() and not p.options.isEnabled()
    assert p.btn_copy.isEnabled() or p.report.isHidden()  # o relatório não depende do módulo
    p.off_box.btn.click()
    assert modules.is_enabled(s, "recuperacao") and seen == ["modulos"]
    assert p.off_box.isHidden() and p.options.isEnabled()


# ------------------------------------------------------------------ janela principal (OpenGL)
@pytest.fixture(scope="module")
def win():
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    s = clean_settings()
    s.setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def load_scene(w):
    w.open_test_scene()
    if not pump(lambda: w.info is not None, 15):
        pytest.skip("não foi possível abrir a cena de teste (ffprobe?)")
    w.project_path = None
    w._saved_state = w._state()
    w._update_title()


def test_window_starts_without_recovery_and_with_a_silent_notifier(win):
    from pelicula.ui import notifier
    assert win.recovery is None and isinstance(win.notifier.backend, notifier.NullBackend)
    win._recovery_point()  # sem controlador: não faz nada


def test_autosave_only_with_unsaved_changes(win):
    load_scene(win)
    ctl, _w, s = controller(window=win)
    try:
        assert ctl.autosave() is None  # nada mudou desde que abriu
        win.store.set("grao_forca", 1.9)
        hist = list(win.store._hist)
        path = ctl.autosave()
        assert path is not None and win.store._hist == hist  # não fecha o passo de desfazer em andamento
        data = recovery.read_copy(path)
        assert data["projeto"]["valores"]["grao_forca"] == 1.9 and data["projeto"]["miniatura_jpeg"] == ""
        assert os.path.isabs(data["projeto"]["midia"]["caminho"]) and data["projeto_original"] == ""
        assert data["interface"]["modo"] == "pelicula" and "quadro" in data["interface"]
        assert ctl.autosave() is None  # igual à última cópia
        win._recovery_point()  # sem `win.recovery` ligado ainda
        win.recovery = ctl
        win.store.set("grao_forca", 1.2)
        win._recovery_point()
        assert len(ctl.session.copies()) == 2
        s.setValue(recovery.KEY_VERSIONS, 1)
        win.store.set("grao_forca", 1.3)
        ctl.autosave()
        assert len(ctl.session.copies()) == 1
        modules.set_enabled(s, "recuperacao", False)
        win.settings_changed.emit("modulos")
        assert ctl.session.copies() == []  # desligado: as cópias desta janela saem
        win.store.set("grao_forca", 1.4)
        assert ctl.autosave() is None
    finally:
        win.recovery = None
        ctl.close()
        clean_settings()


def test_recover_restores_the_project_marked_as_modified(win):
    load_scene(win)
    tmp = tmpdir("plc_")
    plc = tmp / "trabalho.plc"
    win.store.set("grao_forca", 0.7)
    assert win._write_project(str(plc))
    saved_frame = win.frame_idx
    win.store.set("grao_forca", 1.6)  # mudança não salva
    win.request_frame(min(3, win.info.frames - 1))
    root, logs = tmpdir("rec_"), tmpdir("logs_")
    old, _w, _s = controller(window=win, root=root, logs=logs)
    old.session.id = "20260101000000dead0002"  # a "sessão que travou"
    path = old.autosave()
    assert path is not None
    old.stop()
    write_marker(root, old.session.id)
    # Fecha o projeto e "abre o app de novo".
    win.project_path = None
    win.store.set_all(recovery.read_copy(path)["projeto"]["valores"] | {"grao_forca": 0.1})
    ctl, _w, _s = controller(window=win, root=root, logs=logs)
    ctl.ask = lambda c, data: (recovery_ui.RECOVER, False)
    try:
        assert ctl.startup() == recovery_ui.RECOVER
        assert win.store.get("grao_forca") == 1.6
        assert win.project_path is not None and os.path.samefile(win.project_path, plc)
        assert win.is_dirty() and "•" in win.windowTitle()
        assert not (root / old.session.id).exists()
        assert len(ctl.session.copies()) == 1  # a sessão nova já guarda o trabalho recuperado
        assert win.save_project()
        assert json.loads(plc.read_text(encoding="utf-8"))["valores"]["grao_forca"] == 1.6
        assert not win.is_dirty() and saved_frame >= 0
    finally:
        ctl.close()


def test_export_finished_notifies_through_the_window(win):
    load_scene(win)
    n = win.notifier
    n.focus_override = False
    n.beep = lambda: None
    alerts = []
    n.alert = alerts.append
    clean_settings()
    job = export.ExportJob(info=win.info, values={}, settings=export.ExportSettings(),
                           out_path=str(tmpdir("out_") / "final.mp4"), name="final.mp4")
    job.status = "concluido"
    win.queue.jobs.append(job)  # sem passar pela thread de exportação
    try:
        win._queue_tick()
        kinds = [h[0].kind for h in n.history]
        assert kinds[-1] == "exportacao_concluida" and n.history[-1][0].target == job.out_path
        assert alerts == [win]
        win._queue_tick()
        assert len(n.history) == len(kinds)  # cada exportação avisa uma vez só
    finally:
        win.queue.jobs.remove(job)
        n.focus_override = None


def test_recover_an_edit_mode_montage_with_its_view(win):
    load_scene(win)
    scene = win.file_info.path
    win.project_path = None
    win.set_mode("edicao")
    win.import_paths([scene])  # a cena no fim: a montagem deixa de ser "o arquivo inteiro"
    assert pump(lambda: len(win.model.seq.clips) >= 2, 10)
    clip = win.model.seq.clips[-1].id
    win.model.select([clip])
    canvas = win.tl_editor.canvas
    canvas.set_ppf(canvas.ppf * 2)
    canvas.set_scroll(5)
    view = (canvas.ppf, canvas.scroll)
    ctl, _w, _s = controller(window=win)
    try:
        data = recovery.read_copy(ctl.autosave())
        assert data["projeto"]["edicao"]["clipes"] and data["projeto"]["modo"] == "edicao"
        assert data["interface"]["selecao"] == [clip] and data["interface"]["modo"] == "edicao"
        clips = [c.to_json() for c in win.model.seq.clips]
        win.new_project()
        win.set_mode("pelicula")
        assert not win.model.seq.clips
        assert ctl.restore(data)
        assert win.mode == "edicao" and [c.to_json() for c in win.model.seq.clips] == clips
        assert win.model.selection == [clip]
        assert (canvas.ppf, canvas.scroll) == pytest.approx(view)
        assert win.project_path is None and win.is_dirty() and "Edição sem título" in win.windowTitle()
    finally:
        ctl.close()
        win.new_project()
        win.set_mode("pelicula")
