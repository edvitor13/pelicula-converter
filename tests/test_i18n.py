"""Traduções: catálogos completos, campos {} iguais ao original, troca de idioma e números por idioma."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import string
import subprocess
import sys
import types
from pathlib import Path

import pytest

from pelicula import i18n

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "pelicula"
LANGS = ("en", "es")


def _load_extractor():
    spec = importlib.util.spec_from_file_location("i18n_extract", ROOT / "tools" / "i18n_extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EX = _load_extractor()


@pytest.fixture(scope="module")
def strings() -> dict[str, list[str]]:
    return EX.collect()


@pytest.fixture(autouse=True)
def _back_to_source_language():
    """Cada teste começa e termina em português (o resto da suíte espera os textos originais)."""
    i18n.set_language(i18n.SOURCE)
    yield
    i18n.set_language(i18n.SOURCE)


def _catalog(lang: str) -> dict[str, str]:
    return json.loads((PACKAGE / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ catálogos
@pytest.mark.parametrize("lang", LANGS)
def test_catalog_file_is_sorted_utf8_json(lang):
    path = PACKAGE / "locales" / f"{lang}.json"
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict) and data.get("@idioma") == i18n.LANGUAGES[lang]
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
    assert raw == EX.dump(data), "rode tools/i18n_extract.py --update para normalizar o arquivo"


@pytest.mark.parametrize("lang", LANGS)
def test_every_string_has_a_translation(lang, strings):
    data = _catalog(lang)
    missing = [t for t in sorted(strings) if not data.get(t, "").strip()]
    assert not missing, (f"{len(missing)} textos sem tradução em {lang}.json "
                         f"(tools/i18n_extract.py --check): {missing[:15]}")


@pytest.mark.parametrize("lang", LANGS)
def test_placeholders_match_the_source(lang):
    bad = []
    for key, value in _catalog(lang).items():
        if key.startswith("@") or not value:
            continue
        try:
            fields = EX.placeholders(key)
            if EX.placeholders(value) != fields:
                bad.append(key)
                continue
            dummy = {name: "x" for name in fields}
            if fields:
                value.format(**dummy)
        except (ValueError, KeyError, IndexError):
            bad.append(key)
    assert not bad, f"campos {{}} diferentes do original em {lang}.json: {bad[:10]}"


def test_code_placeholders_are_named_and_passed_to_format():
    """Todo `_("... {x} ...").format(...)` passa os campos por nome (os tradutores podem reordenar)."""
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"):
                continue
            inner = node.func.value
            if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "_"
                    and inner.args):
                continue
            text = EX._literal(inner.args[0])
            if text is None:
                continue
            fields = EX.placeholders(text)
            names = {kw.arg for kw in node.keywords}
            if None in names:  # **kwargs: não dá para conferir
                continue
            if node.args or any(not f or f.isdigit() for f in fields) or not fields <= names:
                problems.append(f"{rel}:{node.lineno}: {text[:60]!r} campos={sorted(fields)} format={sorted(names)}")
    assert not problems, "\n".join(problems)


def test_extractor_collects_code_and_data_strings(strings):
    expected = [
        "Exportar",                                          # _() no código
        "Na fila",                                           # N_() numa tabela da interface
        "Halação", "Brilho avermelhado em volta das luzes",  # título e subtítulo de seção
        "Perfil do vídeo", "Mistura o resultado com o vídeo original.",  # rótulo e dica
        "Pancromático (neutro)", "1,85 (widescreen)",        # opções
        "Só textura (cor original)", "Desliga todos os efeitos.", "Cinema 35 mm", "Meus presets",  # presets
        "Copiar original (sem recodificar)", "23,976", "Desligada (processador)", "FFV1 (sem perdas)",  # export
        "MP4 H.264 — o formato mais comum, abre em tudo",   # qualidade pronta
    ]
    for text in expected:
        assert text in strings, text
    assert "24" not in strings  # sem letras e sem vírgula decimal: não precisa de tradução
    assert any(w.startswith("pelicula/") for w in strings["Exportar"])


def test_extractor_check_and_update(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(EX, "LOCALES", tmp_path)
    (tmp_path / "en.json").write_text(json.dumps({"@idioma": "English", "Exportar": "Export", "texto antigo": "old"}),
                                      encoding="utf-8")
    assert EX.main(["--check", "--lang", "en"]) == 1  # faltam traduções
    assert EX.main(["--update", "--lang", "en"]) == 0
    data = json.loads((tmp_path / "en.json").read_text(encoding="utf-8"))
    assert data["Exportar"] == "Export" and data["@idioma"] == "English"
    assert data["texto antigo"] == "old"  # obsoleta só sai com --prune
    assert data["Halação"] == ""  # chave nova, valor vazio para traduzir
    assert (tmp_path / "en.json").read_text(encoding="utf-8") == EX.dump(data)
    assert EX.main(["--update", "--prune", "--lang", "en"]) == 0
    assert "texto antigo" not in json.loads((tmp_path / "en.json").read_text(encoding="utf-8"))
    assert not (tmp_path / "es.json").exists()
    assert EX.main(["--update", "--lang", "es"]) == 0  # cria o catálogo que ainda não existe
    assert (tmp_path / "es.json").exists()
    capsys.readouterr()


# ------------------------------------------------------------------ troca de idioma
def test_set_language_translates_and_falls_back_to_source():
    assert i18n.language() == "pt_BR" and i18n._("Exportar") == "Exportar"
    assert i18n.set_language("en") == "en" and i18n.language() == "en"
    assert i18n._("Exportar") == "Export"
    assert i18n._("Halação") == "Halation"
    assert i18n._("Um texto que não está no catálogo") == "Um texto que não está no catálogo"
    assert i18n._("") == ""
    assert i18n.set_language("es") == "es"
    assert i18n._("Fechar") == "Cerrar" and i18n._("Halação") == "Halación"
    assert i18n.set_language("xx") == "en"  # idioma desconhecido → inglês
    assert i18n._("Fechar") == "Close"
    assert i18n.set_language("pt_BR") == "pt_BR"
    assert i18n._("Fechar") == "Fechar"


def test_missing_or_broken_catalog_falls_back_to_source(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "locales_dir", lambda: tmp_path)
    i18n.set_language("en")  # arquivo não existe
    assert i18n._("Fechar") == "Fechar"
    (tmp_path / "es.json").write_text("{quebrado", encoding="utf-8")
    i18n.set_language("es")
    assert i18n._("Fechar") == "Fechar"
    (tmp_path / "en.json").write_text(json.dumps({"@idioma": "English", "Fechar": "", "Abrir": 3, "Sim": "Yes"}),
                                      encoding="utf-8")
    i18n.set_language("en")
    assert i18n._("Fechar") == "Fechar" and i18n._("Abrir") == "Abrir" and i18n._("Sim") == "Yes"
    assert i18n._("@idioma") == "@idioma"


def test_data_stays_portuguese_and_is_translated_on_display():
    from pelicula import export, params, presets
    i18n.set_language("en")
    assert params.PARAMS["bitola"].label == "Bitola"
    assert presets.BY_ID["so_textura"]["nome"] == "Só textura (cor original)"
    assert dict(export.AUDIO)["none"] == "Sem áudio"
    assert i18n._(params.PARAMS["bitola"].label) == "Film gauge"
    assert i18n._(presets.BY_ID["so_textura"]["nome"]) == "Texture only (original color)"
    assert i18n._(presets.BY_ID["vision3_250d"]["nome"]) == "Kodak Vision3 250D"  # marca não muda
    assert i18n._(dict(export.FPS)["24000/1001"]) == "23.976"


def test_quality_preset_labels_follow_the_language(monkeypatch):
    from pelicula import export
    monkeypatch.setattr(export, "available", lambda key: False)
    pt = dict((k, lab) for k, lab, _s in export.quality_presets(None))
    assert pt["mp4"] == "MP4 H.264 — o formato mais comum, abre em tudo"
    i18n.set_language("en")
    en = dict((k, lab) for k, lab, _s in export.quality_presets(None))
    assert en["mp4"] == "MP4 H.264 — the most common format, plays everywhere"
    assert set(en) == set(pt)


# ------------------------------------------------------------------ idioma do sistema
class _FakeLocale:
    def __init__(self, name: str, ui: list[str]):
        self._name, self._ui = name, ui

    def name(self) -> str:
        return self._name

    def uiLanguages(self) -> list[str]:
        return self._ui


def _fake_qt(monkeypatch, name: str | None, ui: list[str] | None = None):
    if name is None:
        monkeypatch.setitem(sys.modules, "PySide6.QtCore", None)  # import falha → ignora o Qt
        return
    loc = _FakeLocale(name, ui or [])
    fake = types.SimpleNamespace(QLocale=types.SimpleNamespace(system=lambda: loc))
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", fake)


@pytest.fixture
def clean_locale_env(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n.locale, "getlocale", lambda *a: (None, None))
    return monkeypatch


@pytest.mark.parametrize("name, ui, expected", [
    ("pt_BR", ["pt-BR"], "pt_BR"),
    ("pt_PT", ["pt-PT"], "pt_BR"),
    ("es_ES", ["es-ES"], "es"),
    ("es_MX", [], "es"),
    ("es_419", ["es-419"], "es"),
    ("en_US", ["en-US"], "en"),
    ("en_GB", [], "en"),
    ("fr_FR", ["fr-FR"], "en"),
    ("de_DE", ["de-DE", "de"], "en"),
    ("ja_JP", [], "en"),
    ("C", [], "en"),
    ("et_EE", ["et-EE"], "en"),  # estoniano não é espanhol
    ("fr_FR", ["fr-FR", "es-ES"], "es"),  # primeiro idioma suportado na lista de preferência
])
def test_system_language_mapping(clean_locale_env, name, ui, expected):
    _fake_qt(clean_locale_env, name, ui)
    assert i18n.system_language() == expected


@pytest.mark.parametrize("env, expected", [
    ({"LANG": "es_AR.UTF-8"}, "es"),
    ({"LC_ALL": "pt_BR.UTF-8"}, "pt_BR"),
    ({"LANG": "en_AU.UTF-8"}, "en"),
    ({"LANG": "it_IT.UTF-8"}, "en"),
    ({}, "en"),
])
def test_system_language_without_qt_uses_environment(clean_locale_env, env, expected):
    _fake_qt(clean_locale_env, None)
    for k, v in env.items():
        clean_locale_env.setenv(k, v)
    assert i18n.system_language() == expected


@pytest.mark.parametrize("loc, expected", [
    (("pt_BR", "cp1252"), "pt_BR"),
    (("Portuguese_Brazil", "1252"), "pt_BR"),  # nome no estilo do Windows
    (("Spanish_Mexico", "1252"), "es"),
    (("English_United States", "1252"), "en"),
    (("Estonian_Estonia", "1257"), "en"),
    (("German_Germany", "1252"), "en"),
])
def test_system_language_from_python_locale(clean_locale_env, loc, expected):
    _fake_qt(clean_locale_env, None)
    clean_locale_env.setattr(i18n.locale, "getlocale", lambda *a: loc)
    assert i18n.system_language() == expected


# ------------------------------------------------------------------ números
def test_decimal_and_group_separators_follow_the_language():
    assert i18n.decimal_sep() == "," and i18n.group_sep() == "."
    assert i18n.fmt_decimal(15.5, 1) == "15,5" and i18n.fmt_int(1234567) == "1.234.567"
    i18n.set_language("en")
    assert i18n.decimal_sep() == "." and i18n.group_sep() == ","
    assert i18n.fmt_decimal(15.5, 1) == "15.5" and i18n.fmt_int(1234567) == "1,234,567"
    i18n.set_language("es")
    assert i18n.fmt_decimal(0.25, 2) == "0,25"
    for txt, v in (("1,5", 1.5), ("1.5", 1.5), (" -0,25 ", -0.25), ("3", 3.0)):
        assert i18n.parse_decimal(txt) == v


def test_widget_values_and_memory_follow_the_language():
    from pelicula import params, system
    from pelicula.ui.widgets import fmt_value, parse_value
    ev, pct, seed = params.PARAMS["exposicao"], params.PARAMS["mix_geral"], params.PARAMS["grao_semente"]
    assert fmt_value(ev, 1.5) == "1,50 EV" and system.gb(1 << 30) == "1,0 GB"
    i18n.set_language("en")
    assert fmt_value(ev, 1.5) == "1.50 EV" and fmt_value(pct, 0.5) == "50%" and fmt_value(seed, 7) == "7"
    assert system.gb(int(15.5 * (1 << 30))) == "15.5 GB"
    for lang in ("pt_BR", "en", "es"):
        i18n.set_language(lang)
        assert parse_value(ev, "1,5 EV") == 1.5 and parse_value(ev, "1.5") == 1.5
        assert parse_value(pct, "50%") == 0.5


# ------------------------------------------------------------------ código
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp,
           ast.GeneratorExp)


def _direct(scope):
    """Nós do escopo, sem entrar em funções, lambdas, compreensões e classes internas."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, _SCOPES + (ast.ClassDef,)):
            stack.extend(ast.iter_child_nodes(n))


