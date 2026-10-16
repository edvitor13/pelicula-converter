"""Atualizador: versões, escolha do pacote, conferência do SHA-256 e consulta ao GitHub (simulada)."""

import hashlib
import io
import json
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

import pytest

from pelicula import __version__, updater


def release(names, tag="v9.0.0"):
    assets = {n: (f"https://example.invalid/{n}", 10) for n in names}
    return updater.Release(tag=tag, version=updater.parse_version(tag), name=tag, body="", url="u",
                           published="2026-10-16", assets=assets)


@pytest.mark.parametrize("text, expected", [("v1.2.3", (1, 2, 3)), ("1.10", (1, 10)), ("v2.0.0-beta", (2, 0, 0)),
                                            ("", (0,)), ("abc", (0,))])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


def test_is_newer():
    cur = updater.current_version()
    assert updater.is_newer(release([], "v" + ".".join(str(n) for n in (cur[0] + 1, 0, 0))))
    assert not updater.is_newer(release([], "v" + __version__))
    assert not updater.is_newer(release([], "v0.0.1"))


NAMES = ["PeliculaConverter-v9.0.0-windows-x64.msi", "PeliculaConverter-v9.0.0-windows-x64.zip",
         "PeliculaConverter-v9.0.0-linux-x64.deb", "PeliculaConverter-v9.0.0-linux-x64.tar.gz",
         "PeliculaConverter-v9.0.0-macos.dmg", "SHA256SUMS.txt"]


@pytest.mark.parametrize("kind, expected", [("msi", NAMES[0]), ("zip", NAMES[1]), ("deb", NAMES[2]), ("tar", NAMES[3]),
                                            ("dmg", NAMES[4])])
def test_pick_asset(kind, expected):
    assert updater.pick_asset(release(NAMES), kind)[0] == expected


def test_pick_asset_missing_or_source():
    assert updater.pick_asset(release(NAMES[1:]), "msi") is None
    assert updater.pick_asset(release(NAMES), "source") is None


def test_install_info_from_source():
    assert updater.install_info() == {"kind": "source"}
    assert not updater.can_auto_install("source")


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(routes):
    def opener(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        if url not in routes:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return FakeResponse(routes[url])
    return opener


def test_check_parses_api(monkeypatch):
    api = {"tag_name": "v9.0.0", "name": "9.0", "body": "notas", "html_url": "https://github.com/x",
           "published_at": "2026-10-16T10:00:00Z",
           "assets": [{"name": NAMES[0], "browser_download_url": "https://d/msi", "url": "https://api/msi", "size": 5}]}
    monkeypatch.delenv("PELICULA_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen({updater.API_LATEST: json.dumps(api).encode()}))
    rel = updater.check()
    assert rel.tag == "v9.0.0" and rel.version == (9, 0, 0)
    assert rel.assets[NAMES[0]] == ("https://d/msi", 5)
    assert rel.published == "2026-10-16" and rel.body == "notas"


def test_check_private_repo_404(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen({}))
    with pytest.raises(updater.UpdateError, match="no-public-release"):
        updater.check()


def test_check_offline(monkeypatch):
    def boom(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(updater.UpdateError, match="offline"):
        updater.check()


def test_download_verifies_checksum(monkeypatch, tmp_path):
    payload = b"conteudo do instalador" * 100
    good = hashlib.sha256(payload).hexdigest()
    rel = release(NAMES)
    name = NAMES[1]
    sums_url = rel.assets["SHA256SUMS.txt"][0]
    routes = {rel.assets[name][0]: payload, sums_url: f"{good}  {name}\n".encode()}
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen(routes))
    path = updater.download(rel, (name, rel.assets[name][0], len(payload)))
    assert open(path, "rb").read() == payload


def test_download_rejects_bad_checksum(monkeypatch):
    rel = release(NAMES)
    name = NAMES[1]
    routes = {rel.assets[name][0]: b"adulterado", rel.assets["SHA256SUMS.txt"][0]: f"{'0' * 64}  {name}\n".encode()}
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen(routes))
    with pytest.raises(updater.UpdateError, match="checksum-mismatch"):
        updater.download(rel, (name, rel.assets[name][0], 10))


def test_download_requires_checksums(monkeypatch):
    rel = release(NAMES[:-1])
    with pytest.raises(updater.UpdateError, match="no-checksums"):
        updater.download(rel, (NAMES[1], rel.assets[NAMES[1]][0], 10))


# ------------------------------------------------------------------ instalação no Windows
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="instalação por PowerShell só no Windows")

_SPAWN_CHILD = r"""
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from pelicula import updater
updater.spawn_powershell(Path(sys.argv[2]))
"""


@windows_only
def test_spawn_powershell_survives_windowless_parent(tmp_path):
    """O app empacotado não tem console. Com DETACHED_PROCESS o PowerShell morria antes de rodar o
    script (atualização 1.1.0 -> 1.2.0 não instalava nada). O script tem de rodar mesmo que o
    processo que o chamou (aqui um pythonw, sem console) termine na hora."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip("pythonw.exe não encontrado")
    marker = tmp_path / "rodou.txt"
    script = tmp_path / "teste.ps1"
    script.write_text(f"Start-Sleep -Milliseconds 300\nSet-Content -Path {updater._ps(marker)} -Value 'ok'\n",
                      encoding="utf-8-sig")
    child = tmp_path / "filho.py"
    child.write_text(_SPAWN_CHILD, encoding="utf-8")
    root = str(Path(updater.__file__).resolve().parents[1])
    subprocess.run([str(pythonw), str(child), root, str(script)], timeout=60, check=True)
    deadline = time.time() + 45
    while time.time() < deadline and not marker.exists():
        time.sleep(0.25)
    assert marker.exists(), "o PowerShell lançado pelo atualizador não rodou o script"


@windows_only
def test_install_msi_writes_logged_script(tmp_path, monkeypatch):
    work = tmp_path / "pasta d'Ana"  # apóstrofo no caminho precisa ser escapado
    work.mkdir()
    pkg = work / "PeliculaConverter-v9.0.0-windows-x64.msi"
    pkg.write_bytes(b"x")
    spawned = []
    monkeypatch.setattr(updater, "spawn_powershell", spawned.append)
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "App d'Ana" / "PeliculaConverter.exe"))
    updater.install(str(pkg), "msi")
    assert spawned == [work / "atualizar.ps1"]
    body = spawned[0].read_text(encoding="utf-8-sig")
    assert body.startswith("Start-Transcript -Path '") and "d''Ana" in body
    assert "msiexec.exe" in body and "'/passive'" in body and "'/l*v'" in body and "instalar.log" in body
    assert body.index("msiexec.exe") < body.index("Process]::Start(") < body.index("Stop-Transcript")
    assert "$psi.UseShellExecute = $false" in body  # reabre direto, sem o shell do Windows
    assert "App d''Ana" in body
    # Conferência de sintaxe pelo próprio PowerShell (sem executar).
    check = ("$e = $null; [System.Management.Automation.Language.Parser]::ParseFile("
             f"{updater._ps(spawned[0])}, [ref]$null, [ref]$e) | Out-Null; $e.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", out.stdout + out.stderr


def test_spawn_does_not_use_detached_process(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: calls.append(k))
    updater.spawn_powershell(Path("x.ps1"))
    flags = calls[0]["creationflags"]
    assert not flags & 0x00000008  # DETACHED_PROCESS derruba o PowerShell sem console
    assert calls[0]["stdin"] is subprocess.DEVNULL
