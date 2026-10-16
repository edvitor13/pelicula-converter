# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller para o PeliculaConverter (Windows e Linux; macOS preparado).
#
# Gera uma pasta única (onedir) com DOIS executáveis que dividem as mesmas bibliotecas
# (Python, Qt, moderngl, numpy em _internal/, sem cópias duplicadas):
#     Windows: dist/PeliculaConverter/PeliculaConverter.exe   (janela, sem console)
#              dist/PeliculaConverter/pelicula-cli.exe        (modo de terminal, com console)
#     Linux:   dist/PeliculaConverter/PeliculaConverter
#              dist/PeliculaConverter/pelicula-cli
#
# Uso:  python -m PyInstaller --noconfirm --clean PeliculaConverter.spec
#
# Só o ffmpeg fica de fora: o app procura no PATH e em pastas comuns e, se não achar,
# oferece baixar de uma fonte confiável (Configurações > Dependências e atualizações).
# Os instaladores (.msi, .deb, .dmg) são montados a partir desta pasta: veja packaging/.

import os
import sys

ROOT = SPECPATH  # noqa: F821  (variável injetada pelo PyInstaller)
NAME = "PeliculaConverter"
CLI_NAME = "pelicula-cli"

# O moderngl carrega o backend do contexto OpenGL dinamicamente; cada sistema usa um.
if sys.platform == "win32":
    GL_BACKENDS = ["glcontext.wgl"]
elif sys.platform == "darwin":
    GL_BACKENDS = ["glcontext.darwin"]
else:
    GL_BACKENDS = ["glcontext.x11", "glcontext.egl"]

# Ícone só no Windows (.ico). No Linux o ícone vem do tema / arquivo .desktop.
ICON = os.path.join(ROOT, "assets", "logo.ico") if sys.platform == "win32" else None

# Dados lidos em tempo de execução. As pastas de traduções e de novidades são lidas pelo app
# com Path(__file__).parent / "locales" (ou "novidades"); entram só se existirem.
DATAS = [(os.path.join(ROOT, "assets"), "assets")]
for _sub in ("locales", "novidades"):
    _src = os.path.join(ROOT, "pelicula", _sub)
    if os.path.isdir(_src):
        DATAS.append((_src, os.path.join("pelicula", _sub)))

COMMON = dict(
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    hiddenimports=["glcontext", *GL_BACKENDS],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)

# ------------------------------------------------------------------ interface (janela)
a = Analysis([os.path.join(ROOT, "PeliculaConverter.pyw")], **COMMON)  # noqa: F821
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
)

# ------------------------------------------------------------------ modo de terminal (console)
a_cli = Analysis([os.path.join(ROOT, "packaging", "pelicula_cli.py")], **COMMON)  # noqa: F821
pyz_cli = PYZ(a_cli.pure)  # noqa: F821
exe_cli = EXE(  # noqa: F821
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name=CLI_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=ICON,
)

# Uma pasta só para os dois executáveis: o PyInstaller junta as listas e remove os repetidos.
coll = COLLECT(  # noqa: F821
    exe,
    exe_cli,
    a.binaries,
    a_cli.binaries,
    a.datas,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NAME,
)

# macOS: preparado, mas desativado por enquanto (o job do CI está com `if: false`).
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{NAME}.app",
        icon=None,
        bundle_identifier="com.peliculaconverter.app",
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.0.0"},
    )
