"""Capítulos a partir dos marcadores: texto para o YouTube, regras e FFMETADATA na exportação."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pelicula import chapters, export, media, timeline as tl
from pelicula.export import ExportJob, ExportSettings


def seq_with(*marks, fps="24/1") -> tl.Sequence:
    seq = tl.Sequence(1920, 1080, fps)
    for frame, name, chapter in marks:
        seq.add_marker(frame, name=name, chapter=chapter)
    return seq


# ------------------------------------------------------------------ YouTube
def test_youtube_text_and_rules_ok():
    seq = seq_with((0, "Abertura", True), (24 * 15, "Meio", True), (24 * 40, "Fim", True), (24 * 5, "nota", False))
    assert chapters.points(seq) == [(0, "Abertura"), (360, "Meio"), (960, "Fim")]  # só os capítulos
    chs = chapters.relative(chapters.points(seq), 0, 24 * 60, 24.0)
    assert chapters.youtube_text(chs, 60.0) == "00:00 Abertura\n00:15 Meio\n00:40 Fim"
    assert chapters.youtube_problems(chs, 60.0) == []


def test_youtube_rules_explain_what_is_missing():
    seq = seq_with((24 * 3, "Começo", True), (24 * 8, "Curto", True))
    chs = chapters.relative(chapters.points(seq), 0, 24 * 30, 24.0)
    probs = chapters.youtube_problems(chs, 30.0)
    assert len(probs) == 3
    assert "00:00" in probs[0] and "00:03" in probs[0]   # o primeiro precisa estar no início
    assert "3" in probs[1] and "2" in probs[1]            # pelo menos 3 capítulos
    assert "00:03 Começo" in probs[2] and "00:08 Curto" not in probs[2]  # 5 s é pouco; o último tem 22 s
    assert chapters.youtube_problems([], 30.0) and "Capítulo" in chapters.youtube_problems([], 30.0)[0]


def test_youtube_text_uses_hours_in_long_videos_and_names_untitled_chapters():
    seq = seq_with((0, "", True), (24 * 3605, "Depois de uma hora", True))
    chs = chapters.relative(chapters.points(seq), 0, 24 * 4000, 24.0)
    assert chapters.youtube_text(chs, 4000.0) == "0:00:00 Capítulo 1\n1:00:05 Depois de uma hora"


def test_relative_to_the_exported_range():
    pts = [(0, "A"), (240, "B"), (480, "C"), (900, "D")]
    # trecho de 300 a 600: "B" já estava valendo e vira o capítulo em 0; "D" fica de fora
    assert chapters.relative(pts, 300, 600, 24.0) == [(0.0, "B"), (7.5, "C")]
    assert chapters.relative(pts, 480, 600, 24.0) == [(0.0, "C")]
    assert chapters.relative([(500, "X")], 0, 400, 24.0) == []


def test_ffmetadata_text_and_escaping():
    text = chapters.ffmetadata([(0.0, "Abertura"), (1.5, "a=b;c#d\\e\nf")], 4.0)
    assert text.splitlines()[0] == ";FFMETADATA1"
    blocks = text.split("[CHAPTER]")[1:]
    assert len(blocks) == 2
    assert "TIMEBASE=1/1000\nSTART=0\nEND=1500\ntitle=Abertura" in blocks[0]
    assert "START=1500\nEND=4000\ntitle=a\\=b\\;c\\#d\\\\e f" in blocks[1]


def test_export_file_only_for_containers_that_keep_chapters():
    pts = [(0, "Abertura"), (24, "Segunda")]
    for container in ("webm", "avi", "png", "gif"):
        assert chapters.export_file(pts, container, 0, 48, 24.0) is None
    assert chapters.export_file([], "mp4", 0, 48, 24.0) is None
    assert chapters.export_file([(100, "Fora")], "mp4", 0, 48, 24.0) is None  # nenhum capítulo no trecho
    for container in ("mp4", "mov", "mkv"):
        path = chapters.export_file(pts, container, 0, 48, 24.0)
        try:
            text = Path(path).read_text(encoding="utf-8")
            assert "START=1000\nEND=2000\ntitle=Segunda" in text
        finally:
            os.remove(path)


# ------------------------------------------------------------------ comando do codificador
@pytest.fixture
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    return "ffmpeg"


def test_encoder_cmd_adds_the_chapters_input_and_map(fake_ffmpeg, make_info):
    info = make_info(path="C:/v/entrada.mp4")
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="aac192")
    plain = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 1.0, 2.0)
    cmd = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 1.0, 2.0, chapters_path="cap.txt")
    i = cmd.index("cap.txt")
    assert cmd[i - 3:i] == ["-f", "ffmetadata", "-i"] and i < cmd.index("-map")  # entrada antes das saídas
    assert cmd[cmd.index("-map_chapters") + 1] == "2" and cmd[-1] == "o.mp4"
    # sem capítulos, o comando é exatamente o de antes; com eles, só entram a entrada e o -map_chapters
    assert "-map_chapters" not in plain and "ffmetadata" not in plain
    j = plain.index("-map")
    assert cmd == plain[:j] + ["-f", "ffmetadata", "-i", "cap.txt"] + plain[j:-1] + ["-map_chapters", "2", "o.mp4"]
    s.audio = "none"
    cmd = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 0.0, 2.0, chapters_path="cap.txt")
    assert cmd[cmd.index("-map_chapters") + 1] == "1"


def test_chapters_with_target_size_only_in_the_pass_that_writes(fake_ffmpeg, make_info):
    info = make_info(path="C:/v/entrada.mp4")
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="aac192", bitrate=4.0)
    first = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 0.0, 2.0, chapters_path="cap.txt",
                                     two_pass=1)
    assert "ffmetadata" not in first and "-map_chapters" not in first  # a 1ª passada não grava arquivo
    second = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 0.0, 2.0, chapters_path="cap.txt",
                                      two_pass=2)
    # a passada roda com cwd numa pasta temporária: o arquivo de capítulos vai com caminho absoluto
    assert os.path.abspath("cap.txt") in second and second[second.index("-map_chapters") + 1] == "2"


def test_run_job_writes_the_range_and_removes_the_file(make_info, tmp_path, monkeypatch):
    seen = {}

    def fake_encode(job, engine, run, s, **kw):
        path = run.chapters_path
        seen["path"] = path
        seen["text"] = Path(path).read_text(encoding="utf-8") if path else ""
        return False

    monkeypatch.setattr(export, "_encode", fake_encode)
    info = make_info(path=str(tmp_path / "entrada.mp4"), frames=480, duration=20.0, has_audio=False)
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="none")
    job = ExportJob(info=info, values={}, settings=s, out_path=str(tmp_path / "saida.mp4"), start_frame=48,
                    end_frame=239, chapters=[(0, "A"), (96, "B"), (300, "C")])
    export.run_job(job, None)
    text = seen["text"]
    assert "START=0\nEND=2000\ntitle=A" in text and "START=2000\nEND=8000\ntitle=B" in text
    assert "title=C" not in text
    assert not os.path.exists(seen["path"])
    # recipiente sem capítulos ou opção desligada (lista vazia): nada de arquivo
    job = ExportJob(info=info, values={}, settings=ExportSettings(codec="vp9", container="webm", pix="yuv420p",
                                                                  audio="none"),
                    out_path=str(tmp_path / "saida.webm"), chapters=[(0, "A")])
    export.run_job(job, None)
    assert seen["path"] is None


# ------------------------------------------------------------------ ffmpeg de verdade
@pytest.mark.ffmpeg
@pytest.mark.parametrize("container", ["mp4", "mov", "mkv"])
def test_exported_file_has_the_chapters(ffmpeg_ok, sample_video, tmp_path, container):
    info = media.probe(sample_video)
    path = chapters.export_file([(0, "Abertura"), (12, "Meio = parte; 2")], container, 0, 24, 24.0)
    s = ExportSettings(codec="x264", container=container, pix="yuv420p", quality=30, preset="ultrafast",
                       audio="aac192")
    out = tmp_path / f"saida.{container}"
    try:
        cmd = export.build_encoder_cmd(str(out), info, s, 320, 180, "24/1", 8, 0.0, 1.0, chapters_path=path)
        frames = np.zeros((24, 180, 320, 3), np.uint8).tobytes()
        res = subprocess.run(cmd, input=frames, capture_output=True, timeout=120)
        assert res.returncode == 0, res.stderr.decode("utf-8", "replace")[-2000:]
    finally:
        os.remove(path)
    probe = subprocess.run([media.ffprobe(), "-v", "error", "-show_chapters", "-show_streams", "-of", "json",
                            str(out)], capture_output=True, timeout=60)
    data = json.loads(probe.stdout.decode("utf-8"))
    chs = data["chapters"]
    assert [c["tags"]["title"] for c in chs] == ["Abertura", "Meio = parte; 2"]
    assert [round(float(c["start_time"]), 2) for c in chs] == [0.0, 0.5]
    assert abs(float(chs[-1]["end_time"]) - 1.0) < 0.05
    kinds = sorted(st["codec_type"] for st in data["streams"])
    assert "video" in kinds and "audio" in kinds  # o vídeo e o som continuam lá
