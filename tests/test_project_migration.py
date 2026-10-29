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
import math
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
    defaults = params.defaults()  # cores em lista, como no JSON (1.6: as primeiras cores novas)
    for k in set(new) - set(old):
        assert new[k] == defaults[k], k


@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["simples", "edicao"])
def test_values_and_state_are_the_same(opened, name):
    ref, now, *_ = opened
    _same_values(ref[name]["valores"], now[name]["valores"])
    assert now[name]["estado"] == ref[name]["estado"]


def _same_numbers(old, new, where: str = "") -> None:
    """Igual, com números de ponto flutuante até o arredondamento: as matrizes de gamut passam por
    `np.linalg.inv`, cujo resultado muda na última casa conforme o processador (o OpenBLAS escolhe o código
    pela CPU); a referência foi gravada numa máquina e o CI roda em outras."""
    if isinstance(old, dict):
        assert isinstance(new, dict) and new.keys() == old.keys(), where
        for k in old:
            _same_numbers(old[k], new[k], f"{where}/{k}")
    elif isinstance(old, list):
        assert isinstance(new, list) and len(new) == len(old), where
        for i, (a, b) in enumerate(zip(old, new)):
            _same_numbers(a, b, f"{where}[{i}]")
    elif isinstance(old, float) or isinstance(new, float):
        assert math.isclose(new, old, rel_tol=1e-12, abs_tol=1e-12), f"{where}: {new} != {old}"
    else:
        assert new == old, where


@pytest.mark.ffmpeg
@pytest.mark.parametrize("name", ["simples", "edicao"])
def test_look_plans_are_the_same(opened, name):
    ref, now, *_ = opened
    _same_numbers(ref[name]["look"], now[name]["look"], name)


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
    assert data["formato"] == 3 and data["recursos"] == ["alfa"] and data["edicao"]["formato"] == tl.FORMAT_15
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
    assert seq.features() == {"teste_montagem"} and seq.to_json()["formato"] == tl.FORMAT_15
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


# ------------------------------------------------------------------ formato 4 (1.6)
def _known_without(schema: str, key: str, choice: str | None = None) -> dict:
    """O retrato da 1.5 como se `key` (ou só a opção `choice` dele) tivesse vindo na 1.6."""
    known = {k: dict(v) for k, v in params.known_1_5().items()}
    if choice is None:
        del known[schema][key]
    else:
        known[schema][key] = [c for c in known[schema][key] if c != choice]
    return known


def test_the_1_5_snapshot_keeps_every_key_and_choice():
    """O retrato da 1.5 nunca perde chave nem opção: renomear ou tirar quebra projetos (regra dos ajustes)."""
    from pelicula import editparams
    raw = json.loads(params.KNOWN_1_5_FILE.read_text(encoding="utf-8"))
    assert raw["versao"] == "1.5.0"
    for name, schema in (("look", params.FILM), ("video", editparams.VIDEO), ("audio", editparams.AUDIO)):
        for k, choices in params.known_1_5()[name].items():
            p = schema.params.get(k)
            assert p is not None, f"{name}/{k}"
            if choices is not None:
                assert p.kind == "choice" and set(choices) <= {c[0] for c in p.choices}, f"{name}/{k}"
        assert not params.beyond_1_5(schema, params.known_1_5()[name], schema.defaults()), name


