"""Casos dos módulos na interface (rodados por test_modules_ui.py num subprocesso offscreen).

Configurações › Recursos, a escolha do perfil no primeiro acesso e a janela principal: cada
módulo esconde e devolve as suas ferramentas, o modo Edição volta para o modo Película sem
mexer na montagem e o aviso aparece ao abrir um projeto ou aplicar um preset que usa um
módulo desligado — sem mudar os valores que vão para a renderização.

As preferências ficam num .ini só deste arquivo (nada de outros testes nem do usuário).
"""

from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_modules_ui_")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import app as app_main, modules, presets, project, timeline as tl  # noqa: E402
from pelicula.ui import prefs  # noqa: E402
from pelicula.ui import profile_dialog  # noqa: E402
from pelicula.ui.profile_dialog import ProfileDialog  # noqa: E402
from pelicula.ui.settings_dialog import SettingsDialog  # noqa: E402

STABLE = [m.id for m in modules.MODULES if m.status == modules.ESTAVEL]


def reset_modules(s=None):
    """Volta ao padrão: nenhum módulo gravado (todo recurso estável ligado)."""
    s = s or prefs.settings()
    for m in modules.MODULES:
        s.remove(modules.KEY_PREFIX + m.id)
    s.remove(modules.KEY_PROFILE)
    s.remove(modules.KEY_SHOW_TESTS)
    return s


def recursos():
    """(diálogo, página Recursos, sinais emitidos)."""
    dlg = SettingsDialog(None, prefs.settings(), "recursos", main=None)
    seen: list[str] = []
    dlg.settings_changed.connect(seen.append)
    return dlg, dlg.page("recursos"), seen


def checked_cards(cards) -> list[str]:
    return [pid for pid, c in cards.items() if c.isChecked()]


# ------------------------------------------------------------------ página Recursos
def test_page_lists_every_group_and_stable_module():
    reset_modules()
    _dlg, page, seen = recursos()
    assert set(page.rows) == {m.id for m in modules.MODULES}
    assert set(page.group_heads) == {m.group for m in modules.MODULES}
    for mid in STABLE:
        row = page.rows[mid]
        assert not row.isHidden() and row.switch.isChecked()
        assert row.badge.status == modules.ESTAVEL and row.badge.text()
    assert checked_cards(page.cards) == ["tudo"]
    assert page.custom.isHidden()
    assert seen == []


def test_profile_cards_apply_profiles_and_emit():
    s = reset_modules()
    _dlg, page, seen = recursos()
    page.cards["simples"].click()
    assert modules.current_profile(s) == "simples" and s.value(modules.KEY_PROFILE) == "simples"
    chosen = next(p[3] for p in modules.PROFILES if p[0] == "simples")
    for mid in STABLE:
        assert page.rows[mid].switch.isChecked() == (mid in chosen), mid
        assert modules.is_enabled(s, mid) == (mid in chosen), mid
    assert checked_cards(page.cards) == ["simples"]
    assert seen == ["modulos"]
    page.cards["simples"].click()  # clicar no perfil marcado não o desmarca
    assert checked_cards(page.cards) == ["simples"]
    page.cards["tudo"].click()
    assert all(page.rows[mid].switch.isChecked() for mid in STABLE)
    assert checked_cards(page.cards) == ["tudo"] and seen[-1] == "modulos"


def test_switch_makes_the_profile_custom_and_back():
    s = reset_modules()
    _dlg, page, seen = recursos()
    page.rows["scopes"].switch.click()
    assert s.value(modules.KEY_PREFIX + "scopes") == "0" and not modules.is_enabled(s, "scopes")
    assert modules.current_profile(s) is None
    assert checked_cards(page.cards) == [] and not page.custom.isHidden()
    assert seen == ["modulos"]
    page.rows["scopes"].switch.click()
    assert modules.is_enabled(s, "scopes") and checked_cards(page.cards) == ["tudo"]
    assert page.custom.isHidden() and seen == ["modulos", "modulos"]


def test_clicking_the_row_toggles_the_module():
    s = reset_modules()
    dlg, page, seen = recursos()
    dlg.resize(900, 620)
    dlg.show()
    APP.processEvents()
    row = page.rows["davinci"]
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(30, 12))
    assert not modules.is_enabled(s, "davinci") and not row.switch.isChecked()
    assert seen == ["modulos"]
    dlg.close()


