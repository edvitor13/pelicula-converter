"""Esquemas dos ajustes por clipe do modo Edição (imagem e som).

Mesma ideia de `params.py`: a interface do inspetor é gerada a partir destas seções, e o
compositor (`compositor.py`) e a mixagem de som (`audiomix.py`) leem os valores pelas chaves.
Todo padrão é neutro: um clipe recém-importado sai idêntico ao arquivo de origem.

Unidades: percentuais vão de -1 a 1 (mostrados como -100% a 100%); distâncias e posições são
frações do quadro da sequência (independentes de resolução); tempos de fade em segundos.
"""

from __future__ import annotations

import copy
from typing import Any

from .i18n import N_
from .params import ENTRADAS, LOGC3_EIS, B, C, F, I, Param, Schema, Section

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
        # 1.7: desespremer do clipe (`compositor.desqueeze`), antes do encaixe; a Lente anamórfica do look é outra coisa.
        C("desespremer", "Desespremer", "nao", [
            ("nao", N_("Não")), ("1.33", N_("1,33×")), ("1.5", N_("1,5×")), ("1.55", N_("1,55×")), ("1.8", N_("1,8×")),
            ("2.0", N_("2×")), ("manual", N_("Taxa manual"))],
          "Para vídeo filmado com lente ou adaptador anamórfico: o clipe fica mais largo antes de se encaixar no "
          "quadro. \"Esticar\" ignora este ajuste."),
        F("desespremer_taxa", "Taxa manual", 1.0, 1.0, 2.5, 0.01, 2, "×", "A compressão da lente, se não está na lista."),
        F("escala", "Escala", 1.0, 0.1, 4.0, 0.01, 2, "×"),
        # 1.7: escala por eixo (multiplica a "Escala", que é o controle proporcional); a rotação vem depois.
        F("escala_x", "Escala horizontal", 1.0, 0.1, 4.0, 0.01, 2, "×",
          "Só a largura do clipe, antes da rotação; multiplica a Escala."),
        F("escala_y", "Escala vertical", 1.0, 0.1, 4.0, 0.01, 2, "×",
          "Só a altura do clipe, antes da rotação; multiplica a Escala."),
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
            ("clarear", N_("Só o mais claro")), ("escurecer", N_("Só o mais escuro")),
            # 1.9: modos novos (`mesclagem.py`; ids 7 em diante em `compositor.BLEND_IDS`)
            ("diferenca", N_("Diferença")), ("exclusao", N_("Exclusão")), ("luz_suave", N_("Luz suave")),
            ("luz_forte", N_("Luz forte")), ("subtrair", N_("Subtrair")), ("dividir", N_("Dividir")),
            ("matiz", N_("Matiz")), ("saturacao_m", N_("Saturação")), ("cor", N_("Cor")),
            ("luminosidade", N_("Luminosidade"))],
          "Como este clipe se mistura com as faixas de baixo."),
    ], "Escala, posição, rotação, corte e opacidade"),

    Section("tempo", "Velocidade", None, SPEED + [
        B("congelar", "Congelar quadro", False, "Mostra só o primeiro quadro do clipe pelo tempo todo."),
    ], "Câmera lenta, acelerado e quadro congelado"),

    Section("transicao", "Transições", None, [
        C("entrada_tipo", "Entrada", "corte", [
            ("corte", N_("Corte seco")), ("dissolver", N_("Dissolver com o clipe anterior")),
            ("preto", N_("Surgir do preto")), ("branco", N_("Surgir do branco")),
            # 1.5 (`transitions.py`, módulo "transicoes"): só acrescentar no fim, nunca renomear.
            ("fusao", N_("Fusão ótica (soma as exposições)")), ("exposicao", N_("Surgir do preto na exposição")),
            ("queima", N_("Queima da película")), ("emenda", N_("Emenda com clarão")),
            ("ponta", N_("Ponta entre os planos")), ("iris", N_("Íris (abre um círculo)")),
            ("empurrar", N_("Empurrar")), ("cortina", N_("Cortina")), ("zoom", N_("Zoom (atravessa o corte)"))]),
        F("entrada_dur", "Duração da entrada", 1.0, 0.04, 5.0, 0.04, 2, " s"),
        C("entrada_direcao", "Direção", "direita", [
            ("direita", N_("Vem da direita")), ("esquerda", N_("Vem da esquerda")), ("baixo", N_("Vem de baixo")),
            ("cima", N_("Vem de cima"))], "De que lado o clipe novo entra."),
        F("entrada_suavidade", "Suavidade da borda", 24.0, 0, 300, 1, 0, " px",
          "Largura da borda suave, em pixels de um quadro de 1080 linhas (0 = borda dura)."),
        _pct("entrada_centro_x", "Centro horizontal", lo=-0.5, hi=0.5,
             tip="Onde a transição começa: fração da largura do quadro (0 = meio)."),
        _pct("entrada_centro_y", "Centro vertical", lo=-0.5, hi=0.5,
             tip="Onde a transição começa: fração da altura do quadro (0 = meio; positivo desce)."),
        F("entrada_anel", "Anel preto", 0.0, 0, 200, 1, 0, " px",
          "Anel preto em volta do círculo, como nos filmes mudos (0 = sem anel)."),
        C("entrada_ponta", "Ponta", "preta", [("preta", N_("Ponta preta")), ("clara", N_("Ponta clara"))],
          "A ponta é a película sem imagem do começo e do fim dos rolos: preta, ou clara (transparente)."),
        F("entrada_zoom", "Ampliação", 2.0, 1.1, 4.0, 0.05, 2, "×", "Quanto a imagem amplia no meio da transição."),
        F("entrada_quadros", "Quadros do clarão", 2.0, 1, 3, 1, 0, "",
          "Quantos quadros estouram de luz na emenda (1 a 3)."),
        F("entrada_clarao", "Força do clarão", 2.0, 0.5, 4.0, 0.1, 1, " EV",
          "Quanto a luz estoura no quadro da emenda, em pontos de exposição."),
        C("saida_tipo", "Saída", "corte", [
            ("corte", N_("Corte seco")), ("preto", N_("Sumir no preto")), ("branco", N_("Sumir no branco")),
            ("transparente", N_("Sumir (mostra a faixa de baixo)")),
            # 1.5 (`transitions.py`, módulo "transicoes"): só acrescentar no fim, nunca renomear.
            ("exposicao", N_("Escurecer na exposição")),
            ("queima", N_("Queimar a película (mostra a faixa de baixo)")), ("iris", N_("Íris (fecha o círculo)"))]),
        F("saida_dur", "Duração da saída", 1.0, 0.04, 5.0, 0.04, 2, " s"),
        F("saida_suavidade", "Suavidade da borda", 24.0, 0, 300, 1, 0, " px",
          "Largura da borda suave, em pixels de um quadro de 1080 linhas (0 = borda dura)."),
        _pct("saida_centro_x", "Centro horizontal", lo=-0.5, hi=0.5,
             tip="Para onde a transição fecha: fração da largura do quadro (0 = meio)."),
        _pct("saida_centro_y", "Centro vertical", lo=-0.5, hi=0.5,
             tip="Para onde a transição fecha: fração da altura do quadro (0 = meio; positivo desce)."),
        F("saida_anel", "Anel preto", 0.0, 0, 200, 1, 0, " px",
          "Anel preto em volta do círculo, como nos filmes mudos (0 = sem anel)."),
    ], "Dissolver, surgir do preto e sumir"),

    # 1.6 (`camera.py`): perfil de câmera do clipe. "look" segue a entrada do look, como antes (bit a bit).
    Section("camera", "Câmera", None, [
        C("camera_entrada", "Perfil do clipe", "look", [("look", N_("Igual ao do look"))] + list(ENTRADAS),
          "Como este clipe foi gravado, para misturar câmeras numa montagem: o clipe é convertido para o perfil do "
          "look (Película › Entrada e exposição), que lê a montagem inteira. “Igual ao do look” deixa o clipe "
          "como está."),
        B("camera_reescalado", "Log reescalado (HDMI “Limited”)", False,
          "Só para S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log: ligue se este clipe veio de uma gravação externa "
          "com o log já reescalado para a faixa legal (saída HDMI em “Limited”).", advanced=True),
        C("camera_ei", "EI do ARRI LogC3", "800", LOGC3_EIS,
          "Só para o ARRI LogC3: o EI com que este clipe foi gravado (está nos metadados do clipe).", advanced=True),
    ], "Perfil de cor da câmera deste clipe"),
]

