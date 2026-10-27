"""Projetos .plc: salvar, abrir, caminhos relativos e arquivos inválidos."""

import json
import os
import shutil

import pytest

from pelicula import params, presets, project


def make(tmp_path, media_name="video.mp4"):
    media = tmp_path / media_name
    media.write_bytes(b"x")
    vals = presets.builtin_values("super8_kodachrome")
    vals["grao_forca"] = 1.7
    return project.Project(media_path=str(media), values=vals, preset_id="super8_kodachrome", frame=42,
                           in_point=10, out_point=99, compare="side", preview="1080", export_quality="mp4",
                           thumbnail_jpeg=b"\xff\xd8\xff\xd9")


def test_roundtrip(tmp_path):
    p = make(tmp_path)
    project.save(p, str(tmp_path / "proj"))
    path = tmp_path / "proj.plc"
    assert path.is_file()
    q = project.load(str(path))
    assert q.media_path == p.media_path
    assert q.values == params.sanitize(p.values)
    assert (q.preset_id, q.frame, q.in_point, q.out_point) == ("super8_kodachrome", 42, 10, 99)
    assert (q.compare, q.preview, q.export_quality) == ("side", "1080", "mp4")
    assert q.thumbnail_jpeg == b"\xff\xd8\xff\xd9"
    assert q.name == "proj"
    assert q.saved_at > 0


def test_file_is_readable_json(tmp_path):
    p = make(tmp_path)
    project.save(p, str(tmp_path / "a.plc"))
    data = json.loads((tmp_path / "a.plc").read_text(encoding="utf-8"))
    assert data["app"] == "PeliculaConverter"
    assert data["formato"] == project.FORMAT_SIMPLE  # sem sequência: abre nas versões antigas
    assert data["midia"]["relativo"] == "video.mp4"
    assert data["modo"] == "pelicula" and "edicao" not in data


def test_relink_by_relative_path(tmp_path):
    src = tmp_path / "pasta1"
    src.mkdir()
    p = make(src)
    project.save(p, str(src / "proj.plc"))
    moved = tmp_path / "pasta2"
    shutil.move(str(src), str(moved))
    q = project.load(str(moved / "proj.plc"))
    assert os.path.normcase(q.media_path) == os.path.normcase(str(moved / "video.mp4"))


def test_missing_media_kept_as_is(tmp_path):
    p = make(tmp_path)
    project.save(p, str(tmp_path / "proj.plc"))
    os.remove(p.media_path)
    q = project.load(str(tmp_path / "proj.plc"))
    assert q.media_path == p.media_path
    info = project.peek(str(tmp_path / "proj.plc"))
    assert info["media_ok"] is False


def test_null_in_out(tmp_path):
    p = make(tmp_path)
    p.in_point = p.out_point = None
    project.save(p, str(tmp_path / "proj.plc"))
    q = project.load(str(tmp_path / "proj.plc"))
    assert q.in_point is None and q.out_point is None


@pytest.mark.parametrize("content", ["", "{}", "[1, 2]", '{"app": "Outro"}', "não é json"])
def test_invalid_files(tmp_path, content):
    f = tmp_path / "x.plc"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(project.ProjectError):
        project.load(str(f))
    assert project.peek(str(f)) is None


def test_newer_format_rejected(tmp_path):
    p = make(tmp_path)
    project.save(p, str(tmp_path / "proj.plc"))
    data = json.loads((tmp_path / "proj.plc").read_text(encoding="utf-8"))
    data["formato"] = project.FORMAT + 1
    (tmp_path / "proj.plc").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(project.ProjectError):
        project.load(str(tmp_path / "proj.plc"))


def test_bad_values_are_sanitized(tmp_path):
    p = make(tmp_path)
    project.save(p, str(tmp_path / "proj.plc"))
    data = json.loads((tmp_path / "proj.plc").read_text(encoding="utf-8"))
    data["valores"]["exposicao"] = 99
    data["valores"]["bitola"] = "inexistente"
    data["valores"]["chave_desconhecida"] = 1
    (tmp_path / "proj.plc").write_text(json.dumps(data), encoding="utf-8")
    q = project.load(str(tmp_path / "proj.plc"))
    assert q.values["exposicao"] == params.PARAMS["exposicao"].max
    assert q.values["bitola"] == params.PARAMS["bitola"].default
    assert "chave_desconhecida" not in q.values