def _binds_underscore(scope) -> bool:
    """O escopo cria uma variável local `_` (fora de `from ..i18n import _`)?"""
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        if any(arg is not None and arg.arg == "_" for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]):
            return True
    if isinstance(scope, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        for gen in scope.generators:
            if any(isinstance(n, ast.Name) and n.id == "_" for n in ast.walk(gen.target)):
                return True
    for n in _direct(scope):
        if isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, (ast.Store, ast.Del)):
            return True
        if isinstance(n, ast.ExceptHandler) and n.name == "_":
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == "_":
            return True
    return False


def test_no_scope_shadows_the_translation_function():
    """`path, _ = QFileDialog...` num lugar onde `_()` traduz quebra o texto (UnboundLocalError)."""
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()

        def visit(node, shadowed: bool):
            for child in ast.iter_child_nodes(node):
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_"
                        and shadowed):
                    problems.append(f"{rel}:{child.lineno}")
                if isinstance(child, _SCOPES):
                    visit(child, shadowed or _binds_underscore(child))
                else:
                    visit(child, shadowed)

        visit(tree, _binds_underscore(tree))
    assert not problems, "_ usado como variável onde _() traduz: " + ", ".join(problems)


# ------------------------------------------------------------------ interface em inglês
_UI_SCRIPT = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from pelicula import i18n
i18n.set_language("en")
catalog = i18n.load_catalog("en")
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QWidget
app = QApplication([])
from pelicula import params, presets
from pelicula.export import ExportQueue
from pelicula.ui.looks import LooksPanel
from pelicula.ui.queue_dialog import QueueDialog
from pelicula.ui.store import ParamStore
from pelicula.ui.viewer import Viewer
from pelicula.ui.widgets import SectionCard

