#!/usr/bin/env bash
# Compila o plugin OpenFX do PeliculaConverter no Linux (g++ -O2 -shared -fPIC, sem -ffast-math):
#   plugins/ofx/dist/PeliculaConverter.ofx.bundle/Contents/Linux-x86-64/PeliculaConverter.ofx
# Precisa de g++ (Debian/Ubuntu: sudo apt install g++). As opções ficam em build.py.
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v "${CXX:-g++}" >/dev/null 2>&1; then
    echo "g++ não encontrado (Debian/Ubuntu: sudo apt install g++)." >&2
    exit 2
fi
PY=../../.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" build.py "$@"
