#!/usr/bin/env bash
# Cria o ambiente .venv e instala as dependências do PeliculaConverter (Linux).
# Uso:  bash instalar.sh   (ou chmod +x instalar.sh && ./instalar.sh)
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$DIR"

echo
echo " =============================================="
echo "  PeliculaConverter - instalação (Linux)"
echo " =============================================="
echo

if [ ! -x ".venv/bin/python" ]; then
    PY=""
    for cand in python3.15 python3.14 python3.13 python3.12 python3; do
        if command -v "$cand" >/dev/null 2>&1 && \
           "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
            PY="$cand"
            break
        fi
    done
    if [ -z "$PY" ]; then
        echo " Não encontrei o Python 3.12 ou mais novo (recomendado: 3.15)."
        echo " Instale pelo gerenciador de pacotes da sua distribuição ou em https://www.python.org/downloads/"
        exit 1
    fi
    echo " Criando o ambiente .venv com $("$PY" --version)..."
    if ! "$PY" -m venv .venv; then
        echo
        echo " Não consegui criar o .venv. No Debian/Ubuntu instale o módulo venv, por exemplo:"
        echo "     sudo apt install python3-venv"
        exit 1
    fi
else
    echo " O ambiente .venv já existe. Atualizando as dependências..."
fi

echo " Python do ambiente: $(.venv/bin/python -c 'import sys; print(sys.version.split()[0])')"
echo
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    echo " ffmpeg encontrado: $(ffmpeg -hide_banner -version | head -n 1)"
else
    echo " Atenção: o ffmpeg não foi encontrado."
    echo " Instale com o gerenciador da distribuição (ex.: sudo apt install ffmpeg) ou deixe o"
    echo " PeliculaConverter baixar sozinho na primeira abertura (Configurações > Dependências e atualizações)."
fi

echo
echo " Se a janela não abrir, instale as bibliotecas que o Qt usa no Linux, por exemplo (Debian/Ubuntu):"
echo "     sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1"
echo
echo " Pronto! Use ./executar.sh para abrir o PeliculaConverter."
