"""Gera o manifesto de SHA-256 (arquivo por arquivo) do código de um commit fixo no GitHub.

O zip que o GitHub monta para um commit pode mudar de bytes com o tempo (compressão, datas), então o
app não confere o zip inteiro: confere cada arquivo extraído contra este manifesto. Para gerar, o
script baixa o zip do commit e confere **cada arquivo** contra o objeto do git no próprio commit
(SHA-1 do blob, pela API do GitHub), e só então grava as linhas `<sha256>  <caminho>`.

Uso (só para quem atualiza a versão fixada; precisa de rede):

    python tools/gerar_manifesto.py nikopueringer/CorridorKey2.0 485f5e9ab759ead6138cc990776184b59d6ea971 \
        pelicula/data/corridorkey/codigo-485f5e9.sha256 --pular "*.bat" --pular "*.sh"
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "PeliculaConverter-manifesto"}


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="dono/repositório no GitHub")
    ap.add_argument("commit", help="SHA completo do commit")
    ap.add_argument("saida", help="arquivo do manifesto")
    ap.add_argument("--pular", action="append", default=[], help="padrão de arquivo que o app não instala")
    args = ap.parse_args(argv)

    tree = json.loads(_get(f"https://api.github.com/repos/{args.repo}/git/trees/{args.commit}?recursive=1"))
    if tree.get("truncated"):
        raise SystemExit("a árvore do commit veio truncada")
    blobs = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"}
    data = _get(f"https://codeload.github.com/{args.repo}/zip/{args.commit}")
    lines = []
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename.split("/", 1)[1]
            content = z.read(info)
            blob = hashlib.sha1(b"blob %d\x00" % len(content) + content).hexdigest()
            if blobs.get(rel) != blob:
                raise SystemExit(f"{rel}: o zip não bate com o commit")
            seen.add(rel)
            if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], p) for p in args.pular):
                continue
            lines.append(f"{hashlib.sha256(content).hexdigest()}  {rel}")
    missing = sorted(set(blobs) - seen)
    if missing:
        raise SystemExit(f"arquivos do commit fora do zip: {missing}")
    head = [f"# {args.repo} @ {args.commit}",
            "# Gerado por tools/gerar_manifesto.py (cada arquivo conferido com o blob do git no commit).",
            f"# Fora do manifesto (o app não instala): {', '.join(args.pular) or 'nada'}"]
    Path(args.saida).write_text("\n".join(head + sorted(lines, key=lambda s: s[66:])) + "\n", encoding="utf-8")
    print(f"{len(lines)} arquivos em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