def test_show_tests_option(monkeypatch):
    s = reset_modules()
    beta = modules.Module("teste_beta", "Recurso em teste", "Só para o teste.", "cor", modules.BETA)
    monkeypatch.setattr(modules, "MODULES", modules.MODULES + (beta,))
    monkeypatch.setitem(modules._BY_ID, beta.id, beta)
    _dlg, page, seen = recursos()
    row = page.rows["teste_beta"]
    assert row.isHidden() and not row.switch.isChecked()  # em teste: começa desligado e escondido
    assert row.badge.status == modules.BETA
    assert not page.chk_tests.isChecked() and page.no_tests.isHidden()
    page.chk_tests.setChecked(True)
    assert modules.show_tests(s) and not row.isHidden() and page.no_tests.isHidden()
    assert seen == ["modulos"]
    row.switch.click()
    assert modules.is_enabled(s, "teste_beta")
    assert checked_cards(page.cards) == ["tudo"]  # perfis só olham os recursos estáveis
    page.chk_tests.setChecked(False)
    assert not modules.show_tests(s) and not row.isHidden()  # ligado continua na lista para desligar
    row.switch.click()
    page.refresh()
    assert row.isHidden()


def test_no_test_features_hint():
    s = reset_modules()
    s.setValue(modules.KEY_SHOW_TESTS, "1")
    _dlg, page, _seen = recursos()
    assert page.chk_tests.isChecked()
    assert page.no_tests.isHidden() == any(m.status != modules.ESTAVEL for m in modules.MODULES)


# ------------------------------------------------------------------ primeiro acesso
def test_profile_dialog_defaults_to_everything_and_picks():
    dlg = ProfileDialog(None)
    assert dlg.selected == "tudo" and checked_cards(dlg.cards) == ["tudo"]
    assert list(dlg.cards) == [p[0] for p in modules.PROFILES]
    dlg.cards["criador"].click()
    assert dlg.selected == "criador" and checked_cards(dlg.cards) == ["criador"]
    dlg.cards["criador"].click()
    assert checked_cards(dlg.cards) == ["criador"]
    assert ProfileDialog(None, "nao_existe").selected == "tudo"


def test_choose_profile_only_on_first_run(monkeypatch):
    s = reset_modules()
    shown = []

    def fake_exec(dlg):
        shown.append(dlg.selected)
        dlg.cards["simples"].click()
        return 1

    monkeypatch.setattr(profile_dialog.ProfileDialog, "exec", fake_exec)
    assert app_main.choose_profile(s, first_run=False) is None
    assert shown == [] and s.value(modules.KEY_PROFILE) is None
    assert modules.enabled_ids(s) == set(STABLE)  # instalação antiga: tudo como estava
    assert app_main.choose_profile(s, first_run=True) == "simples"
    assert shown == ["tudo"]  # a janela começa com "Tudo" marcado
    assert modules.current_profile(s) == "simples" and not modules.is_enabled(s, "laboratorio")


# ------------------------------------------------------------------ janela principal
@pytest.fixture(scope="module")
def win():
    from pelicula.ui.main_window import MainWindow
    MainWindow._check_deps = lambda self: None          # nada de janelas de dependências
    MainWindow._auto_check_update = lambda self: None   # nem de rede
    s = reset_modules()
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


def fresh(win):
    """Módulos no padrão, sem aviso fechado, modo Película e uma montagem vazia."""
    reset_modules(win.settings)
    win._notice_muted.clear()
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


def set_module(win, module_id, on):
    modules.set_enabled(win.settings, module_id, on)
    win.settings_changed.emit("modulos")
    APP.processEvents()


def shown(tool) -> bool:
    """A ferramenta não foi escondida (vale também dentro de páginas que não estão na frente)."""
    return tool.isVisible() if isinstance(tool, QAction) else not tool.isHidden()


def fake_source(path, frames=48):
    return tl.Source(path, 640, 360, 24.0, "24/1", frames, frames / 24.0, has_audio=False)


def test_window_starts_with_every_tool(win):
    fresh(win)
    tools = win._module_tools()
    assert set(tools) <= {m.id for m in modules.MODULES}
    for module_id, items in tools.items():
        assert items and all(shown(t) for t in items), module_id
    assert win.module_notice.isHidden()
    assert all(s.isEnabled() for s in win._edit_shortcuts)


