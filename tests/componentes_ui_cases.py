"""Casos da página Componentes e da ponte da fila de tarefas (rodados por test_componentes_ui.py num
subprocesso offscreen).

Nada de rede: os downloads vêm de pacotes locais (`file://`) ou de um fluxo lento simulado; a
consulta da versão do ffmpeg e o download do ffmpeg são substituídos. A pasta do app (ffmpeg e
ferramentas) e o APPDATA apontam para uma pasta temporária; as preferências ficam no .ini
temporário do PELICULA_SETTINGS_DIR (herdado da conftest).
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_DATA = Path(tempfile.mkdtemp(prefix="pelicula_componentes_"))
os.environ["LOCALAPPDATA"] = str(_DATA / "local")
os.environ["XDG_DATA_HOME"] = str(_DATA / "local")
os.environ["APPDATA"] = str(_DATA / "roaming")

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import deps, jobs, media, tools  # noqa: E402
from pelicula.tools import Artifact, Detected, Tool  # noqa: E402
from pelicula.ui import icons, prefs  # noqa: E402
from pelicula.ui.job_bridge import JobBridge, bridge  # noqa: E402
from pelicula.ui.pages import componentes  # noqa: E402
from pelicula.ui.settings_dialog import SettingsDialog  # noqa: E402

EXE = ".exe" if sys.platform == "win32" else ""
SETTINGS = prefs.settings()
SETTINGS.setValue("auto_update", "false")
SETTINGS.remove("ffmpeg_dir")
deps.latest_version = lambda timeout=10.0: "99.0"  # nunca consulta a rede


def make_pkg(name: str, files: dict[str, bytes]) -> Path:
    folder = _DATA / "pacotes"
    folder.mkdir(exist_ok=True)
    path = folder / name
    with zipfile.ZipFile(path, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    return path


def fake_tool(tool_id: str, pkg: Path, digest: str | None = None, url: str | None = None, **kw) -> Tool:
    art = Artifact(platform=deps.platform_key(), version="1.0.0", url=url or pkg.as_uri(),
                   sha256=digest or hashlib.sha256(pkg.read_bytes()).hexdigest(), size=pkg.stat().st_size,
                   executables=(f"bin/ferramenta{EXE}",))
    return Tool(id=tool_id, name=f"Ferramenta {tool_id}", description="Só para os testes.", icon="box",
                homepage="https://example.org", license="MIT", license_url="https://example.org/licenca",
                modules=("scopes",), artifacts=(art,), **kw)


PKG = make_pkg("ferramenta.zip", {f"bin/ferramenta{EXE}": b"binario", "LEIA-ME.txt": b"ola"})
SLOW_PKG = make_pkg("lento.zip", {f"bin/ferramenta{EXE}": b"binario", "dados.bin": os.urandom(4000)})
GOOD = fake_tool("ferramenta_boa", PKG)
BAD = fake_tool("ferramenta_hash_errado", PKG, digest="0" * 64)
SLOW = fake_tool("ferramenta_lenta", SLOW_PKG, url="https://example.invalid/lento.zip")
TERMS = fake_tool("ferramenta_termos", PKG, consent="Uso só com atribuição ao autor.")
tools.TOOLS = (tools.FFMPEG, GOOD, BAD, SLOW, TERMS, tools.DAVINCI_RESOLVE)


class SlowStream:
    """Resposta HTTP simulada: o pacote em pedaços pequenos, devagar, até alguém cancelar."""

    def __init__(self):
        self.data = SLOW_PKG.read_bytes()  # ~4 KB em pedaços de 64 bytes a cada 50 ms: uns 3 s
        self.pos = 0
        self.headers = {"Content-Length": str(len(self.data))}

    def read(self, n=-1):
        time.sleep(0.05)
        chunk = self.data[self.pos:self.pos + 64]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_open = tools._open
tools._open = lambda url, timeout=60.0: SlowStream() if "lento" in url else _open(url, timeout)


def pump(cond, timeout: float = 15.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    APP.processEvents()
    return bool(cond())


def dialog(main=None) -> SettingsDialog:
    return SettingsDialog(None, SETTINGS, "componentes", main=main)


def page_of(dlg: SettingsDialog) -> componentes.Page:
    return dlg.page("componentes")


def shown(w) -> bool:
    return not w.isHidden()


def finish(job: jobs.Job) -> None:
    assert job is not None
    assert pump(lambda: job.finished, 20), f"o trabalho não terminou: {job}"
    pump(lambda: False, 0.1)  # deixa os sinais da ponte chegarem


# ------------------------------------------------------------------ página
def test_page_lists_components_and_system_section():
    page = page_of(dialog())
    assert list(page.cards)[0] == "ffmpeg"
    assert set(page.cards) == {t.id for t in tools.TOOLS}
    ff = page.cards["ffmpeg"]
    assert ff.name.text() == "ffmpeg" and "formatos de vídeo" in ff.desc.text()
    assert "https://ffmpeg.org" in ff.links.text() and "GPL-3.0" in ff.links.text()
    assert "núcleo do app" in ff.used.text()
    if deps.platform_supported():
        assert "Fonte do download" in ff.links.text()
    good = page.cards["ferramenta_boa"]
    assert "Scopes" in good.used.text() and "Binário oficial do autor" in good.links.text()
    assert "Efeitos na GPU: não detectada" in page.gpu.text()
    assert "Python" in page.sysinfo.text() and "PySide6" in page.sysinfo.text()
    assert "Espaço usado pelos componentes" in page.total.text()
    assert not shown(page.reason_box)


def test_download_runs_in_the_job_queue_then_remove():
    page = page_of(dialog())
    card = page.cards["ferramenta_boa"]
    assert card.chip.text() == "Não instalado" and not shown(card.badge)
    assert shown(card.btn_main) and card.btn_main.text().strip() == "Baixar" and not shown(card.btn_remove)
    assert "Versão 1.0.0 para baixar" in card.info.text()
    card.btn_main.click()
    job = bridge().queue.find(componentes.job_key("ferramenta_boa"))
    assert job is not None and job.kind == jobs.REDE and job.title == "Baixar Ferramenta ferramenta_boa"
    finish(job)
    assert job.state == jobs.CONCLUIDO, job.error
    assert card.chip.text() == "Instalado" and shown(card.badge)
    assert card.badge.toolTip().endswith(GOOD.artifacts[0].sha256)
    assert "Versão 1.0.0" in card.info.text() and "no disco" in card.info.text()
    assert card.message.text() == "Ferramenta ferramenta_boa instalado e pronto para uso."
    assert not shown(card.progress_row) and shown(card.btn_remove)
    assert card.btn_main.text().strip() == "Baixar de novo"
    assert str(tools.tools_dir()) in card.where.text()
    assert tools.executable(GOOD) is not None
    assert "0 B" not in page.total.text()

    asked = []
    page._confirm = lambda title, text: asked.append(text) or True
    card.btn_remove.click()
    job = bridge().queue.find(componentes.job_key("ferramenta_boa"))
    finish(job)
    assert job.state == jobs.CONCLUIDO and asked and "Remover Ferramenta ferramenta_boa" in asked[0]
    assert card.chip.text() == "Não instalado" and not shown(card.btn_remove) and not shown(card.badge)
    assert card.message.text().startswith("Ferramenta ferramenta_boa removido:")
    assert tools.installed(GOOD) == []


def test_remove_needs_confirmation():
    page = page_of(dialog())
    finish(page.download("ferramenta_boa"))
    page._confirm = lambda title, text: False
    assert page.remove("ferramenta_boa") is None
    assert tools.installed(GOOD) != []
    page._confirm = lambda title, text: True
    finish(page.remove("ferramenta_boa"))
    assert tools.installed(GOOD) == []


def test_progress_and_cancel():
    page = page_of(dialog())
    card = page.cards["ferramenta_lenta"]
    job = page.download("ferramenta_lenta")
    assert page.download("ferramenta_lenta") is job  # clicar de novo não abre outro download
    assert pump(lambda: shown(card.progress_row) and card.bar.value() > 0)
    assert card.chip.text() == "Baixando…" and not card.btn_main.isEnabled()
    assert card.stage.text().startswith("Baixando Ferramenta ferramenta_lenta…") and " de " in card.stage.text()
    card.btn_cancel.click()
    finish(job)
    assert job.state == jobs.CANCELADO
    assert card.message.text() == "Download cancelado." and not shown(card.progress_row)
    assert card.btn_main.isEnabled() and tools.installed(SLOW) == []
    base = tools.tool_dir(SLOW)
    assert not base.exists() or not any(p.name.startswith(".") for p in base.iterdir())


def test_sha_mismatch_shows_the_error_and_installs_nothing():
    page = page_of(dialog())
    card = page.cards["ferramenta_hash_errado"]
    job = page.download("ferramenta_hash_errado")
    finish(job)
    assert job.state == jobs.ERRO and "SHA-256" in job.error
    assert "SHA-256" in card.message.text() and "Nada foi instalado" in card.message.text()
    assert card.chip.text() == "Não instalado" and tools.installed(BAD) == []


def test_tools_with_license_conditions_ask_first():
    page = page_of(dialog())
    seen = []
    page._consent = lambda tool: seen.append(tool.id) or False
    assert page.download("ferramenta_termos") is None
    assert seen == ["ferramenta_termos"] and bridge().queue.find(componentes.job_key("ferramenta_termos")) is None
    page._consent = lambda tool: True
    job = page.download("ferramenta_termos")
    finish(job)
    assert job.state == jobs.CONCLUIDO and tools.installed(TERMS)
    tools.remove(TERMS)


def test_running_download_survives_closing_the_window():
    dlg1 = dialog()
    job = page_of(dlg1).download("ferramenta_lenta")
    assert pump(lambda: job.state == jobs.RODANDO)
    dlg1.deleteLater()
    pump(lambda: False, 0.2)
    page2 = page_of(dialog())
    card = page2.cards["ferramenta_lenta"]
    assert card.job is job and shown(card.progress_row) and card.chip.text() == "Baixando…"
    card.btn_cancel.click()
    finish(job)
    assert job.state == jobs.CANCELADO and not shown(card.progress_row)


def test_unavailable_tool_has_no_download_button():
    other = "linux" if deps.platform_key() != "linux" else "win32"
    art = GOOD.artifacts[0]
    elsewhere = Tool(id="so_em_outro_sistema", name="Outra", description="x", icon="box",
                     homepage="https://example.org", license="MIT", license_url="https://example.org/l",
                     artifacts=(Artifact(other, art.version, art.url, art.sha256, art.size),))
    saved = tools.TOOLS
    tools.TOOLS = saved + (elsewhere,)
    try:
        page = page_of(dialog())
        card = page.cards["so_em_outro_sistema"]
        assert card.chip.text() == "Indisponível neste sistema" and not shown(card.btn_main)
        assert "ainda não tem download para este sistema" in card.info.text()
        assert page.download("so_em_outro_sistema") is None
        assert card.message.text() == "Outra ainda não tem download para este sistema."
    finally:
        tools.TOOLS = saved


# ------------------------------------------------------------------ ffmpeg
def _fake_ffmpeg_download(progress=None, cancel=None):
    bin_dir = deps.ffmpeg_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    for n in ("ffmpeg", "ffprobe"):
        (bin_dir / f"{n}{EXE}").write_bytes(b"x" * 1000)
    (bin_dir.parent / "ORIGEM.txt").write_text(f"Baixado de: https://exemplo/ff.zip\nFonte: teste\n"
                                              f"SHA-256: {'b' * 64}\n", encoding="utf-8")
    if progress:
        progress("Baixando o ffmpeg…", 500, 1000)
        progress("Pronto.", 1, 1)
    return bin_dir


def test_show_deps_routes_to_this_page_with_reason_and_auto_download():
    from pelicula.ui.main_window import MainWindow

    class FakeMain(QWidget):
        settings_changed = Signal(str)

        def __init__(self):
            super().__init__()
            self.settings = SETTINGS
            self.info = None

    opened = []
    changed = []
    real_exec = SettingsDialog.exec
    real_download = deps.download_ffmpeg
    SettingsDialog.exec = lambda self: opened.append(self) or 0
    deps.download_ffmpeg = _fake_ffmpeg_download
    SETTINGS.setValue("ffmpeg_dir", str(_DATA / "pasta_antiga"))
    try:
        main = FakeMain()
        main.settings_changed.connect(changed.append)
        MainWindow.show_deps(main, "O ffmpeg não foi encontrado.", auto_download=True)
        assert len(opened) == 1
        dlg = opened[0]
        page = page_of(dlg)
        assert dlg.stack.currentWidget() is page
        assert shown(page.reason_box) and page.reason.text() == "O ffmpeg não foi encontrado."
        assert pump(lambda: bridge().queue.find(componentes.job_key("ffmpeg")) is not None
                    or page.cards["ffmpeg"].message.text() != "")
        card = page.cards["ffmpeg"]
        if deps.platform_supported():
            assert pump(lambda: card.job is not None and card.job.finished)
            pump(lambda: False, 0.1)
            assert card.job.state == jobs.CONCLUIDO, card.job.error
            assert SETTINGS.value("ffmpeg_dir", None) in (None, "")  # o ffmpeg do app passa a valer
            assert media.ffmpeg() == str(deps.ffmpeg_dir() / f"ffmpeg{EXE}")
            assert shown(card.badge) and "(baixado pelo app)" in card.where.text()
            assert "ffmpeg" in changed
            # Remover a cópia do app (confirmando o aviso).
            page._confirm = lambda title, text: "não vai conseguir abrir" in text
            finish(page.remove("ffmpeg"))
            assert not deps.ffmpeg_dir().exists()
            assert media.tool_dir() != str(deps.ffmpeg_dir())
        else:
            assert "não está disponível" in card.message.text()
    finally:
        SettingsDialog.exec = real_exec
        deps.download_ffmpeg = real_download
        SETTINGS.remove("ffmpeg_dir")
        media.configure()


def test_choose_another_ffmpeg_folder():
    page = page_of(dialog())
    changed = []
    page.dialog.settings_changed.connect(changed.append)
    card = page.cards["ffmpeg"]
    empty = _DATA / "vazia"
    empty.mkdir(exist_ok=True)
    assert not page.use_ffmpeg_folder(str(empty))
    assert card.message.text() == "Não encontrei o ffmpeg e o ffprobe nessa pasta."
    folder = _DATA / "meu_ffmpeg"
    folder.mkdir(exist_ok=True)
    for n in ("ffmpeg", "ffprobe"):
        (folder / f"{n}{EXE}").write_bytes(b"x")
    real_inspect = deps.inspect
    deps.inspect = lambda p: deps.FFmpegInfo(p, "ffmpeg version 7.1", (7, 1), None)
    try:
        assert page.use_ffmpeg_folder(str(folder))
        assert SETTINGS.value("ffmpeg_dir") == str(folder) and changed == ["ffmpeg"]
        assert card.message.text() == "" and str(folder) in card.where.text()
        assert "(pasta escolhida)" in card.where.text()
        assert card.chip.text() == "Instalado" and "Versão 7.1" in card.info.text()
        assert not shown(card.btn_remove)  # o ffmpeg de outra pasta nunca é apagado pelo app
        # "Procurar versão nova": a versão publicada aparece e o botão vira "Atualizar ffmpeg".
        assert shown(card.btn_check) == componentes.can_check_latest()
        if componentes.can_check_latest():
            job = page.check_latest()  # o mesmo que clicar em card.btn_check
            assert not card.btn_check.isEnabled() or job.finished
            finish(job)
            assert componentes.latest_ffmpeg() == "99.0" and card.btn_check.isEnabled()
            assert card.message.text() == "Versão mais recente publicada: 99.0."
            assert "versão 99.0 disponível" in card.info.text()
            assert card.btn_main.text().strip() == "Atualizar ffmpeg"
    finally:
        deps.inspect = real_inspect
        deps._latest_seen.update(value="", t=None)
        SETTINGS.remove("ffmpeg_dir")
        media.configure()


def test_opening_the_page_never_queries_the_network():
    calls = []
    real = deps.latest_version
    deps.latest_version = lambda timeout=10.0: calls.append(timeout) or "99.0"
    SETTINGS.setValue("auto_update", "true")
    try:
        page = page_of(dialog())
        pump(lambda: False, 0.2)
        assert calls == [] and bridge().queue.find(componentes.LATEST_KEY) is None
        # A versão já consultada ao abrir o app (deps.latest_version guarda) aparece sem rede.
        deps.remember_latest_version("98.1")
        page.refresh("ffmpeg")
        assert componentes.latest_ffmpeg() == "98.1" and calls == []
    finally:
        deps.latest_version = real
        deps._latest_seen.update(value="", t=None)
        SETTINGS.setValue("auto_update", "false")


# ------------------------------------------------------------------ programas do sistema
def test_resolve_card_shows_detection():
    page = page_of(dialog())
    card = page.cards["davinci_resolve"]
    real = tools.DETECTORS["davinci_resolve"]
    try:
        tools.DETECTORS["davinci_resolve"] = lambda: Detected(False)
        page.refresh("davinci_resolve")
        assert card.chip.text() == "Não encontrado" and "só detecta, não baixa" in card.info.text()
        assert not shown(card.btn_main) and not shown(card.btn_remove) and not shown(card.where_row)
        assert "Plugin do DaVinci Resolve" in card.used.text()
        tools.DETECTORS["davinci_resolve"] = lambda: Detected(True, "19.1.4", str(_DATA), [
            "Plugin OpenFX do PeliculaConverter: versão 1.3"])
        page.refresh("davinci_resolve")
        assert card.chip.text() == "No sistema" and "Versão 19.1.4" in card.info.text()
        assert shown(card.notes) and "Plugin OpenFX" in card.notes.text()
        assert shown(card.where_row) and str(_DATA) in card.where.text()
        assert not shown(card.btn_other)  # sem janela principal, sem atalho para a janela do plugin
    finally:
        tools.DETECTORS["davinci_resolve"] = real


# ------------------------------------------------------------------ ícones
def _has_ink(name: str) -> bool:
    img = icons.icon(name, "#ffffff", 24).pixmap(24, 24).toImage()
    return any(QColor(img.pixel(x, y)).alpha() > 0 for x in range(img.width()) for y in range(img.height()))


def test_every_component_icon_is_drawn():
    for name in {t.icon for t in tools.TOOLS} | {"video", "download", "shield", "chip", "box"}:
        assert _has_ink(name), name


# ------------------------------------------------------------------ ponte da fila (Qt)
def test_job_bridge_delivers_everything_on_the_main_thread():
    q = jobs.JobQueue()
    br = JobBridge(q)
    main_thread = threading.current_thread()
    seen = []
    br.added.connect(lambda j: seen.append(("added", threading.current_thread() is main_thread)))
    br.changed.connect(lambda j: seen.append(("changed", threading.current_thread() is main_thread)))
    br.finished.connect(lambda j: seen.append(("finished", threading.current_thread() is main_thread)))
    done = []

    reports = 0

    def chatty(job):
        nonlocal reports
        for i in range(400):
            job.report("contando", i + 1, 400)
            reports += 1
            if i % 20 == 0:
                time.sleep(0.01)  # uns 200 ms rodando: dá tempo de o progresso aparecer
        return "fim"

    job = br.submit(chatty, "falante", kind=jobs.CPU, on_finished=lambda j: done.append(
        (j.result, threading.current_thread() is main_thread)))
    assert pump(lambda: done)
    pump(lambda: False, 0.1)
    assert done == [("fim", True)]
    assert all(ok for _e, ok in seen)
    kinds = [e for e, _ok in seen]
    assert kinds[0] == "added" and kinds[-1] == "finished" and kinds.count("finished") == 1
    assert reports == 400
    assert 1 <= kinds.count("changed") < 60, "o progresso chega resumido (no máximo a cada 50 ms)"
    assert job.state == jobs.CONCLUIDO
    # Erro no callback não impede o sinal finished.
    bad = []
    br.finished.connect(lambda j: bad.append(j.id))
    job2 = br.submit(lambda j: 1, "x", on_finished=lambda j: 1 / 0)
    assert pump(lambda: job2.id in bad)
    br.detach()
    q.shutdown()


def test_shared_bridge_uses_the_shared_queue():
    assert bridge() is bridge() and bridge().queue is jobs.shared()
    assert isinstance(bridge(), QObject) and bridge().parent() is APP