# 1.6, cor simples (`colorsimple.py`, módulo "cor_simples"): seções de cor novas, acrescentadas no fim (o inspetor as
# mostra perto das parecidas: `ui/edit_panels.DISPLAY_AFTER`). Todo padrão é neutro e as chaves vão para o JSON só
# fora do padrão (`SPARSE_KEYS`). O HSL mostra só as linhas de uma faixa por vez, por isso a cor escolhida é outra
# seção.
VIDEO_SECTIONS += [
    Section("pele", "Pele natural", None, [
        _pct("pele_natural", "Pele natural", lo=0.0,
             tip="A pele não acompanha as mudanças de cor deste clipe (balanço, saturação, rodas, cor escolhida, "
                 "degradê) e fica com a cor mais uniforme. Só a cor: a textura não muda."),
        F("pele_centro", "Cor da pele", 64.5, 0, 360, 0.5, 1, "°",
          "Matiz da pele que a máscara procura (o conta-gotas da pele acerta este valor).", advanced=True),
    ], "Protege e uniformiza a cor da pele"),

    Section("alvo", "Cor escolhida", None, [
        F("alvo_matiz", "Cor", 0.0, 0, 360, 1, 0, "°",
          "A cor que muda (matiz). O conta-gotas \"Cor\" acerta este valor clicando na prévia."),
        F("alvo_largura", "Largura", 30.0, 5, 90, 1, 0, "°", "Quanto o matiz pode se afastar da cor escolhida."),
        F("alvo_desvio", "Matiz", 0.0, -180, 180, 1, 0, "°", "Gira a cor escolhida para outra."),
        _pct("alvo_sat", "Saturação"),
        _pct("alvo_luz", "Luminância"),
    ], "Clique numa cor da prévia e mude só ela"),

    Section("degrade", "Degradê", None, [
        C("degrade_tipo", "Forma", "linear", [("linear", N_("Linear (céu ou chão)")),
                                              ("radial", N_("Radial (dentro do círculo)"))]),
        F("degrade_angulo", "Direção", 0.0, -180, 180, 1, 0, "°",
          "Que lado muda no degradê linear: 0° = em cima (céu), 90° = à direita, 180° = embaixo (chão)."),
        F("degrade_x", "Centro horizontal", 0.0, -1920, 1920, 10, 0, " px",
          "Desloca a linha ou o círculo (px de um quadro de 1080 linhas do clipe; 0 = centro)."),
        F("degrade_y", "Centro vertical", 0.0, -1080, 1080, 10, 0, " px", "Negativo sobe; positivo desce."),
        F("degrade_raio", "Raio", 500.0, 10, 2000, 10, 0, " px", "Tamanho do círculo do degradê radial."),
        F("degrade_suavidade", "Suavidade", 400.0, 0, 2000, 10, 0, " px",
          "Largura da passagem (0 = borda seca)."),
        B("degrade_inverter", "Inverter", False, "Troca o lado que muda."),
        F("degrade_exposicao", "Exposição", 0.0, -3, 3, 0.05, 2, " EV", "Mais ou menos luz só no lado marcado."),
        F("degrade_temperatura", "Temperatura", 0.0, -100, 100, 1, 0, "", "Negativo esfria, positivo esquenta."),
        F("degrade_tonalidade", "Tonalidade", 0.0, -100, 100, 1, 0, "",
          "Negativo puxa para verde, positivo para magenta."),
        _pct("degrade_saturacao", "Saturação"),
    ], "Céu ou chão com cor e luz próprias"),
]

