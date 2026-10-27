"""Casos das notificações na interface (rodados por test_notify_ui.py num subprocesso offscreen).

Nenhuma notificação de verdade aparece: o `Notifier` usa backends falsos (que só anotam), o som e o
piscar são substituídos e o D-Bus é imitado por um objeto Qt com o método `Notify` (a mesma chamada
tipada que vai para o `org.freedesktop.Notifications`). Preferências num .ini temporário.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_notify_ui_")
_DATA = Path(tempfile.mkdtemp(prefix="pelicula_notify_data_"))
os.environ["LOCALAPPDATA"] = str(_DATA / "local")
os.environ["XDG_DATA_HOME"] = str(_DATA / "local")

from PySide6.QtCore import QObject, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import i18n, jobs, modules, notify  # noqa: E402
from pelicula.ui import notifier as nt  # noqa: E402
from pelicula.ui import prefs  # noqa: E402
from pelicula.ui.job_bridge import JobBridge  # noqa: E402
from pelicula.ui.settings_dialog import SettingsDialog  # noqa: E402

i18n.set_language("pt_BR")


class Recorder(nt.Backend):
    """Backend que só anota o que seria mostrado."""

    name = "teste"

    def __init__(self, works: bool = True):
        super().__init__()
        self.works = works
        self.shown: list[tuple[int, str, str, bool]] = []
        self.closed = False

    def show(self, token, title, body, sound):
        if not self.works:
            return False, False
        self.shown.append((token, title, body, sound))
        return True, False

    def close(self):
        self.closed = True


class Broken(nt.Backend):
    def show(self, token, title, body, sound):
        raise RuntimeError("backend com defeito")


def clean_settings():
    s = prefs.settings()
    for key in list(s.allKeys()):
        if key.startswith(("notificacoes/", "modulos/")):
            s.remove(key)
    return s


def make(window=None, focused=False, backend=None):
    s = clean_settings()
    n = nt.Notifier(window, s, backend or Recorder())
    n.focus_override = focused
    n.beeps, n.alerts, n.files, n.folders = [], [], [], []
    n.beep = lambda: n.beeps.append(1)
    n.alert = lambda w: n.alerts.append(w)
    n.open_file = n.files.append
    n.open_folder = n.folders.append
    return n, s


# ------------------------------------------------------------------ decisão na janela
def test_notifies_in_background_with_flash_and_no_sound():
    win = QWidget()
    n, _s = make(win)
    d = n.notify(notify.export_done("a.mp4", "/x/a.mp4"))
    assert d.show and n.backend.shown and n.backend.shown[0][1] == "Exportação concluída"
    assert n.alerts == [win] and n.beeps == []


def test_window_in_focus_stays_quiet():
    n, _s = make(QWidget(), focused=True)
    assert n.notify(notify.export_done("a.mp4", "/x/a.mp4")) == notify.NOTHING
    assert n.backend.shown == [] and n.alerts == [] and n.beeps == []


def test_sound_and_flash_follow_the_preferences():
    win = QWidget()
    n, s = make(win)
    notify.set_option(s, notify.KEY_SOUND, True)
    notify.set_option(s, notify.KEY_FLASH, False)
    n.notify(notify.update_available("9.9.9"))
    assert n.backend.shown[-1][3] is True  # o backend recebe o pedido de som
    assert n.beeps == [1] and n.alerts == []  # o backend não tocou: o app toca o som do sistema


def test_kind_turned_off_and_module_off():
    win = QWidget()
    n, s = make(win)
    notify.set_kind(s, notify.EXPORT_DONE, False)
    assert not n.notify(notify.export_done("a", "/x/a.mp4")).anything
    notify.set_kind(s, notify.EXPORT_DONE, True)
    modules.set_enabled(s, "notificacoes", False)
    d = n.notify(notify.export_done("a", "/x/a.mp4"))
    assert not d.show and d.flash and n.backend.shown == [] and n.alerts == [win]  # só pisca, como antes
    assert not n.notify(notify.update_available("9")).anything


def test_broken_or_missing_backend_never_crashes():
    n, _s = make(QWidget(), backend=Broken())
    assert n.notify(notify.export_done("a", "/x/a.mp4")).show
    assert n.history[-1][2] is False
    n.set_backend(nt.NullBackend())
    assert n.test() is False


def test_test_button_ignores_focus():
    n, _s = make(QWidget(), focused=True)
    assert n.test() is True
    assert n.backend.shown[-1][2] == "As notificações estão funcionando."


def test_set_backend_closes_the_old_one():
    old = Recorder()
    n, _s = make(backend=old)
    new = Recorder()
    n.set_backend(new)
    assert old.closed and old.on_click is None and new.on_click == n.activate


# ------------------------------------------------------------------ clique
def test_click_reveals_the_exported_file(tmp_path):
    f = tmp_path / "final.mp4"
    f.write_bytes(b"x")
    n, _s = make(QWidget())
    n.notify(notify.export_done("final.mp4", str(f)))
    token = n.backend.shown[-1][0]
    n.backend._clicked(token)
    assert n.files == [str(f)] and n.folders == []


def test_click_opens_a_folder_or_the_parent_of_a_missing_file(tmp_path):
    n, _s = make(QWidget())
    n.notify(notify.export_done("quadros", str(tmp_path)))
    n.backend._clicked(n.backend.shown[-1][0])
    assert n.folders == [str(tmp_path)]
    n.notify(notify.export_done("sumiu.mp4", str(tmp_path / "sumiu.mp4")))
    n.backend._clicked(n.backend.shown[-1][0])
    assert n.folders[-1] == str(tmp_path) and n.files == []


def test_click_runs_the_window_action():
    n, _s = make(QWidget())
    seen = []
    n.actions[notify.ACTION_COMPONENTS] = lambda: seen.append("componentes")
    n.notify(notify.component_done("ffmpeg"))
    n.backend._clicked(n.backend.shown[-1][0])
    n.backend._clicked(None)    # bandeja clicada sem aviso: só traz a janela
    n.backend._clicked(12345)   # aviso antigo, já esquecido
    assert seen == ["componentes"]


# ------------------------------------------------------------------ fila de exportação
def test_export_progress_notifies_each_and_then_the_summary():
    n, _s = make(QWidget())
    a = notify.Finished("concluido", "a.mp4", "/v/a.mp4")
    b = notify.Finished("concluido", "b.mp4", "/v/b.mp4")
    assert [x.kind for x in n.export_progress([a], idle=False)] == [notify.EXPORT_DONE]
    assert [x.kind for x in n.export_progress([b], idle=True)] == [notify.QUEUE_DONE]
    assert n.export_progress([], idle=True) == []
    # Fila nova: uma exportação sozinha avisa por conta própria.
    c = notify.Finished("erro", "c.mp4", error="falhou")
    assert [x.kind for x in n.export_progress([c], idle=True)] == [notify.EXPORT_FAILED]
    # "Fila concluída" desligado: a última da fila avisa por conta própria (e não some junto com o resumo).
    notify.set_kind(_s, notify.QUEUE_DONE, False)
    assert [x.kind for x in n.export_progress([a], idle=False)] == [notify.EXPORT_DONE]
    assert [x.kind for x in n.export_progress([b], idle=True)] == [notify.EXPORT_DONE]


# ------------------------------------------------------------------ componentes (fila de tarefas)
def test_component_downloads_notify_through_the_job_bridge():
    q = jobs.JobQueue()
    b = JobBridge(q)
    n, _s = make(QWidget())
    n.watch_jobs(b)
    done = b.submit(lambda j: "ok", "Baixar", kind=jobs.REDE, key="componente:ffmpeg",
                    data={"tool": "ffmpeg", "acao": "baixar"})
    def fail(j):
        raise RuntimeError("SHA-256 não confere")
    bad = b.submit(fail, "Baixar", kind=jobs.REDE, key="componente:ffmpeg2",
                   data={"tool": "nao_existe", "acao": "baixar"})
    other = b.submit(lambda j: 1, "Remover", key="componente:ffmpeg3", data={"tool": "ffmpeg", "acao": "remover"})
    for j in (done, bad, other):
        assert j.wait(10)
    for _i in range(50):
        APP.processEvents()
    kinds = [h[0].kind for h in n.history]
    assert kinds.count(notify.COMPONENT_DONE) == 1 and kinds.count(notify.COMPONENT_FAILED) == 1
    failed = next(h[0] for h in n.history if h[0].kind == notify.COMPONENT_FAILED)
    assert "nao_existe" in failed.body and "SHA-256" in failed.body
    b.detach()
    q.shutdown()


# ------------------------------------------------------------------ backends
class FakeServer(QObject):
    """Imita o `org.freedesktop.Notifications`: o método `Notify` com a assinatura da especificação."""

    def __init__(self):
        super().__init__()
        self.calls = []

    @Slot(str, "uint", str, str, str, "QStringList", "QVariantMap", int, result="uint")
    def Notify(self, app, replaces, icon, title, body, actions, hints, timeout):  # noqa: N802
        self.calls.append((app, replaces, icon, title, body, list(actions), dict(hints), timeout))
        return 40 + len(self.calls)


def test_dbus_backend_sends_typed_arguments_and_handles_the_click():
    server = FakeServer()
    backend = nt.DBusBackend("/icone.png", iface=server)
    clicks = []
    backend.on_click = clicks.append
    assert backend.available()
    assert backend.show(7, "Título", "Texto", sound=False) == (True, False)
    app, replaces, icon, title, body, actions, hints, timeout = server.calls[0]
    assert (app, replaces, icon, title, body, timeout) == ("PeliculaConverter", 0, "/icone.png", "Título", "Texto", -1)
    assert actions[0] == "default" and len(actions) == 2
    assert hints.get("desktop-entry") == "pelicula-converter" and hints.get("suppress-sound") is True
    assert backend.show(8, "T", "B", sound=True) == (True, True)
    assert server.calls[1][6].get("sound-name") == "message-new-instant"
    backend._action_invoked(41, "default")
    backend._action_invoked(999, "default")  # notificação de outro programa
    assert clicks == [7]
    backend._notification_closed(42, 1)
    backend._action_invoked(42, "default")
    assert clicks == [7]


def test_dbus_backend_without_bus_falls_back():
    backend = nt.DBusBackend("x")
    backend._failed = True  # como se não houvesse barramento de sessão
    assert not backend.available() and backend.show(1, "a", "b", False) == (False, False)
    rec = Recorder()
    chain = nt.ChainBackend([backend, Recorder(works=False), rec])
    clicks = []
    chain.on_click = clicks.append
    assert chain.show(3, "a", "b", False) == (True, False) and rec.shown[0][0] == 3
    rec._clicked(3)
    assert clicks == [3]
    assert chain.name == "dbus+teste+teste"


def test_tray_backend_without_a_tray_does_nothing():
    """No offscreen não há bandeja: o backend diz que não mostrou, sem erro."""
    tray = nt.TrayBackend()
    if not nt.TrayBackend.available():
        assert tray.show(1, "a", "b", False) == (False, False)
    tray.close()


def test_system_backend_for_this_platform():
    b = nt.system_backend()
    import sys
    if sys.platform.startswith("linux"):
        assert isinstance(b, nt.ChainBackend) and b.name == "dbus+bandeja"
    else:
        assert isinstance(b, nt.TrayBackend)
    b.close()


# ------------------------------------------------------------------ página Configurações › Notificações
class FakeMain(QWidget):
    def __init__(self, notifier=None):
        super().__init__()
        self.notifier = notifier


def page(main=None):
    dlg = SettingsDialog(None, prefs.settings(), "notificacoes", main=main)
    seen: list[str] = []
    dlg.settings_changed.connect(seen.append)
    return dlg, dlg.page("notificacoes"), seen


def test_page_lists_every_kind_and_writes_preferences():
    s = clean_settings()
    _dlg, p, _seen = page()
    assert list(p.kind_checks) == list(notify.KIND_IDS)
    assert all(c.isChecked() for c in p.kind_checks.values())
    assert p.chk_unfocused.isChecked() and not p.chk_sound.isChecked() and p.chk_flash.isChecked()
    p.kind_checks[notify.UPDATE].setChecked(False)
    p.chk_sound.setChecked(True)
    p.chk_flash.setChecked(False)
    p.chk_unfocused.setChecked(False)
    prefs_now = notify.load(s)
    assert not prefs_now.kind_on(notify.UPDATE) and prefs_now.sound and not prefs_now.flash
    assert not prefs_now.only_unfocused


def test_page_test_button_uses_the_window_notifier():
    clean_settings()
    _dlg, p, _seen = page(FakeMain())
    assert not p.btn_test.isEnabled()  # janela sem notificador
    n, _s = make(QWidget(), focused=True)
    _dlg, p, _seen = page(FakeMain(n))
    assert p.btn_test.isEnabled()
    p.btn_test.click()
    assert n.backend.shown and p.test_status.text()
    n.set_backend(nt.NullBackend())
    p.btn_test.click()
    assert "Não foi possível" in p.test_status.text()


def test_page_explains_when_the_module_is_off_and_turns_it_on():
    s = clean_settings()
    modules.set_enabled(s, "notificacoes", False)
    _dlg, p, seen = page()
    assert not p.off_box.isHidden() and not p.options.isEnabled()
    p.off_box.btn.click()
    assert modules.is_enabled(s, "notificacoes") and seen == ["modulos"]
    assert p.off_box.isHidden() and p.options.isEnabled()
