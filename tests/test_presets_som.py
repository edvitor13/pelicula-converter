"""1.8: presets com o som de película (`somf_*`, ARQUITETURA §45.6).

Ficam no fim da lista, depois dos da 1.6 (o índice dos antigos no plugin não muda); a imagem é a do preset mais
parecido (copiada, não referenciada); o som de película vem ligado com a trilha que combina com a bitola e níveis
moderados; o módulo Beta é reconhecido para o aviso; um som curto passa pelo motor sem saturar.
"""

from __future__ import annotations

import numpy as np

from pelicula import modules, params, presets, somfilme

NEW = ["super8_caseiro_som", "16mm_arquivo_som", "cinema_anos_30", "cine_de_bairro"]
OLD_16 = ["lab_slide_reversivel", "lab_cruzado_slide_c41", "lab_vencida_18_anos", "lab_flashing_suave"]

# preset novo → (preset de onde veio a imagem, ajustes de imagem a mais, trilha)
SOURCES = {
    "super8_caseiro_som": ("super8_kodachrome", set(), "magnetica_s8"),
    "16mm_arquivo_som": ("16mm_doc", {"desg_on", "poeira", "riscos"}, "otica_16"),
    "cinema_anos_30": ("noir", {"desg_on", "riscos", "emenda_on", "emenda"}, "otica_antiga"),
    "cine_de_bairro": ("copia_70", set(), "otica_35"),
}


def test_new_presets_are_appended_after_every_old_one():
    ids = [p["id"] for p in presets.BUILTIN]
    assert ids[-len(NEW):] == NEW
    assert ids[-len(NEW) - len(OLD_16):-len(NEW)] == OLD_16, "os da 1.6 não mudam de posição"
    assert ids.index("original") == 43
    for pid in NEW:
        p = presets.BY_ID[pid]
        assert p["grupo"] in presets.GROUPS and p["nome"] and p["desc"]


def test_film_sound_is_on_with_the_matching_track():
    for pid, (_src, _extra, track) in SOURCES.items():
        v = presets.builtin_values(pid)
        assert v == params.sanitize(v)
        assert somfilme.active(v), pid
        assert v["somf_trilha"] == track and somfilme.track_of(v) == track
        assert somfilme.film_values(v) is v and somfilme.film_values(v, no_effects=True) is None
        assert "som_pelicula" in modules.used_by(v), "o aviso do módulo desligado aparece ao aplicar"
        # níveis moderados (escolhidos sem escuta)
        assert v["somf_estalos"] <= 0.7 and v["somf_poeira"] <= 0.6 and v["somf_wow"] <= 0.6
        assert v["somf_projetor"] <= 0.5 and v["somf_sala"] <= 0.6


def test_image_is_the_closest_old_preset():
    for pid, (src, extra, _track) in SOURCES.items():
        new, old = presets.builtin_values(pid), presets.builtin_values(src)
        diff = {k for k in params.PARAMS if not k.startswith("somf_") and new[k] != old[k]}
        assert diff == extra, pid
        assert not somfilme.active(old), "o preset antigo continua sem som de película"
        assert presets.BY_ID[pid]["valores"] is not presets.BY_ID[src]["valores"]


def test_old_presets_have_no_film_sound():
    for p in presets.BUILTIN:
        if p["id"] not in NEW:
            assert not somfilme.active(presets.builtin_values(p["id"])), p["id"]


def test_presets_sound_stays_below_full_scale_and_changes_the_sound():
    rate = somfilme.RATE
    t = np.arange(rate) / rate
    x = np.stack([0.7 * np.sin(2 * np.pi * 440 * t), 0.7 * np.sin(2 * np.pi * 660 * t)], 1)
    for pid in NEW:
        v = presets.builtin_values(pid)
        y = somfilme.process(x, rate, v, 24.0, 0, somfilme.events_for(v, 24.0, 24))
        assert np.isfinite(y).all() and np.abs(y).max() <= somfilme.LIMIT_CEIL + 1e-9, pid
        assert np.abs(y - x).max() > 0.01, pid
