"""Regenera o código C++ do plugin OpenFX (plugins/ofx/generated) a partir de pelicula/resolve.py.

    .venv\\Scripts\\python tools\\gerar_ofx.py          (Windows)
    .venv/bin/python tools/gerar_ofx.py               (Linux)

Rode depois de mudar a cor, os kernels dos DCTLs, os parâmetros ou os presets do app; o teste
tests/test_ofx.py::test_generated_files_are_up_to_date avisa quando esqueceram. Depois compile com
plugins/ofx/build_windows.bat ou plugins/ofx/build_linux.sh.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pelicula import ofx  # noqa: E402


def main() -> int:
    for path in ofx.generate():
        print("gerado:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
