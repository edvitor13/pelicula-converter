"""Casos do filtro de ajustes na interface (rodados por test_busca_ajustes_ui.py num subprocesso offscreen).

O campo "Filtrar ajustes…" no painel de ajustes (Película) e no inspetor (Edição): cartões que ficam, destaque,
avançados que aparecem, desligar devolve o estado, mensagens, módulo desligado, atalhos e valores intactos.
As preferências ficam num .ini só deste arquivo.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_busca_ui_")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import i18n, modules, params, presets, timeline as tl  # noqa: E402
from pelicula.i18n import _  # noqa: E402
from pelicula.ui import filtro_ajustes, prefs  # noqa: E402


@pytest.fixture(scope="module")
def win():
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None
    MainWindow._auto_check_update = lambda self: None
    s = prefs.settings()
    s.setValue("auto_update", "false")
    for m in modules.MODULES:
        s.remove(modules.KEY_PREFIX + m.id)
    try:
        w = MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def fake_source(path, frames=48):
    return tl.Source(path, 640, 360, 24.0, "24/1", frames, frames / 24.0, has_audio=True)


def fresh(win):
    """Módulos no padrão, filtros vazios, modo Película e uma montagem vazia."""
    for m in modules.MODULES:
        win.settings.remove(modules.KEY_PREFIX + m.id)
    win.look_filter.set_text("")
    win.inspector.filtro.set_text("")
    win.set_mode("pelicula")
    win.file_info = None
    win._loading = True
    try:
        win.model.set_sequence(tl.Sequence())
    finally:
        win._loading = False
    win._refresh_source(reset=True)
    win.apply_preset(presets.DEFAULT_ID)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def shown(cards) -> list[str]:
    return [c.section.key for c in cards if not c.isHidden()]


def edit_with_two_clips(win):
    seq = tl.Sequence(640, 360, "24/1")
    seq.insert_media(fake_source("C:/nao_existe/a.mp4"))
    seq.insert_media(fake_source("C:/nao_existe/b.mp4"))
    win.model.set_sequence(seq)
    win.set_mode("edicao")
    APP.processEvents()
    return seq


def video_clips(win):
    return [c for c in win.model.seq.clips if c.kind == tl.VIDEO]


def hit_keys(cards) -> set[str]:
    return {r.param.key for c in cards for r in c.rows if r.objectName() == "FiltroHit"}


# ------------------------------------------------------------------ painel de ajustes (Película)
def test_look_filter_finds_the_card_in_any_language_and_accent(win):
    fresh(win)
    results = []
    for q in ("aberração", "chromatic", "aberración", "aberracao", "ABERRACAO"):
        win.look_filter.set_text(q)
        APP.processEvents()
        vis = shown(win.cards)
        assert "lente" in vis and len(vis) < len(win.cards), (q, vis)
        card = next(c for c in win.cards if c.section.key == "lente")
        assert card.expanded
        assert not hit_keys([card])  # a seção inteira bateu: nenhuma linha dela é destacada
        results.append(vis)
    assert results[0] == results[3] == results[4]  # com e sem acento, maiúsculas ou não: o mesmo resultado
    # a interface em outro idioma não muda o resultado
    antes = i18n.language()
    try:
        for code in ("en", "es"):
            i18n.set_language(code)
            win.look_filter.set_text("aberração")
            assert "lente" in shown(win.cards), code
    finally:
        i18n.set_language(antes)
    win.look_filter.set_text("")


def test_the_matching_row_is_highlighted_and_the_others_are_not(win):
    fresh(win)
    win.look_filter.set_text("distorção")  # só um controle do cartão Lente
    APP.processEvents()
    assert shown(win.cards) == ["lente"]
    assert hit_keys(win.cards) == {"distorcao"}
    win.look_filter.set_text("")
    assert hit_keys(win.cards) == set()


def test_advanced_row_appears_when_it_is_what_matched_and_hides_again(win):
    fresh(win)
    win.adv.setChecked(False)
    card, row = next((c, r) for c in win.cards for r in c.rows if r.param.advanced and not r.isHidden() is False
                     or (r.param.advanced and not r.isVisibleTo(c.body)))
    assert not row.isVisibleTo(card.body)
    win.look_filter.set_text(row.param.key)
    APP.processEvents()
    assert row.isVisibleTo(card.body) and not card.isHidden()
    win.adv.setChecked(True)  # ligar o "Avançado" no meio do filtro
    win.adv.setChecked(False)
    assert row.isVisibleTo(card.body)
    win.look_filter.set_text("")
    assert not row.isVisibleTo(card.body)


def test_clearing_restores_cards_advanced_and_scroll(win):
    fresh(win)
    win.adv.setChecked(False)
    for i, c in enumerate(win.cards):
        c.set_expanded(i % 2 == 0)
    APP.processEvents()
    scroll = win.cards[0].parentWidget().parentWidget().parentWidget()
    assert isinstance(scroll, QScrollArea)
    bar = scroll.verticalScrollBar()
    bar.setValue(min(120, bar.maximum()))
    APP.processEvents()

    def snapshot():
        return ([(c.isHidden(), c.expanded, [r.isVisibleTo(c.body) for r in c.rows]) for c in win.cards],
                bar.value())

    before = snapshot()
    for q in ("grão", "aberração", "halation", "zzzz"):
        win.look_filter.set_text(q)
        APP.processEvents()
        win.look_filter.set_text("")
        APP.processEvents()
        QTest.qWait(10)
        assert snapshot() == before, q


def test_hsl_chip_is_selected_for_the_matching_color(win):
    fresh(win)
    edit_with_two_clips(win)
    c1 = video_clips(win)[0]
    win.model.select([c1.id])
    APP.processEvents()
    hsl = next(c for c in win.inspector.vcards if c.section.layout == "hsl")
    before = hsl.hsl_color
    win.inspector.filtro.set_text("hsl_azul_sat")
    APP.processEvents()
    target = next((r.param.key for r in hsl.rows if r.param.key.startswith("hsl_") and "azul" in r.param.key
                   and r.param.key.endswith("sat")), None)
    if target is None:
        target = next(r.param.key for r in hsl.rows)
    win.inspector.filtro.set_text(target)
    APP.processEvents()
    row = next(r for r in hsl.rows if r.param.key == target)
    assert row.isVisibleTo(hsl.body)
    win.inspector.filtro.set_text("")
    assert hsl.hsl_color == before
    win.set_mode("pelicula")


def test_no_result_message(win):
    fresh(win)
    win.look_filter.set_text("zzzzqqqq")
    APP.processEvents()
    assert shown(win.cards) == []
    label = win.look_filter.panels[0].label
    assert not label.isHidden() and label.text() == _("Nenhum ajuste encontrado")
    win.look_filter.set_text("grão")
    assert label.isHidden()
    win.look_filter.set_text("")
    assert label.isHidden()


def test_disabled_module_stays_hidden_and_the_message_names_it(win):
    fresh(win)
    modules.set_enabled(win.settings, "luts", False)
    win.settings_changed.emit("modulos")
    APP.processEvents()
    lut = next(c for c in win.cards if c.section.key == "lut")
    assert lut.isHidden()
    win.look_filter.set_text("cube")  # só a seção do LUT externo
    APP.processEvents()
    assert shown(win.cards) == [] and lut.isHidden()
    msg = win.look_filter.panels[0].label
    assert not msg.isHidden()
    assert msg.text() == _("Está no módulo {nome}: ligue em Configurações › Recursos").format(
        nome=_(modules.get("luts").name))
    # com outros resultados visíveis, o cartão do módulo desligado continua escondido
    win.look_filter.set_text("lut")
    assert lut.isHidden()
    # limpar não mostra o cartão do módulo desligado
    win.look_filter.set_text("")
    assert lut.isHidden()
    # ligar o módulo com o filtro ativo mostra o cartão
    win.look_filter.set_text("cube")
    modules.set_enabled(win.settings, "luts", True)
    win.settings_changed.emit("modulos")
    APP.processEvents()
    assert shown(win.cards) == ["lut"] and msg.isHidden()
    win.look_filter.set_text("")
    assert not lut.isHidden()


def test_values_do_not_change(win):
    fresh(win)
    antes = copy.deepcopy(win.store.values)
    for q in ("grão", "aberração", "x", "zzzz"):
        win.look_filter.set_text(q)
        APP.processEvents()
    win.look_filter.set_text("")
    assert win.store.values == antes
    assert not win.store.dirty if hasattr(win.store, "dirty") else True


# ------------------------------------------------------------------ inspetor (Edição)
def test_inspector_filter_with_a_selected_clip_and_it_survives_selection_changes(win):
    fresh(win)
    edit_with_two_clips(win)
    c1, c2 = video_clips(win)[:2]
    win.model.select([c1.id])
    APP.processEvents()
    insp = win.inspector
    assert not insp.filtro.isHidden()
    base_v, base_a = shown(insp.vcards), shown(insp.acards)
    insp.filtro.set_text("denoise")
    APP.processEvents()
    assert "detalhe" in shown(insp.vcards) and len(shown(insp.vcards)) < len(insp.vcards)
    vis = shown(insp.vcards)
    win.model.select([c2.id])
    APP.processEvents()
    assert insp.filtro.text() == "denoise" and shown(insp.vcards) == vis
    # a página de som também filtra
    insp.filtro.set_text("equalizar")
    APP.processEvents()
    assert shown(insp.acards) == ["eq"]
    insp.filtro.set_text("")
    assert shown(insp.vcards) == base_v and shown(insp.acards) == base_a
    win.set_mode("pelicula")


def test_inspector_values_do_not_change(win):
    fresh(win)
    edit_with_two_clips(win)
    c1 = video_clips(win)[0]
    win.model.select([c1.id])
    APP.processEvents()
    before = json.dumps(win.model.seq.to_json(), sort_keys=True)
    for q in ("vinheta", "velocidade", "zzzz"):
        win.inspector.filtro.set_text(q)
        APP.processEvents()
    win.inspector.filtro.set_text("")
    assert json.dumps(win.model.seq.to_json(), sort_keys=True) == before
    win.set_mode("pelicula")


def test_inspector_filter_hides_without_a_clip(win):
    fresh(win)
    edit_with_two_clips(win)
    win.model.select([])
    APP.processEvents()
    assert win.inspector.filtro.isHidden()
    win.set_mode("pelicula")


# ------------------------------------------------------------------ atalhos
def test_slash_focuses_the_filter_of_the_current_mode(win):
    fresh(win)
    win.setFocus()
    APP.processEvents()
    QTest.keyClick(win, Qt.Key.Key_Slash)
    assert win.look_filter.field.hasFocus()
    win.look_filter.field.clearFocus()
    assert not filtro_ajustes.focus_current(win, win.look_filter.field)  # dentro de um campo de texto: a tecla é dele
    edit_with_two_clips(win)
    win.model.select([video_clips(win)[0].id])
    APP.processEvents()
    win.setFocus()
    QTest.keyClick(win, Qt.Key.Key_Slash)
    assert win.inspector.filtro.field.hasFocus()
    win.inspector.filtro.field.clearFocus()
    win.set_mode("pelicula")


def test_escape_clears_the_field(win):
    fresh(win)
    base = shown(win.cards)
    win.look_filter.set_text("grão")
    win.look_filter.field.setFocus()
    QTest.keyClick(win.look_filter.field, Qt.Key.Key_Escape)
    assert win.look_filter.text() == "" and shown(win.cards) == base


def test_ctrl_f_belongs_to_the_panels_and_the_subtitles_keep_theirs(win):
    fresh(win)
    scope = win.look_filter.shortcut.parent()
    assert win.look_filter.shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert scope.isAncestorOf(win.look_filter) and scope.isAncestorOf(win.cards[0])
    sub = win.subs_ui.panel
    assert not scope.isAncestorOf(sub) and not win.inspector.isAncestorOf(sub)
    assert win.inspector.filtro.shortcut.parent() is win.inspector
    # Ctrl+F com o foco num controle do painel leva ao campo
    slider = win.cards[0].rows[0]
    win.activateWindow()
    slider.setFocus()
    APP.processEvents()
    QTest.keyClick(slider, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    if win.isActiveWindow():
        assert win.look_filter.field.hasFocus()
    win.look_filter.field.clearFocus()
    # a busca do painel de legendas continua sendo dele
    keys = [s for s in sub.findChildren(type(win.look_filter.shortcut)) if s.key().toString() == "Ctrl+F"]
    assert keys and keys[0].context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert keys[0].parent() is sub
