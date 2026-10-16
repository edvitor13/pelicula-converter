#!/usr/bin/env bash
# Monta o pacote .deb do PeliculaConverter a partir da pasta gerada pelo PyInstaller.
#
# Uso:  bash packaging/linux/build_deb.sh PASTA_DIST SAIDA.deb [VERSAO_DO_PACOTE]
#   PASTA_DIST        dist/PeliculaConverter (com PeliculaConverter e pelicula-cli)
#   SAIDA.deb         arquivo a gerar
#   VERSAO_DO_PACOTE  versão Debian (padrão: a do app, de pelicula/__init__.py); builds de
#                     desenvolvimento podem usar algo como 1.1.0~git1a2b3c4
#
# Conteúdo do pacote:
#   /opt/pelicula-converter/                  o app (pasta do PyInstaller) + pelicula-install.json {"kind": "deb"}
#   /usr/bin/pelicula-converter, pelicula-cli links para os executáveis
#   /usr/share/applications/…desktop           atalho no menu (abre arquivos .plc)
#   /usr/share/mime/packages/…xml              tipo application/x-pelicula-project (*.plc)
#   /usr/share/icons/hicolor/…                 ícones do app e do tipo de arquivo
#
# Precisa de dpkg-deb (Debian/Ubuntu) e Python 3; usa objdump (binutils), se houver, para
# calcular a versão mínima da glibc.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SRC="${1:?Informe a pasta do PyInstaller (por exemplo dist/PeliculaConverter)}"
OUT="${2:?Informe o arquivo .deb de saída}"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb não encontrado: o .deb só pode ser montado no Debian/Ubuntu (ou derivados)." >&2
    exit 1
fi
if [ ! -x "$SRC/PeliculaConverter" ]; then
    echo "Não achei $SRC/PeliculaConverter. Rode o PyInstaller antes." >&2
    exit 1
fi

VER="$("$PY" "$REPO/packaging/install_marker.py" --print-version)"
DEBVER="${3:-$VER}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
PKG=pelicula-converter
APP=/opt/pelicula-converter

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOTFS="$STAGE/$PKG"

echo "Montando $PKG $DEBVER ($ARCH)..."
install -d "$ROOTFS$APP" "$ROOTFS/usr/bin" "$ROOTFS/usr/share/applications" \
    "$ROOTFS/usr/share/mime/packages" "$ROOTFS/usr/share/doc/$PKG" "$ROOTFS/DEBIAN"

# ------------------------------------------------------------------ app
cp -a "$SRC/." "$ROOTFS$APP/"
"$PY" "$REPO/packaging/install_marker.py" "$ROOTFS$APP" deb --version "$VER"

# O bootloader do PyInstaller resolve o link e acha a pasta _internal ao lado do executável real.
ln -s "$APP/PeliculaConverter" "$ROOTFS/usr/bin/pelicula-converter"
if [ -x "$SRC/pelicula-cli" ]; then
    ln -s "$APP/pelicula-cli" "$ROOTFS/usr/bin/pelicula-cli"
fi

# ------------------------------------------------------------------ integração com a área de trabalho
install -m 0644 "$HERE/pelicula-converter.desktop" "$ROOTFS/usr/share/applications/pelicula-converter.desktop"
install -m 0644 "$HERE/pelicula-converter.xml" "$ROOTFS/usr/share/mime/packages/pelicula-converter.xml"
for size in 256 512; do
    install -D -m 0644 "$REPO/assets/logo-$size.png" \
        "$ROOTFS/usr/share/icons/hicolor/${size}x${size}/apps/pelicula-converter.png"
    install -D -m 0644 "$REPO/assets/logo-$size.png" \
        "$ROOTFS/usr/share/icons/hicolor/${size}x${size}/mimetypes/application-x-pelicula-project.png"
done
install -D -m 0644 "$REPO/assets/logo.svg" "$ROOTFS/usr/share/icons/hicolor/scalable/apps/pelicula-converter.svg"

