"""Atualizador: versões, escolha do pacote, conferência do SHA-256 e consulta ao GitHub (simulada)."""

import hashlib
import io
import json
import urllib.error

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