def test_each_module_hides_and_restores_its_tools(win):
    fresh(win)
    cards = {c.section.key: c for c in win.cards}
    expected = {"laboratorio": cards["lab"], "defeitos": cards["desgaste"], "scan": cards["scan"],
                "luts": cards["lut"], "scopes": win.hist, "curva": win.curve_switch, "davinci": win.act_resolve,
                "exportar_lut": win.act_luts[0], "edicao": win.mode_switch, "medidor_som": win.meter}
    for module_id, items in win._module_tools().items():
        set_module(win, module_id, False)
        assert not any(shown(t) for t in items), module_id
        others = [t for mid, ts in win._module_tools().items() if mid != module_id for t in ts]
        assert all(shown(t) for t in others), module_id
        set_module(win, module_id, True)
        assert all(shown(t) for t in items), module_id
    for module_id, tool in expected.items():
        assert tool in win._module_tools()[module_id], module_id
    assert win.edit_scopes in win._module_tools()["scopes"]
    assert set(win.act_luts) <= set(win._module_tools()["exportar_lut"])


def test_curve_graph_follows_the_switch_without_touching_the_preference(win):
    fresh(win)
    win.curve_switch.setChecked(True)
    assert shown(win.curve_graph) and win.settings.value("show_curve") == "true"
    set_module(win, "curva", False)
    assert not shown(win.curve_graph) and not shown(win.curve_label)
    assert win.curve_switch.isChecked() and win.settings.value("show_curve") == "true"
    set_module(win, "curva", True)
    assert shown(win.curve_graph)
    win.curve_switch.setChecked(False)
    assert not shown(win.curve_graph)


def test_turning_edit_off_falls_back_to_film_mode_keeping_the_edit(win):
    fresh(win)
    seq = tl.Sequence(640, 360, "24/1")
    seq.insert_media(fake_source("C:/nao_existe/a.mp4"))
    seq.insert_media(fake_source("C:/nao_existe/b.mp4"))
    win.model.set_sequence(seq)
    win.set_mode("edicao")
    assert win.mode == "edicao"
    before = json.dumps(win.model.seq.to_json(), sort_keys=True)
    set_module(win, "edicao", False)
    assert win.mode == "pelicula" and not shown(win.mode_switch)
    assert not any(s.isEnabled() for s in win._edit_shortcuts)
    assert json.dumps(win.model.seq.to_json(), sort_keys=True) == before  # a montagem não mudou
    assert win.src_seq is not None  # e continua sendo a entrada do look
    win.set_mode("edicao")  # Ctrl+2, projeto, importar...: fica no modo Película
    assert win.mode == "pelicula"
    win.import_paths([__file__])
    assert json.dumps(win.model.seq.to_json(), sort_keys=True) == before
    assert win.module_notice.ids == ["edicao"] and shown(win.module_notice)
    set_module(win, "edicao", True)
    assert shown(win.mode_switch) and all(s.isEnabled() for s in win._edit_shortcuts)
    assert win.module_notice.isHidden()
    win.set_mode("edicao")
    assert win.mode == "edicao"
    win.set_mode("pelicula")


def test_preset_with_a_disabled_module_warns_and_turns_it_back_on(win):
    fresh(win)
    set_module(win, "laboratorio", False)
    win.apply_preset("vision3_250d")
    assert win.module_notice.isHidden()
    win.apply_preset("lab_v3_250d_2383")
    assert shown(win.module_notice) and win.module_notice.ids == ["laboratorio"]
    assert modules.get("laboratorio").name in win.module_notice.text.text()
    assert win.store.values == presets.builtin_values("lab_v3_250d_2383")  # a renderização recebe o mesmo
    win.module_notice.btn_on.click()
    APP.processEvents()
    assert modules.is_enabled(win.settings, "laboratorio")
    assert win.module_notice.isHidden()
    assert shown({c.section.key: c for c in win.cards}["lab"])
    assert win.store.values == presets.builtin_values("lab_v3_250d_2383")


def test_closed_notice_only_returns_for_something_new(win):
    fresh(win)
    set_module(win, "laboratorio", False)
    win.apply_preset("lab_v3_250d_2383")
    win.module_notice.btn_close.click()
    assert win.module_notice.isHidden() and "laboratorio" in win._notice_muted
    win.apply_preset("lab_v3_500t_noite")
    assert win.module_notice.isHidden()
    set_module(win, "defeitos", False)
    win.apply_preset("lab_technicolor2")  # Laboratório + defeitos: o novo traz o aviso de volta
    assert shown(win.module_notice) and win.module_notice.ids == ["defeitos", "laboratorio"]
    set_module(win, "laboratorio", True)
    assert "laboratorio" not in win._notice_muted
    assert win.module_notice.ids == ["defeitos"]