# ------------------------------------------------------------------ licença (formato DEP-5)
{
    echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
    echo "Upstream-Name: PeliculaConverter"
    echo "Source: https://github.com/edvitor13/pelicula-converter"
    echo "Comment: O pacote traz o Python e bibliotecas de terceiros (Qt/PySide6, moderngl, numpy)"
    echo " em $APP/_internal, cada uma com a própria licença. O ffmpeg não faz parte do pacote."
    echo
    echo "Files: *"
    echo "Copyright: 2026 Vitor Gabriel"
    echo "License: MIT"
    sed -e 's/^[[:space:]]*$/./' -e 's/^/ /' "$REPO/LICENSE"
} > "$ROOTFS/usr/share/doc/$PKG/copyright"
chmod 0644 "$ROOTFS/usr/share/doc/$PKG/copyright"

# ------------------------------------------------------------------ permissões
find "$ROOTFS" -type d -exec chmod 0755 {} +
find "$ROOTFS" -type f -exec chmod u+rw,go-w,go+r {} +

# ------------------------------------------------------------------ dependências
# Versão mínima da glibc: o maior símbolo GLIBC_x.y usado pelos binários do pacote.
GLIBC=""
if command -v objdump >/dev/null 2>&1; then
    GLIBC="$( (find "$ROOTFS$APP" -type f \( -name '*.so*' -o -perm -u+x \) -print0 \
                | xargs -0 -r objdump -T 2>/dev/null || true) \
              | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/^GLIBC_//' | sort -Vu | tail -n 1 || true)"
fi
# Bibliotecas do sistema que o Qt (PySide6, plataforma xcb) e o OpenGL (moderngl/glcontext) usam.
# No Ubuntu 24.04+ algumas viraram "*t64" e continuam satisfeitas pelo nome antigo (Provides).
DEPENDS="libc6${GLIBC:+ (>= $GLIBC)}, libgl1, libegl1, libopengl0, libglib2.0-0, libfontconfig1, libfreetype6,"
DEPENDS="$DEPENDS libdbus-1-3, libx11-6, libx11-xcb1, libxkbcommon0, libxkbcommon-x11-0, libxcb1, libxcb-cursor0,"
DEPENDS="$DEPENDS libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render0,"
DEPENDS="$DEPENDS libxcb-render-util0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0,"
DEPENDS="$DEPENDS libxcb-xinerama0, libxcb-xkb1"

SIZE="$(du -sk --apparent-size --exclude=DEBIAN "$ROOTFS" | cut -f1)"

cat > "$ROOTFS/DEBIAN/control" <<EOF
Package: $PKG
Version: $DEBVER
Architecture: $ARCH
Maintainer: Vitor Gabriel <11736724+edvitor13@users.noreply.github.com>
Installed-Size: $SIZE
Depends: $DEPENDS
Recommends: ffmpeg
Section: video
Priority: optional
Homepage: https://github.com/edvitor13/pelicula-converter
Description: simula película cinematográfica em vídeos digitais
 O PeliculaConverter transforma vídeo digital em película de cinema: cor de
 negativos e cópias, grão, halação, bitolas de 8 mm a IMAX, tremor de
 projetor, defeitos e o scan da película com furos, tudo processado na placa
 de vídeo (OpenGL 3.3) e com prévia em tempo real.
 .
 Inclui o modo de terminal (pelicula-cli). O ffmpeg lê e grava os vídeos; se
 não estiver instalado, o app oferece baixar um build verificado.
EOF
install -m 0755 "$HERE/debian/postinst" "$ROOTFS/DEBIAN/postinst"
install -m 0755 "$HERE/debian/postrm" "$ROOTFS/DEBIAN/postrm"

mkdir -p "$(dirname "$OUT")"
dpkg-deb --root-owner-group -Zxz --build "$ROOTFS" "$OUT"
echo
echo "Pacote gerado: $OUT"
echo "  glibc mínima: ${GLIBC:-(não calculada; instale o binutils)}"
dpkg-deb --info "$OUT" | sed -n '/Package:/,/Description:/p'
