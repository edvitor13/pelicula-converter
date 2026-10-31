"""Casos da interface de sequência dentro de sequência (1.7, #57): pôr uma sequência da Mídia na linha do tempo, dois cliques
num clipe de sequência, "Aninhar seleção", "Desaninhar", o desenho do clipe, a forma de onda, o inspetor e as ferramentas
que leem o arquivo.

Rodados por test_aninhar_ui.py num subprocesso offscreen (via `uicases.run_cases`): os widgets do Qt precisam de uma
QApplication própria. Este arquivo não é coletado sozinho pelo pytest. O offscreen do Windows não tem fontes de verdade:
nada aqui conclui sobre o encaixe de texto.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import aninhar, audiomix, media, timeline as tl  # noqa: E402
from pelicula.ui import aninhar_ui, main_window as mw, prefs, theme  # noqa: E402
from pelicula.ui.sequence_dialog import SequenceDialog  # noqa: E402

from sequencias_ui_cases import pump, tone_video  # noqa: E402,F401  (os mesmos ajudantes das abas)

LMB = Qt.MouseButton.LeftButton


@pytest.fixture(scope="module")
def win():
    prefs.settings().setValue("auto_update", "false")
    try:
        w = mw.MainWindow()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    w.confirm_discard = lambda: True
    w.resize(1400, 900)
    w.show()
    APP.processEvents()
    yield w


def color_seq(n=2, w=320, h=180, fps="24/1", secs=2.0, track=0) -> tl.Sequence:
    """Montagem só com clipes sem arquivo (abre sem perguntar por arquivos que faltam): `n` cores em fila."""
    seq = tl.Sequence(w, h, fps, micro_fade=True)
    for i in range(n):
        seq.insert_media(tl.Source.virtual("cor", w, h, fps, seconds=secs, data={"cor": ["#336699", "#993366", "#669933"][i % 3]}),
                         vtrack=track)
    return seq


def fresh(win, mode="edicao", seq=None):
    win.new_project()
    win.set_mode(mode)
    if seq is not None:
        win._loading = True
        win.model.set_sequence(seq)
        win._loading = False
        win.seqs_ui.reset()
        for src in seq.sources.values():
            win.adopt_source(src)
        win._refresh_source(reset=True)
    win._saved_state = win._state()
    pump()


def accepting(monkeypatch):
    monkeypatch.setattr(SequenceDialog, "exec", lambda self: 1)


def other_sequence(win, monkeypatch, n=1, **kw):
    """Cria uma segunda sequência (com `n` cores dentro) e volta para a primeira. Devolve (id da primeira, da segunda)."""
    accepting(monkeypatch)
    first = win.model.seq
    win.seqs_ui.new_sequence()
    pump()
    inner = win.model.seq
    for i in range(n):
        inner.insert_media(tl.Source.virtual("cor", inner.width, inner.height, inner.fps_str, seconds=kw.get("secs", 2.0),
                                             data={"cor": "#99aa33"}))
    win.model.commit()
    win.model.changed.emit("structure")
    win.seqs_ui.activate(first.id)
    pump()
    return first.id, inner.id


def event(canvas, pos, kind=QEvent.Type.MouseButtonPress, button=LMB):
    p = QPointF(pos)
    return QMouseEvent(kind, p, canvas.mapToGlobal(p), button, button, Qt.KeyboardModifier.NoModifier)


def double_click(canvas, pos):
    canvas.mouseDoubleClickEvent(event(canvas, pos, QEvent.Type.MouseButtonDblClick))


def context_actions(canvas, pos, monkeypatch, trigger: str | None = None) -> list[str]:
    """Os textos do menu de contexto no ponto (e, com `trigger`, aciona essa ação)."""
    seen: list[QMenu] = []
    from pelicula.ui import timeline_view

    class SpyMenu(QMenu):   # o `exec` de um menu de verdade espera um clique
        def exec(self, *a, **k):
            seen.append(self)
            if trigger:
                for act in self.actions():
                    if act.text() == trigger:
                        act.trigger()
            return None

    monkeypatch.setattr(timeline_view, "QMenu", SpyMenu)
    canvas._context_menu(event(canvas, pos, QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton))
    return [a.text() for a in seen[0].actions() if a.text()]


def nested_clips(win, kind=tl.VIDEO):
    return [c for c in win.model.seq.clips if c.kind == kind and win.model.seq.sources[c.src].is_nested]


def status(win) -> str:
    return win.statusBar().currentMessage()


# ------------------------------------------------------------------ da Mídia para a linha do tempo
def test_add_to_timeline_places_a_sequence_as_a_linked_video_and_sound_clip(win, monkeypatch, tmp_path):
    v = tone_video(tmp_path, "tom.mp4", "160x90", 24, 440)
    fresh(win)
    win.import_paths([v])
    pump(lambda: win.cur is not None)
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    pump()
    inner_id = win.model.seq.id
    win.model.insert_media(win.model.seq.sources[next(iter(win.model.seq.sources))], at=0)    # o vídeo dentro da nova
    first = win.model.sequences()[0]
    win.seqs_ui.activate(first.id)
    pump()
    n = len(win.model.seq.clips)
    key = f"sequencia:{inner_id}"
    win.add_to_timeline(key)
    pump()
    made = nested_clips(win) + nested_clips(win, tl.AUDIO)
    assert len(win.model.seq.clips) == n + len(made) and 1 <= len(made) <= 2
    vids = nested_clips(win)
    assert vids and win.model.seq.nested(vids[0]).id == inner_id
    if len(made) == 2:
        assert made[0].link and made[0].link == made[1].link
    assert set(win.model.selection) == {c.id for c in made}


def test_a_sequence_does_not_impose_its_format_on_the_one_receiving_it(win, monkeypatch):
    fresh(win)
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    pump()
    inner = win.model.seq
    inner.insert_media(tl.Source.virtual("cor", inner.width, inner.height, inner.fps_str, seconds=1.0, data={"cor": "#445566"}))
    win.model.commit()
    win.model.set_settings(640, 360, "30/1")
    win.seqs_ui.activate(win.model.sequences()[0].id)
    pump()
    outer = win.model.seq
    before = (outer.width, outer.height, outer.fps_str)
    assert not outer.clips
    win.add_to_timeline(f"sequencia:{inner.id}")
    pump()
    assert (outer.width, outer.height, outer.fps_str) == before and nested_clips(win)


def test_place_at_cursor_and_drop_work_for_a_sequence_and_follow_insert_and_overwrite(win, monkeypatch):
    fresh(win, seq=color_seq(2))
    other_id = other_sequence(win, monkeypatch)[1]
    key = f"sequencia:{other_id}"
    seq = win.model.seq
    a, b = seq.clips[0], seq.clips[1]
    win.seek(10)
    pump()
    win.place_at_cursor([key], True)            # inserir: empurra o que vem depois
    pump()
    nested = nested_clips(win)[0]
    assert nested.start == 10 and (a.dur, b.start) == (10, 48 + nested.dur) or b.start >= nested.end
    win.model.undo()
    pump()
    assert not nested_clips(win)
    end = win.drop_on_timeline([key], 60, tl.VIDEO, 1)
    pump()
    drop = nested_clips(win)[0]
    assert (drop.start, drop.track) == (60, 1) and end == drop.end
    assert win.model.history.can_undo()


def test_a_sequence_that_cannot_go_there_is_refused_with_a_short_reason_and_nothing_changes(win, monkeypatch):
    fresh(win, seq=color_seq(1))
    ids = other_sequence(win, monkeypatch)
    seq = win.model.seq
    before = seq.to_json()
    win.add_to_timeline(f"sequencia:{ids[0]}")     # nela mesma
    assert "nela mesma" in status(win) and seq.to_json() == before
    win.add_to_timeline(f"sequencia:{ids[1]}")
    pump()
    assert nested_clips(win)
    win.seqs_ui.activate(ids[1])
    pump()
    before = win.model.seq.to_json()
    win.statusBar().clearMessage()
    win.add_to_timeline(f"sequencia:{ids[0]}")     # a de fora já tem esta: um ciclo
    assert "ciclo" in status(win) and win.model.seq.to_json() == before


def test_an_empty_sequence_is_refused(win, monkeypatch):
    fresh(win, seq=color_seq(1))
    accepting(monkeypatch)
    win.seqs_ui.new_sequence()
    pump()
    empty = win.model.seq
    win.seqs_ui.activate(win.model.sequences()[0].id)
    pump()
    n = len(win.model.seq.clips)
    win.add_to_timeline(f"sequencia:{empty.id}")
    assert "vazia" in status(win) and len(win.model.seq.clips) == n


def test_the_nesting_limit_is_refused_with_its_reason(win, monkeypatch):
    fresh(win, seq=color_seq(1))
    group = win.model.seq.ensure_set()
    deep = group.create(320, 180, "24/1")
    deep.insert_media(tl.Source.virtual("cor", 320, 180, "24/1", seconds=1.0, data={"cor": "#111111"}))
    top = deep
    for _i in range(tl.MAX_NEST - 1):
        nxt = group.create(320, 180, "24/1")
        group.sync()
        nxt.insert_media(group.sources[f"sequencia:{top.id}"], 0)
        top = nxt
    win.seqs_ui.reset()
    n = len(win.model.seq.clips)
    win.add_to_timeline(f"sequencia:{top.id}")
    assert "níveis" in status(win) and len(win.model.seq.clips) == n


def test_the_media_menu_of_a_sequence_places_it(win, monkeypatch):
    fresh(win, seq=color_seq(1))
    other_id = other_sequence(win, monkeypatch)[1]
    key = f"sequencia:{other_id}"
    win.bin.list.clearSelection()
    win.bin.list.media(key).setSelected(True)
    menu = QMenu()
    win.bin.fill_media_menu(menu)
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[:4] == ["Abrir a sequência", "Adicionar ao fim da linha do tempo", "Inserir no cursor (,)",
                         "Sobrescrever no cursor (.)"]
    next(a for a in menu.actions() if a.text() == "Adicionar ao fim da linha do tempo").trigger()
    pump()
    assert nested_clips(win)
    # dois cliques na Mídia continuam abrindo a aba
    win.bin.openRequested.emit(key)
    pump()
    assert win.model.seq.id == other_id


# ------------------------------------------------------------------ dois cliques num clipe de sequência
def test_double_click_on_a_nested_clip_opens_its_tab_at_the_inner_frame_and_the_other_tab_keeps_its_state(win, monkeypatch):
    fresh(win, seq=color_seq(1))
    first_id, inner_id = other_sequence(win, monkeypatch, n=2, secs=4.0)     # dentro: 192 quadros
    win.add_to_timeline(f"sequencia:{inner_id}")
    pump()
    clip = nested_clips(win)[0]
    canvas = win.tl_editor.canvas
    win.seek(7)
    pump()
    canvas.set_ppf(2.0)
    win.model.select([])
    r = canvas.clip_rect(clip)
    x = r.left() + r.width() * 0.5
    frame = int(canvas.x_to_frame(x))
    double_click(canvas, QPointF(x, r.center().y()))
    pump(lambda: win.model.seq.id == inner_id)
    pump()
    assert win.model.seq.id == inner_id and win.model.seq.display_name in win.seqs_ui.tabs.tabs[1].name
    expect = min(max(0, win.model.sequences()[0].src_frame(clip, frame)), win.model.seq.duration - 1)
    assert win.frame_idx == expect and expect > 0
    assert win.model.selection == []
    # a aba de fora, de volta: o cursor, o zoom e a seleção do estado dela
    win.seqs_ui.activate(first_id)
    pump()
    assert win.frame_idx == 7 and abs(canvas.ppf - 2.0) < 1e-6


def test_double_click_clamps_the_inner_frame_to_the_sequence_and_follows_speed(win, monkeypatch):
    fresh(win, seq=color_seq(1))
    first_id, inner_id = other_sequence(win, monkeypatch, n=1, secs=2.0)       # 48 quadros dentro
    win.add_to_timeline(f"sequencia:{inner_id}")
    pump()
    clip = nested_clips(win)[0]
    win.model.set_clip_values(clip.id, {**clip.values, "velocidade": 2.0})
    assert clip.dur == 24
    canvas = win.tl_editor.canvas
    r = canvas.clip_rect(clip)
    double_click(canvas, QPointF(r.right() - 3, r.center().y()))      # perto do fim: quadro 22 × 2 = 44
    pump(lambda: win.model.seq.id == inner_id)
    pump()
    assert win.model.seq.id == inner_id and 40 <= win.frame_idx <= 47


# ------------------------------------------------------------------ aninhar seleção
def count_history(win) -> int:
    h = win.model.history
    return len(h.undo_stack) if hasattr(h, "undo_stack") else h.pos


def test_nest_selection_from_the_menu_the_shortcut_and_one_undo_step(win, monkeypatch):
    fresh(win, seq=color_seq(2))
    seq = win.model.seq
    a, b = seq.clips[0], seq.clips[1]
    win.model.select([a.id, b.id])
    pump()
    acts = context_actions(win.tl_editor.canvas, win.tl_editor.canvas.clip_rect(a).center(), monkeypatch)
    assert "Aninhar seleção (Ctrl+Shift+G)" in acts and "Desaninhar" not in acts
    before = win.model.history.pos if hasattr(win.model.history, "pos") else None
    ids_before = [c.id for c in seq.clips]
    win.statusBar().clearMessage()
    context_actions(win.tl_editor.canvas, win.tl_editor.canvas.clip_rect(a).center(), monkeypatch,
                    trigger="Aninhar seleção (Ctrl+Shift+G)")
    pump()
    assert "aninhada em" in status(win) and "Ctrl+Z desfaz" in status(win)
    sel = win.model.selection
    assert len(win.model.sequences()) == 2 and win.model.seq is win.model.sequences()[0]    # a aba é a de fora
    assert sel and all(win.model.seq.nested(win.model.seq.find(i)) is not None for i in sel)
    assert {c.id for c in win.model.sequences()[1].clips} >= set(ids_before)                  # ids mantidos
    assert any(p.startswith("sequencia:") for p in win.bin.paths())
    assert win.model.can_undo()
    win.model.undo()                                  # um passo só
    pump()
    assert len(win.model.sequences()) == 1 and [c.id for c in win.model.seq.clips] == ids_before
    if before is not None:
        assert win.model.history.pos == before
    # o atalho
    win.model.select([a.id, b.id])
    win.nest_ui.shortcut.activated.emit()
    pump()
    assert len(win.model.sequences()) == 2 and win.model.seq is win.model.sequences()[0]


def test_nest_selection_refuses_in_the_status_bar_and_changes_nothing(win):
    fresh(win, seq=color_seq(2))
    seq = win.model.seq
    win.model.select([])
    before = seq.to_json()
    win.statusBar().clearMessage()
    assert win.nest_ui.nest_selection() is False
    assert "Selecione" in status(win) and win.model.seq.to_json() == before and len(win.model.sequences()) == 1
    seq.track(tl.VIDEO, 0).locked = True
    win.model.select([seq.clips[0].id])
    assert win.nest_ui.nest_selection() is False and "travada" in status(win)
    seq.track(tl.VIDEO, 0).locked = False


def test_nest_selection_keeps_the_view_of_a_lone_sequence(win):
    fresh(win, seq=color_seq(2))
    canvas = win.tl_editor.canvas
    canvas.set_ppf(3.0)
    win.seek(20)
    pump()
    seq = win.model.seq
    win.model.select([seq.clips[0].id])
    assert win.nest_ui.nest_selection()
    pump()
    assert win.frame_idx == 20 and abs(canvas.ppf - 3.0) < 1e-6


def test_nest_selection_warns_when_the_look_reads_the_cuts(win):
    fresh(win, seq=color_seq(2))
    win.store.set("mfilme_on", True)
    win.model.select([win.model.seq.clips[0].id])
    win.nest_ui.nest_selection()
    assert "cortes" in status(win)
    win.store.set("mfilme_on", False)


# ------------------------------------------------------------------ desaninhar
def nest_first(win) -> tl.Clip:
    seq = win.model.seq
    win.model.select([seq.clips[0].id])
    assert win.nest_ui.nest_selection()
    pump()
    return nested_clips(win)[0]


def test_unnest_from_the_menu_one_undo_step_and_the_inner_sequence_stays(win, monkeypatch):
    fresh(win, seq=color_seq(2))
    ids = [c.id for c in win.model.seq.clips]
    nested = nest_first(win)
    canvas = win.tl_editor.canvas
    acts = context_actions(canvas, canvas.clip_rect(nested).center(), monkeypatch)
    assert "Desaninhar" in acts and "Abrir a sequência" in acts
    context_actions(canvas, canvas.clip_rect(nested).center(), monkeypatch, trigger="Desaninhar")
    pump()
    assert "desaninhada" in status(win) and not nested_clips(win)
    assert sorted(c.id for c in win.model.seq.clips) == sorted(ids) and len(win.model.sequences()) == 2
    win.model.undo()
    pump()
    assert nested_clips(win)


def test_unnest_asks_before_losing_adjustments_and_refuses_speed(win, monkeypatch):
    fresh(win, seq=color_seq(2))
    nested = nest_first(win)
    win.model.set_clip_values(nested.id, {**nested.values, "opacidade": 0.5})
    asked = []
    monkeypatch.setattr(win.nest_ui, "confirm_unnest", lambda name, loss: asked.append(loss) or False)
    assert win.nest_ui.unnest(nested.id) is False
    assert asked and "opacidade" in asked[0] and nested_clips(win)           # recusou a pergunta: nada mudou
    monkeypatch.setattr(win.nest_ui, "confirm_unnest", lambda name, loss: asked.append(loss) or True)
    win.model.set_clip_values(nested.id, {**nested.values, "velocidade": 2.0})
    assert win.nest_ui.unnest(nested.id) is False and "velocidade" in status(win) and nested_clips(win)
    win.model.set_clip_values(nested.id, {**nested.values, "velocidade": 1.0})
    assert win.nest_ui.unnest(nested.id) is True and not nested_clips(win)


# ------------------------------------------------------------------ o clipe na linha do tempo
def test_a_nested_clip_is_painted_with_its_own_color_and_the_name_of_the_sequence(win):
    fresh(win, seq=color_seq(2))
    nested = nest_first(win)
    win.model.select([])
    canvas = win.tl_editor.canvas
    canvas.resize(canvas.width(), canvas.height())
    img = canvas.grab().toImage()
    r = canvas.clip_rect(nested)
    probe = img.pixelColor(int(r.left() + r.width() * 0.6), int(r.bottom() - 6))
    want = QColor(theme.CLIP_NESTED)
    assert abs(probe.red() - want.red()) < 12 and abs(probe.blue() - want.blue()) < 12
    other = canvas.clip_rect(win.model.seq.clips[-1]) if win.model.seq.clips[-1] is not nested else None
    if other is not None:
        amber = img.pixelColor(int(other.left() + other.width() * 0.6), int(other.bottom() - 6))
        assert amber.red() > amber.blue() + 30                            # a cor do vídeo comum é outra
    assert canvas._clip_colors(nested)[0] == QColor(theme.CLIP_NESTED)
    # o nome é o de agora da sequência
    inner = win.model.seq.nested(nested)
    win.seqs_ui.rename(inner.id, "Abertura")
    pump()
    src = win.model.seq.sources[nested.src]
    assert src.name == "Abertura"


def test_the_waveform_of_a_nested_audio_clip_comes_from_the_wav_of_its_mix(win, tmp_path, monkeypatch):
    v = tone_video(tmp_path, "tom.mp4", "160x90", 24, 330, secs=2)
    fresh(win)
    win.import_paths([v])
    pump(lambda: win.cur is not None)
    seq = win.model.seq
    win.model.select([c.id for c in seq.clips])
    assert win.nest_ui.nest_selection()
    pump()
    aud = nested_clips(win, tl.AUDIO)
    assert aud
    src = win.model.seq.sources[aud[0].src]
    nest_dir = tmp_path / "som_aninhado"
    monkeypatch.setattr(audiomix, "nested_dir", lambda: nest_dir)
    win.nest_ui._wav.clear()
    assert win._peaks_for(src.path) is None                    # o WAV ainda não existe: a linha reta
    assert audiomix.render_mix(win.model.seq.copy(), str(tmp_path / "mix.wav")) is True
    win.nest_ui._wav.clear()
    win.nest_ui.mix_finished()
    win._peaks_for(src.path)                                   # agora lê o WAV, em segundo plano
    pump(lambda: win._peaks_for(src.path) is not None, timeout=20)
    peaks = win._peaks_for(src.path)
    assert peaks is not None and len(peaks) > 100 and float(peaks.max()) > 0.05
    # uma edição de dentro muda a chave: outra onda
    inner = win.model.seq.nested(src)
    key1 = win.nest_ui._wav[src.path]
    inner.clips = [c for c in inner.clips if c.kind == tl.VIDEO]
    win.model.changed.emit("structure")
    win.nest_ui._wav.clear()
    win.nest_ui.peaks(src)
    assert win.nest_ui._wav[src.path] != key1


# ------------------------------------------------------------------ inspetor e ferramentas que leem o arquivo
def test_the_inspector_hides_the_camera_profile_and_the_automatic_chip_for_a_nested_clip(win):
    fresh(win, seq=color_seq(2))
    insp = win.inspector
    plain = win.model.seq.clips[1]
    win.model.select([plain.id])
    pump()
    cam = next(c for c in insp.vcards if c.section.key == "camera")
    assert not cam.isHidden() and insp.chip_auto.isEnabled()
    nested = nest_first(win)
    win.model.select([nested.id])
    pump()
    assert cam.isHidden() and not insp.chip_auto.isEnabled() and "sequência" in insp.chip_auto.toolTip()
    assert insp.title.text() == win.model.seq.sources[nested.src].name and "Sequência" in insp.info.text()
    win.model.select([plain.id] if win.model.seq.find(plain.id) else [])
    pump()
    assert not cam.isHidden() and insp.chip_auto.isEnabled() and "sequência" not in insp.chip_auto.toolTip()
    # o resto do inspetor (opacidade, cor, enquadramento, velocidade, transições) segue ali
    win.model.select([nested.id])
    pump()
    keys = {k for card in insp.vcards if not card.isHidden() for k in card.keys()}
    assert {"opacidade", "escala", "velocidade", "entrada_tipo", "saturacao"} <= keys


def test_the_color_tools_are_off_for_a_nested_clip_and_say_why(win):
    fresh(win, seq=color_seq(2))
    tools = win.color_tools if hasattr(win, "color_tools") else None
    if tools is None:
        from pelicula.ui import cor_ui
        tools = getattr(cor_ui, "tools_of", lambda w: None)(win)
    if tools is None:
        pytest.skip("barra de cor simples desligada")
    nested = nest_first(win)
    win.model.select([nested.id])
    pump()
    tools.refresh()
    for b in (tools.btn_wb, tools.btn_color, tools.btn_match):
        assert not b.isEnabled() and "sequência" in b.toolTip()
    assert tools.current_frame_of(nested) is None
    c, rgb = tools.clip_color_at(0.5, 0.5)
    assert rgb is None


def test_automatic_color_refuses_a_nested_clip_without_changing_it(win):
    fresh(win, seq=color_seq(2))
    nested = nest_first(win)
    before = dict(nested.values)
    win.auto_adjust_clip(nested.id)
    assert "arquivo" in status(win) and nested.values == before
    win.auto_adjust_clip(nested.id, whole=False)
    assert nested.values == before


def test_corridorkey_and_generator_editors_skip_a_nested_clip(win):
    from pelicula.ui import corridorkey_dialog
    fresh(win, seq=color_seq(2))
    nested = nest_first(win)
    win.model.select([nested.id])
    pump()
    path, info = corridorkey_dialog.current_source(win)
    assert not path.startswith("sequencia:")
    assert win.gen_editor.isHidden() and win.title_editor.isHidden()
    assert win.model.set_source_data(nested.src, {"cor": "#ffffff"}) is False
    assert win.model.seq.sources[nested.src].is_nested and "sequencia" in win.model.seq.sources[nested.src].data


def test_the_shortcut_is_listed_in_the_help(win, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda parent, title, text: shown.append(text)))
    win.show_shortcuts()
    assert "Ctrl+Shift+G" in shown[0] and aninhar_ui.SHORTCUT == "Ctrl+Shift+G"
