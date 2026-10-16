#!/usr/bin/env bash
# Monta a imagem de disco .dmg do PeliculaConverter (macOS: PREPARADO, MAS DESATIVADO).
#
# Uso:  bash packaging/macos/build_dmg.sh dist/PeliculaConverter.app SAIDA.dmg
#
# Grava o pelicula-install.json {"kind": "dmg"} ao lado do executável
# (PeliculaConverter.app/Contents/MacOS), refaz a assinatura ad hoc do .app (mexer no bundle
# invalida a assinatura que o PyInstaller fez) e cria um .dmg compactado com o app e um atalho
# para /Applications. Assinatura com Developer ID e notarização: veja docs/ASSINATURA.md.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
APPB="${1:?Informe o PeliculaConverter.app}"
OUT="${2:?Informe o arquivo .dmg de saída}"
PY="${PYTHON:-python3}"

if [ "$(uname -s)" != "Darwin" ] || ! command -v hdiutil >/dev/null 2>&1; then
    echo "O .dmg só pode ser montado no macOS (hdiutil)." >&2
    exit 1
fi
if [ ! -d "$APPB/Contents/MacOS" ]; then
    echo "Não achei $APPB/Contents/MacOS. Rode o PyInstaller antes." >&2
    exit 1
fi

"$PY" "$REPO/packaging/install_marker.py" "$APPB/Contents/MacOS" dmg
codesign --force --deep --sign - "$APPB"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APPB" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

rm -f "$OUT"
hdiutil create -volname "PeliculaConverter" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
echo "Imagem gerada: $OUT"
