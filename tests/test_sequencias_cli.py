"""Várias sequências no terminal (#57): `--sequencia` em `exportar` e `quadro` e a lista de `info` num projeto."""

from __future__ import annotations

import json

import pytest

from pelicula import cli, i18n, media, params, project, timeline as tl


@pytest.fixture(autouse=True)
def portuguese(monkeypatch):
    monkeypatch.setenv("PELICULA_LANG", "pt_BR")
    i18n.set_language("pt_BR")
    yield
    i18n.set_language("pt_BR")


@pytest.fixture
def gl_session(gl_engine):
    """Como em test_cli.py: o terminal cria e libera o próprio contexto OpenGL na thread atual."""
    yield gl_engine
    gl_engine.ctx.__enter__()


def _two_sequence_project(tmp_path, video: str, active_second: bool = False):
    """Projeto com duas sequências: a primeira com o vídeo inteiro (24 quadros, 320×180 a 24/s) e a "Curta" com o vídeo
    em 160×90 a 30/s. `active_second`: a aberta ao salvar é a segunda."""
    src = media.probe_source(video)
    a = tl.Sequence.for_source(src)
    b = a.ensure_set().create(160, 90, "30/1", name="Curta")
    b.insert_media(src, 0)
    top = b if active_second else a
    p = project.Project(media_path=video, values=params.defaults(), preset_id="", sequence=top.to_json(),
                        mode="edicao")
    path = tmp_path / "duas.plc"
    project.save(p, str(path))
    return path, a, b


# ------------------------------------------------------------------ sem GPU nem ffmpeg
def _fake_project(tmp_path, active_second=False):
    media_path = tmp_path / "v.mp4"
    media_path.write_bytes(b"x")
    src = tl.Source(str(media_path), 320, 180, 24.0, "24/1", 48, 2.0)
    a = tl.Sequence.for_source(src)
    a.split(10)
    b = a.ensure_set().create(160, 90, "30/1", name="Curta")
    b.insert_media(src, 0)
    top = b if active_second else a
    return project.Project(media_path=str(media_path), sequence=top.to_json(), mode="edicao"), a, b


def test_the_default_sequence_is_the_one_open_when_saved(tmp_path):
    for second in (False, True):
        p, a, b = _fake_project(tmp_path, active_second=second)
        seq = cli.project_sequence(p)
        assert seq.id == (b.id if second else a.id) and len(seq.family()) == 2


def test_the_sequence_is_chosen_by_name_or_id_without_caring_for_case(tmp_path):
    p, a, b = _fake_project(tmp_path)
    assert cli.project_sequence(p, "Curta").id == b.id
    assert cli.project_sequence(p, "curta").id == b.id
    assert cli.project_sequence(p, b.id).id == b.id
    assert cli.project_sequence(p, "Sequência 1").id == a.id
    assert cli.project_sequence(p, a.id).id == a.id


def test_a_wrong_name_is_an_error_that_lists_the_valid_ones(tmp_path):
    p, a, b = _fake_project(tmp_path)
    with pytest.raises(cli.CliError) as exc:
        cli.project_sequence(p, "Nao existe")
    msg = str(exc.value)
    assert "Nao existe" in msg and "Sequência 1" in msg and "Curta" in msg and b.id in msg and a.id in msg


def test_choosing_in_a_project_with_one_sequence_only_accepts_its_name(tmp_path):
    media_path = tmp_path / "v.mp4"
    media_path.write_bytes(b"x")
    src = tl.Source(str(media_path), 320, 180, 24.0, "24/1", 48, 2.0)
    seq = tl.Sequence.for_source(src)
    seq.split(10)
    p = project.Project(media_path=str(media_path), sequence=seq.to_json(), mode="edicao")
    assert cli.project_sequence(p, "Sequência 1") is not None
    with pytest.raises(cli.CliError, match="Sequência 1"):
        cli.project_sequence(p, "Curta")
    with pytest.raises(cli.CliError, match="--sequencia"):
        cli.project_sequence(project.Project(media_path=str(media_path)), "Curta")


def test_an_empty_sequence_is_refused_with_the_list_of_the_others(tmp_path):
    p, a, b = _fake_project(tmp_path)
    a.siblings.create(320, 180, "24/1", name="Vazia")
    p.sequence = a.to_json()
    with pytest.raises(cli.CliError, match="Vazia") as exc:
        cli.project_sequence(p, "Vazia")
    assert "não tem clipes" in str(exc.value) and "Curta" in str(exc.value)


def test_sequencia_only_makes_sense_for_a_project(tmp_path):
    media_path = tmp_path / "v.mp4"
    media_path.write_bytes(b"x")
    with pytest.raises(cli.CliError, match=r"\.plc"):
        cli._source_and_values(str(media_path), None, [], "Curta")