# 1.6, manivela (`tempo_camera.py`, módulo Beta "camera_cinema"): o clipe "filmado" a 16/18 qps e projetado na taxa da
# sequência. Trocar a cadência acelera o clipe (`Sequence.set_values`: 24 ÷ 16 = 1,5×; o som segue pela velocidade); a
# oscilação da mão desloca o instante de cada imagem (`Sequence.src_frame`). Padrão: sem manivela (o clipe de sempre).
VIDEO_SECTIONS += [
    Section("manivela", "Manivela", None, [
        C("manivela", "Cadência da manivela", "nenhuma", [
            ("nenhuma", N_("Normal (sem manivela)")), ("16", N_("16 qps (cinema mudo)")),
            ("18", N_("18 qps (Super 8, manivela)")), ("20", N_("20 qps")), ("22", N_("22 qps"))],
          "Quadros por segundo em que a câmera de manivela teria filmado. Projetado na velocidade da sequência, o "
          "movimento fica mais rápido e aos saltos, como nos filmes mudos: escolher a cadência acelera o clipe "
          "(16 qps numa sequência de 24 = 1,5×) e o som acompanha pela velocidade."),
        _pct("manivela_oscila", "Oscilação da mão", lo=0.0,
             tip="A mão não gira a manivela num ritmo perfeito: a velocidade oscila um pouco, sem atrasar o clipe. "
                 "Só a imagem oscila; o som segue a velocidade média (diferença de no máximo 50 ms com 100%)."),
        I("manivela_semente", "Semente", 3, 0, 9999, "Muda o jeito da mão.", advanced=True),
    ], "Cadência de câmera de manivela (16 ou 18 qps)"),
]

# 1.6, marcação de luz por plano (`luz_plano.py`): os pontos da copiadora deste plano, somados às luzes do
# Laboratório do look nos quadros em que o clipe é o plano da V1. Só valem com o Laboratório ligado. Padrão: 0 (a
# luz do look, como antes); as chaves vão para o JSON só fora do padrão (`SPARSE_KEYS`).
VIDEO_SECTIONS += [
    Section("luz_copiadora", "Luz da copiadora", None, [
        F("luz_r", "Luz vermelha", 0.0, -24, 24, 1, 0, " pt",
          "Pontos de luz vermelha da copiadora só neste plano, somados aos do Laboratório do look (12 pontos = 1 "
          "stop da cópia; cerca de 7 pontos = 1 stop da câmera). Mais vermelho deixa a cópia mais ciano."),
        F("luz_g", "Luz verde", 0.0, -24, 24, 1, 0, " pt", "Mais verde deixa a cópia mais magenta."),
        F("luz_b", "Luz azul", 0.0, -24, 24, 1, 0, " pt", "Mais azul deixa a cópia mais amarela (quente)."),
        F("luz_densidade", "Densidade (as três)", 0.0, -24, 24, 1, 0, " pt",
          "Pontos nas três luzes juntas: mais pontos = plano mais escuro na cópia, sem mudar a cor."),
    ], "Marcação de luz deste plano (pontos da copiadora do Laboratório)"),
]

# 1.9 (#68, efeitos visuais; ARQUITETURA §49–§53): as seções dos efeitos de clipe vêm depois destas, em blocos
# reservados, um por frente, nesta ordem (acrescente só dentro do seu bloco; nunca mude a ordem dos blocos). Toda chave
# das seções depois de `_N_BASE` vai para o JSON só fora do padrão (`SPARSE_KEYS`) e todo padrão é neutro (efeito
# desligado: nenhum passo na GPU, `vfx.Effect.active`). Não ponha estas seções em `COLOR_SECTIONS`.
_N_BASE = len(VIDEO_SECTIONS)

# 1.9 F2: recorte e máscaras (§50)
# Recorte por cor ou por brilho (`recorte.py`) e máscara de forma do clipe (`mascaras_clipe.py`), módulo Beta
# "recorte_mascaras". Distâncias em px@1080 do clipe; os números animam (`_anim`). Padrão: nenhum recorte e nenhuma
# forma.
from .params import COR  # noqa: E402


def _anim(p: Param) -> Param:
    p.animatable = True
    return p


