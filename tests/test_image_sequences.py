"""Sequências de imagens numeradas (plano_0001.png…): detecção, leitura com `-start_number`, JSON, relocalizar.

Os quadros de teste são PNGs de uma cor por quadro (o vermelho diz o número), gravados sem o ffmpeg; a versão
com transparência e a de 16 bits em TIFF são gravadas pelo ffmpeg.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from helpers import write_png
from pelicula import media, project, sequence
from pelicula import timeline as tl

W, H = 64, 36
FIRST, COUNT = 7, 12


def color_of(n: int) -> tuple[int, int, int]:
    return (10 * (n % 25), 200, 30)


def make_sequence(folder: Path, prefix="plano_", first=FIRST, count=COUNT, width=4, ext=".png") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(first, first + count):
        img = np.zeros((H, W, 3), np.uint8)
        img[:] = color_of(n)
        write_png(folder / f"{prefix}{n:0{width}d}{ext}", img)
    return folder


@pytest.fixture
def seq_dir(tmp_path) -> Path:
    return make_sequence(tmp_path / "plano")


# ------------------------------------------------------------------ detecção
def test_find_sequence_from_a_file_and_from_the_folder(seq_dir):
    f = media.find_sequence(str(seq_dir / "plano_0010.png"))
    assert f is not None and f.first == FIRST and f.count == COUNT and f.last == FIRST + COUNT - 1
    assert Path(f.pattern).name == "plano_%04d.png" and Path(f.pattern).parent == seq_dir
    assert f.gaps == [] and f.label == "plano_[0007-0018].png"
    assert Path(f.file(12)).name == "plano_0012.png"
    g = media.find_sequence(str(seq_dir))
    assert g == f
    assert media.is_sequence_pattern(f.pattern) and not media.is_sequence_pattern(str(seq_dir / "plano_0010.png"))
    assert media.sequence_stem(f.pattern) == "plano"
    assert media.sequence_from_pattern(f.pattern) == f
    assert media.path_exists(f.pattern) and media.path_exists(f.pattern, FIRST)
    assert not media.path_exists(f.pattern, 3)


def test_single_numbered_image_and_other_files_are_not_sequences(tmp_path):
    make_sequence(tmp_path, prefix="logo_", first=2024, count=1)
    (tmp_path / "notas.txt").write_text("x")
    assert media.find_sequence(str(tmp_path / "logo_2024.png")) is None
    assert media.find_sequence(str(tmp_path)) is None
    assert media.find_sequence(str(tmp_path / "notas.txt")) is None


def test_unpadded_numbers_and_largest_group_in_a_folder(tmp_path):
    make_sequence(tmp_path, prefix="q", first=8, count=5, width=1)  # q8.png … q12.png
    make_sequence(tmp_path, prefix="outro_", first=1, count=3)
    f = media.find_sequence(str(tmp_path / "q9.png"))
    assert Path(f.pattern).name == "q%d.png" and (f.first, f.count) == (8, 5)
    assert Path(f.file(10)).name == "q10.png"
    assert Path(media.find_sequence(str(tmp_path)).pattern).name == "q%d.png"  # o maior grupo da pasta


def test_gaps_split_the_sequence_and_are_reported(seq_dir):
    os.remove(seq_dir / "plano_0011.png")
    os.remove(seq_dir / "plano_0012.png")
    f = media.find_sequence(str(seq_dir / "plano_0008.png"))
    assert (f.first, f.count) == (7, 4) and f.gaps == [(11, 12)]
    after = media.find_sequence(str(seq_dir / "plano_0015.png"))
    assert (after.first, after.count) == (13, 6) and after.gaps == [(11, 12)]
    assert media.sequence_from_pattern(f.pattern) == f
    assert media.sequence_from_pattern(f.pattern, 13) == after


def test_percent_in_the_name_is_escaped(tmp_path):
    make_sequence(tmp_path, prefix="100%_", count=3)
    f = media.find_sequence(str(tmp_path / "100%_0008.png"))
    assert Path(f.pattern).name == "100%%_%04d.png"
    assert Path(f.file(8)).name == "100%_0008.png" and f.label == "100%_[0007-0009].png"


def test_exr_and_dpx_only_with_the_decoder(monkeypatch):
    monkeypatch.setattr(media, "decoders", lambda: {"png", "exr"})
    assert ".exr" in media.sequence_exts() and ".dpx" not in media.sequence_exts()
    assert ".png" in media.sequence_exts() and ".tif" in media.sequence_exts()


# ------------------------------------------------------------------ fonte e JSON
def _source(seq_dir, fps="25/1") -> tl.Source:
    return tl.Source.from_info(media.probe_sequence(media.find_sequence(str(seq_dir)), fps))


@pytest.mark.ffmpeg
def test_probe_sequence_and_source_json(seq_dir):
    src = _source(seq_dir)
    assert src.is_sequence and src.seq_start == FIRST and not src.is_image and src.frames == COUNT
    assert src.fps_str == "25/1" and src.duration == pytest.approx(COUNT / 25)
    assert (src.width, src.height) == (W, H) and not src.has_alpha and not src.has_audio
    assert src.name == "plano_[0007-0018].png"
    d = json.loads(json.dumps(src.to_json()))
    assert d["sequencia"] == {"inicio": FIRST} and d["imagem"] is False
    assert tl.Source.from_json(d) == src
    plain = tl.Source("C:/v/a.mp4", W, H, 24.0, "24/1", 48, 2.0).to_json()
    assert "sequencia" not in plain and tl.Source.from_json(plain).seq_start == -1
    seq = tl.Sequence.for_source(src)
    assert seq.fps_str == "25/1" and seq.duration == COUNT
    assert "sequencia_imagens" in seq.features() and seq.to_json()["formato"] == tl.FORMAT
    assert seq.is_trivial() == src.path and seq.direct_file() is None  # no modo Película, pela montagem
    assert media.probe(src.path).seq_start == FIRST and media.probe(src.path, "30/1").fps_str == "30/1"
    assert media.probe_source(src.path).is_sequence
    info = sequence.media_info(seq)
    assert Path(info.path).name == "plano_edicao.mov"


@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_reader_and_grab_read_the_numbered_files(seq_dir, depth):
    src = _source(seq_dir)
    info = src.to_info()
    mx = 255 if depth == 8 else 65535
    frames = []
    r = media.FrameReader(info, W, H, depth, start_frame=3, max_frames=4)
    try:
        while (img := r.read()) is not None:
            frames.append(img.copy())
    finally:
        r.close()
    assert len(frames) == 4
    for k, img in enumerate(frames):
        want = np.array(color_of(FIRST + 3 + k)) * (mx / 255)
        assert np.abs(img.reshape(-1, 3).mean(0) - want).max() <= (1 if depth == 8 else 257), k
    one = media.grab_frame(info, 5, W, H, depth)
    alone = media.grab_frame(media.probe(str(seq_dir / f"plano_{FIRST + 5:04d}.png")), 0, W, H, depth)
    assert np.array_equal(one, alone)  # o quadro 5 é o arquivo número 12, igual a abrir a imagem sozinha


@pytest.mark.ffmpeg
def test_montage_reads_the_sequence_like_a_video(seq_dir):
    # 25 quadros/s: 2 quadros = 0,08 s exato (a 24, `seq.copy()` arredonda a entrada no JSON e o quadro muda —
    # limitação da base, fora daqui)
    src = _source(seq_dir, "25/1")
    seq = tl.Sequence.for_source(src)
    clip = next(c for c in seq.clips if c.kind == tl.VIDEO)
    seq.trim_start(clip.id, 2)
    seq.move(clip.id, 0)
    reader = sequence.SequenceReader(seq, W, H, 8, 0, 5)
    try:
        for t in range(5):
            a, b = sequence.grab(seq, t, W, H, 8).layers, reader.read().layers
            assert np.array_equal(a[0].image, b[0].image), t
            want = np.array(color_of(FIRST + seq.layers_at(t)[0].src_frame))
            assert np.abs(a[0].image.reshape(-1, 3).mean(0) - want).max() <= 1
    finally:
        reader.close()


@pytest.mark.ffmpeg
def test_alpha_sequence_keeps_the_transparency(ffmpeg_ok, tmp_path):
    out = tmp_path / "alfa"
    out.mkdir()
    res = subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=24:d=0.25",
                          "-vf", "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*gte(X,32)'",
                          "-start_number", "1", str(out / "a_%03d.png")], capture_output=True)
    if res.returncode != 0:
        pytest.skip("o ffmpeg não gravou a sequência com alfa")
    src = _source(out, "24/1")
    assert src.has_alpha and src.frames == 6 and src.seq_start == 1
    img = media.grab_frame(src.to_info(), 2, W, H, 8, alpha=True)
    assert img.shape == (H, W, 4) and img[:, :30, 3].max() == 0 and img[:, 34:, 3].min() == 255
    assert "alfa" in tl.Sequence.for_source(src).features()


@pytest.mark.ffmpeg
def test_tiff_16_bit_sequence(ffmpeg_ok, tmp_path):
    out = tmp_path / "tif"
    out.mkdir()
    res = subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=24:d=0.25",
                          "-pix_fmt", "rgb48le", str(out / "t_%05d.tif")], capture_output=True)
    if res.returncode != 0:
        pytest.skip("o ffmpeg não gravou TIFF de 16 bits")
    src = _source(out)
    assert src.bit_depth == 16 and src.frames == 6 and Path(src.path).name == "t_%05d.tif"
    assert media.grab_frame(src.to_info(), 5, W, H, 16).dtype == np.uint16


# ------------------------------------------------------------------ arquivos que sumiram e relocalizar
@pytest.mark.ffmpeg
def test_missing_files_and_relink_with_the_pattern(seq_dir, tmp_path):
    src = _source(seq_dir)
    seq = tl.Sequence.for_source(src)
    assert sequence.missing_sources(seq) == []
    moved = tmp_path / "outra_pasta"
    shutil.move(str(seq_dir), str(moved))
    assert sequence.missing_sources(seq) == [src.path]
    # na pasta nova a numeração começa em outro número
    for n in range(FIRST, FIRST + COUNT):
        os.rename(moved / f"plano_{n:04d}.png", moved / f"plano_{n + 93:04d}.png")
    found = media.find_sequence(str(moved / "plano_0100.png"))
    seq.relink(src.path, found.pattern, seq_start=found.first)
    new = seq.sources[found.pattern]
    assert new.seq_start == FIRST + 93 and sequence.missing_sources(seq) == []
    assert all(c.src == found.pattern for c in seq.clips)
    img = sequence.grab(seq, 0, W, H, 8).layers[0].image
    assert np.abs(img.reshape(-1, 3).mean(0) - np.array(color_of(FIRST))).max() <= 1


@pytest.mark.ffmpeg
def test_project_finds_the_sequence_by_the_relative_path(seq_dir, tmp_path):
    src = _source(seq_dir)
    seq = tl.Sequence.for_source(src)
    path = tmp_path / "filme.plc"
    project.save(project.Project(media_path=src.path, sequence=seq.to_json()), str(path))
    raw = json.loads(path.read_text(encoding="utf-8"))
    fonte = raw["edicao"]["fontes"][0]
    assert fonte["sequencia"] == {"inicio": FIRST} and fonte["relativo"].replace("\\", "/") == "plano/plano_%04d.png"
    dest = tmp_path.parent / (tmp_path.name + "_movido")
    shutil.copytree(tmp_path, dest)
    shutil.rmtree(seq_dir)
    back = tl.Sequence.from_json(project.load(str(dest / "filme.plc")).sequence)
    (moved,) = back.sources
    assert Path(moved).parent == dest / "plano" and sequence.missing_sources(back) == []
