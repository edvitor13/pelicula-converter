"""Entrada do executável de terminal ``pelicula-cli`` (PyInstaller, console=True).

Divide a pasta do PeliculaConverter com o executável da interface; veja PeliculaConverter.spec.
"""

import sys

from pelicula.cli import main

raise SystemExit(main(sys.argv[1:]))