def test_open_dialog_lists_projects():
    """O botão Abrir mostra vídeos, imagens e .plc juntos; o "localizar o vídeo" continua só com mídia."""
    pytest.importorskip("PySide6")
    from pelicula.ui import main_window
    filters = main_window.open_filter().split(";;")
    assert "*.plc" in filters[0] and "*.mp4" in filters[0] and "*.exr" in filters[0]
    assert any(f.endswith("(*.plc)") for f in filters[1:])
    assert "*.plc" not in main_window.media_filter()


# ------------------------------------------------------------------ modo Edição
def _seq_json(media_path: str) -> dict:
    from pelicula import timeline
    src = timeline.Source(media_path, 320, 180, 24.0, "24/1", 48, 2.0, has_audio=True)
    seq = timeline.Sequence.for_source(src)
    seq.split(20)
    return seq.to_json()


def test_sequence_roundtrip_and_format(tmp_path):
    p = make(tmp_path)
    p.sequence = _seq_json(p.media_path)
    p.mode = "edicao"
    project.save(p, str(tmp_path / "ed.plc"))
    data = json.loads((tmp_path / "ed.plc").read_text(encoding="utf-8"))
    assert data["formato"] == project.FORMAT == 2 and data["modo"] == "edicao"
    assert data["edicao"]["fontes"][0]["relativo"] == "video.mp4"
    q = project.load(str(tmp_path / "ed.plc"))
    assert q.mode == "edicao"
    assert q.sequence["clipes"] == p.sequence["clipes"]


def test_sequence_sources_relinked_when_folder_moves(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    p = make(a)
    p.sequence = _seq_json(p.media_path)
    project.save(p, str(a / "ed.plc"))
    b = tmp_path / "b"
    shutil.move(str(a), str(b))
    q = project.load(str(b / "ed.plc"))
    from pelicula import timeline
    seq = timeline.Sequence.from_json(q.sequence)
    new = str(b / "video.mp4")
    assert set(seq.sources) == {os.path.normpath(new)}
    assert all(c.src == os.path.normpath(new) for c in seq.clips) and len(seq.clips) == 4


def test_old_project_without_sequence(tmp_path):
    p = make(tmp_path)
    project.save(p, str(tmp_path / "v.plc"))
    data = json.loads((tmp_path / "v.plc").read_text(encoding="utf-8"))
    data.pop("modo")
    data["formato"] = 1
    (tmp_path / "v.plc").write_text(json.dumps(data), encoding="utf-8")
    q = project.load(str(tmp_path / "v.plc"))
    assert q.sequence is None and q.mode == "pelicula"
    data["modo"] = "outro"
    data["edicao"] = "lixo"
    (tmp_path / "v.plc").write_text(json.dumps(data), encoding="utf-8")
    q = project.load(str(tmp_path / "v.plc"))
    assert q.sequence is None and q.mode == "pelicula"


def test_markers_saved_without_changing_the_format(tmp_path):
    from pelicula import timeline
    p = make(tmp_path)
    seq = timeline.Sequence.from_json(_seq_json(p.media_path))
    seq.add_marker(12, "Abertura", chapter=True)
    p.sequence = seq.to_json()
    project.save(p, str(tmp_path / "m.plc"))
    data = json.loads((tmp_path / "m.plc").read_text(encoding="utf-8"))
    assert data["formato"] == 2 and data["edicao"]["marcadores"][0]["nome"] == "Abertura"
    q = project.load(str(tmp_path / "m.plc"))
    again = timeline.Sequence.from_json(q.sequence)
    assert [(m.frame, m.name, m.chapter) for m in again.markers] == [(12, "Abertura", True)]
