"""Esquemas dos ajustes por clipe do modo Edição (imagem e som).

Mesma ideia de `params.py`: a interface do inspetor é gerada a partir destas seções, e o
compositor (`compositor.py`) e a mixagem de som (`audiomix.py`) leem os valores pelas chaves.
Todo padrão é neutro: um clipe recém-importado sai idêntico ao arquivo de origem.

Unidades: percentuais vão de -1 a 1 (mostrados como -100% a 100%); distâncias e posições são
frações do quadro da sequência (independentes de resolução); tempos de fade em segundos.
"""

from __future__ import annotations

from typing import Any

from .i18n import N_
from .params import B, C, F, Param, Schema, Section

# Faixas de cor do HSL: (chave, rótulo, matiz central em graus no círculo de cores RGB).
HSL_COLORS: list[tuple[str, str, float]] = [
    ("vermelho", N_("Vermelhos"), 0.0),
    ("laranja", N_("Laranjas"), 30.0),
    ("amarelo", N_("Amarelos"), 60.0),
    ("verde", N_("Verdes"), 120.0),
    ("ciano", N_("Cianos"), 180.0),
    ("azul", N_("Azuis"), 225.0),
    ("roxo", N_("Roxos"), 270.0),
    ("magenta", N_("Magentas"), 315.0),
]


def W(key, label, tip="", advanced=False) -> Param:
    """Roda de cor: ponto [x, y] no disco unitário (direção = matiz, distância = força)."""
    return Param(key, label, "wheel", (0.0, 0.0), -1.0, 1.0, 0.01, 2, "", None, tip, advanced)


def _pct(key, label, default=0.0, lo=-1.0, hi=1.0, tip="", advanced=False) -> Param:
    return F(key, label, default, lo, hi, tip=tip, advanced=advanced, percent=True)


def _hsl_params() -> list[Param]:
    out = []
    for key, _label, _hue in HSL_COLORS:
        out += [_pct(f"hsl_{key}_matiz", "Matiz", tip="Gira a cor desta faixa para as vizinhas."),
                _pct(f"hsl_{key}_sat", "Saturação"),
                _pct(f"hsl_{key}_luz", "Luminância")]
    return out


SPEED = [
    F("velocidade", "Velocidade", 1.0, 0.1, 8.0, 0.05, 2, "×",
      "Abaixo de 1× é câmera lenta; acima, acelerado. A duração do clipe muda junto."),
]

