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


# Uniforms do shader CLIP que vieram depois da 1.4, com o valor que deixa tudo como era (sem transparência).
NEW_UNIFORMS = {"u_tex_alpha": 0}


def _without_new(u: dict) -> dict:
    for k, neutral in NEW_UNIFORMS.items():
        assert u.get(k, neutral) == neutral, k
    return {k: v for k, v in u.items() if k not in NEW_UNIFORMS}


@pytest.mark.ffmpeg
def test_edit_layers_and_uniforms_are_the_same(opened):
    ref, now, *_ = opened
    a, b = ref["edicao"]["montagem"], now["edicao"]["montagem"]
    b = {**b, "uniforms": [_without_new(u) for u in b["uniforms"]]}
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


# ------------------------------------------------------------------ formato 3 e os passos da migração
def _alpha_source(path="C:/v/recorte_cutout.mov", alpha=True):
    from pelicula import timeline as tl
    return tl.Source(path, 320, 180, 24.0, "24/1", 48, 2.0, pix_fmt="yuva444p10le", bit_depth=10, codec="prores",
                     has_alpha=alpha)


def _plain_source(path="C:/v/fundo.mp4"):
    from pelicula import timeline as tl
    return tl.Source(path, 320, 180, 24.0, "24/1", 48, 2.0, pix_fmt="yuv420p", has_audio=True)


def test_step_1_to_2_normalizes_a_simple_project():
    from pelicula import project
    old = {"app": "PeliculaConverter", "formato": 1, "valores": {}, "edicao": "lixo"}
    new = project._v1_to_v2(old)
    assert new["formato"] == 2 and new["modo"] == "pelicula" and "edicao" not in new
    assert old == {"app": "PeliculaConverter", "formato": 1, "valores": {}, "edicao": "lixo"}  # puro
    assert project._v1_to_v2({"formato": 1, "modo": "edicao"})["modo"] == "edicao"


def test_step_2_to_3_migrates_the_sequence_block():
    from pelicula import project, timeline as tl
    seq = tl.Sequence(320, 180, "24/1")
    seq.insert_media(_plain_source())
    seq.insert_media(_alpha_source(), at=0, vtrack=1, with_audio=False)
    block = seq.to_json()
    for s in block["fontes"]:  # como a 1.4 gravava: sem tipo e sem alfa
        s.pop("tipo", None)
        s.pop("alfa", None)
    block["formato"] = 1
    old = {"app": "PeliculaConverter", "formato": 2, "edicao": block}
    new = project._v2_to_v3(old)
    assert new["formato"] == 3 and new["recursos"] == [] and new["edicao"]["formato"] == tl.FORMAT
    by = {s["caminho"]: s for s in new["edicao"]["fontes"]}
    assert by["C:/v/fundo.mp4"]["tipo"] == "arquivo" and by["C:/v/fundo.mp4"]["alfa"] is False
    assert by["C:/v/recorte_cutout.mov"]["alfa"] is True  # a 1.4 não guardava: sai do pix_fmt
    assert "alfa" not in old["edicao"]["fontes"][0]  # puro
    again = tl.Sequence.from_json(new["edicao"])
    assert again.sources["C:/v/recorte_cutout.mov"].has_alpha and not again.sources["C:/v/fundo.mp4"].has_alpha


def test_migrate_runs_every_step_and_refuses_newer_formats():
    from pelicula import project, timeline as tl
    assert project.migrate({"formato": 1})["formato"] == project.FORMAT
    assert project.migrate({})["formato"] == project.FORMAT  # sem "formato" = 1
    with pytest.raises(project.ProjectError):
        project.migrate({"formato": project.FORMAT + 1})
    assert tl.migrate({"formato": 1})["formato"] == tl.FORMAT
    with pytest.raises(tl.FormatError):
        tl.migrate({"formato": tl.FORMAT + 1})
    assert set(project.MIGRATIONS) == set(range(1, project.FORMAT))
    assert set(tl.MIGRATIONS) == set(range(1, tl.FORMAT))


