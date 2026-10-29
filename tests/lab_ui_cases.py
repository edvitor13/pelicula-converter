"""Casos da interface dos controles novos do Laboratório da 1.6 (filmes do datasheet, tipo de scanner, película
vencida, pré-exposição e processos novos).

Rodados por test_lab_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
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

# chave → (tipo da linha, padrão neutro)
NEW = {
    "lab_scanner": ("ChoiceRow", "rgb"),
    "lab_vencida": ("NumberRow", 0.0),
    "lab_pre_exposicao": ("BoolRow", False),
    "lab_pre_exposicao_stops": ("NumberRow", 4.0),
    "lab_pre_exposicao_cor": ("ChoiceRow", "neutra"),
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


def _plan(st):
    return look.build_plan(dict(st.values), 320, 180, 0, 24.0, None, dither=False)


def test_every_new_control_has_its_row_with_the_neutral_default():
    st, cards = _look()
    rows = {r.param.key: r for r in cards["lab"].rows}
    for key, (kind, default) in NEW.items():
        assert key in rows, f"{key} fora do Laboratório"
        assert type(rows[key]).__name__ == kind, key
        assert st.get(key) == default, key
        assert rows[key].toolTip().strip(), f"{key} sem dica"


def test_datasheet_films_and_new_processes_are_in_the_choices():
    st, cards = _look()
    neg = _row(cards, "lab_negativo").combo
    items = {neg.itemData(i): neg.itemText(i) for i in range(neg.count())}
    assert items["vision3_250d_v2"] == "Kodak Vision3 250D (datasheet)"
    cop = _row(cards, "lab_copia").combo
    assert cop.itemData(cop.count() - 1) == "2383_v2" and cop.itemText(cop.count() - 1) == "Kodak 2383 (datasheet)"
    proc = _row(cards, "lab_processo").combo
    data = [proc.itemData(i) for i in range(proc.count())]
    assert data[-3:] == ["reversivel", "cruzado_e6c41", "cruzado_c41e6"]
    assert proc.itemText(proc.count() - 3) == "Reversível (slide, sem cópia)"
    st.set("lab_on", True)
    proc.setCurrentIndex(proc.count() - 3)
    assert st.get("lab_processo") == "reversivel"
    assert _plan(st).uniforms["u_lab_b_on"] == 1


def test_scanner_choice_switches_the_lab_variant():
    st, cards = _look()
    st.set("lab_on", True)
    st.set("lab_copia", "nenhuma")
    row = _row(cards, "lab_scanner")
    assert [row.combo.itemData(i) for i in range(row.combo.count())] == ["rgb", "branca"]
    assert "u_lx_on" not in _plan(st).uniforms
    row.combo.setCurrentIndex(1)
    assert st.get("lab_scanner") == "branca"
    assert _plan(st).uniforms["u_lx_white"] == 1
    st.set("lab_scanner", "rgb")  # o store manda no combo
    assert row.combo.currentData() == "rgb" and "u_lx_on" not in _plan(st).uniforms


def test_expired_film_slider_sets_the_store_and_the_plan():
    st, cards = _look()
    st.set("lab_on", True)
    row = _row(cards, "lab_vencida")
    row.edit.setText("15")
    row.edit.editingFinished.emit()
    assert st.get("lab_vencida") == pytest.approx(15.0)
    add = _plan(st).uniforms["u_lx_add_a"]
    assert add[2] > add[1] > 0.0  # a camada do azul ganha mais véu
    row.edit.setText("0")
    row.edit.editingFinished.emit()
    assert "u_lx_on" not in _plan(st).uniforms


def test_pre_exposure_switch_stops_and_color():
    st, cards = _look()
    st.set("lab_on", True)
    sw = _row(cards, "lab_pre_exposicao")
    assert not sw.sw.isChecked()
    sw.sw.click()
    assert st.get("lab_pre_exposicao") is True
    a = _plan(st).uniforms["u_lx_add_a"]
    stops = _row(cards, "lab_pre_exposicao_stops")
    stops.edit.setText("2")
    stops.edit.editingFinished.emit()
    b = _plan(st).uniforms["u_lx_add_a"]
    assert b[1] == pytest.approx(4.0 * a[1], rel=1e-3)  # 2 stops a menos de distância = 4× a luz
    cor = _row(cards, "lab_pre_exposicao_cor")
    assert cor.combo.itemText(1) == "Âmbar (quente)"
    cor.combo.setCurrentIndex(1)
    c = _plan(st).uniforms["u_lx_add_a"]
    assert c[0] > c[2]
    st.set("lab_pre_exposicao", False)
    assert not sw.sw.isChecked() and "u_lx_on" not in _plan(st).uniforms