VIDEO_SECTIONS += [
    Section("recorte", "Recorte (chroma/luma)", None, [
        C("chave_tipo", "Recortar", "nenhuma", [
            ("nenhuma", N_("Nada")), ("verde", N_("Fundo verde")), ("azul", N_("Fundo azul")),
            ("cor", N_("Uma cor escolhida")), ("luma", N_("Pelo brilho"))],
          "Tira o fundo do clipe e mostra as faixas de baixo no lugar. Para uma tela verde ou azul fora do comum, "
          "use o conta-gotas: ele escolhe a cor do fundo."),
        COR("chave_cor", "Cor do fundo", (0.15, 0.70, 0.25),
            "A cor que sai em \"Uma cor escolhida\" (o conta-gotas acerta este valor clicando no fundo)."),
        _anim(_pct("chave_tolerancia", "Tolerância", 0.4, 0.0, 1.0,
                   tip="Quanto uma cor pode se afastar da cor do fundo e ainda sair. Aumente se sobrar fundo; "
                       "diminua se o recorte comer a pessoa.")),
        _anim(_pct("chave_suavidade", "Suavidade", 0.25, 0.0, 1.0,
                   tip="Largura da passagem entre o que sai e o que fica (cabelo, desfoque de movimento).")),
        _anim(F("chave_limpar", "Encolher a borda", 0.0, -20, 20, 0.5, 1, " px",
                "Positivo encolhe o recorte (tira a franja do fundo); negativo aumenta. Pixels de um quadro de "
                "1080 linhas.")),
        _anim(_pct("chave_spill", "Tirar o reflexo do fundo", 0.0, 0.0, 1.0,
                   tip="Tira a cor do fundo que respingou na pessoa (o verde no cabelo e nos ombros). Cinzas e "
                       "brancos não mudam.")),
        _anim(_pct("chave_luz_borda", "Luz do fundo na borda", 0.0, 0.0, 1.0,
                   tip="Traz a luz das faixas de baixo para a borda do recorte, como se a pessoa estivesse lá.")),
        _anim(F("chave_luz_largura", "Largura da luz na borda", 20.0, 1, 200, 1, 0, " px",
                "Até onde a luz do fundo entra na borda (pixels de um quadro de 1080 linhas).")),
        _anim(_pct("chave_luma_min", "Brilho mínimo", 0.0, 0.0, 1.0,
                   tip="\"Pelo brilho\": o que é mais escuro que isto sai.")),
        _anim(_pct("chave_luma_max", "Brilho máximo", 1.0, 0.0, 1.0,
                   tip="\"Pelo brilho\": o que é mais claro que isto sai.")),
    ], "Tirar um fundo verde, azul, de uma cor ou pelo brilho"),

    Section("mascara", "Máscara", None, [
        C("mascara_forma", "Forma", "nenhuma", [
            ("nenhuma", N_("Nenhuma")), ("retangulo", N_("Retângulo")), ("elipse", N_("Elipse")),
            ("poligono", N_("Polígono"))],
          "Uma forma no clipe: arraste as alças na prévia. No polígono, clique para pôr os pontos e dê dois "
          "cliques para fechar (Esc cancela)."),
        _anim(F("mascara_x", "Centro horizontal", 0.0, -4000, 4000, 1, 0, " px",
                "Centro da forma a partir do centro do clipe (pixels de um quadro de 1080 linhas do clipe).")),
        _anim(F("mascara_y", "Centro vertical", 0.0, -4000, 4000, 1, 0, " px", "Negativo sobe; positivo desce.")),
        _anim(F("mascara_largura", "Largura", 800.0, 1, 8000, 1, 0, " px", "Largura do retângulo ou da elipse.")),
        _anim(F("mascara_altura", "Altura", 600.0, 1, 8000, 1, 0, " px", "Altura do retângulo ou da elipse.")),
        _anim(F("mascara_rotacao", "Rotação", 0.0, -180, 180, 0.5, 1, "°",
                "Gira a forma (positivo: sentido horário).")),
        _anim(F("mascara_suavidade", "Suavidade da borda", 10.0, 0, 500, 1, 0, " px",
                "Largura da borda suave (0 = borda seca).")),
        _anim(F("mascara_expandir", "Expandir", 0.0, -500, 500, 1, 0, " px",
                "Aumenta (positivo) ou encolhe (negativo) a forma em todos os lados.")),
        B("mascara_inverter", "Inverter", False, "Troca o dentro pelo fora."),
        C("mascara_uso", "O que fazer dentro", "recortar", [
            ("recortar", N_("Mostrar só o que está dentro")), ("desfocar", N_("Desfocar")),
            ("pixelar", N_("Pixelar")), ("so_forma", N_("Nada (só a forma, para o desfoque de lente)"))],
          "Recortar deixa ver as faixas de baixo fora da forma; desfocar e pixelar escondem o que está dentro (um "
          "rosto, uma placa); \"Nada\" guarda a forma para o desfoque de lente usar."),
        _anim(F("mascara_forca", "Força", 20.0, 1, 200, 1, 0, " px",
                "Raio do desfoque ou tamanho dos quadradinhos do pixelado (pixels de um quadro de 1080 linhas).")),
    ], "Retângulo, elipse ou polígono para recortar, desfocar ou pixelar"),
]

# 1.9 F3: estabilização e rastreio (§51)
VIDEO_SECTIONS += [
    # `estabilizacao.py`: a correção sai da análise guardada na fonte (botão "Analisar" do cartão) e entra na geometria
    # do clipe (`vfx.GEOMETRY`). Desligada (padrão) ou sem análise, o clipe de sempre.
    Section("estabilizar", "Estabilizar", "estab_on", [
        B("estab_on", "Estabilizar", False, "Tira o tremor da câmera na mão. Analise o arquivo antes (botão Analisar)."),
        F("estab_suavizar", "Suavizar", 1.0, 0.1, 10.0, 0.1, 1, " s",
          "Quanto do movimento fica: pouco segue a câmera de perto (só some o tremor); muito deixa o movimento lento e "
          "liso, como num tripé com cabeça fluida."),
        B("estab_rotacao", "Corrigir a rotação", True, "Desligado, a imagem só anda (o horizonte pode balançar)."),
        C("estab_bordas", "Bordas", "ampliar", [
            ("ampliar", N_("Ampliar (sem bordas)")), ("preto", N_("Mostrar as bordas"))],
          "Ao corrigir, a imagem anda e as bordas aparecem. Ampliar escolhe o menor zoom que as esconde no arquivo "
          "inteiro."),
        _pct("estab_zoom_extra", "Zoom a mais", lo=0.0, hi=0.5, tip="Amplia mais um pouco, além do necessário."),
    ], "Tira o tremor da câmera na mão"),
    # `rastreio.py`: o tamanho do alvo e a busca do rastreio de ponto (botão "Rastrear ponto"); não mudam a imagem.
    Section("rastreio", "Rastrear ponto", None, [
        F("rastreio_caixa", "Tamanho do alvo", 64, 16, 256, 2, 0, " px",
          "Lado do quadrado em volta do ponto que é procurado nos outros quadros (px num quadro de 1080 linhas). "
          "Pegue algo com detalhe e que não mude muito."),
        F("rastreio_busca", "Busca por quadro", 48, 8, 256, 2, 0, " px",
          "Quanto o ponto pode andar de um quadro para o outro. Aumente para movimentos rápidos.", advanced=True),
    ], "Um título (ou o próprio clipe) seguindo um ponto da imagem"),
]

