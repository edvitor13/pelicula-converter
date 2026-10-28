"""Registro de módulos (pelicula/modules.py): padrões, perfis e uso por projetos."""

from __future__ import annotations

import pytest

from pelicula import modules, params


class FakeSettings(dict):
    def value(self, key, default=None):
        return self.get(key, default)

    def setValue(self, key, value):  # noqa: N802 (mesma API do QSettings)
        self[key] = value


def test_ids_are_unique_ascii_and_have_known_groups():
    ids = [m.id for m in modules.MODULES]
    assert len(ids) == len(set(ids))
    groups = {g for g, _name in modules.GROUPS}
    for m in modules.MODULES:
        assert m.id.isascii() and m.id == m.id.lower() and " " not in m.id
        assert m.group in groups
        assert m.status in modules.STATUS_LABELS
        assert m.name and m.description


def test_defaults_keep_stable_modules_on_for_existing_users():
    s = FakeSettings()
    for m in modules.MODULES:
        assert modules.is_enabled(s, m.id) == (m.status == modules.ESTAVEL)
    assert modules.current_profile(s) == "tudo"


def test_set_and_read_back_including_legacy_values():
    s = FakeSettings()
    modules.set_enabled(s, "laboratorio", False)
    assert s["modulos/laboratorio"] == "0"
    assert not modules.is_enabled(s, "laboratorio")
    s["modulos/laboratorio"] = "true"
    assert modules.is_enabled(s, "laboratorio")
    s["modulos/laboratorio"] = True
    assert modules.is_enabled(s, "laboratorio")
    with pytest.raises(KeyError):
        modules.set_enabled(s, "nao_existe", True)
    assert not modules.is_enabled(s, "nao_existe")


@pytest.mark.parametrize("profile", [p[0] for p in modules.PROFILES])
def test_profiles_round_trip(profile):
    s = FakeSettings()
    modules.apply_profile(s, profile)
    assert modules.current_profile(s) == profile
    assert s[modules.KEY_PROFILE] == profile
    chosen = next(p[3] for p in modules.PROFILES if p[0] == profile)
    for m in modules.MODULES:
        if m.status == modules.ESTAVEL:
            assert modules.is_enabled(s, m.id) == (m.id in chosen)


def test_profiles_are_nested_and_known():
    sets = {pid: ids for pid, _n, _d, ids in modules.PROFILES}
    assert sets["simples"] <= sets["criador"] <= sets["cinema"] <= sets["tudo"]
    every = {m.id for m in modules.MODULES}
    for ids in sets.values():
        assert ids <= every


@pytest.mark.parametrize("profile", [p[0] for p in modules.PROFILES])
def test_a_module_newer_than_the_chosen_profile_follows_it(profile):
    """Quem escolheu o perfil numa versão antiga não tem preferência gravada para os módulos que vieram
    depois (os da 1.5): eles seguem o perfil, e o perfil continua o mesmo."""
    s = FakeSettings()
    modules.apply_profile(s, profile)
    newer = ("transicoes", "legendas", "silencios", "titulos_geradores")
    for mid in newer:
        del s[modules.KEY_PREFIX + mid]
    chosen = next(p[3] for p in modules.PROFILES if p[0] == profile)
    for mid in newer:
        assert modules.is_enabled(s, mid) == (mid in chosen), mid
    assert modules.current_profile(s) == profile
    assert not modules.is_enabled(s, "legendas_auto")  # recurso em teste: nunca pelo perfil
    s[modules.KEY_PROFILE] = "perfil_que_nao_existe"
    assert all(modules.is_enabled(s, mid) for mid in newer)


def test_custom_choice_has_no_profile():
    s = FakeSettings()
    modules.apply_profile(s, "simples")
    modules.set_enabled(s, "scopes", True)
    assert modules.current_profile(s) is None


def test_used_by_detects_sections_from_values():
    v = params.defaults()
    assert modules.used_by(v) == set()
    v.update(lab_on=True, desg_on=True, scan_on=True, lut_on=True, lut_arquivo="C:/x.cube")
    assert modules.used_by(v) == {"laboratorio", "defeitos", "scan", "luts"}
    v.update(lut_arquivo="")
    assert "luts" not in modules.used_by(v)


def test_used_by_detects_a_real_edit():
    class Seq:
        def __init__(self, trivial):
            self.trivial = trivial

        def is_trivial(self):
            return self.trivial

    assert "edicao" in modules.used_by(None, Seq(False))
    assert "edicao" not in modules.used_by(None, Seq(True))


def test_used_by_ignores_an_empty_or_whole_file_sequence():
    from pelicula import timeline
    assert "edicao" not in modules.used_by(None, timeline.Sequence())
    src = timeline.Source("C:/v/a.mp4", 1920, 1080, 24.0, "24/1", 48, 2.0, has_audio=False)
    whole = timeline.Sequence.for_source(src)
    assert whole.is_trivial() and "edicao" not in modules.used_by(None, whole)
    whole.split(12)
    assert "edicao" in modules.used_by(None, whole)


def test_visible_hides_tests_unless_asked():
    s = FakeSettings()
    shown = {m.id for m in modules.visible(s)}
    assert shown == {m.id for m in modules.MODULES if m.status == modules.ESTAVEL}
    s[modules.KEY_SHOW_TESTS] = "1"
    assert {m.id for m in modules.visible(s)} == {m.id for m in modules.MODULES}
