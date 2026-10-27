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
# oferece baixar de uma fonte confiável (Configurações > Componentes).
# Os instaladores (.msi, .deb, .dmg) são montados a partir desta pasta: veja packaging/.

import os
import re
import sys

ROOT = SPECPATH  # noqa: F821  (variável injetada pelo PyInstaller)
NAME = "PeliculaConverter"
CLI_NAME = "pelicula-cli"

# Versão lida do código (sem importar o pacote), usada nos metadados dos executáveis.
with open(os.path.join(ROOT, "pelicula", "__init__.py"), encoding="utf-8") as _f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _f.read()).group(1)

# O moderngl carrega o backend do contexto OpenGL dinamicamente; cada sistema usa um.
if sys.platform == "win32":
    GL_BACKENDS = ["glcontext.wgl"]
elif sys.platform == "darwin":
    GL_BACKENDS = ["glcontext.darwin"]
else:
    GL_BACKENDS = ["glcontext.x11", "glcontext.egl"]

# Páginas de Configurações: ui/settings_dialog.py as carrega com importlib (pelo nome), e o PyInstaller
# não enxerga esse import sozinho. Sem isto o executável abre Configurações sem as páginas (e o aviso
# de "ffmpeg ausente", que abre a página Componentes, falha).
SETTINGS_PAGES = sorted(
    "pelicula.ui.pages." + _f[:-3] for _f in os.listdir(os.path.join(ROOT, "pelicula", "ui", "pages"))
    if _f.endswith(".py") and not _f.startswith("_"))

# Ícone só no Windows (.ico). No Linux o ícone vem do tema / arquivo .desktop.
ICON = os.path.join(ROOT, "assets", "logo.ico") if sys.platform == "win32" else None



def version_info(description, filename):
    """Metadados do .exe (Propriedades > Detalhes). A SignPath exige nome e versão do produto iguais
    em todos os arquivos assinados de uma mesma build."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3])
    nums = nums + (0,) * (4 - len(nums))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                          subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("041604B0", [  # pt-BR, Unicode
                StringStruct("CompanyName", "Vitor Gabriel"),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", filename.rsplit(".", 1)[0]),
                StringStruct("LegalCopyright", "© 2026 Vitor Gabriel. Licença MIT."),
                StringStruct("OriginalFilename", filename),
                StringStruct("ProductName", NAME),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )


# Dados lidos em tempo de execução. As pastas de traduções, de novidades e de dados (listas
# travadas e manifestos dos componentes de IA) são lidas pelo app com Path(__file__).parent /
# "locales" (ou "novidades", "data"); entram só se existirem.
DATAS = [(os.path.join(ROOT, "assets"), "assets")]
for _sub in ("locales", "novidades", "data"):
    _src = os.path.join(ROOT, "pelicula", _sub)
    if os.path.isdir(_src):
        DATAS.append((_src, os.path.join("pelicula", _sub)))

# Plugin OpenFX do DaVinci Resolve (funciona no gratuito), já compilado por plugins/ofx/build.py:
# vai em _internal/ofx/PeliculaConverter.ofx.bundle e a janela do Resolve só copia para a pasta do
# OpenFX. Sem ele o app funciona e a janela explica como compilar; o CI define
# PELICULA_EXIGIR_OFX=1 para que um pacote nunca saia sem o plugin.
OFX_BUNDLE = os.path.join(ROOT, "plugins", "ofx", "dist", "PeliculaConverter.ofx.bundle")
_OFX_ARCH = {"win32": "Win64", "darwin": "MacOS"}.get(sys.platform, "Linux-x86-64")
if os.path.isfile(os.path.join(OFX_BUNDLE, "Contents", _OFX_ARCH, "PeliculaConverter.ofx")):
    DATAS.append((OFX_BUNDLE, os.path.join("ofx", "PeliculaConverter.ofx.bundle")))
elif os.environ.get("PELICULA_EXIGIR_OFX") == "1":
    raise SystemExit("Plugin OpenFX não compilado: rode python plugins/ofx/build.py antes do PyInstaller.")
else:
    print("AVISO: plugin OpenFX não compilado (plugins/ofx/dist); o pacote sai sem ele.")

COMMON = dict(
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    hiddenimports=["glcontext", *GL_BACKENDS, *SETTINGS_PAGES],
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
    version=version_info("PeliculaConverter", f"{NAME}.exe"),
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
    version=version_info("PeliculaConverter (modo terminal)", f"{CLI_NAME}.exe"),
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
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": VERSION},
    )
