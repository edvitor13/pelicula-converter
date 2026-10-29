"""Casos da interface da entrada da câmera na 1.6 (rodados por test_entrada_ui.py num subprocesso offscreen).

O cartão "Câmera" do inspetor do modo Edição (perfil de câmera por clipe, `camera.py`) e a sugestão do perfil pelos
metadados (`media.suggest_input`): o aviso com um botão no modo Película e o preenchimento dos clipes novos no modo
Edição.

As preferências ficam num .ini só deste arquivo (nada de outros testes nem do usuário).
"""

from __future__ import annotations

import dataclasses
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_entrada_ui_")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import camera, editparams, params, timeline as tl  # noqa: E402
from pelicula.timeline import VIDEO  # noqa: E402
from pelicula.ui.edit_model import TimelineModel  # noqa: E402
from pelicula.ui.edit_panels import ClipInspector  # noqa: E402


def src(path="C:/v/a.mov", frames=48, **kw) -> tl.Source:
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=False, **kw)


def model_with(*sources) -> TimelineModel:
    m = TimelineModel()
    seq = tl.Sequence(1920, 1080, "24/1")
    for s in sources:
        seq.insert_media(s)
    m.set_sequence(seq)
    return m


def vclips(m):
    return sorted((c for c in m.seq.clips if c.kind == VIDEO), key=lambda c: c.start)


# ------------------------------------------------------------------ inspetor: cartão "Câmera"
def test_inspector_has_the_camera_card_with_the_profiles():
    m = model_with(src())
    ins = ClipInspector(m)
    card = next(c for c in ins.vcards if c.section.key == "camera")
    rows = {r.param.key: r for r in card.rows}
    assert list(rows) == list(camera.KEYS)
    combo = rows["camera_entrada"].combo
    keys = [combo.itemData(i) for i in range(combo.count())]
    assert keys == ["look"] + [k for k, _l in params.ENTRADAS]
    assert combo.itemText(0) == "Igual ao do look"
    assert not card.expanded                                 # fechado: a maioria das montagens não precisa
    card.set_advanced(False)
    assert rows["camera_reescalado"].isHidden() and rows["camera_ei"].isHidden()
    card.set_advanced(True)
    assert not rows["camera_reescalado"].isHidden()


def test_choosing_a_clip_profile_changes_only_that_clip():
    m = model_with(src("C:/v/a.mov"), src("C:/v/b.mov"))
    ins = ClipInspector(m)
    a, b = vclips(m)
    m.select([b.id])
    assert ins.clip_id == b.id and ins.vstore.get("camera_entrada") == "look"
    ins.vstore.set("camera_entrada", "vlog")
    assert m.seq.find(b.id).values["camera_entrada"] == "vlog"
    assert m.seq.find(a.id).values["camera_entrada"] == "look"
    assert camera.uses_profiles(m.seq)
    # "Restaurar cor" e um ajuste rápido não mexem no perfil (não é cor)
    ins._reset_color()
    assert m.seq.find(b.id).values["camera_entrada"] == "vlog"
    # desfazer volta ao padrão, e o JSON do clipe fica o de sempre
    m.undo()
    assert m.seq.find(b.id).values["camera_entrada"] == "look"
    assert "camera_entrada" not in m.seq.to_json()["clipes"][1]["valores"]
    assert not camera.uses_profiles(m.seq)
    assert editparams.is_neutral(VIDEO, m.seq.find(b.id).values)


# ------------------------------------------------------------------ perfil sugerido pelos metadados
def test_input_notice_offers_and_applies_with_one_click():
    from pelicula.ui.input_notice import InputNotice
    n = InputNotice()
    got = []
    n.accepted.connect(got.append)
    assert n.isHidden()
    n.offer("slog3", "rec709")
    assert not n.isHidden() and "Sony S-Log3" in n.text.text() and "Rec.709" in n.text.text()
    n.set_suppressed(True)                                   # tela cheia: some sem esquecer
    assert n.isHidden() and n.profile == "slog3"
    n.set_suppressed(False)
    assert not n.isHidden()
    n.btn_use.click()
    assert got == ["slog3"] and n.isHidden() and n.profile is None
    n.offer("vlog", "rec709")
    n.sync("rec709")
    assert not n.isHidden()
    n.sync("vlog")                                           # o look já está no perfil sugerido
    assert n.isHidden()
    n.offer("vlog", "rec709")
    n.btn_close.click()                                      # "Manter o perfil atual"
    assert n.isHidden() and got == ["slog3"]


