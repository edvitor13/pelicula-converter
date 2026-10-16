"""Dependências externas: localizar, conferir a versão e baixar o ffmpeg de fontes confiáveis.

Windows: build "release essentials" do gyan.dev (o build para Windows indicado pelo ffmpeg.org),
conferido com o SHA-256 publicado pelo próprio site.
Linux: build estático GPL do BtbN (GitHub), conferido com o checksums.sha256 da release.
macOS: preparado, mas desativado por enquanto.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
MIN_VERSION = (7, 0)
UA = {"User-Agent": f"{APP_NAME}/{__version__}"}

SOURCES = {
    "win32": dict(
        name="gyan.dev (build oficial para Windows indicado pelo ffmpeg.org)",
        version_url="https://www.gyan.dev/ffmpeg/builds/release-version",
        url="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        sha_url="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256",
        kind="zip",
    ),
    "linux": dict(
        name="BtbN FFmpeg-Builds (GitHub, build estático)",
        version_url="",
        url="https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz",
        sha_url="https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/checksums.sha256",
        kind="tar",
    ),
}

PLATFORM_ENABLED = {"win32": True, "linux": True, "darwin": False}


def platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def platform_supported() -> bool:
    return PLATFORM_ENABLED.get(platform_key(), False)


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def config_dir() -> Path:
    """Pasta dos presets e LUTs do usuário.

    Windows: %APPDATA%; Linux: $XDG_CONFIG_HOME (~/.config); macOS: Application Support.
    Se APPDATA estiver definida em qualquer sistema, ela vale (usado pelos testes).
    """
    if os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def ffmpeg_dir() -> Path:
    """Pasta onde o app guarda o ffmpeg que ele mesmo baixou."""
    return app_data_dir() / "ffmpeg" / "bin"


@dataclass
class FFmpegInfo:
    path: str
    raw: str             # primeira linha de `ffmpeg -version`
    version: tuple | None
    build_date: date | None

    @property
    def label(self) -> str:
        if self.version:
            return ".".join(str(n) for n in self.version)
        if self.build_date:
            return f"build de desenvolvimento de {self.build_date.strftime('%d/%m/%Y')}"
        return self.raw or "desconhecida"

    @property
    def outdated(self) -> bool:
        if self.version:
            return self.version < MIN_VERSION
        if self.build_date:
            return (date.today() - self.build_date).days > 540
        return False


def inspect(ffmpeg_path: str) -> FFmpegInfo | None:
    try:
        res = subprocess.run([ffmpeg_path, "-hide_banner", "-version"], capture_output=True, timeout=15,
                             creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = res.stdout.decode("utf-8", "replace").splitlines()[:1]
    raw = first[0] if first else ""
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)(?:\.(\d+))?", raw)
    version = tuple(int(x) for x in m.groups() if x is not None) if m else None
    d = None
    m2 = re.search(r"(20\d{2})(\d{2})(\d{2})", raw)
    if m2 and not version:
        try:
            d = date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            d = None
    return FFmpegInfo(ffmpeg_path, raw, version, d)


def latest_version(timeout: float = 10.0) -> str:
    src = SOURCES.get(platform_key())
    if not src or not src["version_url"]:
        return ""
    try:
        req = urllib.request.Request(src["version_url"], headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(64).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def parse_version(txt: str) -> tuple | None:
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", txt or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def python_packages() -> list[tuple[str, str]]:
    out = []
    for mod in ("PySide6", "moderngl", "numpy", "glcontext"):
        try:
            m = __import__(mod)
            out.append((mod, getattr(m, "__version__", "?")))
        except ImportError:
            out.append((mod, "não instalado"))
    return out


def missing_python_modules() -> list[str]:
    import importlib.util
    pip_names = {"moderngl": "moderngl", "numpy": "numpy", "glcontext": "glcontext"}
    return [pip_names[m] for m in pip_names if importlib.util.find_spec(m) is None]


def pip_install(packages: list[str]) -> tuple[bool, str]:
    """Instala pacotes no Python que está rodando o app (só quando roda pelo código-fonte)."""
    if getattr(sys, "frozen", False):
        return False, "O executável já traz as bibliotecas."
    res = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", *packages], capture_output=True,
                         creationflags=NO_WINDOW)
    return res.returncode == 0, (res.stdout + res.stderr).decode("utf-8", "replace")[-3000:]


class DownloadCancelled(Exception):
    pass


def download_ffmpeg(progress: Callable[[str, int, int], None] | None = None,
                    cancel: threading.Event | None = None) -> Path:
    """Baixa, confere o SHA-256 e instala o ffmpeg na pasta do app. Devolve a pasta com os executáveis."""
    key = platform_key()
    if not platform_supported() or key not in SOURCES:
        raise RuntimeError("O download automático do ffmpeg ainda não está disponível neste sistema.")
    src = SOURCES[key]
    cancel = cancel or threading.Event()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    report("Conferindo a assinatura publicada…")
    req = urllib.request.Request(src["sha_url"], headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        sha_txt = r.read().decode("utf-8", "replace")
    expected = None
    if key == "linux":
        fname = src["url"].rsplit("/", 1)[-1]
        for line in sha_txt.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == fname:
                expected = parts[0].lower()
    else:
        m = re.search(r"[0-9a-fA-F]{64}", sha_txt)
        expected = m.group(0).lower() if m else None
    if not expected:
        raise RuntimeError("Não foi possível obter o SHA-256 oficial do arquivo.")

    tmp = Path(tempfile.mkdtemp(prefix="pelicula_ffmpeg_"))
    try:
        archive = tmp / ("ffmpeg.zip" if src["kind"] == "zip" else "ffmpeg.tar.xz")
        req = urllib.request.Request(src["url"], headers=UA)
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=60) as r, open(archive, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel.is_set():
                    raise DownloadCancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                report("Baixando o ffmpeg…", done, total)
        if h.hexdigest().lower() != expected:
            raise RuntimeError("O arquivo baixado não confere com o SHA-256 oficial. Nada foi instalado.")
        report("Extraindo…")
        out = tmp / "x"
        out.mkdir()
        if src["kind"] == "zip":
            with zipfile.ZipFile(archive) as z:
                for member in z.namelist():
                    if not _safe_member(member):
                        raise RuntimeError(f"Caminho suspeito dentro do arquivo: {member}")
                z.extractall(out)
        else:
            with tarfile.open(archive, "r:xz") as t:
                t.extractall(out, filter="data")
        exe = ".exe" if sys.platform == "win32" else ""
        found = {}
        for name in ("ffmpeg", "ffprobe"):
            hits = list(out.rglob(f"bin/{name}{exe}")) or list(out.rglob(f"{name}{exe}"))
            if not hits:
                raise RuntimeError(f"{name}{exe} não foi encontrado no pacote baixado.")
            found[name] = hits[0]
        dest = ffmpeg_dir()
        staging = dest.parent / "bin.novo"
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for name, path in found.items():
            target = staging / path.name
            shutil.copy2(path, target)
            if sys.platform != "win32":
                target.chmod(0o755)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        staging.rename(dest)
        (dest.parent / "ORIGEM.txt").write_text(
            f"Baixado de: {src['url']}\nFonte: {src['name']}\nSHA-256: {expected}\n", encoding="utf-8")
        report("Pronto.", 1, 1)
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_member(name: str) -> bool:
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts
