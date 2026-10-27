"""Componentes externos (pelicula/tools.py) e a extração segura de deps.py — sem rede.

Os downloads usam arquivos locais (`file://`) ou um servidor HTTP em 127.0.0.1. A pasta do app
(LOCALAPPDATA / XDG_DATA_HOME) aponta para uma pasta temporária em todos os testes: nada toca o
ffmpeg nem as ferramentas de verdade do usuário.
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import io
import json
import os
import re
import sys
import tarfile
import threading
import time
import types
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from pelicula import deps, modules, tools
from pelicula.i18n import _
from pelicula.tools import Artifact, Tool

EXE = ".exe" if sys.platform == "win32" else ""


@pytest.fixture(autouse=True)
def app_data(monkeypatch, tmp_path) -> Path:
    """Pasta do app (deps.app_data_dir) numa pasta temporária."""
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    assert deps.app_data_dir() == local / "PeliculaConverter"
    return deps.app_data_dir()


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "ferramentas"


# ------------------------------------------------------------------ pacotes de teste
def make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(zipfile.ZipInfo(name), data)
    return path


def make_tar(path: Path, files: dict[str, bytes], mode: str = "w:gz", links: dict[str, str] | None = None,
             hardlinks: dict[str, str] | None = None) -> Path:
    with tarfile.open(path, mode) as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            t.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            t.addfile(info)
        for name, target in (hardlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.LNKTYPE
            info.linkname = target
            t.addfile(info)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_tool(pkg: Path, version: str = "1.0.0", archive: str = "zip", executables=("bin/ferramenta" + EXE,),
              tool_id: str = "ferramenta_teste", url: str | None = None, digest: str | None = None,
              size: int | None = None, **kw) -> Tool:
    art = Artifact(platform=deps.platform_key(), version=version, url=url or pkg.as_uri(),
                   sha256=digest or sha(pkg), size=pkg.stat().st_size if size is None else size, archive=archive,
                   executables=tuple(executables))
    return Tool(id=tool_id, name="Ferramenta de teste", description="Só para os testes.", icon="box",
                homepage="https://example.org", license="MIT", license_url="https://example.org/licenca",
                artifacts=(art,), **kw)


def package(tmp_path: Path, version: str = "1.0.0", extra: dict[str, bytes] | None = None, name: str = "") -> Path:
    files = {f"bin/ferramenta{EXE}": f"binario {version}".encode(), "LEIA-ME.txt": b"ola"}
    files.update(extra or {})
    folder = tmp_path / "pacotes"
    folder.mkdir(exist_ok=True)
    return make_zip(folder / (name or f"ferramenta-{version}.zip"), files)


def leftovers(base: Path) -> list[str]:
    """Pastas temporárias que sobraram (instalação ou remoção)."""
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.name.startswith((tools.STAGING_PREFIX, tools.TRASH_PREFIX)))


# ------------------------------------------------------------------ registro
def test_registry_is_consistent():
    ids = [t.id for t in tools.TOOLS]
    assert ids[0] == "ffmpeg", "o ffmpeg é o primeiro item da página"
    assert len(ids) == len(set(ids))
    module_ids = {m.id for m in modules.MODULES}
    hex64 = re.compile(r"[0-9a-f]{64}")
    for t in tools.TOOLS:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", t.id), t.id
        assert t.kind in tools.KINDS
        assert t.name and t.description and t.icon and t.license
        assert t.homepage.startswith("https://") and t.license_url.startswith("https://")
        assert set(t.modules) <= module_ids, f"{t.id}: módulo desconhecido"
        assert t.backend in ("", "ffmpeg", "receita")
        assert (t.backend == "receita") == (t.recipe is not None), f"{t.id}: receita só com backend 'receita'"
        if t.kind == tools.SISTEMA:
            assert not t.artifacts and t.id in tools.DETECTORS, f"{t.id}: programa do sistema precisa de detector"
        if t.backend == "" and t.kind == tools.BAIXADO:
            assert t.artifacts, f"{t.id}: ferramenta baixada sem artefato"
        for what, lic, url in t.licenses:
            assert what and lic and url.startswith("https://"), f"{t.id}: licença de terceiros sem link https"
        if t.recipe is not None:
            check_recipe(t)
        platforms = [a.platform for a in t.artifacts]
        assert len(platforms) == len(set(platforms)), f"{t.id}: dois artefatos para o mesmo sistema"
        for a in t.artifacts:
            assert a.platform in tools.PLATFORMS
            assert a.url.startswith("https://"), f"{t.id}: só https"
            assert hex64.fullmatch(a.sha256), f"{t.id}: SHA-256 com 64 dígitos hexadecimais minúsculos"
            assert a.size > 0
            assert a.archive in tools.ARCHIVES and a.origin in tools.ORIGINS
            assert re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", a.version), a.version
            assert all(deps.safe_member(e) and "\\" not in e for e in a.executables)
            if a.origin == tools.CI:
                assert t.source_url.startswith("https://"), f"{t.id}: compilado no CI precisa do código-fonte"
                assert "github.com/edvitor13/pelicula-converter/releases/" in a.url
    for m in modules.MODULES:
        assert set(m.requires) <= set(ids), f"módulo {m.id} pede ferramenta desconhecida"


def check_recipe(t: tools.Tool) -> None:
    """Receita fixa tudo: commits, hashes e tamanhos; listas travadas com hash; nada fora de https."""
    hex64 = re.compile(r"[0-9a-f]{64}")
    rec = t.recipe
    assert t.kind == tools.BAIXADO and not t.artifacts
    assert re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", rec.version), rec.version
    assert set(rec.platforms()) <= set(tools.PLATFORMS) and rec.platforms()
    assert re.fullmatch(r"3\.\d+\.\d+", rec.env.python), "versão exata do Python"
    for key, rel in rec.env.requirements.items():
        text = tools.data_path(rel).read_text(encoding="utf-8")
        reqs = [ln for ln in text.splitlines() if ln and not ln.startswith((" ", "#"))]
        assert reqs and all("==" in ln for ln in reqs), f"{rel}: toda biblioteca com versão exata"
        assert text.count("--hash=sha256:") >= len(reqs), f"{rel}: toda biblioteca com hash"
        assert "git+" not in text and "http://" not in text
        assert rec.download_size.get(key, 0) > 0 and rec.disk_size.get(key, 0) > rec.download_size[key] // 2
        assert rec.env.size.get(key, 0) > 0
    for z in rec.code:
        assert z.url.startswith("https://codeload.github.com/") and re.search(r"/zip/[0-9a-f]{40}$", z.url), z.url
        assert tools.read_manifest(z.manifest)
    dests = [p.dest for p in rec.files]
    assert len(dests) == len(set(dests))
    for p in rec.files:
        assert p.url.startswith("https://") and hex64.fullmatch(p.sha256) and p.size > 0, p.dest
        assert deps.safe_member(p.dest) and "\\" not in p.dest and not p.dest.endswith(".pth.tar")
        assert "/resolve/" not in p.url or re.search(r"/resolve/[0-9a-f]{40}/", p.url), f"revisão fixa: {p.url}"
    assert rec.workdir and rec.check


def test_corridorkey_recipe_pins_the_layout_of_download_weights():
    rec = tools.CORRIDORKEY.recipe
    dests = {p.dest for p in rec.files}
    for need in ("codigo/weights/corridorkey_v2.safetensors", "codigo/weights/foundation_stats.safetensors",
                 "codigo/vfms/cradio/C-RADIOv4-SO400M/model.safetensors", "codigo/vfms/cradio/C-RADIOv4-SO400M/hf_model.py",
                 "codigo/vfms/moge/model.pt", "codigo/vfms/rvm/pretrain_rvm_small16_256_204031069.npz"):
        assert need in dests, need
    assert rec.check == ("scripts/smoke_test_runtime.py", "--load_model")
    assert rec.check_env == {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    assert rec.env.torch == "cu128" and tools.CORRIDORKEY.modules == ("recorte_ia",)
    assert {z.dest for z in rec.code} == {"codigo", "utils3d"} and any(z.package for z in rec.code)
    names = " ".join(_(n) for n in tools.CORRIDORKEY.notes)
    assert "CorridorKey" in names and "Corridor Digital" in names and "20" in names
    assert modules.get("recorte_ia").status == modules.BETA


def test_get_and_used_by(monkeypatch):
    assert tools.get("ffmpeg") is tools.FFMPEG
    with pytest.raises(KeyError):
        tools.get("nao_existe")
    assert tools.used_by(tools.DAVINCI_RESOLVE) == ["davinci"]
    fake = modules.Module("teste_ia", "Teste", "Usa o Resolve.", "sistema", requires=("davinci_resolve",))
    monkeypatch.setattr(modules, "MODULES", modules.MODULES + (fake,))
    assert tools.used_by(tools.DAVINCI_RESOLVE) == ["davinci", "teste_ia"]


def test_fmt_size_and_version_order():
    assert tools.fmt_size(0) == "0 B"
    assert tools.fmt_size(1536) == "1,5 KB"
    assert tools.fmt_size(150 * 1024 * 1024) == "150 MB"
    assert tools.fmt_size(int(1.25 * 1024 ** 3)) == "1,2 GB"
    assert tools.version_key("1.10.0") > tools.version_key("1.9.2") > tools.version_key("1.9")
    assert tools.version_key("2024-05-01") > tools.version_key("2023-12-31")


@pytest.mark.parametrize("url, ok", [
    ("https://github.com/a/b/releases/download/v1/x.zip", True),
    ("file:///tmp/x.zip", True),
    ("http://127.0.0.1:8000/x.zip", True),
    ("http://localhost/x.zip", True),
    ("http://example.com/x.zip", False),
    ("ftp://example.com/x.zip", False),
    ("https:///sem-servidor", False),
    ("x.zip", False),
])
def test_check_url(url, ok):
    if ok:
        tools.check_url(url)
    else:
        with pytest.raises(tools.ToolError):
            tools.check_url(url)


# ------------------------------------------------------------------ baixar e instalar
def test_download_installs_atomically_and_reports(tmp_path, root):
    pkg = package(tmp_path)
    tool = fake_tool(pkg)
    seen = []
    inst = tools.download(tool, lambda s, d, t: seen.append((s, d, t)), root=root)
    final = root / tool.id / "1.0.0"
    assert inst.path == final and inst.version == "1.0.0" and inst.sha256 == sha(pkg)
    assert (final / f"bin/ferramenta{EXE}").read_bytes() == b"binario 1.0.0"
    assert (final / "LEIA-ME.txt").read_bytes() == b"ola"
    assert not any(p.name.startswith("pacote-") for p in final.iterdir()), "o pacote baixado não fica na pasta"
    marker = json.loads((final / tools.MARKER).read_text(encoding="utf-8"))
    assert marker["id"] == tool.id and marker["versao"] == "1.0.0" and marker["sha256"] == sha(pkg)
    assert marker["url"] == pkg.as_uri() and marker["plataforma"] == deps.platform_key()
    stages = [s for s, _d, _t in seen]
    assert stages[0] == "Baixando Ferramenta de teste…"
    assert "Conferindo o SHA-256…" in stages and "Extraindo…" in stages and "Instalando…" in stages
    assert stages.index("Conferindo o SHA-256…") < stages.index("Extraindo…")
    assert seen[-1] == ("Pronto.", 1, 1)
    downloading = [(d, t) for s, d, t in seen if s.startswith("Baixando")]
    assert downloading[-1] == (pkg.stat().st_size, pkg.stat().st_size)
    assert leftovers(root / tool.id) == []
    assert [i.version for i in tools.installed(tool, root)] == ["1.0.0"]
    assert tools.executable(tool, root=root) == final / f"bin/ferramenta{EXE}"
    assert tools.executable(tool, "ferramenta", root=root) == final / f"bin/ferramenta{EXE}"
    assert tools.executable(tool, "outra", root=root) is None
    st = tools.status(tool, root)
    assert st.state == tools.INSTALADO and st.installed and st.managed and st.verified and st.downloadable
    assert st.version == "1.0.0" and st.available == "1.0.0" and not st.update_available
    assert st.size == tools.dir_size(final) > 0 and st.folder == str(final) and st.sha256 == sha(pkg)
    assert st.download_size == pkg.stat().st_size and st.origin == tools.OFICIAL


def test_sha_mismatch_is_rejected_before_extracting(tmp_path, root):
    pkg = package(tmp_path, extra={"../fora.txt": b"nao pode"})  # se extraísse, o caminho suspeito apareceria
    tool = fake_tool(pkg, digest="0" * 64)
    with pytest.raises(tools.ToolError, match="SHA-256"):
        tools.download(tool, root=root)
    assert tools.installed(tool, root) == []
    assert leftovers(root / tool.id) == []
    assert not (root / tool.id / "1.0.0").exists()
    assert tools.status(tool, root).state == tools.AUSENTE


def test_sha_mismatch_keeps_the_previous_install(tmp_path, root):
    v1 = package(tmp_path, "1.0.0")
    tools.download(fake_tool(v1), root=root)
    v2 = package(tmp_path, "2.0.0")
    bad = fake_tool(v2, version="2.0.0", digest=hashlib.sha256(b"outra coisa").hexdigest())
    with pytest.raises(tools.ToolError):
        tools.download(bad, root=root)
    assert [i.version for i in tools.installed(bad, root)] == ["1.0.0"]
    assert (root / bad.id / "1.0.0" / f"bin/ferramenta{EXE}").read_bytes() == b"binario 1.0.0"
    st = tools.status(bad, root)
    assert st.state == tools.DESATUALIZADO and st.update_available and st.version == "1.0.0"
    assert leftovers(root / bad.id) == []


@pytest.mark.parametrize("size_delta", [-10, +10])
def test_unexpected_size_is_rejected(tmp_path, root, size_delta):
    pkg = package(tmp_path)
    tool = fake_tool(pkg, size=pkg.stat().st_size + size_delta)
    with pytest.raises(tools.ToolError, match="tamanho"):
        tools.download(tool, root=root)
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []


def test_bigger_stream_than_expected_stops_early(tmp_path, root, monkeypatch):
    """Sem Content-Length, o download para assim que passa do tamanho fixado."""
    pkg = package(tmp_path)

    class Endless(io.RawIOBase):
        headers = {}
        read_calls = 0

        def read(self, n=-1):
            Endless.read_calls += 1
            return b"x" * 4096

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tools, "_open", lambda url, timeout=60.0: Endless())
    tool = fake_tool(pkg, size=10_000)
    with pytest.raises(tools.ToolError, match="tamanho"):
        tools.download(tool, root=root)
    assert Endless.read_calls <= 4
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []


def test_cancel_during_download_installs_nothing(tmp_path, root):
    pkg = package(tmp_path, extra={"grande.bin": os.urandom(3 * tools.CHUNK)})
    tool = fake_tool(pkg)
    cancel = threading.Event()

    def progress(stage, done, total):
        if done > 0 and stage.startswith("Baixando"):
            cancel.set()

    with pytest.raises(tools.Cancelled):
        tools.download(tool, progress, cancel, root=root)
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []


def test_update_replaces_the_old_version_unless_asked(tmp_path, root):
    v1, v2, v3 = (package(tmp_path, v) for v in ("1.0.0", "1.10.0", "1.9.0"))
    tools.download(fake_tool(v1, "1.0.0"), root=root)
    tools.download(fake_tool(v2, "1.10.0"), root=root)
    tool = fake_tool(v2, "1.10.0")
    assert [i.version for i in tools.installed(tool, root)] == ["1.10.0"]
    tools.download(fake_tool(v3, "1.9.0"), root=root, keep_old=True)
    assert [i.version for i in tools.installed(tool, root)] == ["1.10.0", "1.9.0"]  # a mais nova primeiro
    assert tools.current(fake_tool(v3, "1.9.0"), root).version == "1.9.0"  # a fixada no código vale
    assert tools.current(tool, root).version == "1.10.0"
    st = tools.status(tool, root)
    assert st.size == sum(i.size for i in tools.installed(tool, root))
    assert leftovers(root / tool.id) == []


def test_reinstall_same_version_swaps_the_folder(tmp_path, root):
    pkg = package(tmp_path)
    tool = fake_tool(pkg)
    tools.download(tool, root=root)
    final = root / tool.id / "1.0.0"
    (final / "lixo.txt").write_text("de antes", encoding="utf-8")
    tools.download(tool, root=root)
    assert not (final / "lixo.txt").exists(), "a pasta foi trocada inteira"
    assert (final / f"bin/ferramenta{EXE}").read_bytes() == b"binario 1.0.0"
    assert leftovers(root / tool.id) == []


@pytest.mark.parametrize("archive, mode", [("tar.gz", "w:gz"), ("tar.xz", "w:xz")])
def test_tar_packages(tmp_path, root, archive, mode):
    pkg = make_tar(tmp_path / f"f.{archive}", {f"ferramenta-2/bin/ferramenta{EXE}": b"tar", "ferramenta-2/x.txt": b"1"},
                   mode)
    tool = fake_tool(pkg, "2.0", archive=archive, executables=(f"ferramenta-2/bin/ferramenta{EXE}",))
    inst = tools.download(tool, root=root)
    exe = inst.path / f"ferramenta-2/bin/ferramenta{EXE}"
    assert exe.read_bytes() == b"tar"
    if sys.platform != "win32":
        assert os.access(exe, os.X_OK)


def test_single_file_artifact(tmp_path, root):
    pkg = tmp_path / f"ferramenta{EXE}"
    pkg.write_bytes(b"um executavel so")
    tool = fake_tool(pkg, "3.1", archive="arquivo", executables=(f"ferramenta{EXE}",))
    inst = tools.download(tool, root=root)
    exe = inst.path / f"ferramenta{EXE}"
    assert exe.read_bytes() == b"um executavel so"
    assert tools.executable(tool, root=root) == exe
    if sys.platform != "win32":
        assert os.access(exe, os.X_OK)


def test_missing_executable_installs_nothing(tmp_path, root):
    pkg = package(tmp_path)
    tool = fake_tool(pkg, executables=(f"bin/outro{EXE}",))
    with pytest.raises(tools.ToolError, match="não foi encontrado"):
        tools.download(tool, root=root)
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []


def test_no_artifact_for_this_system(tmp_path, root):
    pkg = package(tmp_path)
    other = "linux" if deps.platform_key() != "linux" else "win32"
    tool = fake_tool(pkg)
    tool = replace(tool, artifacts=(replace(tool.artifacts[0], platform=other),))
    st = tools.status(tool, root)
    assert st.state == tools.INDISPONIVEL and not st.downloadable
    with pytest.raises(tools.ToolError, match="ainda não tem download"):
        tools.download(tool, root=root)


def test_not_enough_disk_space(tmp_path, root, monkeypatch):
    pkg = package(tmp_path)
    tool = fake_tool(pkg)
    monkeypatch.setattr(tools.shutil, "disk_usage", lambda p: types.SimpleNamespace(total=1, used=0, free=1000))
    with pytest.raises(tools.ToolError, match="Espaço insuficiente"):
        tools.download(tool, root=root)
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []


def test_stale_temporary_folders_are_cleaned(tmp_path, root):
    pkg = package(tmp_path)
    tool = fake_tool(pkg)
    base = root / tool.id
    old = base / (tools.STAGING_PREFIX + "esquecida")
    recent = base / (tools.STAGING_PREFIX + "de-outro-processo")
    trash = base / (tools.TRASH_PREFIX + "lixo")
    for p in (old, recent, trash):
        (p / "sub").mkdir(parents=True)
        (p / "sub" / "f.bin").write_bytes(b"x" * 10)
    past = time.time() - tools.STALE_SECONDS - 60
    os.utime(old, (past, past))
    tools.download(tool, root=root)
    assert not old.exists() and not trash.exists()
    assert recent.exists(), "pasta recente pode ser um download de outra janela do app"


def test_folders_without_a_valid_marker_are_ignored(tmp_path, root):
    pkg = package(tmp_path)
    tool = fake_tool(pkg)
    (root / tool.id / "9.9").mkdir(parents=True)
    (root / tool.id / "8.0").mkdir()
    (root / tool.id / "8.0" / tools.MARKER).write_text(json.dumps({"id": "outra"}), encoding="utf-8")
    (root / tool.id / "7.0").mkdir()
    (root / tool.id / "7.0" / tools.MARKER).write_text("não é json", encoding="utf-8")
    assert tools.installed(tool, root) == []
    assert tools.status(tool, root).state == tools.AUSENTE


# ------------------------------------------------------------------ pacotes maliciosos
@pytest.mark.parametrize("bad", ["../fora.txt", "bin/../../fora.txt", "/absoluto.txt", "C:/unidade.txt",
                                 "C:unidade.txt", "..\\fora.txt", "bin\\..\\..\\fora.txt", "a/b:fluxo"])
def test_zip_with_path_traversal_is_rejected(tmp_path, root, bad):
    pkg = package(tmp_path, extra={bad: b"invasor"})
    tool = fake_tool(pkg)
    with pytest.raises(tools.ToolError, match="Caminho suspeito"):
        tools.download(tool, root=root)
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []
    assert not (tmp_path / "fora.txt").exists() and not (root / "fora.txt").exists()
    assert not (root / tool.id / "fora.txt").exists()


@pytest.mark.parametrize("files, links, hardlinks", [
    ({"../fora.txt": b"x"}, None, None),
    ({"/abs.txt": b"x"}, None, None),
    ({"ok.txt": b"x"}, {"link": "../../fora.txt"}, None),
    ({"ok.txt": b"x"}, {"link": "/etc/passwd"}, None),
    ({"ok.txt": b"x"}, None, {"duro": "../fora.txt"}),
])
def test_tar_with_path_traversal_or_outside_links_is_rejected(tmp_path, root, files, links, hardlinks):
    pkg = make_tar(tmp_path / "mau.tar.gz", files, links=links, hardlinks=hardlinks)
    tool = fake_tool(pkg, archive="tar.gz", executables=())
    with pytest.raises(tools.ToolError, match="Caminho suspeito"):
        tools.download(tool, root=root)
    assert tools.installed(tool, root) == [] and leftovers(root / tool.id) == []
    assert not (tmp_path / "fora.txt").exists()


def test_extract_archive_accepts_links_that_stay_inside(tmp_path):
    pkg = make_tar(tmp_path / "bom.tar", {"lib/libx.so.1": b"lib", "bin/tool": b"exe"}, mode="w",
                   links={"lib/libx.so": "libx.so.1", "bin/libx": "../lib/libx.so.1"})
    out = deps.extract_archive(pkg, tmp_path / "saida", "tar")
    assert (out / "bin/tool").read_bytes() == b"exe"
    assert (out / "lib/libx.so.1").read_bytes() == b"lib"
    with pytest.raises(ValueError):
        deps.extract_archive(pkg, tmp_path / "x", "rar")


@pytest.mark.parametrize("name, ok", [("bin/ffmpeg.exe", True), ("a/b/c.txt", True), ("pasta/", True),
                                      ("../x", False), ("a/../../x", False), ("/x", False), ("\\x", False),
                                      ("C:/x", False), ("C:x", False), ("a\\..\\..\\x", False), ("x:y", False),
                                      ("", False), ("a\x00b", False)])
def test_safe_member(name, ok):
    assert deps.safe_member(name) is ok
    assert deps._safe_member(name) is ok  # nome antigo continua valendo


# ------------------------------------------------------------------ servidor HTTP local
@pytest.fixture
def http_server(tmp_path):
    folder = tmp_path / "servidor"
    folder.mkdir()

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield folder, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_download_from_a_local_http_server(tmp_path, root, http_server):
    folder, base_url = http_server
    pkg = make_zip(folder / "ferramenta.zip", {f"bin/ferramenta{EXE}": b"http", "grande.bin": b"y" * (tools.CHUNK + 5)})
    tool = fake_tool(pkg, url=f"{base_url}/ferramenta.zip")
    totals = set()
    inst = tools.download(tool, lambda s, d, t: totals.add(t) if s.startswith("Baixando") else None, root=root)
    assert (inst.path / f"bin/ferramenta{EXE}").read_bytes() == b"http"
    assert totals == {pkg.stat().st_size}  # Content-Length do servidor
    missing = fake_tool(pkg, url=f"{base_url}/nao-existe.zip")
    with pytest.raises(tools.ToolError, match="Falha no download"):
        tools.download(replace(missing, id="outra_ferramenta"), root=root)
    assert leftovers(root / "outra_ferramenta") == []


# ------------------------------------------------------------------ remover e espaço em disco
def test_remove_everything_or_one_version(tmp_path, root):
    v1, v2 = package(tmp_path, "1.0"), package(tmp_path, "2.0")
    tools.download(fake_tool(v1, "1.0"), root=root)
    tool = fake_tool(v2, "2.0")
    tools.download(tool, root=root, keep_old=True)
    size_v1 = tools.dir_size(root / tool.id / "1.0")
    assert tools.remove(tool, root, version="1.0") == size_v1
    assert [i.version for i in tools.installed(tool, root)] == ["2.0"]
    total = tools.dir_size(root / tool.id)
    assert tools.remove(tool, root) == total > 0
    assert not (root / tool.id).exists()
    assert tools.remove(tool, root) == 0  # nada instalado: nada a fazer
    assert tools.status(tool, root).state == tools.AUSENTE
    assert leftovers(root) == []
    with pytest.raises(ValueError):
        tools.remove(tool, root, version="../fora")


def test_remove_reports_files_in_use(tmp_path, root, monkeypatch):
    pkg = package(tmp_path)
    tool = fake_tool(pkg)
    tools.download(tool, root=root)

    def in_use(path, parent):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(tools, "_move_aside", in_use)
    with pytest.raises(tools.ToolError, match="em uso"):
        tools.remove(tool, root)
    assert [i.version for i in tools.installed(tool, root)] == ["1.0.0"]  # nada mudou


def test_disk_usage_counts_tools_and_the_app_ffmpeg(tmp_path, root, app_data):
    assert tools.disk_usage(root) == 0
    pkg = package(tmp_path)
    tools.download(fake_tool(pkg), root=root)
    in_tools = tools.dir_size(root)
    assert tools.disk_usage(root) == in_tools > 0
    bin_dir = deps.ffmpeg_dir()
    bin_dir.mkdir(parents=True)
    (bin_dir / f"ffmpeg{EXE}").write_bytes(b"f" * 1000)
    (bin_dir / f"ffprobe{EXE}").write_bytes(b"p" * 500)
    assert tools.disk_usage(root) == in_tools + 1500
    assert tools.disk_usage(root, include_ffmpeg=False) == in_tools
    assert tools.disk_usage() == 1500  # pasta padrão (temporária neste teste) sem ferramentas


# ------------------------------------------------------------------ ffmpeg (fluxo de deps.py)
def _fake_ffmpeg_download(calls):
    def fake(progress=None, cancel=None):
        calls.append((progress, cancel))
        bin_dir = deps.ffmpeg_dir()
        bin_dir.mkdir(parents=True, exist_ok=True)
        for n in ("ffmpeg", "ffprobe"):
            (bin_dir / f"{n}{EXE}").write_bytes(b"x" * 100)
        (bin_dir.parent / "ORIGEM.txt").write_text(f"Baixado de: https://exemplo/ff.zip\nFonte: teste\n"
                                                  f"SHA-256: {'a' * 64}\n", encoding="utf-8")
        if progress:
            progress("Pronto.", 1, 1)
        return bin_dir
    return fake


def test_ffmpeg_entry_uses_deps_and_media(monkeypatch):
    from pelicula import media
    calls = []
    monkeypatch.setattr(deps, "download_ffmpeg", _fake_ffmpeg_download(calls))
    monkeypatch.setattr(deps, "inspect", lambda p: deps.FFmpegInfo(p, "ffmpeg version 7.1", (7, 1), None))
    monkeypatch.setattr(media, "ffmpeg", lambda: (_ for _ in ()).throw(RuntimeError("sem ffmpeg")))
    monkeypatch.setattr(media, "ffprobe", lambda: (_ for _ in ()).throw(RuntimeError("sem ffprobe")))
    st = tools.status(tools.FFMPEG)
    assert st.state in (tools.AUSENTE, tools.INDISPONIVEL) and not st.managed and st.size == 0
    if deps.platform_supported():
        assert st.state == tools.AUSENTE and st.downloadable and st.source_url.startswith("https://")
    cancel = threading.Event()
    inst = tools.download(tools.FFMPEG, cancel=cancel)
    assert len(calls) == 1 and calls[0][1] is cancel
    assert inst.path == deps.ffmpeg_dir().parent and inst.sha256 == "a" * 64 and inst.version == "7.1"
    exe = str(deps.ffmpeg_dir() / f"ffmpeg{EXE}")
    monkeypatch.setattr(media, "ffmpeg", lambda: exe)
    monkeypatch.setattr(media, "ffprobe", lambda: exe)
    st = tools.status(tools.FFMPEG, latest="8.0")
    assert st.state == tools.INSTALADO and st.managed and st.in_use_managed and st.verified
    assert st.version == "7.1" and st.update_available and st.available == "8.0"
    assert st.size == tools.dir_size(deps.ffmpeg_dir().parent) and st.notes == []
    assert st.where_note == "(baixado pelo app)"
    assert tools.status(tools.FFMPEG, latest="7.1").update_available is False
    assert tools.executable(tools.FFMPEG) == Path(exe)
    freed = tools.remove(tools.FFMPEG)
    assert freed > 0 and not deps.ffmpeg_dir().parent.exists()
    assert leftovers(deps.app_data_dir()) == []


def test_system_ffmpeg_is_not_managed(monkeypatch, tmp_path):
    from pelicula import media
    exe = tmp_path / "sistema" / f"ffmpeg{EXE}"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    monkeypatch.setattr(media, "ffmpeg", lambda: str(exe))
    monkeypatch.setattr(media, "ffprobe", lambda: str(exe))
    monkeypatch.setattr(deps, "inspect", lambda p: deps.FFmpegInfo(p, "ffmpeg version 6.0", (6, 0), None))
    st = tools.status(tools.FFMPEG)
    assert st.state == tools.DESATUALIZADO and st.update_available  # 6.0 < 7.0 (mínimo)
    assert not st.managed and not st.in_use_managed and not st.verified and st.size == 0
    assert st.folder == str(exe.parent) and st.where_note == "(do sistema)"
    assert tools.remove(tools.FFMPEG) == 0  # o do sistema nunca é apagado


def test_download_ffmpeg_end_to_end_without_network(monkeypatch, tmp_path):
    """deps.download_ffmpeg com uma fonte local: confere o SHA-256 publicado e extrai com extract_archive."""
    key = deps.platform_key()
    src_dir = tmp_path / "fonte"
    src_dir.mkdir()
    if key == "win32":
        pkg = make_zip(src_dir / "ffmpeg-release-essentials.zip",
                       {"ffmpeg-8.0-essentials/bin/ffmpeg.exe": b"F", "ffmpeg-8.0-essentials/bin/ffprobe.exe": b"P"})
        kind = "zip"
    else:
        pkg = make_tar(src_dir / "ffmpeg-master-latest-linux64-gpl.tar.xz",
                       {"ffmpeg-master/bin/ffmpeg": b"F", "ffmpeg-master/bin/ffprobe": b"P"}, mode="w:xz")
        kind = "tar"
    sums = src_dir / "checksums.sha256"
    sums.write_text(f"{sha(pkg)}  {pkg.name}\n", encoding="utf-8")
    monkeypatch.setitem(deps.SOURCES, key, dict(name="teste", page="https://example.org", version_url="",
                                                url=pkg.as_uri(), sha_url=sums.as_uri(), kind=kind))
    monkeypatch.setitem(deps.PLATFORM_ENABLED, key, True)
    dest = deps.download_ffmpeg()
    assert dest == deps.ffmpeg_dir()
    assert (dest / f"ffmpeg{EXE}").read_bytes() == b"F" and (dest / f"ffprobe{EXE}").read_bytes() == b"P"
    assert f"SHA-256: {sha(pkg)}" in (dest.parent / "ORIGEM.txt").read_text(encoding="utf-8")
    # SHA-256 publicado diferente: nada muda na instalação.
    sums.write_text(f"{'0' * 64}  {pkg.name}\n", encoding="utf-8")
    (dest / f"ffmpeg{EXE}").write_bytes(b"antigo")
    with pytest.raises(RuntimeError, match="SHA-256"):
        deps.download_ffmpeg()
    assert (dest / f"ffmpeg{EXE}").read_bytes() == b"antigo"


# ------------------------------------------------------------------ programas do sistema
def test_system_tools_cannot_be_downloaded_or_removed():
    with pytest.raises(tools.ToolError, match="programa do sistema"):
        tools.download(tools.DAVINCI_RESOLVE)
    with pytest.raises(tools.ToolError, match="programa do sistema"):
        tools.remove(tools.DAVINCI_RESOLVE)
    assert tools.installed(tools.DAVINCI_RESOLVE) == []


def test_resolve_detection_reuses_the_plugin_folders(monkeypatch, tmp_path):
    from pelicula import ofx, resolve
    exe = tmp_path / "Resolve" / ("Resolve.exe" if sys.platform == "win32" else "resolve")
    lut = tmp_path / "LUT"
    monkeypatch.setattr(tools, "resolve_executables", lambda: [exe])
    monkeypatch.setattr(resolve, "lut_dirs", lambda: [lut])
    monkeypatch.setattr(tools, "_win_uninstall_version", lambda pattern: ("19.1.4", ""))
    monkeypatch.setattr(ofx, "installed_version", lambda folder=None: None)
    st = tools.status(tools.DAVINCI_RESOLVE)
    assert st.state == tools.AUSENTE and not st.managed and not st.downloadable
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    st = tools.status(tools.DAVINCI_RESOLVE)
    assert st.state == tools.INSTALADO and st.version == "19.1.4" and st.folder == str(exe.parent)
    assert st.notes == ["Plugin OpenFX do PeliculaConverter: não instalado",
                        "DCTLs e LUTs do PeliculaConverter: não instalados"]
    # Só a pasta de LUTs (instalação fora do lugar padrão), com o plugin instalado.
    exe.unlink()
    (lut / resolve.PACKAGE_NAME).mkdir(parents=True)
    (lut / resolve.PACKAGE_NAME / resolve.MARKER).write_text("PeliculaConverter\nversao=1.3.0\n", encoding="utf-8")
    monkeypatch.setattr(ofx, "installed_version", lambda folder=None: "1.3")
    st = tools.status(tools.DAVINCI_RESOLVE)
    assert st.state == tools.INSTALADO and st.folder == str(lut)
    assert st.notes == ["Plugin OpenFX do PeliculaConverter: versão 1.3",
                        "DCTLs e LUTs do PeliculaConverter: versão 1.3.0"]


def test_detection_errors_mean_not_found(monkeypatch):
    def broken():
        raise OSError("sem acesso")

    monkeypatch.setitem(tools.DETECTORS, "davinci_resolve", broken)
    assert tools.status(tools.DAVINCI_RESOLVE).state == tools.AUSENTE
