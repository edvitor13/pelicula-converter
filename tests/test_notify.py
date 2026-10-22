"""Notificações do sistema sem Qt (`pelicula/notify.py`): preferências, a decisão de avisar e os textos.

Os widgets e os backends (bandeja, D-Bus) ficam em `notify_ui_cases.py`, num subprocesso offscreen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pelicula import i18n, notify


class Settings(dict):
    """Imita o QSettings (value/setValue) num dicionário."""

    def value(self, key, default=None):
        return self.get(key, default)

    def setValue(self, key, value):
        self[key] = value


@pytest.fixture(autouse=True)
def _pt_br():
    old = i18n.language()
    i18n.set_language("pt_BR")
    yield
    i18n.set_language(old)


# ------------------------------------------------------------------ tipos e preferências
def test_kinds_have_ascii_ids_and_labels():
    ids = [k.id for k in notify.KINDS]
    assert len(set(ids)) == len(ids) == 6
    assert set(ids) == {notify.EXPORT_DONE, notify.EXPORT_FAILED, notify.QUEUE_DONE, notify.COMPONENT_DONE,
                        notify.COMPONENT_FAILED, notify.UPDATE}
    for k in notify.KINDS:
        assert k.id.isascii() and k.id == k.id.lower() and " " not in k.id
        assert k.label and k.description
        assert notify.kind_key(k.id) == "notificacoes/" + k.id
        assert notify.get(k.id) is k
    assert notify.TEST not in ids  # o botão de teste não é um tipo das preferências


def test_defaults_without_saved_preferences():
    for s in (Settings(), None):
        p = notify.load(s)
        assert p.kinds == frozenset(notify.KIND_IDS)  # todos ligados
        assert p.only_unfocused is True
        assert p.sound is False
        assert p.flash is True


def test_preferences_round_trip():
    s = Settings()
    notify.set_kind(s, notify.UPDATE, False)
    notify.set_option(s, notify.KEY_SOUND, True)
    notify.set_option(s, notify.KEY_FLASH, False)
    notify.set_option(s, notify.KEY_ONLY_UNFOCUSED, False)
    assert s == {"notificacoes/atualizacao_disponivel": "0", "notificacoes/som": "1", "notificacoes/piscar": "0",
                 "notificacoes/so_sem_foco": "0"}
    p = notify.load(s)
    assert not p.kind_on(notify.UPDATE) and p.kind_on(notify.EXPORT_DONE)
    assert p.sound and not p.flash and not p.only_unfocused
    notify.set_kind(s, notify.UPDATE, True)
    assert notify.load(s).kind_on(notify.UPDATE)


def test_preferences_read_qsettings_style_values():
    """O QSettings em .ini devolve texto; o registro do Windows pode devolver bool."""
    s = Settings({"notificacoes/som": "true", "notificacoes/piscar": False, "notificacoes/so_sem_foco": "",
                  "notificacoes/fila_concluida": "false"})
    p = notify.load(s)
    assert p.sound is True and p.flash is False and p.only_unfocused is True
    assert not p.kind_on(notify.QUEUE_DONE)


def test_unknown_kind_or_option_is_rejected():
    with pytest.raises(KeyError):
        notify.set_kind(Settings(), "nao_existe", True)
    with pytest.raises(KeyError):
        notify.set_option(Settings(), "notificacoes/outra", True)


# ------------------------------------------------------------------ decisão
P = notify.Prefs()


@pytest.mark.parametrize("kind", notify.KIND_IDS)
def test_decide_shows_when_window_is_in_background(kind):
    d = notify.decide(kind, module_on=True, focused=False, prefs=P)
    assert d == notify.Decision(show=True, sound=False, flash=True)
    assert d.anything


@pytest.mark.parametrize("kind", notify.KIND_IDS)
def test_decide_stays_quiet_with_the_window_in_focus(kind):
    assert notify.decide(kind, module_on=True, focused=True, prefs=P) == notify.NOTHING
    assert not notify.NOTHING.anything


def test_decide_with_focus_when_the_option_is_off():
    p = notify.Prefs(only_unfocused=False, sound=True, flash=False)
    assert notify.decide(notify.EXPORT_DONE, True, True, p) == notify.Decision(show=True, sound=True, flash=False)


def test_decide_respects_each_kind():
    p = notify.Prefs(kinds=frozenset(notify.KIND_IDS) - {notify.EXPORT_DONE})
    assert notify.decide(notify.EXPORT_DONE, True, False, p) == notify.NOTHING
    assert notify.decide(notify.EXPORT_FAILED, True, False, p).show


def test_decide_module_off_only_flashes_like_before_for_exports():
    """Sem o módulo, nada de notificação nem som; o ícone pisca no fim de uma exportação, como antes."""
    loud = notify.Prefs(sound=True, flash=True)
    for kind in (notify.EXPORT_DONE, notify.EXPORT_FAILED, notify.QUEUE_DONE):
        assert notify.decide(kind, False, False, loud) == notify.Decision(flash=True)
    for kind in (notify.COMPONENT_DONE, notify.COMPONENT_FAILED, notify.UPDATE):
        assert notify.decide(kind, False, False, loud) == notify.NOTHING
    assert notify.decide(notify.TEST, False, False, loud, test=True) == notify.NOTHING


def test_decide_test_button_ignores_focus_and_kinds():
    p = notify.Prefs(kinds=frozenset(), only_unfocused=True, sound=True, flash=False)
    assert notify.decide(notify.TEST, True, True, p, test=True) == notify.Decision(show=True, sound=True)


# ------------------------------------------------------------------ mensagens
def test_export_done_targets_the_file():
    n = notify.export_done("final.mp4", "C:/saida/final.mp4")
    assert n.kind == notify.EXPORT_DONE and n.target == "C:/saida/final.mp4" and not n.action
    assert "final.mp4" in n.body and n.title == "Exportação concluída"
    assert "final.mp4" in notify.export_done("", "/tmp/final.mp4").body


def test_failed_notices_open_the_queue_with_the_last_error_line():
    n = notify.export_failed("clipe", "linha 1\nCodificador recusou o tamanho\n")
    assert n.kind == notify.EXPORT_FAILED and n.action == notify.ACTION_QUEUE and not n.target
    assert n.body.startswith("clipe não foi exportado.") and n.body.endswith("Codificador recusou o tamanho")
    assert len(notify.export_failed("x", "e" * 1000).body) < 220


def test_component_and_update_notices():
    ok = notify.component_done("ffmpeg")
    bad = notify.component_failed("ffmpeg", "SHA-256 não confere")
    up = notify.update_available("1.4.0")
    assert (ok.kind, ok.action) == (notify.COMPONENT_DONE, notify.ACTION_COMPONENTS)
    assert (bad.kind, bad.action) == (notify.COMPONENT_FAILED, notify.ACTION_COMPONENTS)
    assert "SHA-256" in bad.body
    assert (up.kind, up.action) == (notify.UPDATE, notify.ACTION_UPDATE) and "1.4.0" in up.body


# ------------------------------------------------------------------ fila
F = notify.Finished


def test_single_export_notifies_by_itself():
    out = notify.queue_notices([F("concluido", "a", "/v/a.mp4")], [F("concluido", "a", "/v/a.mp4")], idle=True)
    assert [n.kind for n in out] == [notify.EXPORT_DONE]
    out = notify.queue_notices([F("erro", "a", error="falhou")], [F("erro", "a", error="falhou")], idle=True)
    assert [n.kind for n in out] == [notify.EXPORT_FAILED]


def test_queue_summary_replaces_the_last_notice():
    a, b = F("concluido", "a", "/v/a.mp4"), F("concluido", "b", "/v/b.mp4")
    first = notify.queue_notices([a], [a], idle=False)
    assert [n.kind for n in first] == [notify.EXPORT_DONE]
    last = notify.queue_notices([b], [a, b], idle=True)
    assert [n.kind for n in last] == [notify.QUEUE_DONE]
    assert Path(last[0].target) == Path("/v") and "2 exportações concluídas" in last[0].body  # mesma pasta: abre a pasta


def test_queue_summary_with_errors_or_many_folders_opens_the_queue():
    a, b, c = F("concluido", "a", "/v/a.mp4"), F("erro", "b"), F("concluido", "c", "/w/c.mp4")
    out = notify.queue_notices([b], [a, b], idle=True)
    assert out[0].action == notify.ACTION_QUEUE and not out[0].target
    assert "1 exportações concluídas e 1 com erro" in out[0].body
    out = notify.queue_notices([c], [a, c], idle=True)
    assert out[0].action == notify.ACTION_QUEUE


def test_cancelled_exports_do_not_notify():
    a = F("concluido", "a", "/v/a.mp4")
    assert notify.queue_notices([F("cancelado", "b")], [a, F("cancelado", "b")], idle=True) == []
    assert notify.queue_notices([], [a], idle=True) == []
