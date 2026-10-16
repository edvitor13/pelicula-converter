# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller para o PeliculaConverter (Windows e Linux; macOS preparado).
#
# Gera uma pasta única (onedir), sem janela de console:
#     Windows: dist/PeliculaConverter/PeliculaConverter.exe
#     Linux:   dist/PeliculaConverter/PeliculaConverter
#
# Uso:  python -m PyInstaller --noconfirm --clean PeliculaConverter.spec
#
# O executável já traz o Python e todas as bibliotecas (PySide6, moderngl, numpy).
# Só o ffmpeg fica de fora: o app procura no PATH e em pastas comuns e, se não achar,
# oferece baixar de uma fonte confiável (Configurações > Dependências e atualizações).

import os
import sys

ROOT = SPECPATH  # noqa: F821  (variável injetada pelo PyInstaller)
NAME = "PeliculaConverter"

# O moderngl carrega o backend do contexto OpenGL dinamicamente; cada sistema usa um.
if sys.platform == "win32":
    GL_BACKENDS = ["glcontext.wgl"]
elif sys.platform == "darwin":
    GL_BACKENDS = ["glcontext.darwin"]
else:
    GL_BACKENDS = ["glcontext.x11", "glcontext.egl"]

# Ícone só no Windows (.ico). No Linux o ícone vem do tema / arquivo .desktop.
ICON = os.path.join(ROOT, "assets", "logo.ico") if sys.platform == "win32" else None

a = Analysis(
    [os.path.join(ROOT, "PeliculaConverter.pyw")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "assets"), "assets")],
    hiddenimports=["glcontext", *GL_BACKENDS],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
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