roots = []
store = ParamStore()
for sec in params.SECTIONS:
    card = SectionCard(sec, store)
    card.set_advanced(True)
    roots.append(card)
looks = LooksPanel()
items = [{"id": p["id"], "nome": p["nome"], "grupo": p["grupo"], "desc": p["desc"]} for p in presets.BUILTIN]
items.append({"id": "user:meu", "nome": "Halação", "grupo": "Meus presets", "desc": "minha descrição"})
looks.rebuild(items)
roots += [looks, Viewer(), QueueDialog(None, ExportQueue())]
main_window = "skipped"
if os.environ.get("PELICULA_UI_MAIN") == "1":
    try:
        from pelicula.ui.main_window import MainWindow
        win = MainWindow()
    except Exception as exc:
        main_window = "skipped: " + str(exc)[:200]
    else:
        win._fill_project_menu()
        roots.append(win)
        main_window = "ok"

texts = []
def add(t):
    t = (t or "").strip()
    if t:
        texts.append(t)
for root in roots:
    for w in [root] + root.findChildren(QWidget):
        add(w.toolTip())
        if isinstance(w, (QLabel, QAbstractButton)):
            add(w.text())
        if isinstance(w, QComboBox):
            for i in range(w.count()):
                add(w.itemText(i))
        if isinstance(w, QLineEdit):
            add(w.placeholderText())
        for act in w.actions():
            add(act.text())
            if act.menu():
                for sub in act.menu().actions():
                    add(sub.text())
        menu = getattr(w, "menu", None)
        if callable(menu) and menu() is not None:
            for act in menu().actions():
                add(act.text())
                if act.menu():
                    for sub in act.menu().actions():
                        add(sub.text())
