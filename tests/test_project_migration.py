"""Projetos gravados pela 1.4 abrem, montam e soam exatamente como na 1.4.

`tests/data/projetos_1_4/` tem um projeto simples (formato 1) e uma montagem (formato 2, com cortes, transições,
velocidade, quadro congelado, imagem, fades e transição de som, marcadores e volume de faixa), gravados pela 1.4.0,
e `referencia.json`: o que a 1.4 fez ao abrir esses arquivos (veja `gerar.py`). Aqui o código atual abre os mesmos
arquivos e tem que dar os mesmos valores, as mesmas camadas e uniforms em cada quadro, os mesmos planos do look, o
mesmo grafo do som e o mesmo JSON da montagem.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from pelicula import params

DATA = Path(__file__).with_name("data") / "projetos_1_4"


def _gerar():
    spec = importlib.util.spec_from_file_location("gerar_projetos_1_4", DATA / "gerar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def opened(ffmpeg_ok, tmp_path_factory):
    g = _gerar()
    folder = tmp_path_factory.mktemp("projetos_1_4")
    simples, edicao = g.open_copies(folder, ffmpeg_ok)
    ref = json.loads((DATA / "referencia.json").read_text(encoding="utf-8"))
    now = json.loads(json.dumps(g.references(simples, edicao, str(folder / "midia")), ensure_ascii=False))
    return ref, now, simples, edicao


def _same_values(old: dict, new: dict) -> None:
    """Os valores da 1.4 voltam iguais; ajuste novo (de uma versão depois da 1.4) só pode vir no padrão."""
    for k, v in old.items():
        assert new.get(k) == v, k
    for k in set(new) - set(old):
        assert new[k] == params.PARAMS[k].default, k


@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["simples", "edicao"])
def test_values_and_state_are_the_same(opened, name):
    ref, now, *_ = opened
    _same_values(ref[name]["valores"], now[name]["valores"])
    assert now[name]["estado"] == ref[name]["estado"]


@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["simples", "edicao"])
def test_look_plans_are_the_same(opened, name):
    ref, now, *_ = opened
    assert now[name]["look"] == ref[name]["look"]


@pytest.mark.ffmpeg
def test_edit_layers_and_uniforms_are_the_same(opened):
    ref, now, *_ = opened
    a, b = ref["edicao"]["montagem"], now["edicao"]["montagem"]
    assert (b["canvas"], b["duration"], b["legal"], b["trivial"]) == (a["canvas"], a["duration"], a["legal"],
                                                                      a["trivial"])
    assert len(b["frames"]) == len(a["frames"])
    for t, (fa, fb) in enumerate(zip(a["frames"], b["frames"])):
        assert len(fb) == len(fa), f"quadro {t}: camadas"
        for la, lb in zip(fa, fb):
            ua, ub = a["uniforms"][la["uniforms"]], b["uniforms"][lb["uniforms"]]
            na, nb = a["uniforms"][la["neutral"]], b["uniforms"][lb["neutral"]]
            assert ub == ua, f"quadro {t}, clipe {la['clip']}: uniforms"
            assert nb == na, f"quadro {t}, clipe {la['clip']}: uniforms da comparação"
            strip = lambda d: {k: v for k, v in d.items() if k not in ("uniforms", "neutral")}  # noqa: E731
            assert strip(lb) == strip(la), f"quadro {t}, clipe {la['clip']}"


@pytest.mark.ffmpeg
def test_edit_audio_graph_is_the_same(opened):
    ref, now, *_ = opened
    for key in ("audio", "audio_trecho"):
        assert now["edicao"]["montagem"][key] == ref["edicao"]["montagem"][key], key


@pytest.mark.ffmpeg
def test_edit_json_saved_again_is_the_same(opened):
    ref, now, *_ = opened
    assert now["edicao"]["json"] == ref["edicao"]["json"]


@pytest.mark.ffmpeg
def test_saving_again_keeps_the_old_format(opened, tmp_path):
    """Um projeto da 1.4 sem nada da 1.5 continua sendo gravado no formato que a 1.4 lê."""
    from pelicula import project
    _ref, _now, simples, edicao = opened
    for p, fmt in ((simples, 1), (edicao, 2)):
        project.save(p, str(tmp_path / "de_novo.plc"))
        data = json.loads((tmp_path / "de_novo.plc").read_text(encoding="utf-8"))
        assert data["formato"] == fmt
