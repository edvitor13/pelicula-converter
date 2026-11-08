"""Look de película próprio de cada sequência (1.8, #67; ARQUITETURA §42): o modelo, o formato do .plc, o desfazer da
montagem, `Project.look_for` e o terminal. Sem Qt nem GPU (a imagem de ponta a ponta está em `tests/test_aninhada.py`, a
janela em `look_sequencia_ui_cases.py`)."""

from __future__ import annotations

import json

import pytest

from pelicula import audiomix, cli, i18n, params, presets, project, timeline as tl

OTHER = "lab_technicolor3"


@pytest.fixture(autouse=True)
def portuguese(monkeypatch):
    """O terminal escolhe o idioma ao rodar: fica o português, e nada vaza para os outros testes."""
    monkeypatch.setenv("PELICULA_LANG", "pt_BR")
    i18n.set_language("pt_BR")
    yield
    i18n.set_language("pt_BR")


def _src(path="C:/v/a.mp4") -> tl.Source:
    return tl.Source(path, 320, 180, 0.0, "24/1", 48, 2.0, has_video=True, has_audio=True)


def _pair() -> tuple[tl.Sequence, tl.Sequence]:
    a = tl.Sequence.for_source(_src())
    b = a.ensure_set().create(320, 180, "24/1", "Curta")
    b.insert_media(_src("C:/v/b.mp4"), 0)
    return a, b


def _own(pid=OTHER) -> tl.SeqLook:
    return tl.SeqLook(presets.builtin_values(pid), pid, {"exposicao": [[0, 0.0], [10, 0.5]]})


# ------------------------------------------------------------------ modelo e JSON
def test_a_sequence_follows_the_project_until_it_gets_its_own_look():
    a, b = _pair()
    assert a.look is None and b.look is None
    d = a.to_json()
    assert "look" not in d and all("look" not in s for s in d["sequencias"])
    assert "look_proprio" not in a.features() and a.block_format() == tl.FORMAT_17
    b.look = _own()
    d = a.to_json()
    blk = d["sequencias"][0]
    assert blk["look"]["preset"] == OTHER and blk["look"]["chaves"] == {"exposicao": [[0, 0.0], [10, 0.5]]}
    assert "look" not in d and "look_proprio" in a.features() and d["formato"] == tl.FORMAT == 5
    back = tl.Sequence.from_json(json.loads(json.dumps(d)))
    got = back.family()[1].look
    assert back.family()[0].look is None and got == b.look
    assert got.values == params.sanitize(presets.builtin_values(OTHER))


def test_the_look_goes_with_copy_and_duplicate_and_is_sanitized():
    a, b = _pair()
    b.look = _own()
    assert b.copy().look == b.look and b.copy().look is not b.look
    dup = b.siblings.duplicate(b)
    assert dup.look == b.look and dup.look is not b.look
    raw = tl.SeqLook.from_json({"preset": 3, "valores": {"exposicao": 99.0, "nao_existe": 1}, "chaves": "x"})
    assert raw.preset_id == "3" and raw.keys == {} and "nao_existe" not in raw.values
    assert raw.values["exposicao"] == params.sanitize({"exposicao": 99.0})["exposicao"]
    assert tl.SeqLook.from_json(None) is None and tl.SeqLook.from_json([1]) is None
    assert "chaves" not in tl.SeqLook(params.defaults()).to_json()


def test_a_lone_sequence_keeps_its_own_look_without_an_id():
    seq = tl.Sequence.for_source(_src())
    seq.look = _own()
    d = seq.to_json()
    assert "id" not in d and d["look"]["preset"] == OTHER and d["formato"] == tl.FORMAT
    assert tl.Sequence.from_json(d).look == seq.look


# ------------------------------------------------------------------ formato do projeto
def test_the_project_goes_to_format_6_only_with_an_own_look():
    a, b = _pair()
    p = project.Project(media_path="C:/v/a.mp4", sequence=a.to_json(), mode="edicao")
    assert p.to_json()["formato"] == project.FORMAT_17 == 5     # sem look próprio: o projeto da 1.7, igual
    b.look = _own()
    p.sequence = a.to_json()
    data = p.to_json()
    assert data["formato"] == project.FORMAT == 6 and "look_proprio" in data["recursos"]
    back = project.from_json(json.loads(json.dumps(data)))
    assert tl.Sequence.from_json(back.sequence).family()[1].look == b.look


def test_without_own_looks_the_project_json_is_the_one_of_1_7():
    a, b = _pair()
    before = json.dumps(project.Project(media_path="C:/v/a.mp4", sequence=a.to_json()).to_json(), sort_keys=True)
    b.look = _own()
    b.look = None
    after = json.dumps(project.Project(media_path="C:/v/a.mp4", sequence=a.to_json()).to_json(), sort_keys=True)
    assert before == after


def test_1_7_refuses_a_project_with_an_own_look(tmp_path, monkeypatch):
    a, b = _pair()
    b.look = _own()
    path = tmp_path / "novo.plc"
    project.save(project.Project(media_path="C:/v/a.mp4", sequence=a.to_json()), str(path))
    monkeypatch.setattr(project, "FORMAT", 5)
    monkeypatch.setattr(tl, "FORMAT", 4)
    with pytest.raises(project.ProjectError):
        project.load(str(path))


