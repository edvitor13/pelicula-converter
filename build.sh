#!/usr/bin/env bash
# Gera o PeliculaConverter com o PyInstaller (pasta dist/PeliculaConverter, com PeliculaConverter e
# pelicula-cli) e os pacotes:
#   Linux: .tar.gz portátil e, se houver dpkg-deb (Debian/Ubuntu), o pacote .deb
#   macOS (preparado, mas desativado): .dmg
# Uso:  bash build.sh   (depois de bash instalar.sh)
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$DIR"
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
    echo " O ambiente .venv não existe. Rode primeiro: bash instalar.sh"
    exit 1
fi

echo " Instalando o PyInstaller no ambiente .venv..."
"$PY" -m pip install --upgrade "pyinstaller>=6.10"

if [ "$(uname -s)" != Darwin ]; then
    echo
    echo " Compilando o plugin OpenFX do DaVinci Resolve (vai pronto dentro do app)..."
    codigo=0
    bash plugins/ofx/build_linux.sh || codigo=$?
    if [ "$codigo" -eq 2 ]; then
        echo " Sem g++ (sudo apt install g++): o pacote sai sem o plugin OpenFX."
    elif [ "$codigo" -ne 0 ]; then
        exit "$codigo"
    fi
fi

echo
echo " Gerando os executáveis..."
"$PY" -m PyInstaller --noconfirm --clean PeliculaConverter.spec

VER="$("$PY" packaging/install_marker.py --print-version)"
echo
case "$(uname -s)" in
    Darwin)
        DMG="dist/PeliculaConverter-$VER-macos.dmg"
        PYTHON="$PY" bash packaging/macos/build_dmg.sh dist/PeliculaConverter.app "$DMG"
        echo " Pronto! Imagem de disco: $DMG"
        ;;
    *)
        case "$(uname -m)" in
            x86_64 | amd64) ARCH=x64 ;;
            aarch64 | arm64) ARCH=arm64 ;;
            *) ARCH="$(uname -m)" ;;
        esac
        BASE="dist/PeliculaConverter-$VER-linux-$ARCH"
        echo " Gerando o .tar.gz portátil..."
        "$PY" packaging/install_marker.py dist/PeliculaConverter tar
        tar -czf "$BASE.tar.gz" -C dist PeliculaConverter
        DEB=""
        if command -v dpkg-deb >/dev/null 2>&1; then
            echo
            echo " Gerando o pacote .deb..."
            PYTHON="$PY" bash packaging/linux/build_deb.sh dist/PeliculaConverter "$BASE.deb"
            DEB="$BASE.deb"
        else
            echo " dpkg-deb não encontrado: o .deb só é gerado no Debian/Ubuntu (ou derivados)."
        fi
        echo
        echo " Pronto!"
        echo "   Executáveis: dist/PeliculaConverter/PeliculaConverter e pelicula-cli"
        echo "   Portátil:    $BASE.tar.gz"
        if [ -n "$DEB" ]; then echo "   Pacote:      $DEB   (instale com: sudo apt install ./$DEB)"; fi
        ;;
esac
echo " Lembre: o ffmpeg não vai junto; instale pelo sistema (sudo apt install ffmpeg) ou deixe o app baixar."
