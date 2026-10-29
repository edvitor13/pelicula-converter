"""A entrada da câmera da 1.6 não muda um bit do que já existia (referência da BASE, `tests/entrada_base.py`).

Os uniforms do plano do look valem em qualquer computador. Os quadros do look, os LUTs exportados, a montagem
do modo Edição e o nó Cor do plugin dependem da placa: só são conferidos quando o `GL_RENDERER` é o mesmo da
gravação. A leitura de 8 bits (Rec.709) depende da versão do ffmpeg: só é conferida com o mesmo ffmpeg. A leitura
de 16 bits mudou de propósito na 1.6 (faixa legal expandida exata, `tests/test_entrada_leitura.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import entrada_base as base

REF = json.loads(base.DATA.read_text(encoding="utf-8"))


def _same_gpu(engine) -> None:
    if engine.renderer != REF["renderer"]:
        pytest.skip(f"referência gravada em {REF['renderer']} (aqui: {engine.renderer})")


def _close(a, b, path: str) -> None:
    if isinstance(b, list):
        assert isinstance(a, list) and len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(b, float):
        assert a == pytest.approx(b, rel=1e-12, abs=1e-12), path
    else:
        assert a == b, path


def test_old_profiles_are_still_listed_first():
    from pelicula import look, params
    ids = [c[0] for c in params.PARAMS["entrada"].choices]
    assert ids[:len(base.OLD_INPUTS)] == base.OLD_INPUTS
    old_ids = {"rec709": 0, "linear": 1, "nlog": 2, "slog3": 3, "logc3": 4, "vlog": 5, "cineon": 6, "dwg": 7,
               "log3g10": 8, "bmd_gen5": 9, "logc4": 10, "applelog": 11, "hlg": 12, "pq": 13}
    assert {k: look.INPUT_IDS[k] for k in old_ids} == old_ids


def test_plan_uniforms_are_the_ones_of_the_base():
    """Todo uniform que já existia tem o mesmo valor (os novos, se houver, ficam de fora: são neutros)."""
    now = json.loads(json.dumps(base.plans()))
    old = REF["planos"]
    assert now.keys() == old.keys()
    for name, ref in old.items():
        cur = now[name]
        for k in ("soft_sigma", "grain_size", "grain_seed", "chains"):
            _close(cur[k], ref[k], f"{name}.{k}")
        missing = set(ref["u"]) - set(cur["u"])
        assert not missing, f"{name}: uniforms sumiram: {sorted(missing)}"
        for k, v in ref["u"].items():
            _close(cur["u"][k], v, f"{name}.{k}")


@pytest.mark.gpu
def test_look_frames_are_the_ones_of_the_base(gl_engine):
    _same_gpu(gl_engine)
    now = base.renders(gl_engine)
    bad = [k for k, h in REF["quadros"].items() if now.get(k) != h]
    assert not bad, f"{len(bad)} quadros mudaram: {bad[:8]}"


@pytest.mark.gpu
def test_exported_luts_are_the_ones_of_the_base(gl_engine):
    _same_gpu(gl_engine)
    now = base.luts(gl_engine)
    bad = [k for k, h in REF["luts"].items() if now.get(k) != h]
    assert not bad, f"{len(bad)} LUTs mudaram: {bad[:8]}"


@pytest.mark.gpu
def test_edit_mode_montage_is_the_one_of_the_base(gl_engine):
    _same_gpu(gl_engine)
    now = base.montages(gl_engine)
    bad = [k for k, h in REF["montagens"].items() if now.get(k) != h]
    assert not bad, f"{len(bad)} quadros da montagem mudaram: {bad[:8]}"


@pytest.mark.gpu
def test_plugin_color_node_is_the_one_of_the_base(gl_engine):
    _same_gpu(gl_engine)
    now = base.plugin(gl_engine)
    bad = [k for k, h in REF["plugin"].items() if now.get(k) != h]
    assert not bad, f"{len(bad)} casos do nó Cor mudaram: {bad[:8]}"


def test_8bit_reading_of_rec709_video_is_the_one_of_the_base(tmp_path: Path):
    if base._ffmpeg_version() != REF["ffmpeg"]:
        pytest.skip(f"referência gravada com {REF['ffmpeg']}")
    now = base.decodes(tmp_path)
    keys = [k for k in REF["leitura"] if k.endswith("|8")]
    assert keys
    bad = [k for k in keys if now.get(k) != REF["leitura"][k]]
    assert not bad, f"{len(bad)} leituras de 8 bits mudaram: {bad[:8]}"


def test_reference_images_are_deterministic():
    assert np.array_equal(base.image(8), base.image(8))
    assert base.image(16).dtype == np.uint16