# 1.9 F4: luz e atmosfera (§52)
VIDEO_SECTIONS += [
    # `luzes_clipe.py` (módulo Beta "luzes_lente"): desfoque de lente (ordem 400) e listra, flares e raios (500).
    Section("desfoque_lente", "Desfoque de lente", None, [
        F("desfoque_lente_raio", "Raio", 0.0, 0, 200, 0.5, 1, " px",
          "Tamanho do círculo de desfoque (bokeh), em px de um quadro de 1080 linhas do clipe. 0 = desligado."),
        C("desfoque_lente_forma", "Forma do bokeh", "disco", [
            ("disco", N_("Disco (redondo)")), ("hexagono", N_("Hexágono (seis lâminas)"))],
          "A forma das luzes desfocadas."),
        C("desfoque_lente_mascara", "Onde desfocar", "tudo", [
            ("tudo", N_("A imagem inteira")), ("degrade", N_("Pelo degradê (foco perto ou longe)")),
            ("dentro_mascara", N_("Dentro da máscara do clipe")), ("fora_mascara", N_("Fora da máscara do clipe"))],
          "Com o degradê, o lado marcado fica desfocado e o outro continua nítido."),
        C("desfoque_lente_degrade", "Forma do degradê", "linear", [
            ("linear", N_("Linear (fundo ou frente)")), ("radial", N_("Radial (fora do círculo)"))]),
        F("desfoque_lente_angulo", "Direção", 0.0, -180, 180, 1, 0, "°",
          "Que lado fica desfocado no degradê linear: 0° = em cima (o fundo), 180° = embaixo (a frente)."),
        F("desfoque_lente_x", "Centro horizontal", 0.0, -1920, 1920, 10, 0, " px",
          "Desloca a linha ou o círculo (px de um quadro de 1080 linhas do clipe; 0 = centro)."),
        F("desfoque_lente_y", "Centro vertical", 0.0, -1080, 1080, 10, 0, " px", "Negativo sobe; positivo desce."),
        F("desfoque_lente_circulo", "Raio do círculo", 400.0, 10, 2000, 10, 0, " px",
          "No degradê radial, o que fica dentro do círculo continua nítido."),
        F("desfoque_lente_suavidade", "Suavidade", 400.0, 0, 2000, 10, 0, " px",
          "Largura da passagem entre o nítido e o desfocado."),
        B("desfoque_lente_inverter", "Inverter", False, "Troca o lado desfocado."),
    ], "Desfoque como o de uma lente aberta, com foco perto ou longe"),

    Section("luzes", "Luz (listra, flares, raios)", None, [
        _pct("listra_intensidade", "Listra anamórfica", lo=0.0, hi=2.0,
             tip="Uma linha de luz longa nas luzes fortes, como a de uma lente anamórfica. 0% = desligada."),
        F("listra_limiar", "Limiar da listra", 2.5, 0, 8, 0.1, 1, " EV",
          "Só as partes mais claras que o cinza médio mais estes stops espalham a listra."),
        F("listra_comprimento", "Comprimento da listra", 400.0, 20, 2000, 10, 0, " px",
          "Até onde a listra vai de cada lado (px de um quadro de 1080 linhas do clipe)."),
        Param("listra_cor", "Cor da listra", "color", (0.35, 0.6, 1.0)),
        F("listra_angulo", "Ângulo da listra", 0.0, -90, 90, 1, 0, "°", "0° = horizontal.", advanced=True),
        _pct("flare_intensidade", "Flare", lo=0.0, hi=2.0,
             tip="Reflexos da lente (fantasmas) na linha que vai da luz ao centro do quadro. 0% = desligado."),
        C("flare_fonte", "Origem do flare", "auto", [
            ("auto", N_("As luzes mais fortes da imagem")), ("ponto", N_("Um ponto escolhido"))],
          "Automático: cada luz forte da imagem faz os seus fantasmas. Ponto: os fantasmas saem do ponto escolhido "
          "na prévia, mesmo sem uma luz ali."),
        F("flare_x", "Ponto do flare (horizontal)", 0.0, -1920, 1920, 10, 0, " px",
          "De onde sai o flare com a origem \"Um ponto escolhido\" (px de um quadro de 1080 linhas; 0 = centro)."),
        F("flare_y", "Ponto do flare (vertical)", -300.0, -1080, 1080, 10, 0, " px", "Negativo sobe; positivo desce."),
        I("flare_fantasmas", "Fantasmas", 4, 1, 8, "Quantos reflexos aparecem."),
        F("flare_limiar", "Limiar do flare", 3.0, 0, 8, 0.1, 1, " EV",
          "Na origem automática, só as partes mais claras que o cinza médio mais estes stops fazem fantasmas."),
        F("flare_tamanho", "Tamanho dos fantasmas", 80.0, 10, 600, 5, 0, " px",
          "Raio dos fantasmas de um ponto escolhido; na origem automática, o quanto eles ficam macios."),
        Param("flare_cor", "Cor do flare", "color", (1.0, 0.85, 0.7)),
        _pct("raios_intensidade", "Raios de luz", lo=0.0, hi=2.0,
             tip="Raios que saem de um ponto atravessando as partes claras (luz por entre folhas, janela, "
                 "poeira). 0% = desligados."),
        F("raios_x", "Origem dos raios (horizontal)", 0.0, -1920, 1920, 10, 0, " px",
          "De onde saem os raios (px de um quadro de 1080 linhas; 0 = centro). Pode ficar fora do quadro."),
        F("raios_y", "Origem dos raios (vertical)", -400.0, -2160, 2160, 10, 0, " px", "Negativo sobe; positivo desce."),
        _pct("raios_comprimento", "Comprimento dos raios", 0.5, 0.05, 1.0,
             tip="Fração da distância até a origem que cada raio percorre."),
        _pct("raios_decaimento", "Decaimento dos raios", 0.5, 0.0, 1.0,
             tip="Quanto os raios enfraquecem ao se afastar da luz."),
        F("raios_limiar", "Limiar dos raios", 1.5, 0, 8, 0.1, 1, " EV",
          "Só as partes mais claras que o cinza médio mais estes stops viram raios."),
        Param("raios_cor", "Cor dos raios", "color", (1.0, 0.95, 0.85)),
    ], "Listra anamórfica, reflexos da lente e raios de luz"),

    # `atmosfera.py` (módulo Beta "atmosfera"): névoa (ordem 600) e partículas (700).
    Section("nevoa", "Névoa", None, [
        _pct("nevoa_densidade", "Densidade", lo=0.0, tip="Quanto a névoa cobre a imagem. 0% = sem névoa."),
        Param("nevoa_cor", "Cor da névoa", "color", (0.82, 0.85, 0.9),
              tip="A cor da névoa onde ela é total, como num vídeo comum (Rec.709)."),
        C("nevoa_forma", "Forma", "degrade", [
            ("degrade", N_("Degradê (chão ou céu)")), ("uniforme", N_("Por igual (o quadro todo)"))]),
        F("nevoa_angulo", "Direção", 180.0, -180, 180, 1, 0, "°",
          "Que lado tem névoa: 180° = embaixo (chão), 0° = em cima (céu)."),
        F("nevoa_posicao", "Altura", 0.0, -1080, 1080, 10, 0, " px",
          "Desloca a linha do degradê (px de um quadro de 1080 linhas; negativo sobe)."),
        F("nevoa_suavidade", "Suavidade", 600.0, 0, 3000, 10, 0, " px", "Largura da passagem do degradê."),
        _pct("nevoa_textura", "Textura", 0.5, 0.0, 1.0, tip="0% = névoa lisa; mais = nuvens mais marcadas."),
        F("nevoa_escala", "Tamanho das nuvens", 300.0, 20, 2000, 10, 0, " px", advanced=True),
        F("nevoa_movimento", "Movimento", 20.0, -400, 400, 1, 0, " px/s",
          "Velocidade com que a névoa anda na horizontal (negativo = para a esquerda)."),
        I("nevoa_semente", "Semente", 1, 0, 9999, "Muda o desenho das nuvens.", advanced=True),
    ], "Névoa por degradê, com nuvens que andam"),

    Section("particulas", "Partículas", None, [
        C("part_tipo", "Tipo", "nenhuma", [
            ("nenhuma", N_("Nenhuma")), ("chuva", N_("Chuva")), ("neve", N_("Neve")), ("poeira", N_("Poeira no ar")),
            ("brasas", N_("Brasas"))]),
        _pct("part_quantidade", "Quantidade", 0.5, 0.0, 1.0),
        F("part_tamanho", "Tamanho", 6.0, 1, 60, 0.5, 1, " px",
          "Diâmetro das partículas da frente (px de um quadro de 1080 linhas do clipe)."),
        F("part_velocidade", "Velocidade", 1.0, 0.0, 4.0, 0.05, 2, "×", "1× = a velocidade natural do tipo."),
        _pct("part_vento", "Vento", tip="Empurra as partículas para a esquerda (negativo) ou para a direita."),
        _pct("part_profundidade", "Profundidade", 0.5, 0.0, 1.0,
             tip="Camadas ao fundo menores, mais lentas e mais apagadas (paralaxe)."),
        _pct("part_opacidade", "Opacidade", 0.8, 0.0, 1.0),
        Param("part_cor", "Cor", "color", (1.0, 1.0, 1.0), tip="Tinge as partículas (as brasas e a poeira já têm cor)."),
        _pct("part_desfoque", "Desfoque de movimento", 0.5, 0.0, 1.0,
             tip="Rastro de cada partícula durante a exposição (50% = obturador de 180°)."),
        I("part_semente", "Semente", 1, 0, 9999, "Muda onde cada partícula aparece.", advanced=True),
    ], "Chuva, neve, poeira ou brasas"),
]
# Os números e as cores destas seções aceitam chaves de animação, menos os que desenham a grade das partículas (tamanho,
# rastro, profundidade) e a posição delas e das nuvens pelo tempo (velocidade × tempo): animá-los faria tudo pular.
for _s in VIDEO_SECTIONS[_N_BASE:]:
    for _p in _s.params if _s.key in ("desfoque_lente", "luzes", "nevoa", "particulas") else ():
        if _p.kind in ("float", "color") and _p.key not in ("part_tamanho", "part_velocidade", "part_vento",
                                                              "part_profundidade", "part_desfoque", "nevoa_movimento",
                                                              "nevoa_escala"):
            _p.animatable = True