untranslated = sorted({t for t in texts if t in catalog and catalog[t] != t})
user = {t: [th for th in looks.thumbs.values() if th.pid == "user:meu"][0].name for t in ["x"]}["x"]
print(json.dumps({"untranslated": untranslated, "texts": texts, "user": user, "main": main_window,
                  "groups": [lab.text() for lab, _box, _l in looks.groups]}, ensure_ascii=False))
app.exit(0)
'''


def test_widgets_show_the_english_interface(tmp_path):
    script = tmp_path / "ui_en.py"
    script.write_text(_UI_SCRIPT, encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=str(tmp_path / "appdata"),
               PELICULA_SETTINGS_DIR=str(tmp_path / "settings"), PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1", PELICULA_UI_MAIN="1")
    res = subprocess.run([sys.executable, str(script), str(ROOT)], capture_output=True, env=env, timeout=150,
                         cwd=str(tmp_path))
    out = res.stdout.decode("utf-8", "replace").strip().splitlines()
    assert res.returncode == 0 and out, res.stderr.decode("utf-8", "replace")[-3000:]
    data = json.loads(out[-1])
    assert data["untranslated"] == [], data["untranslated"]
    texts = set(data["texts"])
    for expected in ("Halation", "Film gauge", "Film presets", "Search looks…", "Open file", "Export queue",
                     "Restore this section's default values", "Texture only (original color)"):
        assert any(expected in t for t in texts), expected
    assert "35 MM CINEMA" in data["groups"] and "MY PRESETS" in data["groups"]
    assert data["user"] == "Halação"  # nome dado pelo usuário não é traduzido
    if data["main"] == "ok":
        for expected in ("Export with the current look (Ctrl+E)", "Keyboard shortcuts", "Side by side", "Preview",
                         "New project", "Save project"):
            assert any(expected in t for t in texts), expected
