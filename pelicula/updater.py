"""Atualização automática pelas releases do GitHub.

Fluxo: consulta a última release, compara com a versão instalada, baixa o pacote do mesmo tipo
da instalação atual (.msi, .zip, .deb, .tar.gz), confere o SHA-256 publicado em SHA256SUMS.txt e
entrega a troca para um script que roda depois que o app fecha (o executável em uso não pode ser
substituído enquanto está aberto).

O repositório precisa ser público para a consulta funcionar sem login. Para testar com o
repositório privado, defina a variável de ambiente PELICULA_GITHUB_TOKEN.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__

REPO = "edvitor13/pelicula-converter"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
SUMS_NAME = "SHA256SUMS.txt"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class UpdateError(Exception):
    pass


@dataclass
class Release:
    tag: str
    version: tuple
    name: str
    body: str
    url: str
    published: str
    assets: dict[str, tuple[str, int]] = field(default_factory=dict)  # nome -> (url, tamanho)


def parse_version(text: str) -> tuple:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else (0,)


def current_version() -> tuple:
    return parse_version(__version__)


def _headers(accept: str = "application/vnd.github+json") -> dict:
    h = {"User-Agent": f"{APP_NAME}/{__version__}", "Accept": accept}
    token = os.environ.get("PELICULA_GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def check(timeout: float = 8.0) -> Release:
    """Última release publicada. Lança UpdateError se não der para consultar."""
    req = urllib.request.Request(API_LATEST, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("no-public-release") from exc
        raise UpdateError(f"http-{exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError("offline") from exc
    assets = {}
    for a in data.get("assets", []):
        # Com token (repositório privado) o download precisa passar pela API.
        url = a.get("url") if os.environ.get("PELICULA_GITHUB_TOKEN") else a.get("browser_download_url")
        assets[a.get("name", "")] = (url, int(a.get("size") or 0))
    tag = data.get("tag_name", "")
    return Release(tag=tag, version=parse_version(tag), name=data.get("name") or tag, body=data.get("body") or "",
                   url=data.get("html_url") or RELEASES_PAGE, published=(data.get("published_at") or "")[:10],
                   assets=assets)


def is_newer(rel: Release) -> bool:
    return rel.version > current_version()


def install_info() -> dict:
    """Como o app foi instalado: msi, zip, deb, tar, dmg ou source (código-fonte)."""
    if not getattr(sys, "frozen", False):
        return {"kind": "source"}
    exe_dir = Path(sys.executable).resolve().parent
    for cand in (exe_dir / "pelicula-install.json", exe_dir / "_internal" / "pelicula-install.json"):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("kind"):
                return data
        except (OSError, ValueError):
            continue
    if sys.platform == "win32":
        return {"kind": "zip"}
    if sys.platform == "darwin":
        return {"kind": "dmg"}
    return {"kind": "deb" if str(exe_dir).startswith("/opt/") else "tar"}


PATTERNS = {
    "msi": r"-windows-x64\.msi$",
    "zip": r"-windows-x64\.zip$",
    "deb": r"-linux-x64\.deb$",
    "tar": r"-linux-x64\.tar\.gz$",
    "dmg": r"-macos\.dmg$",
}


def pick_asset(rel: Release, kind: str | None = None) -> tuple[str, str, int] | None:
    kind = kind or install_info()["kind"]
    pat = PATTERNS.get(kind)
    if not pat:
        return None
    for name, (url, size) in rel.assets.items():
        if re.search(pat, name):
            return name, url, size
    return None


def can_auto_install(kind: str | None = None) -> bool:
    kind = kind or install_info()["kind"]
    if kind == "source":
        return False
    if sys.platform == "darwin":
        return False  # macOS ainda desativado
    return kind in PATTERNS


def _get(url: str, dest: Path | None, progress: Callable[[int, int], None] | None, cancel: threading.Event | None,
         timeout: float = 60.0) -> bytes:
    accept = "application/octet-stream" if "api.github.com" in url else "*/*"
    req = urllib.request.Request(url, headers=_headers(accept))
    h = hashlib.sha256()
    buf = bytearray()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        fh = open(dest, "wb") if dest else None
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("cancelled")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                if fh:
                    fh.write(chunk)
                    h.update(chunk)
                else:
                    buf.extend(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        finally:
            if fh:
                fh.close()
    return h.hexdigest().encode() if dest else bytes(buf)


def download(rel: Release, asset: tuple[str, str, int], progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> str:
    """Baixa o pacote e confere o SHA-256 com o SHA256SUMS.txt da release."""
    name, url, _size = asset
    sums = rel.assets.get(SUMS_NAME)
    if not sums:
        raise UpdateError("no-checksums")
    sums_txt = _get(sums[0], None, None, cancel).decode("utf-8", "replace")
    expected = None
    for line in sums_txt.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            expected = parts[0].lower()
    if not expected:
        raise UpdateError("no-checksums")
    folder = Path(tempfile.mkdtemp(prefix="pelicula_atualizacao_"))
    dest = folder / name
    digest = _get(url, dest, progress, cancel, timeout=120).decode()
    if digest.lower() != expected:
        dest.unlink(missing_ok=True)
        raise UpdateError("checksum-mismatch")
    return str(dest)


def _app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def install(package: str, kind: str | None = None) -> None:
    """Prepara a instalação para rodar quando o app fechar. O app deve sair logo em seguida."""
    kind = kind or install_info()["kind"]
    pid = os.getpid()
    exe = str(Path(sys.executable).resolve())
    work = Path(package).parent
    if sys.platform == "win32":
        if kind == "msi":
            body = (f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue\n"
                    f"$p = Start-Process msiexec.exe -ArgumentList @('/i', '\"{package}\"', '/passive', '/norestart') "
                    f"-Wait -PassThru\n"
                    f"Start-Process -FilePath '{exe}'\n")
        elif kind == "zip":
            import zipfile
            new_dir = work / "novo"
            with zipfile.ZipFile(package) as z:
                for m in z.namelist():
                    if Path(m).is_absolute() or ".." in Path(m).parts:
                        raise UpdateError("bad-archive")
                z.extractall(new_dir)
            src = next((p.parent for p in new_dir.rglob("PeliculaConverter.exe")), None)
            if src is None:
                raise UpdateError("bad-archive")
            body = (f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue\n"
                    f"Start-Sleep -Milliseconds 500\n"
                    f"robocopy '{src}' '{_app_dir()}' /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS | Out-Null\n"
                    f"Start-Process -FilePath '{exe}'\n")
        else:
            raise UpdateError("unsupported")
        script = work / "atualizar.ps1"
        script.write_text(body, encoding="utf-8-sig")
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-File", str(script)], creationflags=NO_WINDOW | 0x00000008)  # DETACHED_PROCESS
        return
    if kind == "deb":
        body = (f"#!/bin/sh\nwhile kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n"
                f"pkexec apt-get install -y '{package}' || xdg-open '{package}'\n"
                f"nohup /usr/bin/pelicula-converter >/dev/null 2>&1 &\n")
    elif kind == "tar":
        new_dir = work / "novo"
        new_dir.mkdir(exist_ok=True)
        import tarfile
        with tarfile.open(package, "r:gz") as t:
            t.extractall(new_dir, filter="data")
        src = next((p.parent for p in new_dir.rglob("PeliculaConverter") if p.is_file()), None)
        if src is None:
            raise UpdateError("bad-archive")
        body = (f"#!/bin/sh\nwhile kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n"
                f"cp -a '{src}/.' '{_app_dir()}/'\nnohup '{exe}' >/dev/null 2>&1 &\n")
    else:
        raise UpdateError("unsupported")
    script = work / "atualizar.sh"
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    subprocess.Popen(["/bin/sh", str(script)], start_new_session=True)
