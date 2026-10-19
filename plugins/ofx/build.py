"""Compila o plugin OpenFX do PeliculaConverter (PeliculaConverter.ofx.bundle).

    python plugins/ofx/build.py                 # → plugins/ofx/dist/PeliculaConverter.ofx.bundle
    python plugins/ofx/build.py --saida DIR     # outra pasta
    python plugins/ofx/build.py --gerar         # regenera plugins/ofx/generated antes (precisa do app)

Windows: MSVC (Visual Studio ou Build Tools com "Desenvolvimento para desktop com C++"); acha o
vcvars64.bat pelo vswhere quando o `cl` não está no PATH. Linux: g++. Sem dependências além do
compilador: os cabeçalhos do OpenFX estão em plugins/ofx/openfx (BSD-3, ver SOURCE.txt).

Ponto flutuante preciso (/fp:precise, sem -ffast-math): a cor tem que bater com o app.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OPENFX = HERE / "openfx"
BUNDLE = "PeliculaConverter.ofx.bundle"
BINARY = "PeliculaConverter.ofx"
ARCH = {"win32": "Win64", "linux": "Linux-x86-64", "darwin": "MacOS"}
SOURCES = [HERE / "src" / n for n in ("pc_core.cpp", "pc_capi.cpp", "pc_ofx.cpp")] + [
    OPENFX / "Support" / "Library" / n for n in (
        "ofxsCore.cpp", "ofxsImageEffect.cpp", "ofxsInteract.cpp", "ofxsLog.cpp", "ofxsMultiThread.cpp",
        "ofxsParams.cpp", "ofxsProperty.cpp", "ofxsPropertyValidation.cpp")]
INCLUDES = [OPENFX / "include", OPENFX / "Support" / "include", OPENFX / "Support" / "Library"]
MSVC_FLAGS = ["/nologo", "/O2", "/fp:precise", "/EHsc", "/MT", "/std:c++14", "/utf-8", "/W3", "/wd4996",
              "/wd4290", "/DNDEBUG", "/DWIN32", "/D_WINDOWS", "/D_CRT_SECURE_NO_WARNINGS"]
GCC_FLAGS = ["-O2", "-std=gnu++14",  # gnu: a biblioteca do OpenFX testa a macro `linux`
             "-fPIC", "-shared", "-pthread", "-fvisibility=hidden", "-DNDEBUG",
             "-Wno-deprecated-declarations", "-Wno-deprecated", "-static-libstdc++", "-static-libgcc",
             "-Wl,--exclude-libs,ALL"]  # a libstdc++ estática não pode vazar símbolos para o host


class BuildError(RuntimeError):
    pass


def app_version() -> str:
    text = (ROOT / "pelicula" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def source_hash() -> str:
    """Impressão digital de tudo o que entra no binário (testes reaproveitam a compilação)."""
    h = hashlib.sha256()
    files = sorted(SOURCES + list((HERE / "src").glob("*.h")) + list((HERE / "generated").glob("*.h"))
                   + [Path(__file__).resolve()])
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    h.update(sys.platform.encode())
    return h.hexdigest()[:16]


def _vcvars() -> Path | None:
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        out = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                              "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                             capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        p = Path(line.strip()) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if p.is_file():
            return p
    return None


def find_compiler() -> str | None:
    """Descrição do compilador disponível, ou None (os testes pulam)."""
    if sys.platform == "win32":
        if shutil.which("cl"):
            return "cl (PATH)"
        v = _vcvars()
        return f"MSVC ({v})" if v else None
    for cxx in (os.environ.get("CXX"), "g++", "c++", "clang++"):
        if cxx and shutil.which(cxx):
            return cxx
    return None


def _run(cmd, **kw) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)
    if res.returncode != 0:
        out = res.stdout + "\n" + res.stderr
        errors = [ln for ln in out.splitlines() if "error" in ln.lower()][:60]  # os avisos não escondem o erro
        raise BuildError(f"compilação falhou ({res.returncode}):\n" + "\n".join(errors) + "\n...\n" + out[-4000:])


def _compile_windows(out: Path, objdir: Path) -> None:
    args = MSVC_FLAGS + [f"/I{p}" for p in INCLUDES] + [str(s) for s in SOURCES] + [
        "/LD", f"/Fe:{out}", f"/Fo:{objdir}\\", "/link", "/DLL", "/INCREMENTAL:NO", f"/IMPLIB:{objdir / 'pc.lib'}"]
    if shutil.which("cl"):
        _run(["cl"] + args)
        return
    vc = _vcvars()
    if vc is None:
        raise BuildError("MSVC não encontrado: instale o Visual Studio Build Tools com \"Desenvolvimento para "
                         "desktop com C++\" ou rode num Developer Command Prompt.")
    bat = objdir / "compilar.bat"

    def q(a: str) -> str:
        return f'"{a}"' if (" " in a or "(" in a) else a
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    installer = Path(pf86) / "Microsoft Visual Studio" / "Installer"  # o vcvars procura o vswhere no PATH
    bat.write_text(f'@echo off\r\nset "PATH={installer};%PATH%"\r\ncall "{vc}" >nul || exit /b 1\r\n'
                   f'cl {" ".join(q(a) for a in args)}\r\n', encoding="mbcs" if os.name == "nt" else "utf-8")
    _run(["cmd", "/d", "/c", str(bat)])


def _compile_linux(out: Path) -> None:
    cxx = next(c for c in (os.environ.get("CXX"), "g++", "c++", "clang++") if c and shutil.which(c))
    _run([cxx] + GCC_FLAGS + [f"-I{p}" for p in INCLUDES] + [str(s) for s in SOURCES] + ["-o", str(out)])


def build(dest: str | Path | None = None, work: str | Path | None = None) -> Path:
    """Compila e monta o pacote em `dest` (padrão plugins/ofx/dist). Devolve o caminho do .ofx.bundle."""
    dest = Path(dest) if dest else HERE / "dist"
    bundle = dest / BUNDLE
    arch = ARCH.get(sys.platform, "Linux-x86-64")
    tmp = Path(work) if work else Path(tempfile.mkdtemp(prefix="pelicula_ofx_build_"))
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        binary = tmp / BINARY
        if sys.platform == "win32":
            _compile_windows(binary, tmp)
        else:
            _compile_linux(binary)
        if not binary.is_file():
            raise BuildError("o compilador não gerou o binário")
        if bundle.exists():
            shutil.rmtree(bundle)
        (bundle / "Contents" / arch).mkdir(parents=True)
        res = bundle / "Contents" / "Resources"
        res.mkdir(parents=True)
        shutil.copy2(binary, bundle / "Contents" / arch / BINARY)
        shutil.copy2(OPENFX / "LICENSE", res / "OpenFX-LICENSE.txt")  # BSD-3: aviso junto do binário
        (res / "pelicula-ofx.txt").write_text(
            f"versao={app_version()}\nplugin=com.peliculaconverter.pelicula\nfontes={source_hash()}\n",
            encoding="utf-8", newline="\n")
    finally:
        if work is None:
            shutil.rmtree(tmp, ignore_errors=True)
    return bundle


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compila o plugin OpenFX do PeliculaConverter.")
    ap.add_argument("--saida", help="pasta de saída (padrão plugins/ofx/dist)")
    ap.add_argument("--gerar", action="store_true", help="regenera plugins/ofx/generated antes de compilar")
    args = ap.parse_args(argv)
    if args.gerar:
        sys.path.insert(0, str(ROOT))
        from pelicula import ofx
        for f in ofx.generate():
            print("gerado:", f)
    comp = find_compiler()
    if comp is None:
        print("Nenhum compilador C++ encontrado (Windows: Visual Studio Build Tools; Linux: g++).", file=sys.stderr)
        return 2
    print("compilador:", comp)
    try:
        bundle = build(args.saida)
    except BuildError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("pacote:", bundle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
