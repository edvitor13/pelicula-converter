"""Casos da interface da entrada da câmera na 1.6 (rodados por test_entrada_ui.py num subprocesso offscreen).

O cartão "Câmera" do inspetor do modo Edição (perfil de câmera por clipe, `camera.py`).

As preferências ficam num .ini só deste arquivo (nada de outros testes nem do usuário).
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_entrada_ui_")

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
