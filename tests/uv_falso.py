"""uv falso para os testes da receita de ambiente (tests/test_ambiente.py): nada de rede.

Imita os comandos que `tools.build_env()` usa e anota cada chamada em `$UV_CACHE_DIR/chamadas.txt`:

- `python install <versão> --install-dir D ...`: cria `D/cpython-<versão>-falso/python` (só um marcador);
- `python find <versão> ...`: imprime esse caminho;
- `venv <pasta> --python <base> --relocatable ...`: um venv de verdade (`python -m venv --without-pip`)
  com o Python que roda os testes, e `base.txt` com o Python base pedido;
- `pip install ... -r <lista>`: para cada `pacote==versão` da lista, "baixa" uma wheel no cache
  (`$UV_CACHE_DIR/wheels`, reaproveitada na próxima vez) e grava `pacote.py` (VERSAO) no ambiente;
- `pip install ... --no-deps ... <pasta>`: copia os .py da pasta para o ambiente.

Controle pelos testes (variáveis que `tools.clean_environ` não tira):
PCTEST_FALHAR_UMA_VEZ=<arquivo>: a primeira instalação (sem o arquivo) cai depois de um pacote;
PCTEST_DEMORAR=<segundos>: espera antes de cada pacote (para cancelar no meio).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
cache = Path(os.environ["UV_CACHE_DIR"])
cache.mkdir(parents=True, exist_ok=True)
with open(cache / "chamadas.txt", "a", encoding="utf-8") as log:
    log.write(" ".join(args) + "\n")


def opt(name: str) -> str:
    return args[args.index(name) + 1]


def site_packages(py: str) -> Path:
    out = subprocess.run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


if args[:2] == ["python", "install"]:
    assert "--system-certs" in args and "--no-bin" in args, args
    folder = Path(opt("--install-dir")) / f"cpython-{args[2]}-falso"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "python").write_text(sys.executable, encoding="utf-8")
    print(f"Installed Python {args[2]}")
elif args[:2] == ["python", "find"]:
    folder = Path(os.environ["UV_PYTHON_INSTALL_DIR"]) / f"cpython-{args[2]}-falso"
    if not folder.is_dir():
        print(f"error: No interpreter found for Python {args[2]}", file=sys.stderr)
        sys.exit(2)
    print(folder / "python")
elif args[0] == "venv":
    assert "--relocatable" in args, args
    dest = Path(args[1])
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(dest)], check=True)
    (dest / "base.txt").write_text(opt("--python"), encoding="utf-8")
    print(f"Creating virtual environment at: {dest}")
elif args[:2] == ["pip", "install"] and "-r" in args:
    assert "--require-hashes" in args and "--system-certs" in args, args
    py = opt("--python")
    site = site_packages(py)
    wheels = cache / "wheels"
    wheels.mkdir(exist_ok=True)
    fail_marker = os.environ.get("PCTEST_FALHAR_UMA_VEZ", "")
    fail_now = bool(fail_marker) and not Path(fail_marker).exists()
    delay = float(os.environ.get("PCTEST_DEMORAR", "0") or 0)
    count = 0
    for line in Path(opt("-r")).read_text(encoding="utf-8").splitlines():
        m = re.match(r"([a-z0-9_]+)==([0-9.]+)\s+--hash=sha256:[0-9a-f]{64}", line.strip())
        if not m:
            continue
        name, version = m.groups()
        time.sleep(delay)
        wheel = wheels / f"{name}-{version}.whl"
        if wheel.exists():
            print(f"cache {name}=={version}", flush=True)
        else:
            if fail_now and count >= 1:
                Path(fail_marker).write_text("caiu", encoding="utf-8")
                print("error: Failed to fetch: connection reset by peer", file=sys.stderr, flush=True)
                sys.exit(2)
            wheel.write_bytes(os.urandom(2048))
            print(f"baixou {name}=={version}", flush=True)
            count += 1
        (site / f"{name}.py").write_text(f"VERSAO = {version!r}\n", encoding="utf-8")
    if "--torch-backend" in args:
        (site / "indice_torch.py").write_text(f"INDICE = {opt('--torch-backend')!r}\n", encoding="utf-8")
    print(f"Installed {count} packages")
elif args[:2] == ["pip", "install"]:
    assert "--no-deps" in args and "--offline" in args, args
    site = site_packages(opt("--python"))
    src = Path(args[-1])
    for f in src.rglob("*.py"):
        target = site / f.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    print(f"Installed {src.name}")
else:
    print(f"comando desconhecido: {args}", file=sys.stderr)
    sys.exit(2)