VIDEO_SECTIONS: list[Section] = [
    Section("luz", "Luz", None, [
        F("exposicao", "Exposição", 0.0, -4, 4, 0.05, 2, " EV", "Mais ou menos luz, como abrir ou fechar o diafragma."),
        _pct("contraste", "Contraste"),
        _pct("realces", "Realces", tip="Negativo recupera as partes claras; positivo clareia."),
        _pct("sombras", "Sombras", tip="Positivo clareia as partes escuras; negativo escurece."),
        _pct("brancos", "Brancos", tip="Ponto mais claro da imagem."),
        _pct("pretos", "Pretos", tip="Ponto mais escuro da imagem. Positivo levanta os pretos."),
        _pct("brilho", "Brilho dos tons médios"),
    ], "Exposição e tons"),

    Section("cor", "Cor", None, [
        F("temperatura", "Temperatura", 0.0, -100, 100, 1, 0, "", "Negativo esfria, positivo esquenta."),
        F("tonalidade", "Tonalidade", 0.0, -100, 100, 1, 0, "", "Negativo puxa para verde, positivo para magenta."),
        _pct("vibracao", "Vibração", tip="Satura mais as cores apagadas e protege a pele."),
        _pct("saturacao", "Saturação", tip="-100% deixa em preto e branco."),
        F("matiz", "Matiz", 0.0, -180, 180, 1, 0, "°", "Gira todas as cores."),
    ], "Balanço de branco e saturação"),

    Section("rodas", "Rodas de cor", None, [
        W("roda_sombras", "Sombras", "Arraste o ponto para dar cor às partes escuras. Duplo clique zera."),
        _pct("roda_sombras_luz", "Luz das sombras"),
        W("roda_meios", "Tons médios", "Arraste o ponto para dar cor aos tons médios. Duplo clique zera."),
        _pct("roda_meios_luz", "Luz dos tons médios"),
        W("roda_luzes", "Altas luzes", "Arraste o ponto para dar cor às partes claras. Duplo clique zera."),
        _pct("roda_luzes_luz", "Luz das altas luzes"),
    ], "Cor nas sombras, nos tons médios e nas altas luzes"),

    Section("curva", "Curva de tons", None, [
        _pct("curva_realces", "Realces"),
        _pct("curva_claros", "Claros"),
        _pct("curva_escuros", "Escuros"),
        _pct("curva_sombras", "Sombras"),
    ], "Ajuste fino por faixa de brilho"),

    Section("hsl", "Cor por faixa (HSL)", None, _hsl_params(), "Mude uma cor sem mexer nas outras", layout="hsl"),

    Section("detalhe", "Detalhe", None, [
        _pct("nitidez", "Nitidez", lo=0.0),
        _pct("clareza", "Clareza", tip="Contraste local: realça texturas (positivo) ou suaviza a pele (negativo)."),
        _pct("desfoque", "Desfoque", lo=0.0),
        _pct("reducao_ruido", "Redução de ruído", lo=0.0, tip="Suaviza o ruído do sensor preservando as bordas."),
    ], "Nitidez, clareza, desfoque e ruído"),

    Section("efeitos", "Efeitos", None, [
        _pct("vinheta", "Vinheta", tip="Negativo escurece as bordas; positivo clareia."),
        _pct("vinheta_tamanho", "Tamanho da vinheta", 0.5, 0.0, 1.0),
        _pct("desbotar", "Desbotar", lo=0.0, tip="Levanta os pretos e tira um pouco do contraste, como foto antiga."),
    ], "Vinheta e desbotado"),

    Section("transformar", "Enquadrar e posicionar", None, [
        C("encaixe", "Encaixe no quadro", "ajustar", [
            ("ajustar", N_("Mostrar inteiro (com barras)")), ("preencher", N_("Preencher (corta as sobras)")),
            ("esticar", N_("Esticar"))]),
        F("escala", "Escala", 1.0, 0.1, 4.0, 0.01, 2, "×"),
        _pct("pos_x", "Posição horizontal", tip="Fração da largura do quadro."),
        _pct("pos_y", "Posição vertical", tip="Fração da altura do quadro. Positivo desce."),
        F("rotacao", "Rotação", 0.0, -180, 180, 0.5, 1, "°"),
        B("espelhar_h", "Espelhar na horizontal", False),
        B("espelhar_v", "Espelhar na vertical", False),
        _pct("corte_esq", "Cortar à esquerda", lo=0.0, hi=0.5),
        _pct("corte_dir", "Cortar à direita", lo=0.0, hi=0.5),
        _pct("corte_topo", "Cortar em cima", lo=0.0, hi=0.5),
        _pct("corte_base", "Cortar embaixo", lo=0.0, hi=0.5),
        _pct("opacidade", "Opacidade", 1.0, 0.0, 1.0),
        C("mesclagem", "Mesclagem", "normal", [
            ("normal", N_("Normal")), ("tela", N_("Tela (clareia)")), ("multiplicar", N_("Multiplicar (escurece)")),
            ("sobrepor", N_("Sobrepor (contraste)")), ("adicionar", N_("Adicionar (luz)")),
            ("clarear", N_("Só o mais claro")), ("escurecer", N_("Só o mais escuro"))],
          "Como este clipe se mistura com as faixas de baixo."),
    ], "Escala, posição, rotação, corte e opacidade"),

    Section("tempo", "Velocidade", None, SPEED + [
        B("congelar", "Congelar quadro", False, "Mostra só o primeiro quadro do clipe pelo tempo todo."),
    ], "Câmera lenta, acelerado e quadro congelado"),

    Section("transicao", "Transições", None, [
        C("entrada_tipo", "Entrada", "corte", [
            ("corte", N_("Corte seco")), ("dissolver", N_("Dissolver com o clipe anterior")),
            ("preto", N_("Surgir do preto")), ("branco", N_("Surgir do branco"))]),
        F("entrada_dur", "Duração da entrada", 1.0, 0.04, 5.0, 0.04, 2, " s"),
        C("saida_tipo", "Saída", "corte", [
            ("corte", N_("Corte seco")), ("preto", N_("Sumir no preto")), ("branco", N_("Sumir no branco")),
            ("transparente", N_("Sumir (mostra a faixa de baixo)"))]),
        F("saida_dur", "Duração da saída", 1.0, 0.04, 5.0, 0.04, 2, " s"),
    ], "Dissolver, surgir do preto e sumir"),
]