def test_a_1_7_project_opens_with_every_sequence_following_the_project(tmp_path):
    a, _b = _pair()
    data = project.Project(media_path="C:/v/a.mp4", sequence=a.to_json()).to_json()
    data["formato"], data["edicao"]["formato"] = 5, 4
    for blk in data["edicao"]["sequencias"]:
        blk["formato"] = 4
    p = project.from_json(data)
    assert all(s.look is None for s in tl.Sequence.from_json(p.sequence).family())
    assert project.migrate({"formato": 5})["formato"] == 6 and tl.migrate({"formato": 4})["formato"] == 5


def test_look_for_gives_the_own_look_or_the_projects():
    a, b = _pair()
    b.look = _own()
    p = project.Project(values=presets.builtin_values("vision3_500t"), preset_id="vision3_500t",
                        look_keys={"exposicao": [[0, 0.1], [5, 0.3]]})
    values, pid, keys = p.look_for(a)
    assert pid == "vision3_500t" and keys == p.look_keys and values == p.values and values is not p.values
    values, pid, keys = p.look_for(b)
    assert pid == OTHER and keys == b.look.keys and values == b.look.values and values is not b.look.values
    assert p.look_for(None)[1] == "vision3_500t"


# ------------------------------------------------------------------ desfazer da montagem
def test_the_look_is_not_a_step_of_the_timeline_undo():
    a, b = _pair()
    h = tl.History(a)
    b.look = _own()
    assert not h.push(a) and not h.can_undo()               # o look sozinho não é passo
    a.insert_media(_src("C:/v/c.mp4"), 48)
    assert h.push(a)
    b.look = _own("vision3_250d")                             # mexido depois do último passo
    back = h.undo(a)
    assert back.family()[1].look.preset_id == "vision3_250d"  # o look de agora fica
    assert len(back.clips) < len(a.clips)
    fwd = h.redo(back)
    assert fwd.family()[1].look.preset_id == "vision3_250d" and len(fwd.clips) == len(a.clips)


def test_undoing_a_deleted_sequence_brings_back_its_look():
    a, b = _pair()
    b.look = _own()
    h = tl.History(a)
    b.look = _own("vision3_250d")
    h.push(a)  # o modelo grava (sem passo) antes de cada operação: o look de agora fica no estado
    a.siblings.remove(b)
    assert h.push(a)
    back = h.undo(a)
    inner = next(s for s in back.family() if s.name == "Curta")
    assert inner.look.preset_id == "vision3_250d"


def test_turning_a_look_off_survives_an_undo():
    a, b = _pair()
    b.look = _own()
    h = tl.History(a)
    a.insert_media(_src("C:/v/c.mp4"), 48)
    h.push(a)
    b.look = None
    back = h.undo(a)
    assert back.family()[1].look is None


def test_the_inner_look_does_not_touch_the_outer_montage_or_its_sound():
    a, b = _pair()
    a.insert_media(tl.Source.for_sequence(b), 48)
    layers = [a.layers_at(t) for t in (0, 50, 60)]
    key = audiomix.mix_key(a)
    b.look = _own()
    assert [a.layers_at(t) for t in (0, 50, 60)] == layers and audiomix.mix_key(a) == key
    lone = tl.Sequence.for_source(_src())
    triv = lone.is_trivial()
    lone.look = _own()
    assert lone.is_trivial() == triv  # o modo Película continua lendo o arquivo direto


# ------------------------------------------------------------------ terminal
def _saved(tmp_path, own=True) -> tuple[str, tl.Sequence, tl.Sequence]:
    a, b = _pair()
    if own:
        b.look = _own()
    p = project.Project(media_path="C:/v/a.mp4", values=presets.builtin_values("vision3_500t"),
                        preset_id="vision3_500t", sequence=a.to_json(), look_keys={"exposicao": [[0, 0.1], [5, 0.3]]})
    path = str(tmp_path / "proj.plc")
    project.save(p, path)
    return path, a, b


def test_cli_picks_the_look_of_the_chosen_sequence(tmp_path):
    path, _a, b = _saved(tmp_path)
    proj = project.load(path)
    values, pid, keys = cli.project_look(proj)                # a aberta ao salvar: segue o projeto
    assert pid == "vision3_500t" and keys == {"exposicao": [[0, 0.1], [5, 0.3]]}
    values, pid, keys = cli.project_look(proj, "Curta")
    assert pid == OTHER and keys == b.look.keys and values == b.look.values
    assert cli.look_keys(proj, None, [], "Curta") == b.look.keys
    assert cli.look_keys(proj, None, ["exposicao=0.2"], "Curta") == {}
    assert cli.look_keys(proj, OTHER, [], "Curta") == {}
    assert cli.look_keys(proj, None, []) == {"exposicao": [[0, 0.1], [5, 0.3]]}
    with pytest.raises(cli.CliError):
        cli.project_look(proj, "Não existe")


def test_cli_info_shows_which_sequences_have_their_own_look(tmp_path, capsys):
    path, _a, _b = _saved(tmp_path)
    assert cli.main(["info", path, "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["sequencias"]
    assert [(r["look"], r["preset"]) for r in rows] == [("projeto", "vision3_500t"), ("proprio", OTHER)]
    assert cli.main(["info", path]) == 0
    text = capsys.readouterr().out
    assert f"look próprio ({OTHER})" in text and text.count("look próprio") == 1


def test_cli_lut_of_a_sequence_needs_a_project(tmp_path, capsys):
    path, _a, _b = _saved(tmp_path, own=False)
    with pytest.raises(cli.CliError):
        cli.cmd_lut(cli.build_parser().parse_args(["lut", "--sequencia", "Curta"]))
    args = cli.build_parser().parse_args(["lut", "--projeto", path, "--sequencia", "Curta", "-o", "x.cube"])
    assert args.sequencia == "Curta"