def test_notice_hides_in_full_screen_preview(win):
    fresh(win)
    seq = tl.Sequence(640, 360, "24/1")
    seq.insert_media(fake_source("C:/nao_existe/a.mp4"))
    win.model.set_sequence(seq)
    assert win.info is not None
    set_module(win, "laboratorio", False)
    win.apply_preset("lab_v3_250d_2383")
    assert shown(win.module_notice)
    win.toggle_preview_fullscreen()
    assert win.preview_fullscreen and win.module_notice.isHidden()
    win.toggle_preview_fullscreen()
    assert not win.preview_fullscreen and shown(win.module_notice)


def test_project_with_disabled_modules_warns_and_keeps_its_values(win, tmp_path):
    fresh(win)
    for mid in ("defeitos", "scan"):
        set_module(win, mid, False)
    vals = presets.builtin_values("scan_35mm")
    path = str(tmp_path / "scan.plc")
    project.save(project.Project(values=vals, preset_id="scan_35mm"), path)
    win.open_project(path)
    assert shown(win.module_notice) and win.module_notice.ids == ["defeitos", "scan"]
    assert win.store.values == project.load(path).values
    assert win.store.values["scan_on"] and win.store.values["desg_on"]


def test_edit_project_opens_in_film_mode_when_edit_is_off(win, tmp_path):
    fresh(win)
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    for f in (a, b):
        f.write_bytes(b"")  # só precisa existir (o projeto não pede para localizar)
    seq = tl.Sequence(640, 360, "24/1")
    seq.insert_media(fake_source(str(a)))
    seq.insert_media(fake_source(str(b)))
    path = str(tmp_path / "edicao.plc")
    project.save(project.Project(media_path=str(a), values=presets.builtin_values(presets.DEFAULT_ID),
                                 preset_id=presets.DEFAULT_ID, sequence=seq.to_json(), mode="edicao"), path)
    set_module(win, "edicao", False)
    win.open_project(path)
    assert win.mode == "pelicula"
    assert len(win.model.seq.clips) == len(seq.clips) and win.src_seq is not None
    assert shown(win.module_notice) and win.module_notice.ids == ["edicao"]
    set_module(win, "edicao", True)
    assert win.module_notice.isHidden()


def test_settings_menu_opens_the_features_page(win, monkeypatch):
    fresh(win)
    opened = []
    monkeypatch.setattr(win, "show_settings", lambda page="geral": opened.append(page))
    menu = win.btn_settings.menu()
    texts = [a.text() for a in menu.actions()]
    assert "Recursos…" in texts
    next(a for a in menu.actions() if a.text() == "Recursos…").trigger()
    assert opened == ["recursos"]


def test_features_page_changes_reach_the_window(win):
    fresh(win)
    dlg = SettingsDialog(win, win.settings, "recursos", main=win)
    dlg.settings_changed.connect(win.settings_changed)
    page = dlg.page("recursos")
    page.cards["simples"].click()
    APP.processEvents()
    assert not shown({c.section.key: c for c in win.cards}["lab"]) and not shown(win.hist)
    assert shown(win.mode_switch)
    page.cards["tudo"].click()
    APP.processEvents()
    assert all(shown(t) for ts in win._module_tools().values() for t in ts)
    dlg.reject()


def test_corridorkey_action_needs_the_beta_module_and_the_component(win, monkeypatch):
    from pelicula import corridorkey
    from pelicula.ui import corridorkey_dialog
    fresh(win)
    installed = [False]
    monkeypatch.setattr(corridorkey, "available", lambda root=None: installed[0])
    assert not shown(win.act_corridorkey), "Beta: começa desligado"
    set_module(win, "recorte_ia", True)
    assert not shown(win.act_corridorkey), "sem o componente instalado, sem a ação"
    installed[0] = True
    win.btn_settings.menu().aboutToShow.emit()  # instalado em Componentes: aparece ao abrir o menu
    assert shown(win.act_corridorkey)
    opened = []
    monkeypatch.setattr(corridorkey_dialog, "open_for", lambda main: opened.append(main))
    win.act_corridorkey.trigger()
    assert opened == [win]
    set_module(win, "recorte_ia", False)
    assert not shown(win.act_corridorkey)
    # tudo estável ligado não liga o Beta
    page_dlg = SettingsDialog(win, win.settings, "recursos", main=win)
    page_dlg.settings_changed.connect(win.settings_changed)
    page_dlg.page("recursos").cards["tudo"].click()
    APP.processEvents()
    assert not shown(win.act_corridorkey) and not modules.is_enabled(win.settings, "recorte_ia")
    page_dlg.reject()
