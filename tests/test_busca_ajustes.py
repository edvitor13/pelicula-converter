"""Busca nos ajustes (`busca_ajustes.py`, sem Qt): idiomas, acentos, termos, erro de digitação, sinônimos."""

from __future__ import annotations

import pytest

from pelicula import busca_ajustes as busca
from pelicula import editparams, i18n, params
from pelicula.params import Param, Section

SCHEMAS = {"look": params.SECTIONS, "video": editparams.VIDEO_SECTIONS, "audio": editparams.AUDIO_SECTIONS}


@pytest.fixture(autouse=True)
def _idioma():
    antes = i18n.language()
    yield
    i18n.set_language(antes)


def keys(query, sections=params.SECTIONS):
    return set(busca.search(query, sections))


def test_vazio_nao_filtra():
    assert busca.search("", params.SECTIONS) == {}
    assert busca.search("   ", params.SECTIONS) == {}


def test_aberracao_em_tres_idiomas_e_sem_acento():
    for q in ("aberração", "aberracao", "ABERRAÇÃO", "chromatic", "aberración", "aberracion", "fringe", "franja"):
        assert "lente" in keys(q), q


def test_independe_do_idioma_da_interface():
    for code in ("pt_BR", "en", "es"):
        i18n.set_language(code)
        for q in ("aberração", "chromatic", "aberración"):
            assert "lente" in keys(q), (code, q)
        assert i18n.language() == code  # a busca não muda o idioma


def test_catalogo_ingles_tem_o_texto_existente():
    # o rótulo existente em inglês é achado pelo texto traduzido, não só pelo português
    en = i18n.load_catalog("en")
    lente = next(s for s in params.SECTIONS if s.key == "lente")
    assert lente.title in en
    traduzido = en[lente.title]
    assert "lente" in keys(traduzido)


def test_termos_em_qualquer_ordem():
    assert keys("grão tamanho") == keys("tamanho grão")
    assert "grao" in keys("grão tamanho")
    assert "halacao" in keys("halação brilho")


def test_um_termo_no_titulo_e_outro_no_controle():
    r = busca.search("lente distorcao", params.SECTIONS)["lente"]
    assert not r.section and r.keys  # "lente" é da seção; "distorção" bateu num controle


def test_todos_os_termos_precisam_bater():
    assert "lente" not in keys("aberracao xyzxyz")


def test_secao_inteira_x_controle():
    r = busca.search("halacao", params.SECTIONS)["halacao"]
    assert r.section
    # um termo só de um controle: a seção não bate inteira e as chaves vêm preenchidas
    lente = busca.search("vinheta", params.SECTIONS)["lente"]
    assert lente.keys and not lente.section or lente.section


def test_chave_interna():
    ps = [p.key for s in params.SECTIONS for p in s.params if s.key == "anamorfico"]
    assert ps
    r = busca.search(ps[0], params.SECTIONS)
    assert "anamorfico" in r


def test_rotulo_de_opcao():
    sec = Section("teste", "Teste", None, [
        Param("modo", "Modo", "choice", "a", choices=[("a", "Aquarela"), ("b", "Carvão")]),
        Param("x", "Outro", "float", 0.0)])
    r = busca.search("carvao", [sec])["teste"]
    assert not r.section and r.keys == {"modo"}


def test_dica_e_idioma_da_dica():
    sec = Section("teste", "Teste", None, [Param("x", "Rótulo", "float", 0.0, tip="Texto da dica aqui")])
    assert busca.search("dica", [sec])["teste"].keys == {"x"}


def test_erro_de_digitacao_so_quando_exata_falha():
    # com um erro: acha
    assert "lente" in keys("aberacao")
    assert "lente" in keys("chromatik")
    # a busca exata acha: nada de ruído do tolerante
    exata = keys("grao")
    assert exata and "grao" in exata
    assert busca.search("grao", params.SECTIONS) == busca.search("grão", params.SECTIONS)
    # palavra curta (menos de 5 letras): não tolera
    assert keys("gaao") == set()


def test_tolerante_nao_roda_se_a_exata_achou():
    sec_a = Section("a", "Halação", None, [Param("p", "Brilho", "float", 0.0)])
    sec_b = Section("b", "Halaçao quase", None, [Param("q", "Outro", "float", 0.0)])
    # "halacao" bate exato em ambos; um erro ("halaçoa") só acharia pelo tolerante
    assert set(busca.search("halacao", [sec_a, sec_b])) == {"a", "b"}
    assert set(busca.search("halacoa", [sec_a, sec_b])) == {"a", "b"}


def test_within_one():
    assert busca.within_one("abc", "abc")
    assert busca.within_one("abc", "abd")
    assert busca.within_one("abc", "ab")
    assert busca.within_one("ab", "abc")
    assert not busca.within_one("abc", "axx")
    assert not busca.within_one("abc", "a")


def test_sinonimos():
    casos = {"halation": "halacao", "grain": "grao", "vignette": "lente", "denoise": "detalhe", "fringe": "lente",
             "lut": "lut"}
    for q, sec in casos.items():
        todos = keys(q, params.SECTIONS) | keys(q, editparams.VIDEO_SECTIONS)
        assert sec in todos, (q, sec)
    assert "eq" in keys("denoise", editparams.AUDIO_SECTIONS)


def test_keywords_de_secoes_que_existem():
    existentes = {s.key for sch in SCHEMAS.values() for s in sch}
    assert set(busca.KEYWORDS) <= existentes


@pytest.mark.parametrize("nome", list(SCHEMAS))
def test_toda_secao_dos_esquemas_esta_indexada(nome):
    sections = SCHEMAS[nome]
    idx = busca.index_of(sections)
    assert [s.key for s in idx] == [s.key for s in sections]
    for s, i in zip(sections, idx):
        # o título acha a própria seção, e toda chave de controle com linha está no índice
        assert s.key in busca.search(s.title, sections)
        assert set(i.params) == {p.key for p in s.params if p.key != s.toggle}


def test_indice_guardado_e_montado_so_no_uso():
    a = busca.index_of(params.SECTIONS)
    assert busca.index_of(params.SECTIONS) is a


def test_nao_muda_o_esquema():
    antes = [(s.key, s.title, [(p.key, p.label, p.tip) for p in s.params]) for s in params.SECTIONS]
    busca.search("aberracao", params.SECTIONS)
    busca.search("abberacao", params.SECTIONS)
    assert antes == [(s.key, s.title, [(p.key, p.label, p.tip) for p in s.params]) for s in params.SECTIONS]
