"""Presets prontos e presets do usuário (sempre numa pasta APPDATA temporária)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pelicula import params, presets

IDS = [p["id"] for p in presets.BUILTIN]
FILM_IDS = [p["id"] for p in presets.BUILTIN if p["valores"] is not None]
TOGGLES = [s.toggle for s in params.SECTIONS if s.toggle]


def _norm(key, value):
    return list(value) if params.PARAMS[key].kind == "color" else value


# ------------------------------------------------------------------ prontos
def test_builtin_ids_unique_and_groups_known():
    assert len(IDS) == len(set(IDS))
    for p in presets.BUILTIN:
        assert p["grupo"] in presets.GROUPS, p["id"]
        assert p["nome"] and p["desc"]
    assert presets.DEFAULT_ID in presets.BY_ID
    assert "original" in presets.BY_ID


def test_every_group_has_presets():
    used = {p["grupo"] for p in presets.BUILTIN}
    assert used == set(presets.GROUPS)


def test_film_base_keys_are_real_params():
    unknown = set(presets.FILM_BASE) - set(params.PARAMS)
    assert not unknown


@pytest.mark.parametrize("pid", FILM_IDS)
def test_preset_keys_are_real_params(pid):
    """sanitize() descarta chaves desconhecidas em silêncio, então um erro de digitação passaria despercebido."""
    unknown = set(presets.BY_ID[pid]["valores"]) - set(params.PARAMS)
    assert not unknown, f"{pid}: chaves desconhecidas {unknown}"


@pytest.mark.parametrize("pid", FILM_IDS)
def test_preset_values_are_inside_ranges(pid):
    """Nenhum valor escrito no preset é cortado ou trocado pelo sanitize()."""
    vals = {**presets.FILM_BASE, **presets.BY_ID[pid]["valores"]}
    out = params.sanitize(vals)
    for k, v in vals.items():
        assert out[k] == _norm(k, v), f"{pid}.{k}: {v!r} virou {out[k]!r}"


@pytest.mark.parametrize("pid", IDS)
def test_builtin_values_are_complete_and_sanitized(pid):
    v = presets.builtin_values(pid)
    assert set(v) == set(params.PARAMS)
    assert params.sanitize(v) == v


@pytest.mark.parametrize("pid", FILM_IDS)
def test_film_presets_differ_from_defaults(pid):
    v = presets.builtin_values(pid)
    assert v != params.defaults()
    # Todo preset de película liga pelo menos um efeito.
    assert any(v[t] for t in TOGGLES), pid
    # E aplica tudo o que o preset declara.
    for k, val in presets.BY_ID[pid]["valores"].items():
        assert v[k] == _norm(k, val)


@pytest.mark.parametrize("pid, expected", [
    ("vision3_250d", dict(cor_on=True, grao_on=True, copia="k2383", bitola="35mm")),
    ("super8_kodachrome", dict(bitola="super8", proj_on=True, mold_on=True, proporcao="bitola")),
    ("35mm_scope", dict(mold_on=True, proporcao="2.39")),
    ("65mm_epico", dict(bitola="65mm", proporcao="2.20")),
    ("double_x", dict(pb=True, grao_cor=0.0, copia="nenhuma")),
    ("sepia", dict(pb=True, virada="sepia", desg_on=True)),
    ("so_textura", dict(cor_on=False, grao_on=True)),
    ("scan_35mm", dict(scan_on=True, scan_formato="35mm")),
    ("cinestill_800t", dict(hal_on=True, hal_cor=[1.0, 0.16, 0.05])),
])
def test_known_presets_spot_checks(pid, expected):
    if pid not in presets.BY_ID:
        pytest.skip(f"preset {pid} não existe mais")
    v = presets.builtin_values(pid)
    for k, val in expected.items():
        assert v[k] == val, f"{pid}.{k}"


def test_bw_presets_have_monochrome_grain_and_no_split_toning():
    for pid in FILM_IDS:
        v = presets.builtin_values(pid)
        if v["pb"]:
            assert v["grao_cor"] == 0.0, pid
            assert v["sombras_forca"] == 0.0 and v["luzes_forca"] == 0.0, pid


def test_original_disables_everything():
    v = presets.builtin_values("original")
    for t in TOGGLES:
        assert v[t] is False, t
    assert v["bitola"] == "nenhuma"
    assert v["copia"] == "nenhuma"
    assert v["mix_geral"] == 1.0
    d = params.defaults()
    d["bitola"] = "nenhuma"
    assert v == d


def test_builtin_values_returns_fresh_dict():
    a = presets.builtin_values("vision3_250d")
    a["exposicao"] = 2.5
    a["hal_cor"][0] = 0.0
    b = presets.builtin_values("vision3_250d")
    assert b["exposicao"] != 2.5
    assert b["hal_cor"][0] != 0.0
    o = presets.builtin_values("original")
    o["cor_on"] = True
    assert presets.builtin_values("original")["cor_on"] is False


def test_builtin_values_unknown_id_raises():
    with pytest.raises(KeyError):
        presets.builtin_values("nao_existe")


# ------------------------------------------------------------------ usuário
def test_user_dir_is_redirected(tmp_appdata):
    d = presets.user_dir()
    assert d == tmp_appdata / "PeliculaConverter" / "presets"
    assert d.is_dir()


@pytest.mark.parametrize("name, slug", [
    ("Meu Look", "Meu_Look"), ("a/b:c*?", "abc"), ("  espaços  ", "espaços"), ("Película ç", "Película_ç"),
    ("???", "preset"), ("x" * 200, "x" * 80), ("look-1", "look-1"),
])
def test_slug(name, slug):
    assert presets._slug(name) == slug


def test_user_preset_save_list_import_export_delete_roundtrip(tmp_appdata, tmp_path):
    vals = presets.builtin_values("vision3_500t")
    vals["exposicao"] = 0.5
    vals["hal_cor"] = [0.9, 0.2, 0.1]

    assert presets.list_user() == []
    assert not presets.user_exists("Meu Look 1")
    pid = presets.save_user("Meu Look 1", vals, "minha descrição")
    assert pid == "user:Meu_Look_1"
    assert presets.user_exists("Meu Look 1")
    f = presets.user_dir() / "Meu_Look_1.json"
    assert f.is_file() and str(f).startswith(str(tmp_appdata))
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["nome"] == "Meu Look 1" and data["app"] == "PeliculaConverter" and data["valores"] == vals

    lst = presets.list_user()
    assert len(lst) == 1
    e = lst[0]
    assert e["id"] == pid and e["nome"] == "Meu Look 1" and e["desc"] == "minha descrição"
    assert e["grupo"] == "Meus presets" and e["valores"] == vals and Path(e["arquivo"]) == f

    # exportar para outro lugar e importar de volta: o nome repetido ganha um número
    exp = tmp_path / "exportado.json"
    presets.export_file(str(exp), "Meu Look 1", vals)
    exported = json.loads(exp.read_text(encoding="utf-8"))
    assert exported["nome"] == "Meu Look 1" and exported["valores"] == vals
    pid2 = presets.import_file(str(exp))
    pid3 = presets.import_file(str(exp))
    assert pid2 != pid and pid3 not in (pid, pid2)
    names = sorted(p["nome"] for p in presets.list_user())
    assert names == ["Meu Look 1", "Meu Look 1 (2)", "Meu Look 1 (3)"]
    for p in presets.list_user():
        assert p["valores"] == vals

    # apagar
    for p in presets.list_user():
        presets.delete_user(p["id"])
    assert presets.list_user() == []
    assert not presets.user_exists("Meu Look 1")
    assert list(presets.user_dir().glob("*.json")) == []


def test_export_file_replaces_the_old_file_without_leaving_partials(tmp_path):
    exp = tmp_path / "look.json"
    exp.write_text("preset antigo", encoding="utf-8")
    presets.export_file(str(exp), "Novo", params.defaults())
    assert json.loads(exp.read_text(encoding="utf-8"))["nome"] == "Novo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["look.json"]


def test_save_user_overwrites_same_name(tmp_appdata):
    a = params.defaults()
    b = params.defaults()
    b["exposicao"] = 1.0
    presets.save_user("Mesmo", a)
    presets.save_user("Mesmo", b)
    lst = presets.list_user()
    assert len(lst) == 1 and lst[0]["valores"]["exposicao"] == 1.0


def test_list_user_sanitizes_and_skips_broken_files(tmp_appdata):
    d = presets.user_dir()
    (d / "quebrado.json").write_text("{isto não é json", encoding="utf-8")
    (d / "fora_da_faixa.json").write_text(json.dumps({"nome": "Fora", "valores": {"exposicao": 50, "bitola": "x"}}),
                                          encoding="utf-8")
    (d / "sem_nome.json").write_text(json.dumps({"valores": {}}), encoding="utf-8")
    (d / "nao_e_preset.txt").write_text("ignorar", encoding="utf-8")
    lst = {p["id"]: p for p in presets.list_user()}
    assert set(lst) == {"user:fora_da_faixa", "user:sem_nome"}
    assert lst["user:fora_da_faixa"]["valores"]["exposicao"] == 3.0
    assert lst["user:fora_da_faixa"]["valores"]["bitola"] == params.PARAMS["bitola"].default
    assert lst["user:sem_nome"]["nome"] == "sem_nome"
    assert lst["user:sem_nome"]["valores"] == params.defaults()


def test_import_file_without_name_uses_file_stem_and_sanitizes(tmp_appdata, tmp_path):
    src = tmp_path / "Look Externo.json"
    src.write_text(json.dumps({"valores": {"grao_forca": 99, "cor_on": True}, "desc": "veio de fora"}),
                   encoding="utf-8")
    pid = presets.import_file(str(src))
    e = next(p for p in presets.list_user() if p["id"] == pid)
    assert e["nome"] == "Look Externo" and e["desc"] == "veio de fora"
    assert e["valores"]["grao_forca"] == params.PARAMS["grao_forca"].max
    assert e["valores"]["cor_on"] is True


def test_delete_user_ignores_builtin_and_missing(tmp_appdata):
    presets.save_user("Fica", params.defaults())
    presets.delete_user("vision3_250d")
    presets.delete_user("user:nao_existe")
    assert presets.user_exists("Fica")


def test_user_presets_never_touch_real_appdata(tmp_appdata):
    assert os.environ["APPDATA"] == str(tmp_appdata)
    presets.save_user("Isolado", params.defaults())
    assert (tmp_appdata / "PeliculaConverter" / "presets" / "Isolado.json").is_file()