def test_a_new_look_setting_or_choice_writes_format_4(monkeypatch):
    from pelicula import project
    p = project.Project(media_path="C:/v/fundo.mp4")
    assert p.to_json()["formato"] == project.FORMAT_SIMPLE
    known = _known_without("look", "exposicao")
    monkeypatch.setattr(params, "known_1_5", lambda: known)
    assert p.to_json()["formato"] == project.FORMAT_SIMPLE  # ajuste novo no padrão: nada muda
    p.values = {**p.values, "exposicao": 0.5}
    data = p.to_json()
    assert data["formato"] == project.FORMAT == 4 and data["recursos"] == ["ajustes_1_6"]
    p.values = params.defaults()
    p.look_keys = {"exposicao": [[0, 0.0], [10, 0.5]]}
    assert p.to_json()["formato"] == 4  # chaves num ajuste novo
    p.look_keys = {}
    first = params.PARAMS["entrada"].choices[0][0]
    other = params.PARAMS["entrada"].choices[1][0]
    monkeypatch.undo()
    known = _known_without("look", "entrada", other)
    monkeypatch.setattr(params, "known_1_5", lambda: known)
    p.values = {**params.defaults(), "entrada": first}
    assert p.to_json()["formato"] == project.FORMAT_SIMPLE
    p.values = {**params.defaults(), "entrada": other}
    assert p.to_json()["formato"] == 4  # opção nova numa escolha antiga


def test_a_new_clip_setting_writes_block_3_and_project_4(monkeypatch):
    from pelicula import project, timeline as tl
    seq = tl.Sequence.for_source(_plain_source())
    p = project.Project(media_path="C:/v/fundo.mp4", sequence=seq.to_json())
    assert p.to_json()["formato"] == project.FORMAT_EDIT
    known = _known_without("video", "exposicao")
    monkeypatch.setattr(params, "known_1_5", lambda: known)
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.set_values(v.id, {**v.values, "exposicao": 1.0})
    block = seq.to_json()
    assert seq.features() == {"ajustes_clipe_1_6"} and block["formato"] == tl.FORMAT == 3
    p.sequence = block
    assert p.to_json()["formato"] == 4 and p.to_json()["recursos"] == ["ajustes_clipe_1_6"]
    seq.insert_media(_alpha_source(), at=0, vtrack=1, with_audio=False)  # 1.5 + 1.6: continua 4
    p.sequence = seq.to_json()
    assert p.to_json()["formato"] == 4 and p.to_json()["recursos"] == ["ajustes_clipe_1_6", "alfa"]


def test_step_3_to_4_is_pure_and_keeps_the_fields():
    from pelicula import project, timeline as tl
    seq = tl.Sequence.for_source(_alpha_source())
    old = {"app": "PeliculaConverter", "formato": 3, "valores": {"exposicao": 0.2}, "edicao": seq.to_json(),
           "recursos": ["alfa"]}
    assert old["edicao"]["formato"] == tl.FORMAT_15
    new = project._v3_to_v4(old)
    assert new["formato"] == 4 and new["recursos"] == ["alfa"] and new["valores"] == {"exposicao": 0.2}
    assert new["edicao"] == old["edicao"] and old["formato"] == 3  # o bloco migra ao ser lido
    assert tl.Sequence.from_json(new["edicao"]).sources["C:/v/recorte_cutout.mov"].has_alpha
    assert tl._seq_v2_to_v3({"formato": 2, "clipes": []}) == {"formato": 3, "clipes": []}


def test_a_1_5_reader_refuses_a_format_4_project(tmp_path, monkeypatch):
    """O que a 1.5 faz (FORMAT = 3, bloco 2) com um projeto que usa algo da 1.6: recusa com aviso."""
    from pelicula import project, timeline as tl
    known = _known_without("video", "exposicao")
    monkeypatch.setattr(params, "known_1_5", lambda: known)
    seq = tl.Sequence.for_source(_plain_source())
    v = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.set_values(v.id, {**v.values, "exposicao": 1.0})
    p = project.Project(media_path="C:/v/fundo.mp4", sequence=seq.to_json(), mode="edicao")
    project.save(p, str(tmp_path / "novo.plc"))
    block = seq.to_json()
    monkeypatch.setattr(project, "FORMAT", 3)
    with pytest.raises(project.ProjectError):
        project.load(str(tmp_path / "novo.plc"))
    monkeypatch.setattr(tl, "FORMAT", 2)
    with pytest.raises(tl.FormatError):
        tl.Sequence.from_json(block)