def test_info_of_a_project_lists_the_sequences(tmp_path, capsys):
    p, a, b = _fake_project(tmp_path, active_second=True)
    path = tmp_path / "p.plc"
    project.save(p, str(path))
    assert cli.main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Sequências (2)" in out and "Sequência 1" in out and "Curta" in out and "160×90" in out
    assert "30 quadros/s" in out and "24 quadros/s" in out and "estava aberta ao salvar" in out
    assert [ln for ln in out.splitlines() if "Curta" in ln][0].rstrip().endswith("*")      # a aberta ao salvar vem marcada
    assert cli.main(["info", str(path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["nome"] for s in data["sequencias"]] == ["Sequência 1", "Curta"]
    assert [s["aberta"] for s in data["sequencias"]] == [False, True] and data["formato"] == 5
    assert data["sequencias"][1]["largura"] == 160 and data["sequencias"][0]["clipes"] == 2


def test_info_of_a_project_with_one_sequence_does_not_mark_anything(tmp_path, capsys):
    media_path = tmp_path / "v.mp4"
    media_path.write_bytes(b"x")
    src = tl.Source(str(media_path), 320, 180, 24.0, "24/1", 48, 2.0)
    seq = tl.Sequence.for_source(src)
    seq.split(10)
    path = tmp_path / "um.plc"
    project.save(project.Project(media_path=str(media_path), sequence=seq.to_json(), mode="edicao"), str(path))
    assert cli.main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Sequências (1)" in out and "*" not in out and "id " not in out


def test_the_options_exist_in_the_parser():
    with pytest.raises(SystemExit):
        cli.main(["exportar", "--help"])
    with pytest.raises(SystemExit):
        cli.main(["quadro", "--help"])


# ------------------------------------------------------------------ exportação e quadro de verdade
@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_chooses_the_sequence_and_defaults_to_the_open_one(gl_session, ffmpeg_ok, sample_video, tmp_path):
    plc, a, b = _two_sequence_project(tmp_path, sample_video)
    out_a, out_b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    assert cli.main(["exportar", str(plc), "-o", str(out_a), "--qualidade", "mp4", "--velocidade", "ultrafast",
                     "-q"]) == 0
    assert cli.main(["exportar", str(plc), "-o", str(out_b), "--qualidade", "mp4", "--velocidade", "ultrafast",
                     "--sequencia", "Curta", "-q"]) == 0
    ia, ib = media.probe(str(out_a)), media.probe(str(out_b))
    assert (ia.width, ia.height, ia.frames) == (320, 180, 24) and abs(ia.fps - 24) < 0.01
    assert (ib.width, ib.height, ib.frames) == (160, 90, 30) and abs(ib.fps - 30) < 0.01
    assert ia.has_audio and ib.has_audio


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_by_id_and_with_the_second_sequence_open(gl_session, ffmpeg_ok, sample_video, tmp_path):
    plc, a, b = _two_sequence_project(tmp_path, sample_video, active_second=True)
    out = tmp_path / "padrao.mp4"
    assert cli.main(["exportar", str(plc), "-o", str(out), "--qualidade", "mp4", "--velocidade", "ultrafast",
                     "-q"]) == 0
    assert media.probe(str(out)).width == 160                    # a padrão é a que estava aberta ao salvar
    out2 = tmp_path / "por_id.mp4"
    assert cli.main(["exportar", str(plc), "-o", str(out2), "--qualidade", "mp4", "--velocidade", "ultrafast",
                     "--sequencia", a.id, "-q"]) == 0
    assert media.probe(str(out2)).width == 320


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_frame_of_the_chosen_sequence(gl_session, ffmpeg_ok, sample_video, tmp_path):
    plc, a, b = _two_sequence_project(tmp_path, sample_video)
    big, small = tmp_path / "grande.png", tmp_path / "pequeno.png"
    assert cli.main(["quadro", str(plc), "-o", str(big), "--tempo", "#5"]) == 0
    assert cli.main(["quadro", str(plc), "-o", str(small), "--tempo", "#5", "--sequencia", "Curta"]) == 0
    import numpy as np
    from PySide6.QtGui import QImage
    qa, qb = QImage(str(big)), QImage(str(small))
    assert (qa.width(), qa.height()) == (320, 180) and (qb.width(), qb.height()) == (160, 90)
    assert np.frombuffer(qb.constBits(), dtype=np.uint8).any()


@pytest.mark.ffmpeg
def test_a_wrong_sequence_name_in_the_terminal_fails_and_shows_the_valid_ones(ffmpeg_ok, sample_video, tmp_path, capsys):
    plc, a, b = _two_sequence_project(tmp_path, sample_video)
    for cmd in ("exportar", "quadro"):
        assert cli.main([cmd, str(plc), "-o", str(tmp_path / "x.png" if cmd == "quadro" else tmp_path / "x.mp4"),
                         "--sequencia", "Nao existe"]) == 1
        err = capsys.readouterr().err
        assert "Nao existe" in err and "Curta" in err and "Sequência 1" in err
    assert not (tmp_path / "x.mp4").exists() and not (tmp_path / "x.png").exists()


@pytest.mark.ffmpeg
def test_trecho_with_another_sequence_is_refused(ffmpeg_ok, sample_video, tmp_path, capsys):
    plc, a, b = _two_sequence_project(tmp_path, sample_video)
    assert cli.main(["exportar", str(plc), "-o", str(tmp_path / "t.mp4"), "--sequencia", "Curta", "--trecho"]) == 1
    assert "--trecho" in capsys.readouterr().err
