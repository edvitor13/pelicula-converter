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


def test_visible_hides_tests_unless_asked():
    s = FakeSettings()
    shown = {m.id for m in modules.visible(s)}
    assert shown == {m.id for m in modules.MODULES if m.status == modules.ESTAVEL}
    s[modules.KEY_SHOW_TESTS] = "1"
    assert {m.id for m in modules.visible(s)} == {m.id for m in modules.MODULES}
