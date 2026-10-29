"""Casos da interface dos controles de grão e textura da 1.6 (maciez pelo grão, diferença entre camadas, grão no
negativo, modelo da halação, respiração por camada).

Rodados por test_grao_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
QApplication própria. Este arquivo não é coletado sozinho pelo pytest. Não precisa de OpenGL: usa os cartões das
seções com um ParamStore próprio (nada toca as preferências do usuário).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import i18n, look, params  # noqa: E402

# chave → (seção, tipo da linha, padrão neutro)
NEW = {
    "grao_maciez": ("grao", "NumberRow", 0.0),
    "grao_respiracao": ("grao", "NumberRow", 0.0),
    "mtf_camadas": ("pelicula", "NumberRow", 0.0),
    "lab_grao": ("lab", "BoolRow", False),
    "hal_modelo": ("halacao", "ChoiceRow", "brilho"),
    "lab_grao_modelo": ("lab", "ChoiceRow", "ruido"),  # 1.6: grão físico (módulo Beta "grao_fisico")
}


@pytest.fixture(autouse=True)
def _pt_br():
    i18n.set_language("pt_BR")
    yield


def _look():
    from pelicula.ui.store import ParamStore
    from pelicula.ui.widgets import SectionCard
    st = ParamStore()
    cards = {sec.key: SectionCard(sec, st) for sec in params.SECTIONS}
    st.changed.connect(lambda key: [c.refresh(key) for c in cards.values() if key == "*" or key in c.keys()])
    return st, cards


def _row(cards, key):
    return next(r for c in cards.values() for r in c.rows if r.param.key == key)


def test_every_new_control_has_its_row_with_the_neutral_default():
    st, cards = _look()
    for key, (sec, kind, default) in NEW.items():
        rows = {r.param.key: r for r in cards[sec].rows}
        assert key in rows, f"{key} fora da seção {sec}"
        row = rows[key]
        assert type(row).__name__ == kind, key
        assert st.get(key) == default, key
        assert row.toolTip().strip(), f"{key} sem dica"


def test_sliders_set_the_store_and_the_plan():
    st, cards = _look()
    st.set("grao_on", True)
    row = _row(cards, "grao_respiracao")
    row.edit.setText("50%")
    row.edit.editingFinished.emit()
    assert st.get("grao_respiracao") == pytest.approx(0.5)
    assert row.slider.value() == pytest.approx(0.5)
    p = look.build_plan(dict(st.values), 320, 180, 3, 24.0, None, dither=False)
    assert "u_breath" in p.uniforms
    row.edit.setText("0%")
    row.edit.editingFinished.emit()
    assert st.get("grao_respiracao") == 0.0
    assert "u_breath" not in look.build_plan(dict(st.values), 320, 180, 3, 24.0, None, dither=False).uniforms
    for key in ("grao_maciez", "mtf_camadas"):
        r = _row(cards, key)
        r.slider.valueChanged.emit(1.0)  # arrastar o controle até o fim
        assert st.get(key) == pytest.approx(1.0) and r.edit.text().startswith("100")


def test_halation_model_choice():
    st, cards = _look()
    row = _row(cards, "hal_modelo")
    assert [row.combo.itemData(i) for i in range(row.combo.count())] == ["brilho", "fisica"]
    assert row.combo.itemText(0) == "Brilho (acima do limiar)" and row.combo.itemText(1) == "Física (reflexo na base)"
    st.set("hal_on", True)
    row.combo.setCurrentIndex(1)
    assert st.get("hal_modelo") == "fisica"
    assert look.build_plan(dict(st.values), 320, 180, 0, 24.0, None, dither=False).uniforms["u_hal_on"] == 2
    st.set("hal_modelo", "brilho")  # o store manda no combo
    assert row.combo.currentData() == "brilho"


def test_negative_grain_switch():
    st, cards = _look()
    row = _row(cards, "lab_grao")
    assert not row.sw.isChecked()
    st.set("lab_on", True)
    st.set("grao_on", True)
    row.sw.click()
    assert st.get("lab_grao") is True
    assert look.build_plan(dict(st.values), 320, 180, 0, 24.0, None, dither=False).uniforms["u_grain_on"] == 2
    st.set("lab_grao", False)
    assert not row.sw.isChecked()


def test_physical_grain_model_choice():
    """1.6: o modelo do grão no negativo: "ruido" (o de sempre) ou "fisico" (grao_fisico.py, outro programa)."""
    from pelicula.ui import grao_fisico_ui
    st, cards = _look()
    row = _row(cards, "lab_grao_modelo")
    assert grao_fisico_ui.row(cards.values()) is row
    assert [row.combo.itemData(i) for i in range(row.combo.count())] == ["ruido", "fisico"]
    assert row.combo.itemText(1) == "Físico (grãos de prata)"
    for key in ("lab_on", "grao_on", "lab_grao"):
        st.set(key, True)
    plan = lambda: look.build_plan(dict(st.values), 320, 180, 0, 24.0, None, dither=False).uniforms  # noqa: E731
    assert plan()["u_grain_on"] == 2
    row.combo.setCurrentIndex(1)
    assert st.get("lab_grao_modelo") == "fisico"
    u = plan()
    assert u["u_grain_on"] == 3 and u["u_pg_r"] > 0
    st.set("lab_grao_modelo", "ruido")  # o store manda no combo
    assert row.combo.currentData() == "ruido" and plan()["u_grain_on"] == 2


def test_new_labels_are_translated():
    i18n.set_language("en")
    try:
        st, cards = _look()
        assert _row(cards, "hal_modelo").combo.itemText(1) == "Physical (base reflection)"
        assert _row(cards, "grao_respiracao").toolTip().startswith("The color and brightness of each frame")
    finally:
        i18n.set_language("pt_BR")
