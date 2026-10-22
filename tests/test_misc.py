"""Cena de teste, texto da borda (Qt), informações da máquina e dependências (sem rede)."""

from __future__ import annotations

import subprocess
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from pelicula import deps, edgetext, system, testimage


# ------------------------------------------------------------------ testimage
@pytest.mark.parametrize("w, h", [(320, 180), (321, 181), (64, 36), (960, 540)])
def test_testimage_shape_and_type(w, h):
    img = testimage.make(w, h)
    assert img.shape == (h, w, 3) and img.dtype == np.uint8 and img.flags.c_contiguous


def test_testimage_is_deterministic_and_has_content():
    a = testimage.make(480, 270)
    assert np.array_equal(a, testimage.make(480, 270))
    assert a.min() < 10 and a.max() == 255
    assert a.std() > 30


def test_testimage_grey_ramp_and_checker():
    w, h = 960, 540
    img = testimage.make(w, h).astype(int)
    s = w / 1920.0
    ramp = img[int(950 * s), :, :]
    assert np.all(np.diff(ramp[:, 1]) >= 0) and ramp[0, 1] <= 2 and ramp[-1, 1] >= 250
    assert np.abs(ramp[:, 0] - ramp[:, 2]).max() <= 1  # cinza neutro
    size, x0, y0 = int(118 * s), int(80 * s), int(120 * s)
    patch = img[y0 + size // 2, x0 + size // 2]
    assert np.abs(patch - np.array(testimage.CHECKER[0])).max() <= 1


# ------------------------------------------------------------------ edgetext
def test_edgetext_empty_text_is_none(qapp):
    assert edgetext.render("") is None


def test_edgetext_renders_mask(qapp):
    txt = "KODAK  5219  VISION3  500T   KJ 44  2731  0815 +12"
    m = edgetext.render(txt)
    assert m is not None and m.dtype == np.uint8 and m.ndim == 2
    assert m.shape[0] == 64 and m.shape[1] > 10 * 64
    assert m.flags.c_contiguous
    # Com QT_QPA_PLATFORM=offscreen (CI) não há fontes reais e o traço fica mais fraco.
    assert m.max() > 64 and 0.005 < (m > 32).mean() < 0.6
    assert np.array_equal(m, edgetext.render(txt))
    small = edgetext.render(txt, height=32)
    assert small.shape[0] == 32 and small.shape[1] < m.shape[1]
    assert edgetext.render("KODAK").shape[1] < m.shape[1]


# ------------------------------------------------------------------ system
def test_cpu_threads_and_ram():
    assert system.cpu_threads() >= 1
    total, avail = system.ram()
    assert total > 0 and 0 < avail <= total


@pytest.mark.parametrize("n, txt", [(1 << 30, "1,0 GB"), (int(15.5 * (1 << 30)), "15,5 GB"), (0, "0,0 GB")])
def test_gb(n, txt):
    assert system.gb(n) == txt


@pytest.mark.skipif(sys.platform != "win32", reason="nome do processador pelo registro do Windows")
def test_cpu_name_reads_registry_through_winreg(monkeypatch):
    """Usa um winreg falso: o teste não lê o registro de verdade."""
    calls = []
    fake = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM",
        OpenKey=lambda root, path: calls.append((root, path)) or "chave",
        QueryValueEx=lambda key, name: ("  AMD   Ryzen 7 5800X  8-Core Processor   ", 1),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake)
    system.cpu_name.cache_clear()
    try:
        assert system.cpu_name() == "AMD Ryzen 7 5800X 8-Core Processor"
        assert calls and calls[0][1].endswith(r"CentralProcessor\0")
    finally:
        system.cpu_name.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="nome do processador pelo registro do Windows")
def test_cpu_name_falls_back_when_registry_fails(monkeypatch):
    def boom(*a):
        raise OSError("sem acesso")

    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace(HKEY_LOCAL_MACHINE=0, OpenKey=boom,
                                                                     OpenKeyEx=boom, QueryValueEx=boom))
    monkeypatch.setattr(system, "platform", types.SimpleNamespace(processor=lambda: ""))
    system.cpu_name.cache_clear()
    try:
        assert system.cpu_name() == "Processador"
    finally:
        system.cpu_name.cache_clear()