AUDIO_SECTIONS: list[Section] = [
    Section("som", "Som", None, [
        F("volume", "Volume", 0.0, -60, 12, 0.5, 1, " dB"),
        B("mudo", "Mudo", False),
        _pct("balanco", "Balanço", tip="Negativo puxa para a esquerda; positivo para a direita."),
        F("fade_in", "Aumentar no início", 0.0, 0, 10, 0.1, 1, " s"),
        F("fade_out", "Diminuir no fim", 0.0, 0, 10, 0.1, 1, " s"),
    ], "Volume, balanço e fades"),

    Section("eq", "Equalizar e limpar", None, [
        F("graves", "Graves", 0.0, -12, 12, 0.5, 1, " dB"),
        F("medios", "Médios", 0.0, -12, 12, 0.5, 1, " dB"),
        F("agudos", "Agudos", 0.0, -12, 12, 0.5, 1, " dB"),
        B("voz", "Realçar voz", False, "Corta o grave abafado e comprime de leve: a fala fica mais clara."),
        _pct("reducao_ruido", "Redução de ruído", lo=0.0, tip="Diminui chiado e zumbido constantes."),
        B("normalizar", "Normalizar volume", False, "Deixa o volume parecido ao longo do clipe (-16 LUFS)."),
    ], "Graves, agudos, voz e ruído"),

    Section("tempo", "Velocidade", None, list(SPEED), "Acompanha o vídeo ligado"),
]

VIDEO = Schema(VIDEO_SECTIONS)
AUDIO = Schema(AUDIO_SECTIONS)
SCHEMAS = {"video": VIDEO, "audio": AUDIO}

# Ajustes rápidos do inspetor: valores que substituem os da seção de cor e luz (o resto fica).
QUICK_LOOKS: list[tuple[str, str, dict[str, Any]]] = [
    ("vivo", N_("Mais vivo"), dict(contraste=0.15, vibracao=0.35, saturacao=0.05, clareza=0.15)),
    ("quente", N_("Quente"), dict(temperatura=22, tonalidade=4, vibracao=0.1)),
    ("frio", N_("Frio"), dict(temperatura=-22, tonalidade=-2)),
    ("suave", N_("Suave"), dict(contraste=-0.2, realces=-0.25, sombras=0.2, clareza=-0.15)),
    ("contraste", N_("Contraste"), dict(contraste=0.35, pretos=-0.15, brancos=0.1, clareza=0.1)),
    ("pb", N_("Preto e branco"), dict(saturacao=-1.0, contraste=0.2)),
    ("antigo", N_("Antigo"), dict(desbotar=0.35, saturacao=-0.25, temperatura=12, vinheta=-0.35)),
]

# Chaves zeradas por "Restaurar cor" (tudo que não é enquadramento, tempo nem transição).
COLOR_SECTIONS = ("luz", "cor", "rodas", "curva", "hsl", "detalhe", "efeitos")


def color_keys() -> list[str]:
    return [p.key for s in VIDEO_SECTIONS if s.key in COLOR_SECTIONS for p in s.params]


def apply_quick_look(values: dict[str, Any], key: str) -> dict[str, Any]:
    """Valores do clipe com um ajuste rápido: zera a cor (`color_keys`) e aplica o do ajuste."""
    out = VIDEO.sanitize(values)
    base = VIDEO.defaults()
    for k in color_keys():
        out[k] = base[k]
    look = next((v for k, _label, v in QUICK_LOOKS if k == key), None)
    if look:
        out.update(look)
    return VIDEO.sanitize(out)


def is_neutral(kind: str, values: dict[str, Any]) -> bool:
    """True se todos os ajustes do clipe estão no padrão (o clipe sai igual ao arquivo)."""
    schema = SCHEMAS[kind]
    return schema.sanitize(values) == schema.defaults()