def test_writer_uses_the_smallest_format(tmp_path):
    from pelicula import project, timeline as tl
    p = project.Project(media_path="C:/v/fundo.mp4")
    assert p.to_json()["formato"] == 1 and "recursos" not in p.to_json()
    seq = tl.Sequence.for_source(_plain_source())
    seq.split(10)
    p.sequence = seq.to_json()
    data = p.to_json()
    assert data["formato"] == 2 and data["edicao"]["formato"] == tl.FORMAT_BASE and "recursos" not in data
    assert all("alfa" not in s and "tipo" not in s for s in data["edicao"]["fontes"])
    seq.insert_media(_alpha_source(), at=0, vtrack=1, with_audio=False)
    p.sequence = seq.to_json()
    data = p.to_json()
    assert data["formato"] == 3 and data["recursos"] == ["alfa"] and data["edicao"]["formato"] == tl.FORMAT
    project.save(p, str(tmp_path / "alfa.plc"))
    q = project.load(str(tmp_path / "alfa.plc"))
    assert tl.Sequence.from_json(q.sequence).sources["C:/v/recorte_cutout.mov"].has_alpha


def test_an_older_reader_refuses_a_format_3_project(tmp_path, monkeypatch):
    """O que a 1.4 faz (FORMAT = 2) com um projeto que usa um recurso da 1.5: recusa com aviso."""
    from pelicula import project, timeline as tl
    seq = tl.Sequence.for_source(_alpha_source())
    p = project.Project(media_path="C:/v/recorte_cutout.mov", sequence=seq.to_json(), mode="edicao")
    project.save(p, str(tmp_path / "novo.plc"))
    block = seq.to_json()
    monkeypatch.setattr(project, "FORMAT", 2)
    with pytest.raises(project.ProjectError):
        project.load(str(tmp_path / "novo.plc"))
    monkeypatch.setattr(tl, "FORMAT", 1)
    with pytest.raises(tl.FormatError):
        tl.Sequence.from_json(block)


def test_a_newer_sequence_block_is_refused_by_the_project(tmp_path):
    from pelicula import project
    data = project.Project(media_path="C:/v/a.mp4").to_json()
    data["formato"] = 3
    data["edicao"] = {"formato": 99, "clipes": []}
    (tmp_path / "x.plc").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(project.ProjectError):
        project.load(str(tmp_path / "x.plc"))


def test_feature_registry_is_extended_with_one_line(monkeypatch):
    """Uma frente nova registra o recurso dela numa linha; o projeto passa a pedir o formato 3."""
    from pelicula import project, timeline as tl
    seq = tl.Sequence.for_source(_plain_source())
    p = project.Project(media_path="C:/v/fundo.mp4", sequence=seq.to_json())
    assert p.features() == set() and p.to_json()["formato"] == 2
    monkeypatch.setitem(tl.FEATURES, "teste_montagem", lambda s: len(s.clips) > 1)
    assert seq.features() == {"teste_montagem"} and seq.to_json()["formato"] == tl.FORMAT
    assert p.to_json()["formato"] == 3 and p.to_json()["recursos"] == ["teste_montagem"]
    monkeypatch.setitem(project.FEATURES_V3, "teste_projeto", lambda proj: proj.preset_id == "x")
    p.preset_id = "x"
    assert p.to_json()["recursos"] == ["teste_montagem", "teste_projeto"]


def test_alpha_off_on_an_alpha_pixel_format_round_trips():
    """Fonte com formato de pixel com alfa e transparência desligada: o JSON diz "alfa": false (a migração do
    formato 1 deduziria pelo pix_fmt)."""
    from pelicula import timeline as tl
    seq = tl.Sequence.for_source(_alpha_source(alpha=False))
    d = seq.to_json()
    assert d["formato"] == tl.FORMAT_BASE and d["fontes"][0]["alfa"] is False
    assert not tl.Sequence.from_json(d).sources["C:/v/recorte_cutout.mov"].has_alpha
    assert seq.copy().to_json() == d


def test_recovery_copy_of_a_format_3_project(tmp_path):
    from pelicula import project, recovery, timeline as tl
    seq = tl.Sequence.for_source(_alpha_source())
    p = project.Project(media_path="C:/v/recorte_cutout.mov", sequence=seq.to_json(), mode="edicao")
    payload = recovery.make_payload(p.to_json(), name="x")
    assert payload["formato"] == recovery.FORMAT and payload["projeto"]["formato"] == 3
    path = tmp_path / "copia.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    q, _orig, _ui = recovery.project_from_copy(recovery.read_copy(path))
    assert tl.Sequence.from_json(q.sequence).sources["C:/v/recorte_cutout.mov"].has_alpha
