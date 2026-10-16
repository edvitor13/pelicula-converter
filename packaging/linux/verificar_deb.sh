#!/usr/bin/env bash
# Testa o .deb do PeliculaConverter de verdade: instala com o apt (que resolve as dependências),
# confere os arquivos e a integração com a área de trabalho e remove.
#
# Feito para o CI (runner descartável, com sudo). Uso:
#   bash packaging/linux/verificar_deb.sh PACOTE.deb VERSAO_DO_APP
set -euo pipefail

DEB="$(readlink -f "${1:?Informe o .deb}")"
VER="${2:?Informe a versão do app (x.y.z)}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP=/opt/pelicula-converter
falhas=0

confere() {  # confere "descrição" comando...
    local msg="$1"; shift
    if "$@" >/dev/null 2>&1; then echo "  ok      $msg"; else echo "  FALHOU  $msg"; falhas=$((falhas + 1)); fi
}

echo "== Conteúdo"
dpkg-deb --info "$DEB"
dpkg-deb --contents "$DEB" | grep -v "$APP/_internal/." || true
echo "  ($(dpkg-deb --contents "$DEB" | wc -l) entradas no total)"

echo
echo "== Instalação"
sudo apt-get install -y --no-install-recommends "$DEB"
sudo apt-get install -y --no-install-recommends desktop-file-utils >/dev/null

confere "executável do app em $APP" test -x "$APP/PeliculaConverter"
confere "pelicula-cli em $APP" test -x "$APP/pelicula-cli"
confere "/usr/bin/pelicula-converter aponta para o app" \
    test "$(readlink -f /usr/bin/pelicula-converter)" = "$APP/PeliculaConverter"
confere "/usr/bin/pelicula-cli aponta para o pelicula-cli" \
    test "$(readlink -f /usr/bin/pelicula-cli)" = "$APP/pelicula-cli"
confere "pelicula-install.json = {kind: deb, version: $VER}" python3 -c '
import json, sys
d = json.load(open("/opt/pelicula-converter/pelicula-install.json", encoding="utf-8"))
sys.exit(0 if d == {"kind": "deb", "version": sys.argv[1]} else 1)' "$VER"
confere "atalho .desktop válido" desktop-file-validate /usr/share/applications/pelicula-converter.desktop
confere "tipo application/x-pelicula-project registrado para *.plc" \
    grep -q '^[0-9]*:application/x-pelicula-project:\*\.plc' /usr/share/mime/globs2
confere "*.plc associado ao pelicula-converter.desktop" \
    grep -q '^application/x-pelicula-project=.*pelicula-converter.desktop' /usr/share/applications/mimeinfo.cache
for f in apps/pelicula-converter.png mimetypes/application-x-pelicula-project.png; do
    confere "ícone 256 e 512 ($f)" test -f "/usr/share/icons/hicolor/256x256/$f" -a -f "/usr/share/icons/hicolor/512x512/$f"
done
confere "ícone vetorial" test -f /usr/share/icons/hicolor/scalable/apps/pelicula-converter.svg
confere "licença em /usr/share/doc" test -f /usr/share/doc/pelicula-converter/copyright

# O link em /usr/bin precisa achar a pasta _internal do executável real.
saida="$(/usr/bin/pelicula-cli --help 2>&1)" && codigo=0 || codigo=$?
echo "$saida" | head -n 15
if [ -f "$REPO/pelicula/cli.py" ]; then
    confere "pelicula-cli --help pelo link (código $codigo)" test "$codigo" -eq 0
else
    confere "pelicula-cli sobe pelo link (pelicula/cli.py ainda não existe neste commit)" \
        grep -q "pelicula\.cli" <<<"$saida"
fi

echo
echo "== Remoção"
sudo apt-get remove -y pelicula-converter
confere "pasta $APP removida" test ! -e "$APP"
confere "links em /usr/bin removidos" test ! -e /usr/bin/pelicula-converter -a ! -e /usr/bin/pelicula-cli
confere "tipo *.plc removido do cache" bash -c '! grep -q x-pelicula-project /usr/share/mime/globs2'

echo
if [ "$falhas" -gt 0 ]; then
    echo "O .deb falhou em $falhas conferência(s)."
    exit 1
fi
echo "O .deb passou em todas as conferências."
