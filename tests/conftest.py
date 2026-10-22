"""Fixtures compartilhadas da suíte do PeliculaConverter.

- Testes de GPU (``@pytest.mark.gpu``) pedem ``gl_engine`` e são pulados sem OpenGL 3.3.
- Testes de ffmpeg (``@pytest.mark.ffmpeg``) pedem ``ffmpeg_ok`` e são pulados sem ffmpeg/ffprobe.
- ``APPDATA`` é sempre redirecionado para uma pasta temporária (presets e LUTs do usuário
  nunca são tocados).
"""

from __future__ import annotations

import faulthandler
import itertools
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Não grava .pyc dentro de pelicula/ (o código do app está sendo editado por outra pessoa).
sys.dont_write_bytecode = True

# Preferências do app (QSettings) nunca vão para o registro/config real durante os testes.
if not os.environ.get("PELICULA_SETTINGS_DIR"):
    import tempfile
    os.environ["PELICULA_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="pelicula_test_settings_")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from helpers import SAMPLE_FPS, SAMPLE_H, SAMPLE_W, write_png  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_APPDATA_COUNTER = itertools.count()


# ------------------------------------------------------------------ vigia de testes travados
# Sem dependências extras (nada de pytest-timeout): se um teste passar do limite, as pilhas de
# todas as threads são impressas e a suíte termina com erro em vez de travar o CI para sempre.
TEST_TIMEOUT = float(os.environ.get("PELICULA_TEST_TIMEOUT", "180") or 0)
_RUNNING: dict[str, object] = {"t": None, "id": ""}


def _watchdog(config) -> None:
    while True:
        time.sleep(0.5)
        t0 = _RUNNING["t"]
        if t0 is None or time.time() - t0 <= TEST_TIMEOUT:
            continue
        capman = config.pluginmanager.getplugin("capturemanager")
        try:
            if capman is not None:
                capman.suspend_global_capture(in_=True)
        except Exception:  # noqa: BLE001
            pass
        sys.stderr.write(f"\n\n*** Teste travado há mais de {TEST_TIMEOUT:.0f} s: {_RUNNING['id']}\n"
                         "*** Pilhas de todas as threads (PELICULA_TEST_TIMEOUT muda o limite):\n")
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        sys.stderr.flush()
        os._exit(3)


def pytest_configure(config):
    if TEST_TIMEOUT > 0:
        threading.Thread(target=_watchdog, args=(config,), daemon=True, name="vigia-testes").start()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _RUNNING["t"], _RUNNING["id"] = time.time(), item.nodeid
    try:
        return (yield)
    finally:
        _RUNNING["t"] = None


# ------------------------------------------------------------------ isolamento
@pytest.fixture(scope="session")
def _appdata_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("appdata")


@pytest.fixture(autouse=True)
def tmp_appdata(monkeypatch, _appdata_root) -> Path:
    """APPDATA aponta para uma pasta nova (ainda inexistente) em todos os testes; devolve essa pasta.

    A pasta só é criada quando o app grava algo (presets.user_dir()/luts.user_dir() criam), então
    os milhares de testes que não usam APPDATA não criam pastas temporárias.
    """
    d = _appdata_root / f"t{next(_APPDATA_COUNTER):05d}"
    monkeypatch.setenv("APPDATA", str(d))
    return d


# ------------------------------------------------------------------ cenários isolados (podem travar)
_HANG_RUNS: dict[str, object] = {}


def _start_hang_runs(tmp_path_factory):
    if "runs" not in _HANG_RUNS:
        from helpers import HANG_DEADLINE, HANG_SCENARIOS, Isolated
        tmp = tmp_path_factory.mktemp("isolados")
        env = dict(os.environ, APPDATA=str(tmp), PELICULA_TMP=str(tmp))
        _HANG_RUNS["runs"] = Isolated(HANG_SCENARIOS, env, HANG_DEADLINE)
    return _HANG_RUNS["runs"]


@pytest.fixture(scope="session", autouse=True)
def _hang_runs_in_background(request, tmp_path_factory):
    """Dispara os cenários isolados logo no começo para o prazo correr junto com o resto da suíte."""
    wanted = sys.platform == "win32" and any("hang_runs" in getattr(it, "fixturenames", ())
                                             for it in request.session.items)
    if wanted:
        _start_hang_runs(tmp_path_factory)
    yield
    runs = _HANG_RUNS.pop("runs", None)
    if runs is not None:
        runs.close()


@pytest.fixture(scope="session")
def hang_runs(tmp_path_factory):
    if sys.platform != "win32":
        pytest.skip("pipes nomeados só no Windows")
    return _start_hang_runs(tmp_path_factory)


# ------------------------------------------------------------------ ferramentas externas
@pytest.fixture(scope="session")
def ffmpeg_ok() -> str:
    from pelicula import media
    try:
        ok = media.configure()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ffmpeg indisponível: {exc}")
    if not ok:
        pytest.skip("ffmpeg/ffprobe não encontrados")
    return media.ffmpeg()


@pytest.fixture(scope="session")
def gl_engine():
    """Um Engine para a sessão inteira (o contexto fica atual na thread principal)."""
    try:
        import moderngl
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    from pelicula.engine import Engine
    eng = Engine(ctx)
    yield eng
    eng.release()


@pytest.fixture(scope="session")
def qapp():
    """QGuiApplication única (o texto da borda do scan é desenhado com o Qt)."""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        pytest.skip("PySide6 indisponível")
    if sys.platform != "win32" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


# ------------------------------------------------------------------ mídia de teste
@pytest.fixture(scope="session")
def test_rgb() -> np.ndarray:
    from pelicula import testimage
    return testimage.make(SAMPLE_W, SAMPLE_H)


@pytest.fixture(scope="session")
def sample_image(tmp_path_factory, test_rgb) -> str:
    return str(write_png(tmp_path_factory.mktemp("img") / "cena.png", test_rgb))


@pytest.fixture(scope="session")
def sample_image16(tmp_path_factory, test_rgb) -> str:
    arr = test_rgb.astype(np.uint16) * 257
    return str(write_png(tmp_path_factory.mktemp("img16") / "cena16.png", arr))


@pytest.fixture(scope="session")
def sample_video(ffmpeg_ok, tmp_path_factory) -> str:
    """1 s, 320x180, 24 fps, H.264 yuv420p (com B-frames) + AAC 48 kHz, .mp4."""
    out = tmp_path_factory.mktemp("video") / "amostra.mp4"
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-nostdin",
           "-f", "lavfi", "-i", f"testsrc2=size={SAMPLE_W}x{SAMPLE_H}:rate={SAMPLE_FPS}:duration=1",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", str(out)]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not out.exists():
        pytest.skip("não foi possível gerar o vídeo de teste: " + res.stderr.decode("utf-8", "replace"))
    return str(out)


@pytest.fixture(scope="session")
def sample_vertical_video(ffmpeg_ok, tmp_path_factory) -> str:
    """Vídeo em pé, como o de um celular: 0,5 s, 180x320 (9:16), 24 fps, H.264, sem som."""
    out = tmp_path_factory.mktemp("vertical") / "celular.mp4"
    cmd = [ffmpeg_ok, "-v", "error", "-y", "-nostdin",
           "-f", "lavfi", "-i", f"testsrc2=size={SAMPLE_H}x{SAMPLE_W}:rate={SAMPLE_FPS}:duration=0.5",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not out.exists():
        pytest.skip("não foi possível gerar o vídeo vertical: " + res.stderr.decode("utf-8", "replace"))
    return str(out)


@pytest.fixture(scope="session")
def sample_info(sample_video):
    from pelicula import media
    return media.probe(sample_video)


@pytest.fixture
def make_info():
    """Fábrica de MediaInfo sem precisar de arquivo (testes que não usam o ffmpeg)."""
    from pelicula import media

    def make(**kw) -> "media.MediaInfo":
        base = dict(path="C:/videos/entrada.mp4", width=1920, height=1080, fps=24.0, fps_str="24/1", frames=240,
                    duration=10.0, pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="High", bitrate=20_000_000,
                    color_space="bt709", color_range="tv", color_transfer="bt709", color_primaries="bt709",
                    has_audio=True, audio_codec="aac", container="mov,mp4,m4a,3gp,3g2,mj2", is_image=False)
        base.update(kw)
        return media.MediaInfo(**base)

    return make

