"""Tradução da interface (português do Brasil, inglês e espanhol).

O texto-fonte do código é o português do Brasil. Cada idioma tem um catálogo JSON em
`pelicula/locales/<código>.json` que mapeia o texto em português para a tradução:

    from .i18n import _
    label.setText(_("Abrir"))
    msg = _("{n} LUTs salvos em {pasta}").format(n=3, pasta=d)

Textos que vêm de dados (rótulos de parâmetros, nomes e descrições de presets) também passam
por `_()` na hora de aparecer na tela. Sem tradução, o texto em português é mostrado.
O idioma é escolhido no primeiro acesso e muda ao reabrir o app.
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

SOURCE = "pt_BR"
LANGUAGES: dict[str, str] = {
    "pt_BR": "Português (Brasil)",
    "en": "English",
    "es": "Español",
}

_lang = SOURCE
_catalog: dict[str, str] = {}


def locales_dir() -> Path:
    return Path(__file__).resolve().parent / "locales"


def load_catalog(code: str) -> dict[str, str]:
    if code == SOURCE:
        return {}
    path = locales_dir() / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and v and not k.startswith("@")}


def set_language(code: str) -> str:
    """Ativa um idioma (código de LANGUAGES). Devolve o código efetivamente usado."""
    global _lang, _catalog
    if code not in LANGUAGES:
        code = "en"
    _lang = code
    _catalog = load_catalog(code)
    return code


def language() -> str:
    return _lang


def _(text: str) -> str:
    """Traduz um texto escrito em português do Brasil."""
    if not _catalog or not text:
        return text
    return _catalog.get(text, text)


def N_(text: str) -> str:
    """Marca um texto para o catálogo sem traduzir agora.

    Para tabelas montadas na importação do módulo (antes de o idioma ser escolhido): o texto
    fica em português nos dados e é traduzido com `_()` na hora de aparecer na tela.
    """
    return text


# Separadores numéricos por idioma (o padrão é o do português: 1.234,5).
_DECIMAL_SEP = {"en": "."}
_GROUP_SEP = {"en": ","}


def decimal_sep() -> str:
    """Separador decimal do idioma ativo: vírgula (pt_BR, es) ou ponto (en)."""
    return _DECIMAL_SEP.get(_lang, ",")


def group_sep() -> str:
    """Separador de milhar do idioma ativo: ponto (pt_BR, es) ou vírgula (en)."""
    return _GROUP_SEP.get(_lang, ".")


def fmt_decimal(value: float, decimals: int = 1) -> str:
    """Número com casas decimais e o separador do idioma (1,5 / 1.5)."""
    return f"{value:.{decimals}f}".replace(".", decimal_sep())


def fmt_int(value: float) -> str:
    """Número arredondado com separador de milhar do idioma (1.234 / 1,234)."""
    return f"{value:,.0f}".replace(",", group_sep())


def parse_decimal(text: str) -> float:
    """Lê um número digitado com vírgula ou ponto decimal ("1,5" ou "1.5")."""
    return float(text.strip().replace(",", "."))


def system_language() -> str:
    """Idioma do sistema se for suportado; senão inglês."""
    candidates = []
    try:
        from PySide6.QtCore import QLocale
        candidates += [QLocale.system().name()] + list(QLocale.system().uiLanguages())
    except Exception:  # noqa: BLE001
        pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(var):
            candidates.append(os.environ[var])
    try:
        candidates.append(locale.getlocale()[0] or "")
    except (ValueError, TypeError):
        pass
    # Códigos ISO (pt_BR, es-MX, en.UTF-8) ou nomes do Windows (Portuguese_Brazil, Spanish_Spain).
    known = (("pt", "portuguese", "pt_BR"), ("es", "spanish", "es"), ("en", "english", "en"))
    for c in candidates:
        c = (c or "").replace("-", "_").lower()
        for iso, name, code in known:
            if c == iso or c.startswith((iso + "_", iso + ".", iso + "@", name)):
                return code
    return "en"