def test_nvidia_gpus_parsing(monkeypatch):
    out = b"0, NVIDIA GeForce RTX 3060, 12288\n1, NVIDIA RTX A4000, 16376.0\nlixo\n2, sem memoria, x\n"
    monkeypatch.setattr(system, "shutil", types.SimpleNamespace(which=lambda name: "nvidia-smi"))
    monkeypatch.setattr(system, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=b""),
        TimeoutExpired=subprocess.TimeoutExpired))
    system.nvidia_gpus.cache_clear()
    try:
        assert system.nvidia_gpus() == [(0, "NVIDIA GeForce RTX 3060", 12288), (1, "NVIDIA RTX A4000", 16376)]
    finally:
        system.nvidia_gpus.cache_clear()


def test_nvidia_gpus_without_driver(monkeypatch):
    monkeypatch.setattr(system, "shutil", types.SimpleNamespace(which=lambda name: None))
    monkeypatch.setattr(system, "os", types.SimpleNamespace(path=types.SimpleNamespace(isfile=lambda p: False)))
    system.nvidia_gpus.cache_clear()
    try:
        assert system.nvidia_gpus() == []
    finally:
        system.nvidia_gpus.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="Explorer do Windows")
def test_open_path_and_reveal_use_the_file_manager(monkeypatch, tmp_path):
    """Sem abrir janelas de verdade: os.startfile e subprocess.Popen são substituídos."""
    opened, spawned = [], []
    monkeypatch.setattr(system.os, "startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr(system, "subprocess", types.SimpleNamespace(Popen=lambda args, *a, **k: spawned.append(args)))
    f = tmp_path / "video.mp4"
    f.write_bytes(b"x")
    system.open_path(tmp_path)
    assert opened == [str(tmp_path)]
    system.reveal(f)
    assert spawned and spawned[0][0] == "explorer" and spawned[0][-1] == str(f)
    system.reveal(tmp_path)
    assert opened[-1] == str(tmp_path)


# ------------------------------------------------------------------ gravação segura
@pytest.mark.parametrize("path, expected", [
    ("C:/v/video.mp4", "C:/v/video.parcial-pelicula.mp4"),
    ("saida/meu.filme.mov", "saida/meu.filme.parcial-pelicula.mov"),
    ("look.cube", "look.parcial-pelicula.cube"),
    ("quadro.png", "quadro.parcial-pelicula.png"),
])
def test_partial_path_keeps_the_extension_last(path, expected):
    assert Path(system.partial_path(path)) == Path(expected)
    assert Path(system.partial_path(Path(path))) == Path(expected)


def test_atomic_write_replaces_only_at_the_end(tmp_path):
    dst = tmp_path / "look.cube"
    dst.write_text("antigo", encoding="utf-8")
    with system.atomic_write(dst, "w", encoding="utf-8") as fh:
        fh.write("novo")
        fh.flush()
        assert dst.read_text(encoding="utf-8") == "antigo"  # o antigo continua lá enquanto grava
        assert Path(system.partial_path(dst)).is_file()
    assert dst.read_text(encoding="utf-8") == "novo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["look.cube"]


def test_atomic_write_creates_a_new_file(tmp_path):
    dst = tmp_path / "novo.json"
    with system.atomic_write(dst, "w", encoding="utf-8") as fh:
        fh.write("{}")
    assert dst.read_text(encoding="utf-8") == "{}" and sorted(p.name for p in tmp_path.iterdir()) == ["novo.json"]


def test_atomic_write_error_keeps_the_old_file(tmp_path):
    dst = tmp_path / "look.cube"
    dst.write_text("antigo", encoding="utf-8")
    with pytest.raises(ZeroDivisionError):
        with system.atomic_write(dst, "w", encoding="utf-8") as fh:
            fh.write("pela metade")
            1 / 0
    assert dst.read_text(encoding="utf-8") == "antigo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["look.cube"]


def test_replace_file_retries_while_the_file_is_busy(tmp_path, monkeypatch):
    """No Windows, antivírus e indexador seguram o arquivo por instantes: a troca tenta de novo."""
    src, dst = tmp_path / "a.parcial-pelicula.mp4", tmp_path / "a.mp4"
    src.write_text("novo")
    dst.write_text("antigo")
    real, calls = system.os.replace, []

    def busy_twice(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "em uso")
        real(a, b)

    monkeypatch.setattr(system.os, "replace", busy_twice)
    system.replace_file(src, dst)
    assert len(calls) == 3 and dst.read_text() == "novo" and not src.exists()


def test_replace_file_gives_up_after_the_wait(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.parcial-pelicula.mp4", tmp_path / "a.mp4"
    src.write_text("novo")
    dst.write_text("antigo")

    def always_busy(a, b):
        raise PermissionError(13, "aberto em outro programa")

    monkeypatch.setattr(system.os, "replace", always_busy)
    with pytest.raises(PermissionError):
        system.replace_file(src, dst, wait=0.2)
    assert dst.read_text() == "antigo" and src.read_text() == "novo"


# ------------------------------------------------------------------ deps (sem rede)
@pytest.mark.parametrize("txt, expected", [("7.1", (7, 1)), ("9.0.2", (9, 0, 2)), ("7.1-essentials", (7, 1)),
                                           ("", None), (None, None), ("abc", None)])
def test_parse_version(txt, expected):
    assert deps.parse_version(txt) == expected


@pytest.mark.parametrize("name, ok", [("ffmpeg/bin/ffmpeg.exe", True), ("../fora.exe", False),
                                      ("a/../../b", False), ("bin/../../b", False)])
def test_safe_member(name, ok):
    assert deps._safe_member(name) is ok


def test_safe_member_absolute_paths():
    absolute = "C:/x/ffmpeg.exe" if sys.platform == "win32" else "/usr/bin/ffmpeg"
    assert deps._safe_member(absolute) is False


@pytest.mark.parametrize("first_line, version, built", [
    ("ffmpeg version 9.0.2-essentials_build-www.gyan.dev Copyright (c) 2000-2026", (9, 0, 2), None),
    ("ffmpeg version n7.1 Copyright (c) 2000-2024 the FFmpeg developers", (7, 1), None),
    ("ffmpeg version N-112927-gf89cff96d0-20231207 Copyright (c) 2000-2023", None, date(2023, 12, 7)),
    ("ffmpeg version git-qualquer", None, None),
])
def test_inspect_parses_version_line(monkeypatch, first_line, version, built):
    stdout = (first_line + "\nbuilt with gcc\n").encode()
    monkeypatch.setattr(deps, "subprocess", types.SimpleNamespace(
        run=lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=stdout, stderr=b""),
        TimeoutExpired=subprocess.TimeoutExpired))
    info = deps.inspect("ffmpeg")
    assert info.version == version and info.build_date == built and info.raw == first_line


def test_inspect_missing_executable(tmp_path):
    assert deps.inspect(str(tmp_path / "nao_existe.exe")) is None


def test_ffmpeg_info_label_and_outdated():
    new = deps.FFmpegInfo("f", "x", (9, 0, 2), None)
    assert new.label == "9.0.2" and not new.outdated
    assert deps.FFmpegInfo("f", "x", (6, 1), None).outdated
    old_dev = deps.FFmpegInfo("f", "x", None, date.today() - timedelta(days=900))
    assert old_dev.outdated and old_dev.label.startswith("build de desenvolvimento de ")
    assert not deps.FFmpegInfo("f", "x", None, date.today() - timedelta(days=30)).outdated
    unknown = deps.FFmpegInfo("f", "linha crua", None, None)
    assert unknown.label == "linha crua" and not unknown.outdated
    assert deps.FFmpegInfo("f", "", None, None).label == "desconhecida"


def test_dirs_follow_environment(monkeypatch, tmp_path, tmp_appdata):
    assert deps.config_dir() == tmp_appdata / "PeliculaConverter"
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        assert deps.app_data_dir() == tmp_path / "local" / "PeliculaConverter"
        assert deps.ffmpeg_dir() == tmp_path / "local" / "PeliculaConverter" / "ffmpeg" / "bin"


def test_platform_and_packages():
    assert deps.platform_key() in ("win32", "linux", "darwin") or deps.platform_key()
    if deps.platform_key() in ("win32", "linux"):
        assert deps.platform_supported()
    names = [n for n, _ in deps.python_packages()]
    assert names[:3] == ["PySide6", "moderngl", "numpy"]
    assert deps.missing_python_modules() == []


@pytest.mark.ffmpeg
def test_inspect_real_ffmpeg(ffmpeg_ok):
    info = deps.inspect(ffmpeg_ok)
    assert info is not None and info.raw.startswith("ffmpeg version")
    assert Path(info.path).is_file()
