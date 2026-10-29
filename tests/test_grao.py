"""Grão e textura da 1.6: com os ajustes novos no padrão, o look é o mesmo da BASE, bit a bit.

A referência (`tests/data/grao_base.json`) foi gravada por `tests/grao_base.py` no código da BASE (575c6f5): os
planos (sem GPU), os quadros do modo Película e do modo Edição em 8 e 16 bits, os LUTs exportados, os nós do
plugin do DaVinci (GLSL) e o OpenFX compilado. Os hashes só são conferidos na mesma placa (e no mesmo compilador,
para o OpenFX) da gravação.
"""

from __future__ import annotations

import json
import math

import pytest

import grao_base as base

REF = json.loads(base.DATA.read_text(encoding="utf-8"))


def _close(a, b, path=""):
    if isinstance(b, list):
        assert isinstance(a, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(b, float):
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f"{path}: {a!r} != {b!r}"
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


def test_reference_covers_the_looks():
    assert set(base.looks()) >= {k.split("@")[0] for k in REF["planos"]}
    assert len(REF["planos"]) > 50 and len(REF["pelicula"]) > 300


@pytest.mark.parametrize("key", sorted(REF["planos"]))
def test_plan_with_defaults_is_the_base_plan(key):
    name, rest = key.split("@")
    size, frame = rest.split("#")
    w, h = map(int, size.split("x"))
    got = base.plan_data(base.looks()[name], w, h, int(frame))
    ref = REF["planos"][key]
    for k, v in ref["uniforms"].items():  # só as chaves da BASE: uma frente nova pode acrescentar uniforms
        assert k in got["uniforms"], f"{k} sumiu"
        _close(got["uniforms"][k], v, k)
    for k in ("soft_sigma", "chains", "grain_size", "grain_seed", "lut_path", "edge_text"):
        _close(got[k], ref[k], k)


@pytest.fixture(scope="module")
def same_gpu(gl_engine):
    if gl_engine.renderer != REF["renderer"]:
        pytest.skip(f"referência gravada em {REF['renderer']}")
    return gl_engine


def _diff(got: dict, ref: dict) -> list[str]:
    return sorted(k for k in ref if got.get(k) != ref[k])


def test_film_frames_are_the_base_frames(same_gpu):
    assert not _diff(base.film_hashes(same_gpu), REF["pelicula"])


def test_edit_frames_are_the_base_frames(same_gpu):
    assert not _diff(base.edit_hashes(same_gpu), REF["edicao"])


def test_exported_luts_are_the_base_luts(same_gpu):
    assert not _diff(base.lut_hashes(same_gpu), REF["luts"])


def test_plugin_nodes_are_the_base_nodes(same_gpu):
    assert not _diff(base.plugin_hashes(same_gpu), REF["plugin"])


def test_ofx_is_the_base_ofx():
    if "ofx" not in REF or base.compiler() != REF["ofx_compilador"]:
        pytest.skip("referência do OpenFX gravada com outro compilador")
    core = base.ofx_core()
    if core is None:
        pytest.skip("sem compilador C++")
    assert not _diff(base.ofx_hashes(core), REF["ofx"])
