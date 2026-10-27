"""Casos da janela "Recorte por IA (CorridorKey)" (rodados por test_corridorkey_ui.py num subprocesso offscreen).

Nada de rede nem de GPU: o CorridorKey é a instalação falsa de test_corridorkey.py (uv falso e um
infer.py que imita a saída e os arquivos do deles) e o ffmpeg do app é um arquivo vazio. A pasta do
app aponta para uma pasta temporária; as preferências ficam no .ini temporário da conftest.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_DATA = Path(tempfile.mkdtemp(prefix="pelicula_corridorkey_ui_"))
os.environ["LOCALAPPDATA"] = str(_DATA / "local")
os.environ["XDG_DATA_HOME"] = str(_DATA / "local")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

APP = QApplication.instance() or QApplication([])

import test_ambiente as ta  # noqa: E402
import test_corridorkey as tck  # noqa: E402
from pelicula import corridorkey, deps, jobs, media, timeline as tl, tools  # noqa: E402
from pelicula.ui import corridorkey_dialog as ckd, prefs  # noqa: E402
from pelicula.ui.job_bridge import bridge  # noqa: E402

SETTINGS = prefs.settings()
FFMPEG = _DATA / "ffmpeg" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
FFMPEG.parent.mkdir(parents=True)
FFMPEG.write_bytes(b"")
media.ffmpeg = lambda: str(FFMPEG)
media.probe = lambda path: tl.Source(path, 1920, 1080, color_transfer="bt709")  # sem ffprobe de verdade
CLIP = _DATA / "filmagem" / "tela verde.mp4"
CLIP.parent.mkdir()
CLIP.write_bytes(b"video")
os.environ["PCTEST_ARGS"] = str(_DATA / "args.txt")


def pump(cond, timeout: float = 20.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    APP.processEvents()
    return bool(cond())


def finish(job: jobs.Job) -> None:
    assert job is not None
    assert pump(lambda: job.finished, 30), f"o trabalho não terminou: {job}"
    pump(lambda: False, 0.1)


def fake_main(path: str = "", profile: str = "rec709", mode: str = "pelicula", model=None):
    info = tl.Source(path, 1920, 1080) if path else None
    messages = []
    status = SimpleNamespace(showMessage=lambda text, ms=0: messages.append(text))
    return SimpleNamespace(settings=SETTINGS, mode=mode, file_info=info, model=model, messages=messages,
                           store=SimpleNamespace(values={"entrada": profile}), statusBar=lambda: status)


_installed = False


def install_fake() -> None:
    global _installed
    if _installed:
        return
    if deps.platform_key() not in ("win32", "linux"):
        pytest.skip("CorridorKey só no Windows e no Linux")
    tools.uv_command = lambda *a, **k: list(ta.FAKE_UV)
    corridorkey.NVIDIA_SMI = tck.smi(tck.SMI_3060)  # o CI não tem placa NVIDIA
    corridorkey.gpus(refresh=True)
    fake = tck.fake_corridorkey(_DATA / "fontes")
    tools.TOOLS = tuple(fake if t.id == "corridorkey" else t for t in tools.TOOLS)
    tools.download(fake)
    _installed = True


# ------------------------------------------------------------------ de onde vem o arquivo
def test_current_source_follows_the_mode_and_the_selection():
    main = fake_main(str(CLIP))
    assert ckd.current_source(main)[0] == str(CLIP)
    image = tl.Source("foto.png", 100, 100, is_image=True)
    audio = tl.Source("som.wav", has_video=False, has_audio=True)
    video = tl.Source("C:/brutos/verde.mov", 3840, 2160, color_transfer="smpte2084")
    clips = [SimpleNamespace(src=s.path) for s in (audio, image, video)]
    model = SimpleNamespace(selected_clips=lambda: clips,
                            seq=SimpleNamespace(source=lambda c: {s.path: s for s in (audio, image, video)}[c.src]))
    edit = fake_main(str(CLIP), mode="edicao", model=model)
    path, info = ckd.current_source(edit)
    assert path == "C:/brutos/verde.mov" and info is video, "o arquivo de origem do clipe de vídeo selecionado"
    model.selected_clips = lambda: []
    assert ckd.current_source(edit)[0] == str(CLIP), "sem clipe selecionado: o arquivo aberto"
    assert ckd.current_source(fake_main()) == ("", None)


# ------------------------------------------------------------------ a janela
def test_options_warning_and_preferences():
    dlg = ckd.CorridorKeyDialog(fake_main(str(CLIP), profile="slog3"))
    assert not dlg.isModal()
    texts = " ".join(lbl.text() for lbl in dlg.findChildren(QLabel))
    assert "CorridorKey, da Corridor Digital" in texts and "pode ser usado comercialmente" in texts
    dlg.set_input(str(CLIP))
    assert not dlg.warning.isHidden() and "S-Log3" in dlg.warning.text()
    assert dlg.output.text() == str(CLIP.parent), "a pasta de saída segue a do vídeo"
    assert not dlg.hint_row.isEnabled() and not dlg.hint_quality.isEnabled()
    dlg.hint.setCurrentIndex(dlg.hint.findData("mascara"))
    assert dlg.hint_row.isEnabled()
    dlg.hint_path.setText("C:/m.png")
    dlg.hint_quality.setValue(80)
    dlg.extra_fg.setChecked(True)
    dlg.fmt_exr.setChecked(True)
    dlg.despill.setValue(30)
    dlg.low_vram.setChecked(True)
    o = dlg.options()
    assert (o.input, o.output_dir, o.hint, o.hint_path, o.hint_quality) == (str(CLIP), str(CLIP.parent), "mascara",
                                                                             "C:/m.png", 0.8)
    assert o.extras == ("fg",) and o.exr and o.despill == 0.3 and o.low_vram
    dlg._save_prefs()
    again = ckd.CorridorKeyDialog(fake_main(str(CLIP)))
    assert again.despill.value() == 30 and again.low_vram.isChecked() and again.fmt_exr.isChecked()
    assert again.extra_fg.isChecked() and not again.extra_checker.isChecked()
    for k in ("despill", "pouca_memoria", "exr", "cor", "xadrez"):
        SETTINGS.remove(ckd.KEY_PREFIX + k)
    hdr = ckd.CorridorKeyDialog(fake_main())
    hdr.set_input("C:/x/hdr.mov", tl.Source("C:/x/hdr.mov", color_transfer="arib-std-b67"))
    assert "HDR (HLG)" in hdr.warning.text()
    hdr.set_input(str(CLIP))
    assert hdr.warning.isHidden()


def test_start_without_the_component_explains():
    if corridorkey.available():
        pytest.skip("instalação falsa já feita por outro caso")
    dlg = ckd.CorridorKeyDialog(fake_main(str(CLIP)))
    dlg.set_input(str(CLIP))
    assert dlg.start() is None and "não está instalado" in dlg.message.text()


def test_keying_runs_in_the_gpu_queue_and_reports_back():
    install_fake()
    out = _DATA / "saida"
    main = fake_main(str(CLIP))
    dlg = ckd.CorridorKeyDialog(main)
    dlg.set_input(str(CLIP))
    dlg.output.setText(str(out))
    job = dlg.start()
    assert job is not None and job.kind == jobs.GPU and job.key == ckd.JOB_KEY
    assert job.title == "Recorte por IA: tela verde.mp4" and not dlg.btn_run.isEnabled()
    finish(job)
    assert job.state == jobs.CONCLUIDO, job.error
    assert dlg.message.text() == "Recorte pronto: tela verde_cutout.mov" and not dlg.btn_open.isHidden()
    assert (out / "tela verde_cutout.mov").is_file() and (out / "tela verde_alpha.mp4").is_file()
    assert dlg.btn_run.isEnabled() and dlg.progress_row.isHidden()
    # já existe: pergunta antes de substituir
    asked = []
    dlg._confirm = lambda title, text: asked.append(text) or False
    assert dlg.start() is None and "Substituir" in asked[0]
    # aviso de entrada (log): pergunta antes de recortar
    log = ckd.CorridorKeyDialog(fake_main(str(CLIP), profile="vlog"))
    log.set_input(str(CLIP))
    log.output.setText(str(_DATA / "saida-log"))
    asked.clear()
    log._confirm = lambda title, text: asked.append(text) or False
    assert log.start() is None and "V-Log" in asked[0] and "Recortar assim mesmo?" in asked[0]


def test_reopening_shows_the_running_job_and_cancel():
    install_fake()
    os.environ["PCTEST_DEMORAR"] = "20"
    try:
        main = fake_main(str(CLIP))
        dlg = ckd.CorridorKeyDialog(main)
        dlg.set_input(str(CLIP))
        dlg.output.setText(str(_DATA / "saida-cancelar"))
        job = dlg.start()
        assert pump(lambda: job.stage == "Recortando…")
        dlg.close()
        again = ckd.CorridorKeyDialog(main)  # outra janela: mostra o mesmo trabalho
        assert again.job is job and again.busy and not again.progress_row.isHidden()
        assert again.stage.text().startswith("Recortando…") and not again.btn_cancel.isHidden()
        again.btn_cancel.click()
        finish(job)
        assert job.state == jobs.CANCELADO
        assert dlg.message.text() == "Recorte cancelado."
        assert "Recorte cancelado." in main.messages, "janela fechada: o aviso vai para a barra de status"
        assert not list((_DATA / "saida-cancelar").iterdir())
    finally:
        os.environ.pop("PCTEST_DEMORAR", None)


def test_open_for_reuses_one_window():
    main = fake_main(str(CLIP))
    a = ckd.open_for(main)
    b = ckd.open_for(main)
    assert a is b and a.input.text() == str(CLIP) and a.isVisible()
    a.close()
    assert bridge().queue.find(ckd.JOB_KEY) is None
