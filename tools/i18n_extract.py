"""Coleta os textos traduzíveis do PeliculaConverter e confere os catálogos de tradução.

O texto-fonte é o português do Brasil. Os catálogos `pelicula/locales/<idioma>.json` mapeiam o
texto em português para a tradução (chaves que começam com "@" são metadados).

Textos coletados:

1. Todo literal passado para `_()` ou `N_()` em `pelicula/**/*.py` (lido com `ast`, sem importar).
2. Textos de dados que a interface traduz na hora de mostrar:
   - `params.SECTIONS`: título, subtítulo, rótulo, dica e rótulos das opções de cada parâmetro;
   - `editparams.VIDEO_SECTIONS` e `AUDIO_SECTIONS` (ajustes por clipe do modo Edição), do mesmo jeito;
   - `presets.BUILTIN` (nome, desc, grupo), `presets.GROUPS` e os grupos escritos em `presets.py`
     (por exemplo "Meus presets");
   - tabelas de `export`: rótulos de `CODECS` (e perfis), `AUDIO`, `RESOLUTIONS`, `FPS`,
     `PRIORITIES` e `HWACCEL_LABELS`.
   Textos de dados sem nenhuma letra (por exemplo "24") ficam de fora; números com vírgula
   decimal ("23,976") entram, porque o separador muda no inglês.

Uso:

    python tools/i18n_extract.py              # resumo
    python tools/i18n_extract.py --check      # faltando/obsoletos em cada catálogo (código 1 se faltar)
    python tools/i18n_extract.py --update     # acrescenta as chaves que faltam com valor vazio
    python tools/i18n_extract.py --update --prune   # ... e remove as obsoletas
    python tools/i18n_extract.py --list       # todos os textos, com onde aparecem
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "pelicula"
LOCALES = PACKAGE / "locales"
LANGS = ("en", "es")
FUNCS = {"_", "N_"}

_HAS_LETTER = re.compile(r"[^\W\d_]")
_DECIMAL_COMMA = re.compile(r"\d,\d")


# ------------------------------------------------------------------ código (_() e N_())
def _literal(node: ast.AST) -> str | None:
    """Texto de um literal (aceita "a" "b" e "a" + "b")."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _literal(node.left), _literal(node.right)
        if a is not None and b is not None:
            return a + b
    return None


def _is_marker(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id in FUNCS
    # i18n._("...") também vale
    return isinstance(func, ast.Attribute) and func.attr in FUNCS and isinstance(func.value, ast.Name) \
        and func.value.id == "i18n"


def code_strings(root: Path = PACKAGE) -> dict[str, list[str]]:
    """{texto: ["arquivo:linha", ...]} de todo `_("...")`/`N_("...")` do pacote."""
    out: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_marker(node.func) and node.args:
                text = _literal(node.args[0])
                if text:
                    out.setdefault(text, []).append(f"{rel}:{node.lineno}")
    return out


# ------------------------------------------------------------------ dados
def translatable(text: str) -> bool:
    return bool(text) and bool(_HAS_LETTER.search(text) or _DECIMAL_COMMA.search(text))


def _preset_group_literals(path: Path) -> list[str]:
    """Valores literais de `grupo` em presets.py (dict(grupo=...) e {"grupo": ...})."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "grupo":
            text = _literal(node.value)
            if text:
                found.append(text)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is not None and _literal(k) == "grupo" and _literal(v):
                    found.append(_literal(v))
    return found


def data_strings() -> dict[str, list[str]]:
    """{texto: [origem, ...]} dos dados que a interface traduz na hora de mostrar."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from pelicula import editparams, export, params, presets

    out: dict[str, list[str]] = {}

    def add(text: str, where: str) -> None:
        if text and translatable(text):
            out.setdefault(text, []).append(where)

    for origin, sections in (("params", params.SECTIONS), ("editparams.video", editparams.VIDEO_SECTIONS),
                             ("editparams.audio", editparams.AUDIO_SECTIONS)):
        for sec in sections:
            add(sec.title, f"{origin}:{sec.key}.title")
            add(sec.subtitle, f"{origin}:{sec.key}.subtitle")
            for p in sec.params:
                add(p.label, f"{origin}:{p.key}.label")
                add(p.tip, f"{origin}:{p.key}.tip")
                for value, label in p.choices or []:
                    add(label, f"{origin}:{p.key}.choices[{value}]")

    for item in presets.BUILTIN:
        for k in ("nome", "desc", "grupo"):
            add(item.get(k) or "", f"presets:{item['id']}.{k}")
    for g in presets.GROUPS:
        add(g, "presets:GROUPS")
    for g in _preset_group_literals(Path(presets.__file__)):
        add(g, "presets.py:grupo")

    for key, c in export.CODECS.items():
        add(c.get("label", ""), f"export:CODECS[{key}].label")
        for value, label in c.get("profiles", []):
            add(label, f"export:CODECS[{key}].profiles[{value}]")
    for table in ("AUDIO", "RESOLUTIONS", "FPS", "PRIORITIES"):
        for value, label in getattr(export, table):
            add(label, f"export:{table}[{value}]")
    for value, label in export.HWACCEL_LABELS.items():
        add(label, f"export:HWACCEL_LABELS[{value}]")
    return out


def collect() -> dict[str, list[str]]:
    """Todos os textos traduzíveis: {texto: [onde aparece, ...]}."""
    merged = code_strings()
    for text, where in data_strings().items():
        merged.setdefault(text, []).extend(where)
    return merged


# ------------------------------------------------------------------ catálogos
def placeholders(text: str) -> set[str]:
    """Campos de str.format() de um texto ({nome}, {n:.1f} → nome, n). Levanta ValueError se mal formado."""
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name is not None}


