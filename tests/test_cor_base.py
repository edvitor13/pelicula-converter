"""As ferramentas de cor da 1.6 não mudam nada com os padrões: o que a BASE gravou em `tests/data/cor_base.json`
(`tests/cor_base.py`) continua igual — planos do look, uniforms dos clipes, texto do plugin do DaVinci e, na
mesma placa e driver da gravação, os quadros do look (8 e 16 bits), o LUT exportado e os quadros do modo Edição
bit a bit."""

from __future__ import annotations

import json

import numpy as np
import pytest

import cor_base as base

REF = json.loads(base.DATA.read_text(encoding="utf-8"))

# Uniforms novos da 1.6 (cor): sempre enviados (o Engine só troca os uniforms do dicionário, então uma chave
# que some deixaria o valor do quadro anterior), com o valor que desliga a ferramenta.
NEW_LOOK_UNIFORMS: dict[str, object] = {}
NEW_CLIP_UNIFORMS: dict[str, object] = {}


def _flat(u) -> dict:
    out = {}

    def walk(prefix, v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(f"{prefix}.{k}" if prefix else str(k), x)
        elif isinstance(v, list):
            out[f"{prefix}#"] = len(v)
            for i, x in enumerate(v):
                walk(f"{prefix}[{i}]", x)
        else:
            out[prefix] = v
    walk("", u)
    return out


def _without_new(u: dict, new: dict) -> dict:
    u = dict(u)
    for k, neutral in new.items():
        if k in u:
            got = u.pop(k)
            assert np.allclose(np.asarray(got, dtype=float), np.asarray(neutral, dtype=float)), (k, got, neutral)
    return u


def _same(now, old) -> None:
    a, b = _flat(now), _flat(old)
    assert a.keys() == b.keys()
    for k in b:
        if isinstance(b[k], (int, float)) and not isinstance(b[k], bool):
            assert a[k] == pytest.approx(b[k], rel=1e-12, abs=1e-12), k
        else:
            assert a[k] == b[k], k


def test_look_plans_are_the_ones_of_the_base():
    now = json.loads(json.dumps(base.plan_uniforms()))
    assert now.keys() == REF["planos"].keys()
    for name, old in REF["planos"].items():
        plan = dict(now[name])
        plan["uniforms"] = _without_new(plan["uniforms"], NEW_LOOK_UNIFORMS)
        _same(plan, old)


def test_clip_uniforms_are_the_ones_of_the_base():
    now = json.loads(json.dumps(base.clip_uniforms(base.scenario())))
    assert now.keys() == REF["clipes"].keys()
    for t, rows in REF["clipes"].items():
        assert len(now[t]) == len(rows), t
        for a, b in zip(now[t], rows):
            assert a["mip"] == b["mip"], t
            _same(_without_new(a["u"], NEW_CLIP_UNIFORMS), b["u"])


def test_plugin_sources_are_the_ones_of_the_base():
    assert base.plugin_sources() == REF["plugin"]


@pytest.fixture(scope="module")
def same_card(gl_engine):
    if gl_engine.renderer != REF["renderer"]:
        pytest.skip(f"referência gravada em {REF['renderer']}")
    return gl_engine


@pytest.mark.gpu
def test_look_frames_are_the_bits_of_the_base(same_card):
    assert base.look_hashes(same_card) == REF["look"]


@pytest.mark.gpu
def test_exported_luts_are_the_bits_of_the_base(same_card):
    assert base.lut_hashes(same_card) == REF["lut"]


@pytest.mark.gpu
def test_edit_frames_are_the_bits_of_the_base(same_card):
    assert base.edit_hashes(same_card, base.scenario()) == REF["edicao"]
