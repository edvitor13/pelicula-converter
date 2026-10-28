"""A receita única do quadro (`frame.Recipe`): todo caminho que mostra ou grava um quadro dá o mesmo quadro.

A exportação (FFV1 16 bits, lida de volta), a prévia da janela de exportação (`export.preview_frame`),
`pelicula-cli quadro` e a receita aplicada à mão têm que dar o mesmo quadro bit a bit, para um arquivo e para
uma montagem do modo Edição. A janela principal ("Salvar quadro" e a prévia) é conferida em
`fundacao_ui_cases.py`.
"""

from __future__ import annotations

import numpy as np
import pytest

from helpers import SAMPLE_H, SAMPLE_W, read_all
from pelicula import cli, export, frame, media, presets, project, sequence
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings


@pytest.fixture
def film():
    v = presets.builtin_values("vision3_500t")  # grão, halação, bloom, cópia
    v.update(grao_forca=1.4, desg_on=True, mold_on=True)
    return v


@pytest.fixture
def gl_session(gl_engine):
    """`pelicula-cli quadro` cria e libera o próprio contexto OpenGL: reativa o da sessão no fim."""
    yield gl_engine
    gl_engine.ctx.__enter__()


def _ffv1() -> ExportSettings:
    return ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)


def _export(engine, info, values, out, start, end, seq=None) -> list[np.ndarray]:
    job = ExportJob(info=info, values=values, settings=_ffv1(), out_path=str(out), start_frame=start, end_frame=end,
                    sequence=seq)
    export.run_job(job, engine)
    assert job.status == "concluido", job.error
    o = media.probe(str(out))
    frames = read_all(media.FrameReader(o, o.width, o.height, 16))
    assert len(frames) == end - start + 1
    return frames


def _cli_frame(tmp_path, media_path, values, n, seq=None) -> np.ndarray:
    plc = tmp_path / f"q{n}.plc"
    project.save(project.Project(media_path=media_path, values=values, preset_id="vision3_500t",
                                 sequence=seq.to_json() if seq is not None else None,
                                 mode="edicao" if seq is not None else "pelicula"), str(plc))
    png = tmp_path / f"q{n}.png"
    assert cli.main(["quadro", str(plc), "-o", str(png), "--tempo", f"#{n}"]) == 0
    info = media.probe(str(png))
    return media.grab_frame(info, 0, info.width, info.height, 16)


def _edit_sequence(sample_video) -> tl.Sequence:
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    seq.split(8)
    v = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    seq.set_values(v[1].id, {**v[1].values, "exposicao": 0.4, "saturacao": -0.2, "escala": 0.8, "rotacao": 4.0,
                             "entrada_tipo": "dissolver", "entrada_dur": 0.2})
    over, = seq.insert_media(src, at=4, vtrack=1, with_audio=False)
    seq.set_values(over.id, {**over.values, "escala": 0.4, "pos_x": 0.2, "opacidade": 0.6, "mesclagem": "tela"})
    # Como no app e na linha de comando, a montagem chega por JSON (`Sequence.copy`, projeto, fila): o JSON grava
    # o início no arquivo com 6 casas e, num corte, o quadro de origem pode ser o anterior ao da montagem viva.
    return tl.Sequence.from_json(seq.to_json())


# ------------------------------------------------------------------ sem GPU
def test_export_pipeline_is_the_recipe(make_info):
    assert export.FramePipeline is frame.Recipe
    info = make_info(width=320, height=180, fps=24.0, fps_str="24/1")
    r = export.frame_pipeline(info, {"lut_on": False}, ExportSettings(fps="12", dither=True))
    assert isinstance(r, frame.Recipe)
    assert (r.fps, r.src_fps, r.depth, r.dither, r.legal, r.lut, r.seq, r.keys) == (12.0, 24.0, 8, True, True,
                                                                                     None, None, {})
    assert (r.fit.dec_w, r.fit.dec_h) == (320, 180) and r.montage_size() == (320, 180)


def test_look_values_without_keys_are_the_values_themselves():
    v = presets.builtin_values("vision3_500t")
    r = frame.Recipe.for_source(v, 24.0, 16, legal=True)
    assert r.look_values(10) is v  # sem chaves: nada muda (o plano é o de antes)
    assert r.dither is False and frame.Recipe.for_source(v, 24.0, 8, legal=True, dither=True).dither
    assert frame.Recipe.for_source(v, 24.0, 16, legal=True, dither=True).dither is False  # só em 8 bits
    assert r.with_(depth=8).depth == 8 and r.depth == 16