def test_model_prefills_only_new_clips_in_one_undo_step():
    m = model_with(src("C:/v/a.mov"))
    m.clip_profile_for = lambda s: "vlog" if s.path.endswith("b.mov") else None
    (a,) = vclips(m)
    made = m.insert_media(src("C:/v/b.mov"))
    b = next(c for c in made if c.kind == VIDEO)
    assert m.seq.find(b.id).values["camera_entrada"] == "vlog"
    assert m.seq.find(a.id).values["camera_entrada"] == "look"          # o clipe que já estava não muda
    m.insert_media(src("C:/v/c.mov"))
    assert [c.values["camera_entrada"] for c in vclips(m)] == ["look", "vlog", "look"]
    m.undo()
    m.undo()                                                            # dois passos: c e depois b inteiro
    assert [c.src for c in vclips(m)] == ["C:/v/a.mov"]
    m.clip_profile_for = None                                           # sem a janela: como antes
    m.insert_media(src("C:/v/b.mov"))
    assert [c.values["camera_entrada"] for c in vclips(m)] == ["look", "look"]


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    from pelicula import media
    try:
        if not media.configure():
            pytest.skip("ffmpeg indisponível")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ffmpeg indisponível: {exc}")
    from PySide6.QtGui import QColor, QImage
    from pelicula.ui import prefs
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None          # nada de janelas de dependências
    MainWindow._auto_check_update = lambda self: None   # nem de rede
    prefs.settings().setValue("auto_update", "false")
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    d = tmp_path_factory.mktemp("sugestao")
    paths = {}
    for name, color in (("a", "#808080"), ("b", "#406080")):
        img = QImage(64, 36, QImage.Format.Format_RGB888)
        img.fill(QColor(color))
        p = d / f"{name}.png"
        assert img.save(str(p))
        paths[name] = str(p)
    w.test_paths = paths
    yield w


@pytest.fixture
def suggest(monkeypatch):
    """`media.suggest_input` falso: "b.png" parece V-Log; o resto, nada (um PNG de verdade não sugere nada)."""
    from pelicula import media
    monkeypatch.setattr(media, "suggest_input",
                        lambda info: "vlog" if info is not None and str(info.path).endswith("b.png") else None)


def fresh_sequence(win):
    win._loading = True
    try:
        win.model.set_sequence(tl.Sequence())
    finally:
        win._loading = False


def test_film_mode_suggests_on_open_and_never_on_reopen(win, suggest):
    win.set_mode("pelicula")
    win.store.set("entrada", "rec709")
    win.load_media(win.test_paths["b"], detect=True)                    # arquivo novo
    APP.processEvents()
    assert not win.input_notice.isHidden() and win.input_notice.profile == "vlog"
    assert win.store.get("entrada") == "rec709"                         # nunca muda sozinho
    win.input_notice.btn_use.click()
    assert win.store.get("entrada") == "vlog" and win.input_notice.isHidden()
    win.store.undo()
    assert win.store.get("entrada") == "rec709"
    win.load_media(win.test_paths["b"])                                 # projeto reaberto: sem sugestão
    assert win.input_notice.isHidden()
    win.load_media(win.test_paths["b"], detect=True)
    win.store.set("entrada", "vlog")                                    # escolheu à mão: o aviso some
    assert win.input_notice.isHidden()
    win.store.set("entrada", "rec709")
    win.load_media(win.test_paths["a"], detect=True)                    # sem sugestão
    assert win.input_notice.isHidden()


def test_edit_mode_prefills_new_clips_and_suggests_for_the_first(win, suggest):
    win.set_mode("edicao")
    win.store.set("entrada", "rec709")
    fresh_sequence(win)
    first = win._probe_source(win.test_paths["b"])
    win._insert(first)                                                  # o primeiro arquivo: o look se ajusta a ele
    (b,) = vclips(win.model)
    assert b.values["camera_entrada"] == "look"
    second = win._probe_source(win.test_paths["a"])
    win._insert(second)
    win._insert(first)                                                  # um clipe novo de "b": perfil próprio
    assert [c.values["camera_entrada"] for c in vclips(win.model)] == ["look", "look", "vlog"]
    win.store.set("entrada", "vlog")                                    # look em V-Log: "b" segue o look
    win._insert(first)
    assert vclips(win.model)[-1].values["camera_entrada"] == "look"
    # o primeiro vídeo de uma montagem vazia mostra a sugestão para o look (como no modo Película)
    win.store.set("entrada", "rec709")
    fresh_sequence(win)
    video = tl.Source("C:/v/b.png.mov", 1920, 1080, 24.0, "24/1", 48, 2.0)
    win._file_infos[video.path] = dataclasses.replace(video.to_info(), path="C:/v/b.png")
    win._adopt_format(video)
    assert not win.input_notice.isHidden() and win.input_notice.profile == "vlog"
    win.input_notice.offer(None)
    fresh_sequence(win)
    win.set_mode("pelicula")
