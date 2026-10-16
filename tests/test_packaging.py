"""Empacotamento (packaging/): marcador de instalação, aviso do Discord, licença RTF e receitas.

Nada aqui gera pacotes de verdade (isso é feito e testado no CI); só confere os scripts e os
arquivos fixos que o atualizador e os instaladores usam.
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import pelicula

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


marker = _load(PKG / "install_marker.py")
discord = _load(PKG / "discord_notify.py")
rtf = _load(PKG / "windows" / "license_rtf.py")


# ------------------------------------------------------------------ pelicula-install.json
def test_marker_version_matches_package():
    assert marker.read_version() == pelicula.__version__


@pytest.mark.parametrize("kind", ["msi", "zip", "deb", "tar", "dmg"])
def test_marker_written_next_to_executable(tmp_path, kind):
    path = marker.write_marker(tmp_path, kind, "1.2.3")
    assert path == tmp_path / "pelicula-install.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"kind": kind, "version": "1.2.3"}


@pytest.mark.parametrize("kind, version", [("exe", "1.0.0"), ("msi", "1.0"), ("msi", "1.0.0-beta")])
def test_marker_rejects_invalid(tmp_path, kind, version):
    with pytest.raises(SystemExit):
        marker.write_marker(tmp_path, kind, version)


def test_marker_cli(tmp_path, capsys):
    assert marker.main([str(tmp_path), "deb", "--version", "9.8.7"]) == 0
    assert json.loads((tmp_path / "pelicula-install.json").read_text(encoding="utf-8"))["kind"] == "deb"
    assert marker.main(["--print-version"]) == 0
    assert capsys.readouterr().out.strip().endswith(pelicula.__version__)


# ------------------------------------------------------------------ Discord
def test_discord_summary_stops_at_divider_and_skips_title():
    texto = "# Título\n\n<!-- nota -->\n## Novidades\n- um\n- dois\n![img](x.png)\n\n---\n\nDetalhes\n"
    resumo = discord.resumo_novidades(texto)
    assert resumo.splitlines()[0] == "**Novidades**"
    assert "- um" in resumo and "- dois" in resumo
    assert "Título" not in resumo and "Detalhes" not in resumo and "img" not in resumo and "nota" not in resumo


def test_discord_summary_is_truncated():
    resumo = discord.resumo_novidades("\n".join(f"- item {i}" for i in range(50)), limite=2000, linhas=5)
    assert resumo.count("- item") == 5 and resumo.endswith("…")


def test_discord_release_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "dono/repo")
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://discord.com/api/webhooks/123/segredo")
    nomes = ["PeliculaConverter-v1.1.0-windows-x64.msi", "PeliculaConverter-v1.1.0-windows-x64.zip",
             "PeliculaConverter-v1.1.0-linux-x64.deb", "PeliculaConverter-v1.1.0-linux-x64.tar.gz",
             "SHA256SUMS.txt"]
    for n in nomes:
        (tmp_path / n).write_text("x")
    notas = tmp_path / "notas.md"
    notas.write_text("**Novo**\nCoisas boas.\n", encoding="utf-8")
    payload = discord.msg_release("v1.1.0", notas, tmp_path)
    texto = json.dumps(payload, ensure_ascii=False)
    assert "segredo" not in texto  # o webhook nunca entra na mensagem
    embed = payload["embeds"][0]
    assert embed["color"] == 0xF0A63A
    assert embed["url"] == "https://github.com/dono/repo/releases/tag/v1.1.0"
    assert "Coisas boas." in embed["description"]
    assert embed["thumbnail"]["url"].endswith("/assets/logo-256.png")
    campos = {c["name"]: c["value"] for c in embed["fields"]}
    assert set(campos) == {"Windows", "Linux", "Conferência"}
    for n in nomes:
        assert f"https://github.com/dono/repo/releases/download/v1.1.0/{n}" in texto
    assert payload["allowed_mentions"] == {"parse": []}


def test_discord_without_webhook_sends_nothing(monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_WEBHOOK", raising=False)

    def proibido(*a, **k):
        raise AssertionError("não deveria acessar a rede")

    monkeypatch.setattr(discord.urllib.request, "urlopen", proibido)
    assert discord.main(["teste"]) == 0
    assert "não definido" in capsys.readouterr().out


def test_discord_rejects_non_discord_url(monkeypatch):
    monkeypatch.setattr(discord.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert discord.enviar({"content": "x"}, "https://exemplo.com/api/webhooks/1/2") == 1


# ------------------------------------------------------------------ licença do .msi
def test_license_rtf_escapes_and_keeps_text():
    out = rtf.to_rtf("MIT {a} \\ b\nção\n")
    assert out.startswith("{\\rtf1") and out.rstrip().endswith("}")
    assert "\\{a\\} \\\\ b" in out
    assert "\\u231?\\u227?o" in out  # "ção" em Unicode RTF
    assert out.isascii()


# ------------------------------------------------------------------ receitas fixas
def test_msi_upgrade_code_never_changes():
    # Trocar o UpgradeCode quebra a atualização no lugar (o .msi novo não substituiria o antigo).
    wxs = (PKG / "windows" / "PeliculaConverter.wxs").read_text(encoding="utf-8")
    assert 'UpgradeCode="35055C18-5F06-43BC-85C7-C95E9E42F81B"' in wxs
    assert 'Scope="perUser"' in wxs and "<MajorUpgrade" in wxs
    assert 'ProgId Id="PeliculaConverter.Projeto"' in wxs and 'Extension Id="plc"' in wxs


def test_wxs_is_valid_xml():
    ET.fromstring((PKG / "windows" / "PeliculaConverter.wxs").read_bytes())


def test_desktop_entry_and_mime_type_agree():
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(PKG / "linux" / "pelicula-converter.desktop", encoding="utf-8")
    entry = cp["Desktop Entry"]
    for key in ("Name", "Name[en]", "Name[es]", "Comment", "Exec", "Icon", "MimeType", "Categories"):
        assert entry.get(key), key
    # O desktop-file-validate do Ubuntu 22.04 / Debian 12 (0.26) ainda não conhece a versão 1.5.
    assert entry["Version"] in {"1.0", "1.1", "1.2", "1.3", "1.4"}
    assert entry["Exec"].startswith("pelicula-converter ")
    assert entry["Icon"] == "pelicula-converter"
    mime = ET.parse(PKG / "linux" / "pelicula-converter.xml").getroot()
    ns = {"m": "http://www.freedesktop.org/standards/shared-mime-info"}
    tipo = mime.find("m:mime-type", ns)
    assert tipo.get("type") + ";" in entry["MimeType"]
    assert tipo.find("m:glob", ns).get("pattern") == "*.plc"


def test_spec_builds_gui_and_cli_in_one_folder():
    spec = (ROOT / "PeliculaConverter.spec").read_text(encoding="utf-8")
    assert re.search(r'CLI_NAME\s*=\s*"pelicula-cli"', spec)
    assert re.search(r"COLLECT\(\s*#[^\n]*\n\s*exe,\s*\n\s*exe_cli,", spec)
    assert (PKG / "pelicula_cli.py").is_file()
