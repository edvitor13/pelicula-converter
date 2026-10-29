"""1.6, máquina do tempo (`maquina.py`): a tabela cobre 1920–2020 em cada lugar, toda linha é válida e explicada,
aplicar só mexe nas chaves da tabela e o resultado não depende do que estava nelas."""

from __future__ import annotations

import pytest

from pelicula import maquina, modules, params, presets, tempo_camera


def test_every_row_is_valid_and_explained():
    for row in maquina.ROWS:
        v = row.full_values()
        assert set(row.values) <= set(maquina.KEYS), row.title
        clean = params.sanitize(v)
        for k in maquina.KEYS:
            assert clean[k] == v[k], (row.title, k, v[k])  # o valor existe (escolha válida, dentro da faixa)
        assert row.reason and row.title and row.start <= row.end
        assert row.cadence in ("",) + tuple(c for c, _l in tempo_camera.CRANKS), row.cadence


@pytest.mark.parametrize("venue", [v for v, _l in maquina.VENUES])
def test_years_are_covered_without_gaps(venue):
    rows = sorted((r for r in maquina.ROWS if r.venue == venue), key=lambda r: r.start)
    assert rows[0].start == maquina.YEAR_MIN and rows[-1].end == maquina.YEAR_MAX
    for a, b in zip(rows, rows[1:]):
        assert b.start == a.end + 1
    for y in range(maquina.YEAR_MIN, maquina.YEAR_MAX + 1):
        assert maquina.row_for(y, venue).venue == venue


def test_apply_touches_only_the_table_keys_and_ignores_what_was_there():
    a = presets.values_for(presets.DEFAULT_ID) if hasattr(presets, "values_for") else params.defaults()
    b = params.sanitize({**params.defaults(), "pb": True, "bitola": "imax", "grao_forca": 2.5, "exposicao": 1.0})
    for year, venue in ((1925, "cinema"), (1975, "caseiro"), (1999, "tv"), (2015, "cinema")):
        ra, rb = maquina.apply(a, year, venue), maquina.apply(b, year, venue)
        assert {k: ra[k] for k in maquina.KEYS} == {k: rb[k] for k in maquina.KEYS}
        assert rb["exposicao"] == 1.0, "fora da tabela, o look fica como estava"
        assert {k for k, _x, _y in maquina.changes(b, rb)} <= set(maquina.KEYS)
    assert maquina.row_for(1800, "cinema").start == 1920 and maquina.row_for(2100, "tv").end == 2020


def test_known_eras():
    assert maquina.apply(params.defaults(), 1925, "cinema")["pb"] is True
    assert maquina.apply(params.defaults(), 1955, "cinema")["proporcao"] == "2.39"
    assert maquina.apply(params.defaults(), 1975, "caseiro")["bitola"] == "super8"
    assert maquina.row_for(1975, "caseiro").cadence == "18"
    assert maquina.apply(params.defaults(), 1950, "caseiro")["bitola"] == "8mm"


def test_module_is_stable_and_in_the_creator_profile():
    m = modules.get("maquina_tempo")
    assert m.status == modules.ESTAVEL and m.group == "pelicula"
    assert any(p[0] == "criador" and "maquina_tempo" in p[3] for p in modules.PROFILES)