del _s, _p

# 1.9 F5: tempo da imagem (§53)
VIDEO_SECTIONS += [
    # `tempo_imagem.py` (módulo Beta "tempo_imagem"): deflicker pela análise do arquivo, ruído temporal pelos quadros
    # vizinhos e câmera lenta por mistura de quadros. Padrão: tudo desligado (nenhum passo, nenhuma janela).
    Section("tempo_imagem", "Tempo da imagem", None, [
        _pct("deflicker", "Deflicker", lo=0.0,
             tip="Tira a cintilação (o brilho que pisca de um quadro para o outro, de luz fluorescente, LED ou "
                 "timelapse) igualando o brilho de cada quadro à média dos vizinhos. Precisa da análise do arquivo "
                 "(botão Analisar)."),
        F("deflicker_janela", "Janela do deflicker", 0.5, 0.1, 5.0, 0.05, 2, " s",
          "O tempo em que o brilho é igualado: mais curto segue mudanças de luz de verdade; mais longo tira "
          "cintilações lentas.", advanced=True),
        _pct("ruido_temporal", "Ruído temporal", lo=0.0,
             tip="Tira o ruído do sensor misturando cada pixel com o mesmo pixel nos quadros vizinhos, só onde a "
                 "imagem não mudou (o que se mexe não deixa rastro). Melhor em cenas paradas ou de tripé."),
        I("ruido_temporal_quadros", "Quadros de cada lado", 2, 1, 2,
          "Quantos quadros antes e depois entram na média (mais quadros: menos ruído, mais lento).", advanced=True),
        B("mistura_quadros", "Mistura de quadros", False,
          "Na câmera lenta (menos de um quadro do vídeo por quadro da sequência), mistura os dois quadros mais "
          "próximos em vez de repetir o mesmo: o movimento fica mais contínuo, sem saltos. Não muda o som."),
    ], "Deflicker, ruído temporal e câmera lenta por mistura"),
]

