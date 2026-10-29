"""Módulos da cor da 1.6: "cor_planos" (Beta, desligado) e "cor_simples" (estável, do perfil Criador).

Desligar só esconde a ferramenta: a renderização (look, montagem, LUT, plugin) nunca consulta `modules`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from pelicula import modules, params
from pelicula import timeline as tl

ROOT = Path(__file__).resolve().parents[1] / "pelicula"
RENDER_FILES = ("masks.py", "planes.py", "colorsimple.py", "exposure.py", "look.py", "compositor.py", "engine.py",
                "editshaders.py", "shaders.py", "frame.py")


class FakeSettings(dict):
    def value(self, key, default=None):
        return self.get(key, default)

    def setValue(self, key, value):  # noqa: N802
        self[key] = value


def test_status_and_profiles():
    assert modules.get("cor_planos").status == modules.BETA
    assert modules.get("cor_simples").status == modules.ESTAVEL
    s = FakeSettings()
    assert not modules.is_enabled(s, "cor_planos") and modules.is_enabled(s, "cor_simples")
    profiles = {pid: ids for pid, _n, _d, ids in modules.PROFILES}
    assert "cor_simples" not in profiles["simples"]
    assert {"cor_simples"} <= profiles["criador"] & profiles["cinema"] & profiles["tudo"]
    assert all("cor_planos" not in ids for ids in profiles.values())  # Beta nunca vem de perfil
    for pid in ("simples", "criador"):
        s = FakeSettings()
        modules.apply_profile(s, pid)
        assert modules.is_enabled(s, "cor_simples") == (pid == "criador")
        assert not modules.is_enabled(s, "cor_planos")
    # quem escolheu o Simples antes da 1.6 não ganha a ferramenta ao atualizar
    s = FakeSettings({modules.KEY_PROFILE: "simples"})
    assert not modules.is_enabled(s, "cor_simples")


def test_used_by_planes_only_when_it_does_something():
    v = params.defaults()
    assert "cor_planos" not in modules.used_by(v)
    v["planos_on"] = True
    assert "cor_planos" not in modules.used_by(v)  # ligada, mas tudo em zero
    v["planos_fundo_exposicao"] = -0.5
    assert "cor_planos" in modules.used_by(v)


def test_used_by_simple_color_in_a_clip_or_a_group():
    src = tl.Source("C:/v/a.mp4", 1920, 1080, 24.0, "24/1", 48, 2.0, has_audio=False)
    seq = tl.Sequence.for_source(src)
    assert "cor_simples" not in modules.used_by(None, seq)
    c = seq.clips[0]
    seq.set_values(c.id, {**c.values, "alvo_matiz": 120.0})  # só a cor procurada: nada muda na imagem
    assert "cor_simples" not in modules.used_by(None, seq)
    seq.set_values(c.id, {**c.values, "pele_natural": 0.4})
    assert "cor_simples" in modules.used_by(None, seq)
    seq.set_values(c.id, {**c.values, "pele_natural": 0.0})
    c.color_group = "g"
    assert "cor_simples" in modules.used_by(None, seq)


def test_render_never_reads_modules():
    for name in RENDER_FILES:
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "modules" not in [a.name for a in node.names] and node.module != "modules", name
            if isinstance(node, ast.Import):
                assert all(not a.name.endswith("modules") for a in node.names), name
