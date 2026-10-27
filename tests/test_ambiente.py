"""Receita genérica de ambiente Python com o uv e instalação de receitas (pelicula/tools.py) — sem rede.

O uv é um falso (`tests/uv_falso.py`, que cria um venv de verdade com o Python dos testes); os
downloads vêm de `file://` ou de um servidor HTTP em 127.0.0.1 que aceita continuar (Range). A
pasta do app aponta para uma pasta temporária: nada toca as ferramentas de verdade do usuário.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from pelicula import deps, tools
from pelicula.tools import Piece, PythonEnv, Recipe, SourceZip, Tool

UV_FALSO = Path(__file__).with_name("uv_falso.py")
FAKE_UV = [sys.executable, str(UV_FALSO)]
KEY = deps.platform_key()
EXE = ".exe" if sys.platform == "win32" else ""


@pytest.fixture(autouse=True)
def app_data(monkeypatch, tmp_path) -> Path:
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    for var in ("PCTEST_FALHAR_UMA_VEZ", "PCTEST_DEMORAR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(tools, "uv_command", lambda *a, **k: list(FAKE_UV))
    return deps.app_data_dir()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file()}


def calls(cache: Path) -> list[str]:
    path = cache / "uv" / "chamadas.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def lock_file(path: Path, packages: dict[str, str]) -> Path:
    lines = ["# lista travada falsa"]
    for name, version in packages.items():
        lines.append(f"{name}=={version} --hash=sha256:{sha(f'{name}{version}'.encode())}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def env_run(py: Path, code: str) -> str:
    out = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=60,
                         env=tools.runtime_environ())
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


# ------------------------------------------------------------------ build_env
def test_two_environments_with_different_versions_never_touch_each_other(tmp_path):
    a = PythonEnv(python="3.12.15", requirements={KEY: str(lock_file(tmp_path / "a.txt", {"pacote_a": "1.0"}))},
                  torch="cu128")
    b = PythonEnv(python="3.13.9", requirements={KEY: str(lock_file(tmp_path / "b.txt", {"pacote_a": "2.0",
                                                                                         "pacote_b": "5.1"}))},
                  torch="cpu")
    root_a, root_b = tmp_path / "comp_a", tmp_path / "comp_b"
    py_a = tools.build_env(a, root_a / "1" / "venv", python_dir=root_a / "python", cache=root_a / "cache", uv=FAKE_UV)
    before = snapshot(root_a)
    py_b = tools.build_env(b, root_b / "1" / "venv", python_dir=root_b / "python", cache=root_b / "cache", uv=FAKE_UV)
    assert snapshot(root_a) == before, "montar o ambiente B mexeu no A"
    assert env_run(py_a, "import pacote_a, indice_torch; print(pacote_a.VERSAO, indice_torch.INDICE)") == "1.0 cu128"
    assert env_run(py_b, "import pacote_a, pacote_b; print(pacote_a.VERSAO, pacote_b.VERSAO)") == "2.0 5.1"
    assert (root_a / "python" / "cpython-3.12.15-falso").is_dir() and not (root_a / "python" / "cpython-3.13.9-falso").exists()
    assert (root_b / "python" / "cpython-3.13.9-falso").is_dir() and not (root_b / "python" / "cpython-3.12.15-falso").exists()
    # cada ambiente aponta para o Python base da própria pasta (fora da pasta do ambiente)
    assert Path((root_a / "1" / "venv" / "base.txt").read_text()).is_relative_to(root_a / "python")
    assert Path((root_b / "1" / "venv" / "base.txt").read_text()).is_relative_to(root_b / "python")
    log = "\n".join(calls(root_a / "cache"))
    assert "--relocatable" in log and "--torch-backend cu128" in log and "--only-binary :all:" in log
    assert "--no-bin" in log and ("--no-registry" in log) == (sys.platform == "win32")


def test_libraries_resume_from_the_cache_after_an_interruption(tmp_path, monkeypatch):
    spec = PythonEnv(python="3.12.15", requirements={KEY: str(lock_file(tmp_path / "l.txt", {
        "pacote_a": "1.0", "pacote_b": "1.0", "pacote_c": "1.0"}))})
    root = tmp_path / "comp"
    monkeypatch.setenv("PCTEST_FALHAR_UMA_VEZ", str(tmp_path / "caiu.txt"))
    with pytest.raises(tools.ToolError) as err:
        tools.build_env(spec, root / "v1" / "venv", python_dir=root / "python", cache=root / "cache", uv=FAKE_UV)
    assert "internet" in str(err.value) and "Failed to fetch" in str(err.value)
    assert [p.name for p in (root / "cache" / "uv" / "wheels").iterdir()] == ["pacote_a-1.0.whl"]
    # a limpeza de pastas esquecidas (12 h) não mexe no cache, por mais velho que ele seja
    old = time.time() - 3 * 24 * 3600
    os.utime(root / "cache", (old, old))
    tools._clean_stale(root)
    assert (root / "cache" / "uv" / "wheels" / "pacote_a-1.0.whl").exists()
    py = tools.build_env(spec, root / "v2" / "venv", python_dir=root / "python", cache=root / "cache", uv=FAKE_UV)
    out = [line for line in calls(root / "cache")]
    assert env_run(py, "import pacote_a, pacote_b, pacote_c; print('ok')") == "ok"
    assert sorted(p.name for p in (root / "cache" / "uv" / "wheels").iterdir()) == [
        "pacote_a-1.0.whl", "pacote_b-1.0.whl", "pacote_c-1.0.whl"]
    assert sum("pip install" in c for c in out) == 2


def test_cancel_stops_uv_and_its_children_quickly(tmp_path, monkeypatch):
    spec = PythonEnv(python="3.12.15", requirements={KEY: str(lock_file(tmp_path / "l.txt", {"pacote_a": "1.0"}))})
    monkeypatch.setenv("PCTEST_DEMORAR", "60")
    cancel = threading.Event()
    stages = []

    def progress(stage, done, total):
        stages.append(stage)
        if "bibliotecas" in stage:
            threading.Timer(0.5, cancel.set).start()

    t0 = time.monotonic()
    with pytest.raises(tools.Cancelled):
        tools.build_env(spec, tmp_path / "c" / "venv", python_dir=tmp_path / "c" / "python", cache=tmp_path / "c" / "cache",
                        uv=FAKE_UV, progress=progress, cancel=cancel)
    assert time.monotonic() - t0 < 40, "cancelar precisa encerrar o uv na hora"
    assert any("Python 3.12.15" in s for s in stages)


def test_missing_lock_for_this_system_is_an_error(tmp_path):
    spec = PythonEnv(python="3.12.15", requirements={"outro": "x.txt"})
    with pytest.raises(tools.ToolError):
        tools.build_env(spec, tmp_path / "v", python_dir=tmp_path / "p", cache=tmp_path / "c", uv=FAKE_UV)


def test_environment_variables_of_the_user_do_not_leak(monkeypatch):
    monkeypatch.setenv("UV_INDEX_URL", "https://mirror.invalid/simple")
    monkeypatch.setenv("PIP_INDEX_URL", "https://mirror.invalid/simple")
    monkeypatch.setenv("PYTHONPATH", "C:/outro")
    monkeypatch.setenv("VIRTUAL_ENV", "C:/outro/venv")
    env = tools.uv_environ(Path("cache"), Path("python"))
    assert not {"UV_INDEX_URL", "PIP_INDEX_URL", "PYTHONPATH", "VIRTUAL_ENV"} & set(env)
    assert env["UV_NO_CONFIG"] == "1" and env["UV_CACHE_DIR"].endswith("uv")
    run = tools.runtime_environ({"HF_HUB_OFFLINE": "1"}, ["C:/ffmpeg/bin"])
    assert run["HF_HUB_OFFLINE"] == "1" and run["PYTHONNOUSERSITE"] == "1"
    assert run["PATH"].split(os.pathsep)[0] == "C:/ffmpeg/bin" and "PYTHONPATH" not in run
    assert Path(run["HF_HOME"]).is_relative_to(deps.app_data_dir())


def test_run_process_reads_lines_and_carriage_returns(tmp_path):
    seen = []
    res = tools.run_process([sys.executable, "-c", "import sys; sys.stdout.write('a\\rb\\nc\\r\\n'); print('fim')"],
                            on_line=seen.append, env=tools.runtime_environ())
    assert res.returncode == 0 and seen == ["a", "b", "c", "fim"] and res.tail(2) == "c\nfim"
    with pytest.raises(tools.ToolError):
        tools.run_process([str(tmp_path / "nao-existe" / f"programa{EXE}")])


# ------------------------------------------------------------------ download retomável
class RangeServer(http.server.ThreadingHTTPServer):
    def __init__(self, files: dict[str, bytes]):
        super().__init__(("127.0.0.1", 0), RangeHandler)
        self.files = files
        self.ranges: list[str | None] = []
        self.cut_after: int | None = None
        self.accept_range = True

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class RangeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        srv = self.server
        data = srv.files.get(self.path)
        if data is None:
            self.send_error(404)
            return
        rng = self.headers.get("Range")
        srv.ranges.append(rng)
        if rng and srv.accept_range:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(data):
                self.send_error(416)
                return
            body = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if srv.cut_after is not None:
            body, srv.cut_after = body[:srv.cut_after], None  # a conexão cai no meio
        for i in range(0, len(body), 16384):  # em pedaços, como um servidor de verdade
            self.wfile.write(body[i:i + 16384])

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = RangeServer({"/modelo.bin": os.urandom(300_000)})
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_download_resumes_where_it_stopped(tmp_path, server):
    data = server.files["/modelo.bin"]
    dest = tmp_path / "cache" / sha(data)
    server.cut_after = 120_000
    with pytest.raises(tools.ToolError) as err:
        tools.fetch_file(server.base + "/modelo.bin", dest, sha(data), len(data))
    assert "continua de onde parou" in str(err.value)
    part = dest.with_name(dest.name + ".part")
    assert part.stat().st_size == 120_000 and not dest.exists()
    seen = []
    tools.fetch_file(server.base + "/modelo.bin", dest, sha(data), len(data), progress=lambda s, d, t: seen.append(d))
    assert dest.read_bytes() == data and not part.exists()
    assert server.ranges == [None, "bytes=120000-"]
    assert seen[0] == 120_000 and seen[-1] == len(data)
    # já baixado e conferido: não vai à rede de novo
    tools.fetch_file(server.base + "/modelo.bin", dest, sha(data), len(data))
    assert len(server.ranges) == 2


def test_server_without_range_starts_over_and_still_checks(tmp_path, server):
    data = server.files["/modelo.bin"]
    dest = tmp_path / sha(data)
    dest.with_name(dest.name + ".part").write_bytes(data[:5000])
    server.accept_range = False
    tools.fetch_file(server.base + "/modelo.bin", dest, sha(data), len(data))
    assert dest.read_bytes() == data


def test_download_with_wrong_hash_is_rejected_and_discarded(tmp_path, server):
    data = server.files["/modelo.bin"]
    dest = tmp_path / "x.bin"
    with pytest.raises(tools.ToolError) as err:
        tools.fetch_file(server.base + "/modelo.bin", dest, "0" * 64, len(data))
    assert "SHA-256" in str(err.value)
    assert not dest.exists() and not dest.with_name("x.bin.part").exists()
    with pytest.raises(tools.ToolError):
        tools.fetch_file(server.base + "/modelo.bin", dest, sha(data), len(data) + 1)
    assert not dest.exists()


def test_download_cancel_keeps_the_partial_file(tmp_path, server):
    data = server.files["/modelo.bin"]
    dest = tmp_path / "x.bin"
    cancel = threading.Event()

    def progress(stage, done, total):
        if done > 0:
            cancel.set()

    with pytest.raises(tools.Cancelled):
        tools.fetch_file(server.base + "/modelo.bin", dest, sha(data), len(data), progress=progress, cancel=cancel)
    assert dest.with_name("x.bin.part").exists() and not dest.exists()


# ------------------------------------------------------------------ código conferido arquivo por arquivo
def make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def manifest(path: Path, files: dict[str, bytes]) -> Path:
    path.write_text("# manifesto de teste\n" + "".join(f"{sha(d)}  {n}\n" for n, d in files.items()), encoding="utf-8")
    return path


CODE = {"infer.py": b"print('infer')\n", "pacote/mod.py": b"X = 1\n"}


def test_source_zip_is_checked_file_by_file(tmp_path):
    z = make_zip(tmp_path / "c.zip", {f"repo-abc/{k}": v for k, v in CODE.items()} | {"repo-abc/rodar.bat": b"x"})
    src = SourceZip(z.as_uri(), str(manifest(tmp_path / "m.sha256", CODE)), dest="codigo")
    out = tools.install_source(src, tmp_path / "dest", tmp_path / "work")
    assert (out / "infer.py").read_bytes() == CODE["infer.py"] and (out / "pacote" / "mod.py").exists()
    assert not (out / "rodar.bat").exists(), "fora do manifesto não é instalado"
    tampered = make_zip(tmp_path / "t.zip", {"repo-abc/infer.py": b"print('outro')\n", "repo-abc/pacote/mod.py": b"X = 1\n"})
    with pytest.raises(tools.ToolError) as err:
        tools.install_source(replace(src, url=tampered.as_uri()), tmp_path / "d2", tmp_path / "work")
    assert "infer.py" in str(err.value)
    short = make_zip(tmp_path / "s.zip", {"repo-abc/infer.py": CODE["infer.py"]})
    with pytest.raises(tools.ToolError) as err:
        tools.install_source(replace(src, url=short.as_uri()), tmp_path / "d3", tmp_path / "work")
    assert "pacote/mod.py" in str(err.value)
    evil = make_zip(tmp_path / "e.zip", {"repo-abc/../../fora.py": b"x"})
    with pytest.raises(tools.ToolError):
        tools.install_source(replace(src, url=evil.as_uri()), tmp_path / "d4", tmp_path / "work")


def test_real_manifests_are_valid():
    for rel in ("corridorkey/codigo-485f5e9.sha256", "corridorkey/utils3d-83bfa5b.sha256"):
        m = tools.read_manifest(rel)
        assert m and all(len(h) == 64 for h in m.values())
    code = tools.read_manifest("corridorkey/codigo-485f5e9.sha256")
    assert "infer.py" in code and "scripts/smoke_test_runtime.py" in code
    assert not any(p.endswith((".bat", ".sh")) for p in code), "os .bat/.sh deles não são instalados"


# ------------------------------------------------------------------ receita inteira (código + ambiente + modelos)
CHECK_OK = b"""import os, pathlib, sys
assert os.environ.get("PCTEST_OFFLINE") == "1"
import pacote_a, pacote_local
assert pathlib.Path("modelos/m1.bin").read_bytes() == b"pesos-1" * 1000
assert pathlib.Path("modelos/sub/m2.bin").exists()
print("tudo certo", pacote_a.VERSAO, pacote_local.VERSAO)
"""


def fake_recipe(tmp_path: Path, check: bytes = CHECK_OK, tool_id: str = "falso", version: str = "1.0-abc",
                files: dict[str, bytes] | None = None) -> Tool:
    tmp_path.mkdir(parents=True, exist_ok=True)
    code = {"infer.py": b"print('infer')\n", "verificar.py": check}
    code_zip = make_zip(tmp_path / f"{tool_id}-codigo.zip",
                        {f"proj-abc/{k}": v for k, v in code.items()} | {"proj-abc/rodar.sh": b"x"})
    pkg = {"pacote_local/__init__.py": b"VERSAO = 'local'\n"}
    pkg_zip = make_zip(tmp_path / f"{tool_id}-pacote.zip", {f"lib-abc/{k}": v for k, v in pkg.items()})
    models = files or {"codigo/modelos/m1.bin": b"pesos-1" * 1000, "codigo/modelos/sub/m2.bin": b"pesos-2" * 500}
    pieces = []
    for i, (dest, data) in enumerate(models.items()):
        f = tmp_path / f"{tool_id}-modelo{i}.bin"
        f.write_bytes(data)
        pieces.append(Piece(f.as_uri(), sha(data), len(data), dest))
    rec = Recipe(
        version=version,
        env=PythonEnv(python="3.12.15", requirements={KEY: str(lock_file(tmp_path / f"{tool_id}-lock.txt",
                                                                         {"pacote_a": "1.0"}))}, torch="cpu"),
        code=(SourceZip(code_zip.as_uri(), str(manifest(tmp_path / f"{tool_id}-c.sha256", code)), dest="codigo"),
              SourceZip(pkg_zip.as_uri(), str(manifest(tmp_path / f"{tool_id}-p.sha256", pkg)), dest="pacote_local_src",
                        package=True)),
        files=tuple(pieces), workdir="codigo", check=("verificar.py",), check_env={"PCTEST_OFFLINE": "1"},
        check_timeout=120, download_size={KEY: 20_000}, disk_size={KEY: 50_000})
    return Tool(id=tool_id, name="Falso", description="Só para os testes.", icon="box",
                homepage="https://example.org", license="MIT", license_url="https://example.org/licenca",
                backend="receita", recipe=rec)


def test_recipe_installs_atomically_and_still_runs_after_the_final_move(tmp_path):
    tool = fake_recipe(tmp_path)
    root = tmp_path / "ferramentas"
    stages = []
    inst = tools.download(tool, progress=lambda s, d, t: stages.append(s), root=root)
    base = root / tool.id
    final = base / "1.0-abc"
    assert inst.path == final and inst.version == "1.0-abc"
    assert sorted(p.name for p in base.iterdir()) == ["1.0-abc", "python"], "sem pasta temporária nem cache no fim"
    marker = json.loads((final / tools.MARKER).read_text(encoding="utf-8"))
    assert marker["id"] == "falso" and marker["python"] == "3.12.15" and len(marker["arquivos"]) == 2
    assert marker["sha256"] == tools.recipe_fingerprint(tool)
    assert (final / "codigo" / "modelos" / "m1.bin").exists() and not (final / "codigo" / "rodar.sh").exists()
    # o ambiente foi montado na pasta temporária e continua rodando na pasta final
    py = tools.executable(tool, root=root)
    assert py == tools.env_python(final / "venv")
    assert Path(env_run(py, "import sys; print(sys.prefix)")).resolve() == (final / "venv").resolve()
    assert env_run(py, "import pacote_a, pacote_local; print(pacote_a.VERSAO, pacote_local.VERSAO)") == "1.0 local"
    assert any("Testando" in s for s in stages) and any("modelos" in s for s in stages)
    st = tools.status(tool, root=root)
    assert st.state == tools.INSTALADO and st.verified and st.managed and st.size > 0 and not st.partial
    assert tools.run_check(tool, final).lines[-1].startswith("tudo certo 1.0 local")
    assert "tudo certo" in tools.test_installed(tool, root=root)
    assert tools.remove(tool, root=root) > 0 and not base.exists()


def test_failed_check_installs_nothing_and_keeps_the_downloads(tmp_path):
    bad = b"import sys\nprint('RuntimeError: --load_model requires CUDA (driver)')\nsys.exit(1)\n"
    tool = fake_recipe(tmp_path, check=bad)
    root = tmp_path / "ferramentas"
    with pytest.raises(tools.ToolError) as err:
        tools.download(tool, root=root)
    assert "driver da NVIDIA" in str(err.value)
    base = root / tool.id
    assert not (base / "1.0-abc").exists() and not list(base.glob(".novo-*"))
    cached = sorted(p.name for p in (base / "cache" / "arquivos").iterdir())
    assert cached == sorted(p.sha256 for p in tool.recipe.files), "os modelos baixados ficam para a próxima vez"
    st = tools.status(tool, root=root)
    assert st.state == tools.AUSENTE and st.partial > 0 and st.managed, "dá para remover o download parcial"
    # o download parcial continua: na próxima vez os modelos vêm do cache (o arquivo de origem nem existe mais)
    good = fake_recipe(tmp_path / "outra", tool_id="falso")
    for p in good.recipe.files:
        Path(urllib.request.url2pathname(urllib.parse.urlparse(p.url).path)).unlink()
    inst = tools.download(good, root=root)
    assert (inst.path / "codigo" / "modelos" / "m1.bin").exists()


def test_cancel_during_the_models_installs_nothing(tmp_path):
    tool = fake_recipe(tmp_path)
    root = tmp_path / "ferramentas"
    cancel = threading.Event()

    def progress(stage, done, total):
        if "modelos" in stage and done:
            cancel.set()

    with pytest.raises(tools.Cancelled):
        tools.download(tool, progress=progress, cancel=cancel, root=root)
    base = root / tool.id
    assert not (base / "1.0-abc").exists() and not list(base.glob(".novo-*")) and (base / "cache").is_dir()


def test_leftovers_of_a_closed_app_are_removed_right_away(tmp_path):
    root = tmp_path / "ferramentas"
    base = root / "falso"
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        for name, pid in ((".novo-morto", done.stdout.strip()), (".novo-vivo", str(sleeper.pid)), (".novo-sem-dono", None)):
            (base / name / "conteudo" / "venv").mkdir(parents=True)
            (base / name / "conteudo" / "venv" / "grande.bin").write_bytes(b"x" * 1000)
            if pid:
                (base / name / tools.OWNER).write_text(pid, encoding="ascii")
        assert not tools._process_alive(int(done.stdout)) and tools._process_alive(sleeper.pid)
        tools.download(fake_recipe(tmp_path), root=root)
        left = sorted(p.name for p in base.iterdir() if p.name.startswith("."))
        assert left == [".novo-sem-dono", ".novo-vivo"], "só a do app que não existe mais sai na hora"
    finally:
        sleeper.kill()
        sleeper.wait()


def test_reinstall_and_update_replace_the_old_version(tmp_path):
    root = tmp_path / "ferramentas"
    tools.download(fake_recipe(tmp_path), root=root)
    tools.download(fake_recipe(tmp_path / "a"), root=root)  # mesma versão de novo
    newer = fake_recipe(tmp_path / "b", version="1.1-def")
    tools.download(newer, root=root)
    assert [i.version for i in tools.installed(newer, root)] == ["1.1-def"]
    assert tools.status(newer, root=root).state == tools.INSTALADO


def test_requirements_block_the_download(tmp_path, monkeypatch):
    tool = fake_recipe(tmp_path)
    monkeypatch.setitem(tools.REQUIREMENTS, tool.id, lambda: ["Sem placa de vídeo compatível."])
    st = tools.status(tool, root=tmp_path / "f")
    assert st.blocked == ["Sem placa de vídeo compatível."] and not st.downloadable
    with pytest.raises(tools.ToolError) as err:
        tools.download(tool, root=tmp_path / "f")
    assert "Sem placa" in str(err.value)
    monkeypatch.setitem(tools.REQUIREMENTS, tool.id, lambda: [])
    big = replace(tool, recipe=replace(tool.recipe, disk_size={KEY: 1 << 60}))
    st = tools.status(big, root=tmp_path / "f")
    assert st.blocked and "Espaço insuficiente" in st.blocked[0]


def test_recipe_not_available_on_other_systems(tmp_path):
    tool = fake_recipe(tmp_path)
    other = replace(tool, recipe=replace(tool.recipe, env=replace(tool.recipe.env, requirements={"outro": "x"})))
    st = tools.status(other, root=tmp_path / "f")
    assert st.state == tools.INDISPONIVEL and not st.downloadable
    with pytest.raises(tools.ToolError):
        tools.download(other, root=tmp_path / "f")


REAL_UV_COMMAND = tools.uv_command  # guardado na importação, antes de a fixture trocar pelo uv falso


def test_uv_is_downloaded_once_and_other_versions_are_kept(tmp_path, monkeypatch):
    def uv_tool(version: str) -> tools.Tool:
        pkg = make_zip(tmp_path / f"uv-{version}.zip", {f"uv{EXE}": version.encode()})
        art = tools.Artifact(KEY, version, pkg.as_uri(), sha(pkg.read_bytes()), pkg.stat().st_size, "zip",
                             (f"uv{EXE}",))
        return replace(tools.UV, artifacts=(art,))

    root = tmp_path / "ferramentas"
    monkeypatch.setattr(tools, "UV", uv_tool("9.9.9"))
    monkeypatch.setattr(tools, "UV_VERSION", "9.9.9")
    cmd = REAL_UV_COMMAND(root=root)
    assert Path(cmd[0]) == root / "uv" / "9.9.9" / f"uv{EXE}"
    mtime = Path(cmd[0]).stat().st_mtime_ns
    assert REAL_UV_COMMAND(root=root) == cmd and Path(cmd[0]).stat().st_mtime_ns == mtime, "baixado uma vez só"
    # outro ambiente pede outra versão: as duas ficam (cada ambiente usa a versão com que foi testado)
    monkeypatch.setattr(tools, "UV", uv_tool("10.0.0"))
    monkeypatch.setattr(tools, "UV_VERSION", "10.0.0")
    cmd2 = REAL_UV_COMMAND(root=root)
    assert Path(cmd2[0]) == root / "uv" / "10.0.0" / f"uv{EXE}" and Path(cmd[0]).exists()