AUDIO_SECTIONS: list[Section] = [
    Section("som", "Som", None, [
        F("volume", "Volume", 0.0, -60, 12, 0.5, 1, " dB"),
        B("mudo", "Mudo", False),
        _pct("balanco", "Balanço", tip="Negativo puxa para a esquerda; positivo para a direita."),
        F("fade_in", "Aumentar no início", 0.0, 0, 10, 0.1, 1, " s"),
        F("fade_out", "Diminuir no fim", 0.0, 0, 10, 0.1, 1, " s"),
        F("transicao", "Transição com o anterior", 0.0, 0, 5, 0.1, 1, " s",
          "Transição de som (potência constante) com o clipe colado antes deste na faixa, centrada no corte. "
          "Usa o som do arquivo além do corte; sem sobra, fica mais curta."),
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

# 1.8, limpeza do som (`somlimpo.py`, ARQUITETURA §44): cortes de graves/agudos e o nivelamento da voz no fim do
# "eq"; o ruído aprendido e o zumbido da rede numa seção nova (o inspetor a mostra depois do "eq":
# `ui/edit_panels.DISPLAY_AFTER`). Todo padrão é neutro (o grafo do som de antes) e as chaves vão para o JSON só fora
# do padrão (`SPARSE_KEYS`). `ruido_ini`/`ruido_fim` são o trecho do arquivo aprendido pelo botão (linhas escondidas).
next(s for s in AUDIO_SECTIONS if s.key == "eq").params.extend([
    F("passa_alta", "Cortar graves abaixo de", 0.0, 0, 500, 5, 0, " Hz",
      "Tira o som abaixo desta frequência (vento, estrondo, ronco de motor). 0 = não corta."),
    F("passa_baixa", "Cortar agudos acima de", 0.0, 0, 20000, 100, 0, " Hz",
      "Tira o som acima desta frequência (chiado, sibilância). 0 = não corta."),
    _pct("nivelar_voz", "Nivelar a voz", lo=0.0,
         tip="Sobe as falas baixas e segura as altas, sílaba a sílaba, para a voz ficar num volume parecido."),
])
AUDIO_SECTIONS += [
    Section("limpar", "Limpar o som", None, [
        _pct("ruido_perfil", "Redução pelo ruído aprendido", lo=0.0,
             tip="Tira o ruído que o botão \"Aprender o ruído\" ouviu num trecho só com ele (ar-condicionado, chiado, "
                 "vento constante). 100% tira até 30 dB."),
        F("ruido_ini", "Início do ruído aprendido", 0.0, 0, 86400, 0.01, 2, " s"),
        F("ruido_fim", "Fim do ruído aprendido", 0.0, 0, 86400, 0.01, 2, " s"),
        C("zumbido", "Zumbido da rede elétrica", "nao", [("nao", N_("Não")), ("50", N_("50 Hz")), ("60", N_("60 Hz"))],
          "Tira o zumbido grave dos cabos e da rede elétrica (60 Hz no Brasil e nas Américas, 50 Hz na Europa) e "
          "as harmônicas dele."),
        I("zumbido_harmonicos", "Harmônicas do zumbido", 6, 1, 10,
          "Quantas frequências tirar: o zumbido e os múltiplos dele (6 = até 360 Hz numa rede de 60 Hz).",
          advanced=True),
    ], "Ruído aprendido e zumbido da rede elétrica"),
]

# Predefinições do "eq" (1.8): cada uma acerta só as chaves de `AUDIO_PRESET_KEYS` (as que não cita voltam ao padrão)
# num passo do desfazer (`apply_audio_preset`). Ids sem acento e estáveis; só acrescentar no fim.
AUDIO_PRESET_KEYS = ("graves", "medios", "agudos", "voz", "passa_alta", "passa_baixa", "nivelar_voz")
AUDIO_PRESETS: list[tuple[str, str, dict[str, Any]]] = [
    ("voz_clara", N_("Voz mais clara"), dict(voz=True, passa_alta=80.0, graves=-2.0, medios=1.5, agudos=3.0)),
    ("voz_grave", N_("Voz grave e próxima"), dict(passa_alta=60.0, graves=4.0, medios=-1.0, agudos=1.0,
                                                    nivelar_voz=0.2)),
    ("telefone", N_("Telefone"), dict(passa_alta=300.0, passa_baixa=3400.0, medios=4.0)),
    ("radio_antigo", N_("Rádio antigo"), dict(passa_alta=200.0, passa_baixa=5000.0, graves=-4.0, medios=5.0,
                                              nivelar_voz=0.5)),
    ("menos_vento", N_("Menos vento e estrondo"), dict(passa_alta=120.0, graves=-3.0)),
    ("musica_cheia", N_("Música mais cheia"), dict(graves=3.0, medios=-1.0, agudos=2.5)),
    ("podcast", N_("Podcast"), dict(passa_alta=80.0, graves=1.5, medios=1.5, agudos=2.0, nivelar_voz=0.6)),
    ("sem_ajustes", N_("Sem ajustes"), {}),
]

VIDEO = Schema(VIDEO_SECTIONS)
AUDIO = Schema(AUDIO_SECTIONS)
SCHEMAS = {"video": VIDEO, "audio": AUDIO}

COLOR_SECTIONS = ("luz", "cor", "rodas", "curva", "hsl", "detalhe", "efeitos",
                  "pele", "alvo", "degrade")  # 1.6: cor simples (acrescentadas no fim)

# Ajustes que aceitam chaves de animação (`keyframes.py`, `Clip.keys`): enquadramento e opacidade, todo ajuste
# numérico de cor, luz, detalhe e efeitos (e as rodas) e o volume do som. Escolhas, liga/desliga, corte,
# velocidade e transições ficam de fora. Receita "Tornar um ajuste animável" no AGENTS.md.
ANIMATABLE_VIDEO = ("pos_x", "pos_y", "escala", "rotacao", "opacidade", "escala_x", "escala_y",
                    *(p.key for s in VIDEO_SECTIONS if s.key in COLOR_SECTIONS for p in s.params
                      if p.kind in ("float", "int", "wheel")))
ANIMATABLE_AUDIO = ("volume",)
for _schema, _keys in ((VIDEO, ANIMATABLE_VIDEO), (AUDIO, ANIMATABLE_AUDIO)):
    for _k in _keys:
        _schema.params[_k].animatable = True
del _schema, _keys, _k

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


def apply_audio_preset(values: dict[str, Any], key: str) -> dict[str, Any]:
    """Valores do clipe de som com uma predefinição do "eq": as chaves de `AUDIO_PRESET_KEYS` voltam ao padrão e
    recebem as da predefinição; o resto do clipe fica como está."""
    out = AUDIO.sanitize(values)
    base = AUDIO.defaults()
    for k in AUDIO_PRESET_KEYS:
        out[k] = base[k]
    preset = next((v for k, _label, v in AUDIO_PRESETS if k == key), None)
    if preset:
        out.update(preset)
    return AUDIO.sanitize(out)


def is_neutral(kind: str, values: dict[str, Any]) -> bool:
    """True se todos os ajustes do clipe estão no padrão (o clipe sai igual ao arquivo)."""
    schema = SCHEMAS[kind]
    return schema.sanitize(values) == schema.defaults()


# ------------------------------------------------------------------ 1.5: transições novas e JSON enxuto
# Tipos de transição da 1.5 (desenhados por `transitions.py` e `editshaders.CLIP_TR`); os de antes continuam no
# caminho de sempre, bit a bit. EXTRA_TWO_CLIP: os que mostram a cauda do clipe anterior da faixa por baixo, como
# o "dissolver". Usar um deles grava o projeto no formato 3 (`timeline.FEATURES["transicoes"]`).
EXTRA_IN = ("fusao", "exposicao", "queima", "emenda", "ponta", "iris", "empurrar", "cortina", "zoom")
EXTRA_OUT = ("exposicao", "queima", "iris")
EXTRA_TWO_CLIP = ("fusao", "queima", "iris", "empurrar", "cortina", "zoom")

# Ajustes de clipe que vieram depois da 1.4: só vão para o JSON quando fora do padrão (`stored_values`), então o
# clipe de uma montagem antiga grava exatamente o JSON de antes (a leitura completa com o padrão). Ajuste novo de
# clipe: acrescente a chave aqui.
SPARSE_KEYS: set[str] = {
    "entrada_direcao", "entrada_suavidade", "entrada_centro_x", "entrada_centro_y", "entrada_anel", "entrada_ponta",
    "entrada_zoom", "entrada_quadros", "entrada_clarao",
    "saida_suavidade", "saida_centro_x", "saida_centro_y", "saida_anel",
    "camera_entrada", "camera_reescalado", "camera_ei",  # 1.6: perfil de câmera do clipe (`camera.py`)
    "manivela", "manivela_oscila", "manivela_semente",  # 1.6: manivela (`tempo_camera.py`)
}
SPARSE_KEYS |= {p.key for s in VIDEO_SECTIONS if s.key in ("pele", "alvo", "degrade") for p in s.params}  # 1.6
SPARSE_KEYS |= {"luz_r", "luz_g", "luz_b", "luz_densidade"}  # 1.6: marcação de luz por plano (`luz_plano.py`)
SPARSE_KEYS |= {"escala_x", "escala_y"}  # 1.7: escala por eixo (`compositor.axis_scale`)
SPARSE_KEYS |= {"desespremer", "desespremer_taxa"}  # 1.7: desespremer do clipe (`compositor.desqueeze`)
SPARSE_KEYS |= {"passa_alta", "passa_baixa", "nivelar_voz", "ruido_perfil", "ruido_ini", "ruido_fim", "zumbido",
                "zumbido_harmonicos"}  # 1.8: limpeza do som (`somlimpo.py`)
SPARSE_KEYS |= {p.key for s in VIDEO_SECTIONS[_N_BASE:] for p in s.params}  # 1.9: efeitos visuais (todas as frentes)
_DEFAULTS = {kind: schema.defaults() for kind, schema in SCHEMAS.items()}


def stored_values(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    """Os ajustes do clipe como vão para o JSON: uma cópia sem as chaves de `SPARSE_KEYS` que estão no padrão."""
    base = _DEFAULTS[kind]
    return {k: copy.deepcopy(v) for k, v in values.items()
            if k not in SPARSE_KEYS or k not in base or v != base[k]}
