#!/usr/bin/env bash
# Abre o PeliculaConverter (Linux). Arquivos passados como argumento são abertos direto no app.
# Uso:  ./executar.sh [vídeo, imagem, .cube ou preset .json]
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

if [ ! -x "$DIR/.venv/bin/python" ]; then
    echo "O ambiente do PeliculaConverter ainda não foi criado. Rode primeiro: bash instalar.sh"
    exit 1
fi

exec "$DIR/.venv/bin/python" "$DIR/PeliculaConverter.pyw" "$@"