def catalog_path(lang: str) -> Path:
    return LOCALES / f"{lang}.json"


def load(lang: str) -> dict[str, str]:
    path = catalog_path(lang)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dump(data: dict[str, str]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def save(lang: str, data: dict[str, str]) -> None:
    catalog_path(lang).write_text(dump(data), encoding="utf-8", newline="\n")


def compare(strings: dict[str, list[str]], data: dict[str, str]) -> tuple[list[str], list[str]]:
    """(faltando ou vazios, obsoletos)."""
    missing = sorted(t for t in strings if not data.get(t))
    obsolete = sorted(k for k in data if not k.startswith("@") and k not in strings)
    return missing, obsolete


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="lista chaves faltando/obsoletas; código 1 se faltar")
    ap.add_argument("--update", action="store_true", help="acrescenta as chaves que faltam com valor vazio")
    ap.add_argument("--prune", action="store_true", help="com --update, remove as chaves obsoletas")
    ap.add_argument("--strict", action="store_true", help="com --check, chaves obsoletas também dão código 1")
    ap.add_argument("--list", action="store_true", help="imprime todos os textos coletados")
    ap.add_argument("--lang", action="append", choices=LANGS, help="só este idioma (pode repetir)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    strings = collect()
    langs = args.lang or list(LANGS)
    if args.list:
        for text in sorted(strings):
            print(json.dumps(text, ensure_ascii=False), "  ←", ", ".join(strings[text][:3]))
        return 0

    status = 0
    print(f"{len(strings)} textos traduzíveis ({len(code_strings())} no código).")
    for lang in langs:
        data = load(lang)
        missing, obsolete = compare(strings, data)
        bad_fields = []
        for key, value in data.items():
            if key.startswith("@") or not value:
                continue
            try:
                if placeholders(value) != placeholders(key):
                    bad_fields.append(key)
            except ValueError:
                bad_fields.append(key)
        print(f"[{lang}] {len(data) - sum(k.startswith('@') for k in data)} chaves • {len(missing)} faltando • "
              f"{len(obsolete)} obsoletas • {len(bad_fields)} com campos {{}} diferentes do original")
        if args.check:
            for t in missing:
                print(f"  faltando: {json.dumps(t, ensure_ascii=False)}  ({', '.join(strings[t][:2])})")
            for t in obsolete:
                print(f"  obsoleta: {json.dumps(t, ensure_ascii=False)}")
            for t in bad_fields:
                print(f"  campos:   {json.dumps(t, ensure_ascii=False)}")
            if missing or bad_fields or (args.strict and obsolete):
                status = 1
        if args.update:
            changed = False
            for t in missing:
                if t not in data:
                    data[t] = ""
                    changed = True
            if args.prune:
                for t in obsolete:
                    del data[t]
                    changed = True
            path = catalog_path(lang)
            if changed or not path.exists() or path.read_text(encoding="utf-8") != dump(data):
                save(lang, data)
                print(f"  {path.name} atualizado")
    return status


if __name__ == "__main__":
    sys.exit(main())