def test_montage_size_without_fit():
    seq = tl.Sequence(640, 360, "24/1")
    assert frame.Recipe.for_source(None, 24.0, 8, legal=True, seq=seq).montage_size() == (640, 360)
    assert frame.Recipe.for_source(None, 24.0, 8, legal=True, seq=seq, size=(320, 180)).montage_size() == (320, 180)
    img = np.zeros((90, 160, 3), np.uint8)
    assert frame.Recipe.for_source(None, 24.0, 8, legal=True).montage_size(img) == (160, 90)


# ------------------------------------------------------------------ GPU: todos os caminhos, o mesmo quadro
@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_file_frame_is_the_same_through_every_caller(gl_session, ffmpeg_ok, sample_video, sample_info, film,
                                                      tmp_path):
    engine = gl_session
    exported = _export(engine, sample_info, film, tmp_path / "arquivo.mkv", 3, 9)
    recipe = frame.Recipe.for_source(film, sample_info.fps, 16, legal=media.legal_range(sample_info),
                                     size=(SAMPLE_W, SAMPLE_H))
    for n in (3, 6, 9):
        ref = exported[n - 3]
        prev = export.preview_frame(engine, sample_info, film, _ffv1(), n, depth=16)
        assert np.array_equal(prev, ref), f"prévia da exportação, quadro {n}"
        img = media.grab_frame(sample_info, n, SAMPLE_W, SAMPLE_H, 16, hq=True)
        assert np.array_equal(recipe.render(engine, img, n), ref), f"receita, quadro {n}"
    still = _cli_frame(tmp_path, sample_video, film, 6)
    engine.ctx.__enter__()
    assert np.array_equal(still, exported[3]), "pelicula-cli quadro difere do quadro exportado"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_edit_frame_is_the_same_through_every_caller(gl_session, ffmpeg_ok, sample_video, film, tmp_path):
    engine = gl_session
    seq = _edit_sequence(sample_video)
    info = sequence.media_info(seq)
    exported = _export(engine, info, film, tmp_path / "montagem.mkv", 2, 12, seq=seq)
    w, h = sequence.canvas_size(seq)
    recipe = frame.Recipe.for_source(film, info.fps, 16, legal=sequence.legal_range(seq), seq=seq, size=(w, h))
    for n in (2, 5, 9, 12):
        ref = exported[n - 2]
        prev = export.preview_frame(engine, info, film, _ffv1(), n, seq=seq, depth=16)
        assert np.array_equal(prev, ref), f"prévia da exportação, quadro {n}"
        layers = sequence.grab(seq, n, w, h, 16, hq=True)
        assert np.array_equal(recipe.render(engine, layers, n), ref), f"receita, quadro {n}"
    still = _cli_frame(tmp_path, sample_video, film, 9, seq=seq)
    engine.ctx.__enter__()
    assert np.array_equal(still, exported[7]), "pelicula-cli quadro difere do quadro exportado"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_montage_only_preview_matches_the_original_look_in_8_bits(gl_engine, ffmpeg_ok, sample_video):
    """No modo Edição sem película a prévia mostra só a montagem (`values` None) e a exportação usa o look
    "Original": em 8 bits (a prévia) os dois dão a mesma imagem."""
    seq = _edit_sequence(sample_video)
    w, h = sequence.canvas_size(seq)
    layers = sequence.grab(seq, 6, w, h, 8)
    only = frame.Recipe.for_source(None, 24.0, 8, legal=True, seq=seq, size=(w, h), dither=True)
    montage = only.render(gl_engine, layers, 6)
    assert np.array_equal(only.montage(gl_engine, layers), montage)
    # A exportação desliga o pontilhado quando pedem; com ele, a diferença é só o pontilhado (±1).
    original = only.with_(values=presets.builtin_values("original"), legal=sequence.legal_range(seq), dither=False)
    assert np.array_equal(original.render(gl_engine, layers, 6), montage)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_preview_keeps_the_reused_upload(gl_engine, ffmpeg_ok, sample_info, film):
    """A prévia só reenvia a imagem quando ela muda: `look(upload=False)` usa a imagem já enviada."""
    img = media.grab_frame(sample_info, 4, SAMPLE_W, SAMPLE_H, 8)
    r = frame.Recipe.for_source(film, sample_info.fps, 8, legal=True, dither=True)
    a = r.look(gl_engine, img, 4)
    b = r.look(gl_engine, img, 4, upload=False)
    assert np.array_equal(a, b)
