"""Esquema de parâmetros: defaults() e sanitize()."""

from __future__ import annotations

import copy
import math

import pytest

from pelicula import params

TOGGLES = [s.toggle for s in params.SECTIONS if s.toggle]


def test_defaults_contains_every_key_with_schema_default():
    d = params.defaults()
    assert set(d) == set(params.PARAMS)
    for k, p in params.PARAMS.items():
        if p.kind == "color":
            assert isinstance(d[k], list) and d[k] == list(p.default), k
        else:
            assert d[k] == p.default, k


def test_param_keys_are_unique_across_sections():
    keys = [p.key for s in params.SECTIONS for p in s.params]
    assert len(keys) == len(set(keys))


def test_defaults_returns_independent_copies():
    a = params.defaults()
    a["hal_cor"][0] = 0.123
    a["exposicao"] = 2.0
    b = params.defaults()
    assert b["hal_cor"][0] == params.PARAMS["hal_cor"].default[0]
    assert b["exposicao"] == 0.0


@pytest.mark.parametrize("key", list(params.PARAMS))
def test_schema_default_is_valid(key):
    p = params.PARAMS[key]
    assert p.kind in ("float", "int", "bool", "choice", "color", "file")
    if p.kind in ("float", "int"):
        assert p.min <= p.max
        assert p.min <= p.default <= p.max, f"{key}: {p.default} fora de [{p.min}, {p.max}]"
    if p.kind == "int":
        assert isinstance(p.default, int)
    if p.kind == "choice":
        ids = [c[0] for c in p.choices]
        assert len(ids) == len(set(ids)), f"{key}: escolhas repetidas"
        assert p.default in ids
    if p.kind == "color":
        assert len(p.default) == 3 and all(0.0 <= c <= 1.0 for c in p.default)
    if p.percent:
        assert (p.min, p.max) == (0, 1), f"{key}: percent precisa de faixa 0..1"


def test_section_toggles_are_bool_params_inside_their_section():
    for s in params.SECTIONS:
        if s.toggle:
            assert params.PARAMS[s.toggle].kind == "bool"
            assert s.toggle in [p.key for p in s.params]
            # Todos os efeitos começam desligados.
            assert params.PARAMS[s.toggle].default is False


def test_sanitize_defaults_is_identity():
    d = params.defaults()
    assert params.sanitize(d) == d


@pytest.mark.parametrize("value", [None, {}])
def test_sanitize_empty_fills_defaults(value):
    assert params.sanitize(value) == params.defaults()


def test_sanitize_fills_missing_and_ignores_unknown():
    out = params.sanitize({"exposicao": 1.0, "nao_existe": 5, "": 1})
    assert out["exposicao"] == 1.0
    assert "nao_existe" not in out and "" not in out
    assert set(out) == set(params.PARAMS)


def test_sanitize_does_not_mutate_input():
    src = {"exposicao": 99, "hal_cor": [2.0, -1.0, 0.5]}
    before = copy.deepcopy(src)
    params.sanitize(src)
    assert src == before


@pytest.mark.parametrize("raw, expected", [
    (10, 3.0), (-10, -3.0), (1.25, 1.25), ("1.5", 1.5), (float("inf"), 3.0), (float("-inf"), -3.0), (True, 1.0),
])
def test_sanitize_clamps_float(raw, expected):
    assert params.sanitize({"exposicao": raw})["exposicao"] == expected


@pytest.mark.parametrize("key", [k for k, p in params.PARAMS.items() if p.kind == "float"])
def test_sanitize_clamps_every_float_to_its_range(key):
    p = params.PARAMS[key]
    assert params.sanitize({key: p.max + 1000})[key] == p.max
    assert params.sanitize({key: p.min - 1000})[key] == p.min


@pytest.mark.parametrize("raw", ["abc", None, [1, 2], {"a": 1}])
def test_sanitize_bad_float_keeps_default(raw):
    assert params.sanitize({"exposicao": raw})["exposicao"] == params.PARAMS["exposicao"].default


def test_sanitize_rejects_nan():
    out = params.sanitize({"exposicao": float("nan"), "hal_cor": [float("nan"), 0.5, 0.5]})
    assert not math.isnan(out["exposicao"])
    assert all(not math.isnan(c) for c in out["hal_cor"])


@pytest.mark.parametrize("raw, expected", [(99999, 9999), (-5, 0), ("42", 42), (3.9, 3), (12, 12)])
def test_sanitize_int(raw, expected):
    out = params.sanitize({"grao_semente": raw})["grao_semente"]
    assert out == expected and isinstance(out, int)


@pytest.mark.parametrize("raw", ["3.7", "x", None, float("nan")])
def test_sanitize_bad_int_keeps_default(raw):
    assert params.sanitize({"grao_semente": raw})["grao_semente"] == params.PARAMS["grao_semente"].default


@pytest.mark.parametrize("raw, expected", [(0, False), (1, True), (True, True), (False, False), ("", False)])
def test_sanitize_bool(raw, expected):
    assert params.sanitize({"cor_on": raw})["cor_on"] is expected


def test_sanitize_choice_accepts_valid_and_rejects_bad():
    assert params.sanitize({"bitola": "super8"})["bitola"] == "super8"
    assert params.sanitize({"bitola": "70mm"})["bitola"] == params.PARAMS["bitola"].default
    assert params.sanitize({"bitola": None})["bitola"] == params.PARAMS["bitola"].default
    # ISO é guardado como texto, mas números também são aceitos.
    assert params.sanitize({"iso": 400})["iso"] == "400"
    assert params.sanitize({"iso": "123"})["iso"] == params.PARAMS["iso"].default


@pytest.mark.parametrize("key", [k for k, p in params.PARAMS.items() if p.kind == "choice"])
def test_sanitize_every_choice_roundtrips(key):
    for cid, _label in params.PARAMS[key].choices:
        assert params.sanitize({key: cid})[key] == cid


def test_sanitize_color_clamps_and_converts():
    out = params.sanitize({"hal_cor": (2, -1, "0.5", 9), "cor_barras": [0.1, 0.2, 0.3]})
    assert out["hal_cor"] == [1.0, 0.0, 0.5]
    assert out["cor_barras"] == [0.1, 0.2, 0.3]
    assert isinstance(out["hal_cor"], list)


@pytest.mark.parametrize("raw", [0.5, "abc", None, ["r", "g", "b"]])
def test_sanitize_bad_color_keeps_default(raw):
    assert params.sanitize({"hal_cor": raw})["hal_cor"] == list(params.PARAMS["hal_cor"].default)


def test_sanitize_short_color_is_rejected_or_completed():
    out = params.sanitize({"hal_cor": [0.5], "vazamento_cor": [0.1, 0.2]})
    assert len(out["hal_cor"]) == 3
    assert len(out["vazamento_cor"]) == 3


def test_sanitize_file_param():
    assert params.sanitize({"lut_arquivo": None})["lut_arquivo"] == ""
    assert params.sanitize({"lut_arquivo": "C:/luts/a.cube"})["lut_arquivo"] == "C:/luts/a.cube"


def test_sanitize_output_is_always_valid_for_garbage_input():
    garbage = {k: "lixo" for k in params.PARAMS}
    out = params.sanitize(garbage)
    for k, p in params.PARAMS.items():
        v = out[k]
        if p.kind in ("float", "int"):
            assert p.min <= v <= p.max
        elif p.kind == "choice":
            assert v in [c[0] for c in p.choices]
        elif p.kind == "color":
            assert len(v) == 3
