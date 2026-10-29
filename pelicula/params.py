"""Esquema de todos os parâmetros ajustáveis.

A interface é gerada a partir desta lista, e o motor lê os valores pelas chaves.
Distâncias em "px@1080" são pixels medidos num quadro de 1080 linhas e são
convertidas para a resolução real, então a prévia e o vídeo final ficam iguais.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass
class Param:
    key: str
    label: str
    kind: str  # float | int | bool | choice | color | file
    default: Any
    min: float = 0.0
    max: float = 1.0
    step: float = 0.01
    decimals: int = 2
    unit: str = ""
    choices: list[tuple[str, str]] | None = None
    tip: str = ""
    advanced: bool = False
    percent: bool = False  # mostra 0..1 como 0..100 %
    animatable: bool = False  # aceita chaves de animação (`keyframes.py`)


@dataclass
class Section:
    key: str
    title: str
    toggle: str | None
    params: list[Param] = field(default_factory=list)
    subtitle: str = ""
    layout: str = ""  # "" = uma linha por parâmetro; "hsl" = escolha da cor + 3 linhas (modo Edição)


BITOLAS = [
    ("nenhuma", "Nenhuma (manual)"),
    ("8mm", "8 mm"),
    ("super8", "Super 8"),
    ("16mm", "16 mm"),
    ("super16", "Super 16"),
    ("35mm", "35 mm"),
    ("65mm", "65 mm"),
    ("imax", "IMAX 70 mm (15/70)"),
    ("135", "Foto 35 mm (135, 36 × 24)"),  # 1.6: formatos de foto (`scanformatos.py`)
    ("meio_quadro", "Foto meio quadro (18 × 24)"),
    ("120", "Foto médio formato (120)"),
]

ISOS = [(str(v), f"ISO {v}") for v in (50, 100, 125, 200, 250, 400, 500, 800, 1600, 3200)]

COPIAS = [
    ("nenhuma", "Nenhuma (sem cópia)"),
    ("k2383", "Kodak 2383 (cópia de cinema clássica)"),
    ("k2393", "Kodak 2393 (mais contraste)"),
    ("f3513", "Fuji 3513 (mais fria e neutra)"),
]

ENTRADAS = [
    ("rec709", "Rec.709 / sRGB (vídeo comum)"),
    ("linear", "Linear"),
    ("nlog", "Nikon N-Log"),
    ("slog3", "Sony S-Log3 (S-Gamut3.Cine)"),
    ("logc3", "ARRI LogC3 (ARRI Wide Gamut 3)"),
    ("vlog", "Panasonic V-Log"),
    ("log3g10", "RED Log3G10 (RWG) — R3D, Nikon N-RAW e R3D NE"),
    ("dwg", "DaVinci Intermediate (DaVinci Wide Gamut)"),
    ("cineon", "Cineon / DPX log"),
    ("bmd_gen5", "Blackmagic Film Gen 5 (Blackmagic Wide Gamut)"),
    ("logc4", "ARRI LogC4 (ARRI Wide Gamut 4)"),
    ("applelog", "Apple Log (Rec.2020) — iPhone"),
    ("hlg", "HLG (HDR de celular, Rec.2100)"),
    ("pq", "PQ / HDR10 (Rec.2100)"),
    # 1.6: perfis com fórmula publicada pelo fabricante (look.INPUT_IDS 14+)
    ("clog2", "Canon Log 2 (Cinema Gamut)"),
    ("clog3", "Canon Log 3 (Cinema Gamut)"),
    ("flog", "Fujifilm F-Log (F-Gamut)"),
    ("flog2", "Fujifilm F-Log2 (F-Gamut)"),
    ("flog2c", "Fujifilm F-Log2 C (F-Gamut C)"),
    ("dlog", "DJI D-Log (D-Gamut)"),
    ("slog2", "Sony S-Log2 (S-Gamut)"),
    ("llog", "Leica L-Log (Rec.2020)"),
]

# EI do ARRI LogC3 (look.LOGC3_EI): a ALEXA grava uma curva para cada EI; 800 é a de sempre.
LOGC3_EIS = [(ei, f"EI {ei}") for ei in ("160", "200", "250", "320", "400", "500", "640", "800", "1000", "1280",
                                          "1600")]

LUT_ENTRADAS = [
    ("rec709", "Rec.709 (LUTs criativos, Premiere)"),
    ("cineon", "Cineon log (LUTs de cópia do Resolve)"),
    ("logc3", "ARRI LogC3"),
    ("slog3", "Sony S-Log3"),
    ("nlog", "Nikon N-Log"),
    ("vlog", "Panasonic V-Log"),
    ("log3g10", "RED Log3G10 (RWG)"),
    ("dwg", "DaVinci Intermediate (DWG)"),
    ("bmd_gen5", "Blackmagic Film Gen 5"),
    ("logc4", "ARRI LogC4"),
    ("applelog", "Apple Log"),
    ("linear", "Linear"),
    ("hlg", "HLG (Rec.2100)"),
    ("pq", "PQ / HDR10 (Rec.2100)"),
    ("clog2", "Canon Log 2"),
    ("clog3", "Canon Log 3"),
    ("flog", "Fujifilm F-Log"),
    ("flog2", "Fujifilm F-Log2"),
    ("flog2c", "Fujifilm F-Log2 C"),
    ("dlog", "DJI D-Log"),
    ("slog2", "Sony S-Log2"),
    ("llog", "Leica L-Log"),
]

# Laboratório: aproximações artísticas do comportamento de cada filme, menos os marcados "(datasheet)": as curvas
# desses foram ajustadas às curvas publicadas pela Kodak (tools/ajustar_lab.py; fonte em pelicula/data/datasheets/).
# Película calibrada por datasheet público entra como id novo no fim, com a fonte registrada (regra 8 do AGENTS.md).
NEGATIVOS = [
    ("vision3_50d", "Kodak Vision3 50D"),
    ("vision3_250d", "Kodak Vision3 250D"),
    ("vision3_200t", "Kodak Vision3 200T"),
    ("vision3_500t", "Kodak Vision3 500T"),
    ("eterna_250d", "Fujifilm Eterna 250D"),
    ("eterna_vivid", "Fujifilm Eterna Vivid 500"),
    ("exr_5248", "Eastman EXR 5248 (anos 90)"),
    ("ecn2_5247", "Eastman 5247 ECN-II (anos 70)"),
    ("vision2_5201", "Kodak Vision2 5201 50D"),
    ("ecn2_5297", "Eastman ECN-II 5297 250D"),
    ("vision_5246", "Kodak Vision 5246 250D"),
    ("vision_5263", "Kodak Vision 5263 500T"),
    ("vision2_5229", "Kodak Vision2 Expression 5229 500T"),
    ("double_x", "Kodak Double-X 5222 (P&B)"),
    ("vision3_250d_v2", "Kodak Vision3 250D (datasheet)"),
    ("vision3_500t_v2", "Kodak Vision3 500T (datasheet)"),
    ("vision3_200t_v2", "Kodak Vision3 200T (datasheet)"),
]

COPIAS_LAB = [
    ("2383", "Kodak 2383 (cópia de cinema clássica)"),
    ("2393", "Kodak 2393 (mais contraste)"),
    ("3513", "Fuji 3513 (mais fria e neutra)"),
    ("e5386", "Eastman EXR Print 5386"),
    ("e5385", "Eastman Color Print 5385"),
    ("2302", "Kodak 2302 (cópia preto e branco)"),
    ("nenhuma", "Sem cópia (negativo escaneado e invertido)"),
    ("2383_v2", "Kodak 2383 (datasheet)"),
]

HAL_MODELOS = [  # 1.6: halação física (grao.physical_halation)
    ("brilho", "Brilho (acima do limiar)"),
    ("fisica", "Física (reflexo na base)"),
]

GRAO_MODELOS = [  # 1.6: modelo do grão no negativo (grao_fisico.py; "fisico" no módulo Beta grao_fisico)
    ("ruido", "Ruído (campo procedural)"),
    ("fisico", "Físico (grãos de prata)"),
]

PROCESSOS = [
    ("normal", "Normal (negativo + cópia)"),
    ("tech3", "Technicolor 3 tiras (transferência de corante)"),
    ("tech2", "Technicolor 2 cores (anos 20)"),
    ("prata", "Retenção de prata (bleach bypass)"),
    ("reversivel", "Reversível (slide, sem cópia)"),
    ("cruzado_e6c41", "Revelação cruzada: slide no C-41"),
    ("cruzado_c41e6", "Revelação cruzada: negativo no E-6"),
]

# 1.6 (labx.py): scanner do "Sem cópia" e cor da pré-exposição.
SCANNERS = [
    ("rgb", "RGB estreito (cada camada sozinha)"),
    ("branca", "Luz branca (camadas misturadas)"),
]

CORES_PRE_EXPOSICAO = [
    ("neutra", "Neutra"),
    ("ambar", "Âmbar (quente)"),
    ("azul", "Azul (fria)"),
    ("verde", "Verde"),
    ("magenta", "Magenta"),
]

# MTF da película: maciez fina que tira a nitidez "digital" (poros, serrilhado) e mantém o detalhe maior.
MTFS = [
    ("nenhum", "Desligado"),
    ("close", "Close (rosto)"),
    ("medio", "Plano médio"),
    ("aberto", "Plano aberto"),
    ("16mm", "Textura 16 mm"),
    ("super8", "Textura Super 8"),
]

PROPORCOES = [
    ("original", "Original do vídeo"),
    ("bitola", "Da bitola escolhida"),
    ("1.33", "1,33 (4:3)"),
    ("1.37", "1,37 (Academy)"),
    ("1.43", "1,43 (IMAX)"),
    ("1.66", "1,66 (europeu)"),
    ("1.78", "1,78 (16:9)"),
    ("1.85", "1,85 (widescreen)"),
    ("1.90", "1,90 (IMAX digital)"),
    ("2.00", "2,00 (Univisium)"),
    ("2.20", "2,20 (70 mm)"),
    ("2.39", "2,39 (Scope)"),
    ("2.76", "2,76 (Ultra Panavision)"),
]


# 1.6: ângulos do obturador (`tempo_camera`); a escolha não anima (a janela decide quais quadros ler)
ANGULOS = [("45", "45°"), ("90", "90°"), ("144", "144°"), ("172.8", "172,8° (sem cintilação a 50 Hz)"),
           ("180", "180° (o padrão do cinema)"), ("270", "270°"), ("360", "360° (todo aberto)")]


def F(key, label, default, lo, hi, step=0.01, decimals=2, unit="", tip="", advanced=False, percent=False):
    return Param(key, label, "float", default, lo, hi, step, decimals, unit, None, tip, advanced, percent)


def I(key, label, default, lo, hi, tip="", advanced=False):
    return Param(key, label, "int", default, lo, hi, 1, 0, "", None, tip, advanced)


def B(key, label, default, tip="", advanced=False):
    return Param(key, label, "bool", default, tip=tip, advanced=advanced)


def C(key, label, default, choices, tip="", advanced=False):
    return Param(key, label, "choice", default, choices=choices, tip=tip, advanced=advanced)


def COR(key, label, default, tip="", advanced=False):
    return Param(key, label, "color", tuple(default), tip=tip, advanced=advanced)


SECTIONS: list[Section] = [
    Section("pelicula", "Película", None, [
        C("bitola", "Bitola", "35mm", BITOLAS,
          "Tamanho do quadro da película. Bitolas menores têm grão maior, menos nitidez e mais tremor."),
        C("iso", "Sensibilidade", "250", ISOS, "Filmes mais sensíveis têm grão maior e mais visível."),
        C("copia", "Cópia (print)", "nenhuma", COPIAS,
          "Filme usado para copiar o negativo para a projeção. Define o contraste e a cor final."),
        F("copia_forca", "Força da cópia", 1.0, 0, 1, percent=True),
        B("bitola_desfoque_on", "Desfoque da bitola", True,
          "Maciez natural de cada bitola (desfoque gaussiano). Em 1080p: 8 mm 2,4 px • Super 8 1,9 px • "
          "16 mm 1,1 px • Super 16 0,9 px • 35 mm 0,35 px • 65 mm e IMAX nenhum. Desligue para manter a nitidez "
          "do vídeo. Para devolver ainda mais detalhe, use Lente e nitidez → Recuperar detalhe."),
        F("bitola_resolucao", "Intensidade do desfoque", 1.0, 0, 1, percent=True,
          tip="100% = a maciez natural da bitola; 0% = sem desfoque."),
        C("mtf", "MTF da película (maciez fina)", "nenhum", MTFS,
          "Tira a nitidez “digital” demais (poros, serrilhado) e mantém o detalhe maior, como a resposta de "
          "um filme. Escolha pelo enquadramento: close suaviza mais a pele; plano aberto, menos."),
        F("mtf_forca", "Quantidade do MTF", 0.5, 0, 1, percent=True,
          tip="50% = o valor do enquadramento escolhido; 100% = o dobro."),
        F("mtf_camadas", "Diferença de nitidez entre camadas", 0.0, 0, 1, percent=True,
          tip="Cada cor fica com a nitidez da sua camada na película: no negativo o vermelho é o mais macio; com "
              "uma cópia escolhida, o azul também perde nitidez. Dá franjas sutis nas bordas de alto contraste. "
              "50% = a diferença medida nos datasheets da Kodak (Vision3 250D e cópia 2383), convertida pelo "
              "tamanho do quadro da bitola; 100% = o dobro."),
        F("bitola_vinheta", "Vinheta da bitola", 1.0, 0, 1, percent=True,
          tip="Escurecimento natural das bordas em bitolas pequenas."),
        F("mix_geral", "Força geral do efeito", 1.0, 0, 1, percent=True,
          tip="Mistura o resultado com o vídeo original."),
    ], "Bitola, sensibilidade e cópia"),

    Section("entrada", "Entrada e exposição", None, [
        C("entrada", "Perfil do vídeo", "rec709", ENTRADAS,
          "Como o vídeo foi gravado. Use o perfil log da câmera se gravou em log, ou HLG/PQ para vídeo HDR "
          "(os celulares costumam gravar em HLG). Trocar de preset não muda este ajuste."),
        B("log_reescalado", "Log reescalado (HDMI “Limited”)", False,
          "Só para S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log, que a câmera grava no código de 10 bits. "
          "Ligue em gravações externas em "
          "que a câmera mandou o log já reescalado para a faixa legal (saída HDMI em “Limited”, comum na Nikon): "
          "o app deixa de converter de volta para o código da câmera. Trocar de preset não muda este ajuste.",
          advanced=True),
        C("logc3_ei", "EI do ARRI LogC3", "800", LOGC3_EIS,
          "Só para o ARRI LogC3: a ALEXA grava uma curva para cada EI (veja nos metadados do clipe). O cinza fica "
          "no mesmo lugar; muda a compressão das luzes e das sombras. Trocar de preset não muda este ajuste.",
          advanced=True),
        F("exposicao", "Exposição", 0.0, -3, 3, 0.05, 2, " EV"),
        F("temperatura", "Temperatura", 0.0, -100, 100, 1, 0, "", "Negativo esfria, positivo esquenta."),
        F("tint", "Tonalidade", 0.0, -100, 100, 1, 0, "", "Negativo puxa para verde, positivo para magenta."),
        F("proteger_cores", "Proteger cores saturadas", 0.0, 0, 1, percent=True,
          tip="Traz com suavidade para dentro do Rec.709 as cores que a câmera grava além dele (LED, neon, céu "
              "muito saturado), antes do look e do negativo: em vez de estourar um canal e mudar de tom de "
              "repente, elas chegam à borda das cores. As cores comuns não mudam. Trocar de preset não muda este "
              "ajuste."),
    ], "Perfil de cor e balanço"),

    Section("lab", "Laboratório (negativo e cópia)", "lab_on", [
        B("lab_on", "Ativo", False),
        C("lab_negativo", "Negativo", "vision3_250d", NEGATIVOS,
          "Filme da câmera. Cada um tem latitude, contraste e mistura de camadas próprios (aproximações artísticas)."),
        F("lab_revelacao", "Revelação (puxar / forçar)", 0.0, -2, 3, 0.5, 1, " stop",
          "Forçar (+) aumenta o contraste, fecha as sombras e aumenta o grão; puxar (−) suaviza."),
        B("lab_grao", "Grão no negativo", False,
          "Põe o grão (seção Grão, que precisa estar ligada) dentro do negativo, na densidade de cada camada, "
          "antes da cópia: a curva da cópia molda o grão, que some nos pretos e nas altas luzes estouradas, e o "
          "azul tem mais grão que o verde e o vermelho, como nos datasheets da Kodak. A resposta por tom da "
          "seção Grão deixa de valer: quem decide é a cópia."),
        C("lab_grao_modelo", "Modelo do grão no negativo", "ruido", GRAO_MODELOS,
          "Ruído: o campo do grão de sempre somado à densidade. Físico (Beta): cada camada vira grãos de prata "
          "opacos espalhados ao acaso, tantos quanto a densidade daquele ponto pede (lei de Nutting); nas partes "
          "finas do negativo aparecem grãos soltos, nas densas, buracos soltos, sem nenhum ajuste por faixa de "
          "brilho. A força segue os datasheets da Kodak e o tamanho segue a bitola, o ISO e o Tamanho do grão. "
          "Mais pesado para a placa de vídeo."),
        C("lab_copia", "Cópia", "2383", COPIAS_LAB,
          "Filme em que o negativo é copiado para a projeção. Sem cópia, o negativo é só invertido, como num scan."),
        C("lab_processo", "Processo", "normal", PROCESSOS,
          "Technicolor separa a cena em três (ou dois) registros preto e branco e imprime corantes puros."),
        F("lab_processo_forca", "Força do processo", 1.0, 0, 1, percent=True,
          tip="Mistura o processo especial com o caminho normal (negativo + cópia)."),
        F("lab_chave", "Chave preta (Technicolor)", 0.3, 0, 1, percent=True,
          tip="Imagem preto e branco de baixo contraste somada aos corantes: pretos mais profundos."),
        F("lab_luz_r", "Luz vermelha da copiadora", 0.0, -12, 12, 0.5, 1, " pt",
          "Pontos de luz da copiadora (12 pontos = 1 stop da cópia; cerca de 7 pontos = 1 stop da câmera). Mais "
          "vermelho deixa a cópia mais ciano, como no laboratório."),
        F("lab_luz_g", "Luz verde da copiadora", 0.0, -12, 12, 0.5, 1, " pt",
          "Mais verde deixa a cópia mais magenta."),
        F("lab_luz_b", "Luz azul da copiadora", 0.0, -12, 12, 0.5, 1, " pt",
          "Mais azul deixa a cópia mais amarela (quente)."),
        F("lab_densidade", "Densidade da cópia", 0.0, -12, 12, 0.5, 1, " pt",
          "Luz nas três cores juntas: mais pontos = cópia mais escura. Use com a Exposição para "
          "compensar sub ou superexposição, como um laboratório."),
        F("lab_separacao", "Separação de cores (Hue Split)", 0.0, 0, 1, percent=True,
          tip="Afasta as cores umas das outras em volta de um eixo (laranja ↔ verde-azulado), como a separação "
              "das câmeras de três tiras: pele mais quente, céu e sombras mais frios. O cinza não muda."),
        F("lab_separacao_eixo", "Eixo da separação", 35, 0, 360, 1, 0, "°",
          "Matiz do polo quente do eixo (35° = laranja, o par teal & orange).", advanced=True),
        F("lab_saturacao_filme", "Saturação do filme", 1.0, 0, 2, 0.01, 2, "×",
          "Saturação dentro do negativo (na densidade), como a do próprio filme. O cinza não muda."),
        F("lab_saturacao", "Saturação final", 1.0, 0, 2, 0.01, 2, "×", "Saturação depois da cópia."),
        F("lab_dens_r", "Densidade dos vermelhos", 1.0, 0, 2, 0.01, 2, "×",
          "Acima de 1, vermelhos mais escuros e ricos; abaixo, mais claros. Cinzas e as outras cores não mudam."),
        F("lab_dens_g", "Densidade dos verdes", 1.0, 0, 2, 0.01, 2, "×",
          "Acima de 1, verdes mais escuros e ricos; abaixo, mais claros."),
        F("lab_dens_b", "Densidade dos azuis", 1.0, 0, 2, 0.01, 2, "×",
          "Acima de 1, azuis mais densos e profundos (céu); abaixo, mais claros."),
        F("lab_pe", "Pé da cópia (preto)", 0.0, -1, 1, 0.01, 2,
          tip="Positivo lava os pretos (a cópia chega a menos densidade); negativo aprofunda."),
        F("lab_sombras_rolagem", "Rolagem das sombras", 0.0, 0, 1, percent=True,
          tip="Entrada mais suave no preto: as sombras ganham detalhe e perdem dureza."),
        F("lab_luzes_rolagem", "Rolagem das altas luzes", 0.0, 0, 1, percent=True,
          tip="Chegada mais suave ao branco: as altas luzes estouram menos."),
        F("lab_pele_matiz", "Matiz da pele", 0.0, -30, 30, 1, 0, "°",
          "Negativo puxa a pele para o vermelho; positivo para o amarelo."),
        F("lab_pele_sat", "Saturação da pele", 0.0, -1, 1, 0.01, 2, tip="Mais ou menos cor só nos tons de pele."),
        F("lab_bypass_negativo", "Bleach bypass no negativo", 0.0, 0, 1, percent=True,
          tip="A prata fica no negativo: mais contraste e menos cor, principalmente nas altas luzes."),
        F("lab_bypass_copia", "Bleach bypass na cópia", 0.0, 0, 1, percent=True,
          tip="A prata fica na cópia: pretos mais profundos e cor mais contida (o processo Retenção de prata em "
              "quantidade ajustável)."),
        F("lab_neutro_negativo", "Curva neutra do negativo", 0.0, 0, 1, percent=True,
          tip="Iguala as curvas das três camadas do negativo: tira a variação de cor entre sombras e luzes do "
              "filme.", advanced=True),
        F("lab_neutro_copia", "Curva neutra da cópia", 0.0, 0, 1, percent=True,
          tip="Iguala as curvas das três camadas da cópia.", advanced=True),
        F("lab_diafonia", "Mistura entre camadas", 1.0, 0, 2, 0.01, 2, "×",
          "Absorções indesejadas dos corantes: acima de 1 a cor fica mais suja e densa; abaixo, mais pura.",
          advanced=True),
        C("lab_scanner", "Tipo de scanner", "rgb", SCANNERS,
          "Só na cópia \"Sem cópia\". RGB estreito lê cada camada do negativo sozinha (o de sempre); luz branca "
          "vê as camadas misturadas, como uma câmera fotografando o negativo numa mesa de luz: cores menos "
          "saturadas, cinza igual."),
        F("lab_vencida", "Película vencida", 0.0, 0, 30, 1, 0, " anos",
          "Anos guardada fora da geladeira: véu que levanta e tinge as sombras, menos sensibilidade e menos "
          "contraste, mais na camada do azul (a mais rápida). Regra prática dos laboratórios, não uma medida."),
        B("lab_pre_exposicao", "Pré-exposição (flashing)", False,
          "Uma luz uniforme no negativo antes da cena: levanta e suaviza as sombras e quase não mexe nas altas "
          "luzes."),
        F("lab_pre_exposicao_stops", "Pré-exposição abaixo do cinza", 4.0, 1, 8, 0.5, 1, " stops",
          "Quanto abaixo do cinza médio fica a luz da pré-exposição: menos stops, mais efeito."),
        C("lab_pre_exposicao_cor", "Cor da pré-exposição", "neutra", CORES_PRE_EXPOSICAO,
          "Cor da luz da pré-exposição: tinge as sombras."),
    ], "Simula a película de verdade: negativo, revelação, luzes da copiadora e cópia"),

    Section("cor", "Cor da película", "cor_on", [
        B("cor_on", "Ativo", False),
        F("cor_forca", "Intensidade do look", 1.0, 0, 1, percent=True),
        F("contraste", "Contraste", 1.0, 0.5, 2.0, 0.01, 2),
        F("meio_tom", "Tom médio", 0.45, 0.30, 0.60, 0.005, 3, tip="Brilho do cinza médio na saída."),
        F("preto", "Preto da película", 0.0, 0, 0.15, 0.002, 3, tip="Película raramente chega ao preto absoluto."),
        F("branco", "Branco da película", 1.0, 0.70, 1.0, 0.002, 3),
        F("rolagem_luzes", "Suavidade das altas luzes", 0.0, 0, 1, percent=True),
        F("rolagem_sombras", "Suavidade das sombras", 0.0, 0, 1, percent=True),
        F("saturacao", "Saturação", 1.0, 0, 2, 0.01, 2),
        F("densidade", "Densidade de cor", 0.0, 0, 1, percent=True,
          tip="Cores saturadas ficam mais escuras e ricas, como em película."),
        F("sombras_matiz", "Cor das sombras", 200, 0, 360, 1, 0, "°"),
        F("sombras_forca", "Força nas sombras", 0.0, 0, 1, percent=True),
        F("luzes_matiz", "Cor das altas luzes", 35, 0, 360, 1, 0, "°"),
        F("luzes_forca", "Força nas altas luzes", 0.0, 0, 1, percent=True),
        F("equilibrio", "Equilíbrio sombras/luzes", 0.0, -1, 1, 0.01, 2),
        F("envelhecimento", "Envelhecimento (desbotado)", 0.0, 0, 1, percent=True,
          tip="Imita cópias antigas: preto lavado e cor puxando para o magenta."),
        F("contraste_r", "Contraste do vermelho", 1.0, 0.8, 1.2, 0.005, 3, advanced=True),
        F("contraste_g", "Contraste do verde", 1.0, 0.8, 1.2, 0.005, 3, advanced=True),
        F("contraste_b", "Contraste do azul", 1.0, 0.8, 1.2, 0.005, 3, advanced=True),
        F("offset_r", "Equilíbrio do vermelho", 0.0, -0.5, 0.5, 0.005, 3, " EV", advanced=True),
        F("offset_g", "Equilíbrio do verde", 0.0, -0.5, 0.5, 0.005, 3, " EV", advanced=True),
        F("offset_b", "Equilíbrio do azul", 0.0, -0.5, 0.5, 0.005, 3, " EV", advanced=True),
        F("verdes_matiz", "Matiz dos verdes", 0.0, -40, 40, 1, 0, "°", advanced=True),
        F("azuis_matiz", "Matiz dos azuis", 0.0, -40, 40, 1, 0, "°", advanced=True),
        F("pele_sat", "Saturação da pele", 0.0, -1, 1, 0.01, 2, advanced=True),
        F("pele_matiz", "Matiz da pele", 0.0, -30, 30, 1, 0, "°", "Negativo puxa a pele para o vermelho; positivo para o "
          "amarelo.", advanced=True),
        F("pele_luz", "Luz da pele", 0.0, -1, 1, 0.01, 2, tip="Negativo deixa a pele mais densa e escura; positivo "
          "clareia.", advanced=True),
        B("pb", "Preto e branco", False),
        C("pb_filtro", "Filtro do P&B", "pan", [
            ("pan", "Pancromático (neutro)"), ("vermelho", "Vermelho (céu escuro)"),
            ("laranja", "Laranja"), ("amarelo", "Amarelo"), ("verde", "Verde"), ("azul", "Azul (ortocromático)"),
        ]),
        C("virada", "Viragem do P&B", "nenhuma", [
            ("nenhuma", "Nenhuma"), ("sepia", "Sépia"), ("selenio", "Selênio"),
            ("cianotipo", "Cianótipo"), ("ouro", "Ouro"),
        ]),
        F("virada_forca", "Força da viragem", 0.5, 0, 1, percent=True),
    ], "Curva, cor e tons da emulsão"),

    Section("lut", "LUT externo", "lut_on", [
        B("lut_on", "Ativo", False),
        Param("lut_arquivo", "Arquivo .cube", "file", ""),
        C("lut_entrada", "O LUT espera", "rec709", LUT_ENTRADAS,
          "LUTs de cópia do Resolve (Kodak 2383 etc.) esperam Cineon; os do Premiere esperam Rec.709."),
        C("lut_posicao", "Aplicar", "depois", [("depois", "Depois do look de película"), ("lugar", "No lugar do look")]),
        F("lut_forca", "Intensidade do LUT", 1.0, 0, 1, percent=True),
    ], "Use LUTs do Premiere, Resolve ou qualquer .cube"),

    Section("grao", "Grão", "grao_on", [
        B("grao_on", "Ativo", False),
        F("grao_forca", "Intensidade", 1.0, 0, 3, 0.01, 2),
        F("grao_tamanho", "Tamanho", 1.0, 0.3, 4, 0.01, 2, "×", "Multiplica o tamanho natural da bitola e do ISO."),
        F("grao_aspereza", "Aspereza", 0.22, 0, 1, percent=True, tip="Mistura grãos finos com aglomerados maiores."),
        F("grao_cor", "Grão colorido", 0.3, 0, 1, percent=True, tip="0% é grão monocromático."),
        F("grao_sombras", "Nas sombras", 0.8, 0, 2, 0.01, 2),
        F("grao_meios", "Nos tons médios", 1.0, 0, 2, 0.01, 2),
        F("grao_luzes", "Nas altas luzes", 0.45, 0, 2, 0.01, 2),
        B("grao_animado", "Grão muda a cada quadro", True),
        I("grao_semente", "Semente", 7, 0, 9999, "Muda o padrão aleatório do grão.", advanced=True),
        F("grao_maciez", "Maciez pelo grão", 0.0, 0, 1, percent=True,
          tip="Amacia a imagem até a nitidez do próprio grão, para ele não parecer uma camada por cima de uma "
              "imagem mais nítida que ele. 100% = a maciez do grão; 0% = como antes."),
        F("grao_respiracao", "Respiração por camada", 0.0, 0, 1, percent=True,
          tip="A cor e o brilho de cada quadro variam um pouco, de leve e cada camada por si (vermelho, verde e "
              "azul), como na película: a emulsão, a revelação e a luz da copiadora nunca são iguais de um "
              "quadro para outro. Muda a cada quadro e devagar ao longo da fita, sempre igual para o mesmo quadro "
              "e a mesma semente. 100% = cerca de um ponto de copiadora; 0% = desligado."),
    ], "Textura da emulsão"),

    Section("halacao", "Halação", "hal_on", [
        B("hal_on", "Ativo", False),
        F("hal_forca", "Intensidade", 0.6, 0, 3, 0.01, 2),
        F("hal_raio", "Raio", 14, 1, 100, 0.5, 1, " px", "Medido num quadro de 1080 linhas."),
        F("hal_limiar", "Limiar", 2.5, 0, 6, 0.05, 2, " EV", "A partir de quantos stops acima do cinza médio brilha."),
        COR("hal_cor", "Cor", (1.0, 0.27, 0.05)),
        C("hal_modelo", "Modelo", "brilho", HAL_MODELOS,
          "Brilho: o halo nasce só acima do Limiar e é somado por cima (como sempre foi). Física: a luz que "
          "atravessa a emulsão volta refletida pela base do filme e expõe de novo a camada do vermelho, antes da "
          "cópia; nasce de toda a imagem na proporção da exposição (o Limiar não vale), o raio segue o tamanho do "
          "quadro da bitola e o brilho de áreas lisas não muda: o halo só aparece em volta das luzes fortes."),
    ], "Brilho avermelhado em volta das luzes"),

    Section("bloom", "Bloom e difusão", "bloom_on", [
        B("bloom_on", "Ativo", False),
        F("bloom_forca", "Bloom", 0.25, 0, 2, 0.01, 2),
        F("bloom_raio", "Raio do bloom", 45, 5, 250, 1, 0, " px"),
        F("bloom_limiar", "Limiar do bloom", 1.8, 0, 6, 0.05, 2, " EV"),
        F("nevoa_forca", "Névoa (filtro difusor)", 0.0, 0, 1, percent=True,
          tip="Imita filtros tipo Pro-Mist: luzes espalham e o contraste cai."),
        F("nevoa_raio", "Raio da névoa", 70, 10, 300, 1, 0, " px"),
    ], "Brilho suave nas luzes"),

    Section("lente", "Lente e nitidez", "lente_on", [
        B("lente_on", "Ativo", False),
        F("maciez", "Maciez", 0.0, 0, 1, percent=True),
        F("raio_maciez", "Raio da maciez", 1.2, 0.3, 6, 0.05, 2, " px"),
        F("nitidez", "Recuperar detalhe", 0.0, 0, 2, 0.01, 2, tip="Devolve parte do detalhe fino (efeito de nitidez)."),
        F("aberracao", "Aberração cromática", 0.0, 0, 10, 0.05, 2, " px"),
        F("distorcao", "Distorção da lente", 0.0, -0.3, 0.3, 0.005, 3, tip="Negativo = almofada, positivo = barril."),
        F("vinheta", "Vinheta", 0.0, 0, 1, percent=True),
        F("vinheta_raio", "Raio da vinheta", 0.85, 0.2, 1.6, 0.01, 2),
        F("vinheta_suavidade", "Suavidade da vinheta", 0.8, 0.05, 1.5, 0.01, 2),
        F("vinheta_redondeza", "Redondeza", 0.5, 0, 1, percent=True),
    ], "Maciez, aberração e vinheta"),

    Section("projetor", "Projetor", "proj_on", [
        B("proj_on", "Ativo", False),
        F("tremor_x", "Tremor horizontal", 1.2, 0, 12, 0.05, 2, " px"),
        F("tremor_y", "Tremor vertical", 0.9, 0, 12, 0.05, 2, " px"),
        F("tremor_rot", "Tremor de rotação", 0.04, 0, 0.6, 0.005, 3, "°"),
        F("tremor_vel", "Velocidade do tremor", 1.0, 0.1, 3, 0.01, 2, "×"),
        F("cintilacao", "Cintilação", 0.05, 0, 0.4, 0.005, 3, " EV", "Variação de brilho entre quadros."),
        F("cintilacao_vel", "Velocidade da cintilação", 1.0, 0.1, 3, 0.01, 2, "×"),
    ], "Tremor do quadro e cintilação"),

    Section("desgaste", "Defeitos da película", "desg_on", [
        B("desg_on", "Ativo", False),
        B("poeira_on", "Poeira", True, "Sujeira que passa pelo quadro, diferente a cada quadro."),
        F("poeira", "Quantidade de poeira", 0.3, 0, 1, percent=True),
        F("poeira_tamanho", "Tamanho da poeira", 1.0, 0.3, 4, 0.01, 2, "×"),
        C("poeira_tipo", "Tipo de poeira", "escura", [
            ("escura", "Escura (sujeira na cópia)"), ("clara", "Clara (sujeira no negativo)"), ("mista", "Mista")]),
        B("riscos_on", "Riscos", True, "Riscos verticais de película arrastada no projetor."),
        F("riscos", "Quantidade de riscos", 0.15, 0, 1, percent=True),
        F("riscos_largura", "Largura dos riscos", 1.5, 0.3, 6, 0.05, 2, " px"),
        B("cabelo_on", "Fio de cabelo no quadro", False, "Um fio preso na janela do projetor, tremendo na borda."),
        F("cabelo", "Frequência do fio", 0.5, 0, 1, percent=True),
        F("cabelo_tamanho", "Tamanho do fio", 1.0, 0.3, 3, 0.01, 2, "×"),
        B("manchas_on", "Manchas químicas", False, "Manchas da revelação que aparecem por alguns quadros."),
        F("manchas", "Frequência das manchas", 0.3, 0, 1, percent=True),
        B("queima_on", "Clarões de fim de rolo", False, "Quadros estourados de luz, como no começo e fim do rolo."),
        F("queima", "Frequência dos clarões", 0.25, 0, 1, percent=True),
        B("marcas_on", "Marcas de troca de rolo", False, "Os círculos no canto que avisam o projecionista."),
        F("marcas_intervalo", "Intervalo das marcas", 20, 4, 120, 1, 0, " s"),
        B("cor_instavel_on", "Cor instável", False, "A cor oscila levemente de um quadro para outro."),
        F("cor_instavel", "Intensidade da oscilação", 0.4, 0, 1, percent=True),
        B("emenda_on", "Emendas", False, "Linha de emenda e pulo do quadro onde a película foi colada."),
        F("emenda", "Frequência das emendas", 0.3, 0, 1, percent=True),
        B("vazamento_on", "Vazamento de luz", True, "Luz entrando pela lateral da câmera."),
        F("vazamento", "Intensidade do vazamento", 0.0, 0, 1, percent=True),
        COR("vazamento_cor", "Cor do vazamento", (1.0, 0.42, 0.12)),
        F("vazamento_vel", "Velocidade do vazamento", 0.5, 0.05, 3, 0.01, 2, "×"),
        I("desgaste_semente", "Semente", 11, 0, 9999, advanced=True),
    ], "Escolha quais aparecem; dá para combinar vários"),

    Section("moldura", "Moldura e proporção", "mold_on", [
        B("mold_on", "Ativo", False),
        C("proporcao", "Proporção", "original", PROPORCOES),
        F("cantos", "Cantos arredondados", 0.0, 0, 0.25, 0.002, 3, tip="Cantos da janela do projetor, típico de 8 e 16 mm."),
        F("borda_suave", "Suavidade da borda", 0.002, 0, 0.05, 0.0005, 4),
        F("borda_irregular", "Borda irregular", 0.0, 0, 1, percent=True),
        COR("cor_barras", "Cor das barras", (0.0, 0.0, 0.0)),
    ], "Barras e janela do projetor"),

    Section("scan", "Scan da película", "scan_on", [
        B("scan_on", "Ativo", False),
        C("scan_formato", "Película", "bitola", [
            ("bitola", "Da bitola escolhida"), ("35mm", "35 mm (4 furos por quadro)"), ("16mm", "16 mm (1 furo)"),
            ("super16", "Super 16"), ("super8", "Super 8"),
            ("135", "Foto 35 mm (135, 8 furos)"), ("meio_quadro", "Foto meio quadro (4 furos)"),
            ("120_66", "Foto 120, 6 × 6 (sem furos)"), ("120_645", "Foto 120, 6 × 4,5 (sem furos)")],
          "Medidas reais de cada película: furos, linhas entre quadros e bordas."),
        C("scan_tipo", "Tipo de scan", "copia", [
            ("copia", "Cópia projetada (furos claros)"), ("negativo", "Negativo invertido (furos escuros)")]),
        C("scan_ajuste", "Enquadramento", "caber", [
            ("caber", "Mostrar o vídeo inteiro (barras no quadro)"), ("preencher", "Preencher o quadro (corta as bordas)")]),
        F("scan_zoom", "Aproximação", 1.0, 1.0, 1.6, 0.01, 2, "×", "Aproxima do quadro e esconde parte das bordas."),
        B("scan_vizinhos", "Mostrar quadros vizinhos", True, "Mostra pedaços do quadro de cima e de baixo."),
        C("scan_texto", "Texto da borda", "auto", [
            ("auto", "Automático (filme e ISO)"), ("nenhum", "Nenhum"), ("kodak_vision3", "KODAK VISION3"),
            ("eastman", "EASTMAN KODAK SAFETY FILM"), ("fuji", "FUJIFILM ETERNA"), ("kodak_2383", "KODAK 2383")]),
        F("scan_luz", "Brilho dos furos", 1.0, 0.3, 2.0, 0.01, 2, "×"),
        COR("scan_base", "Cor da base", (0.035, 0.03, 0.027), "Cor da película fora da imagem."),
    ], "Bordas, furos e quadros vizinhos, como num scan real"),

    # 1.6: Cor por planos (módulo Beta "cor_planos"; `planes.py`). Distâncias em px@1080 a partir do centro.
    Section("planos", "Cor por planos", "planos_on", [
        B("planos_on", "Ativo", False),
        C("planos_tipo", "Separação", "linear", [
            ("linear", "Degradê linear (o fundo do lado da direção)"),
            ("radial", "Degradê radial (a frente dentro do círculo)")],
          "Como separar a frente do fundo: uma linha (céu e chão) ou um círculo em volta do assunto."),
        F("planos_angulo", "Direção", 0.0, -180, 180, 1, 0, "°",
          "Para que lado fica o fundo no degradê linear: 0° = em cima, 90° = à direita, 180° = embaixo."),
        F("planos_pos_x", "Centro horizontal", 0.0, -1920, 1920, 1, 0, " px",
          "Desloca a linha ou o círculo para os lados (px de um quadro de 1080 linhas; 0 = centro)."),
        F("planos_pos_y", "Centro vertical", 0.0, -1080, 1080, 1, 0, " px",
          "Desloca a linha ou o círculo para cima (negativo) ou para baixo (positivo)."),
        F("planos_raio", "Raio", 400.0, 10, 2000, 1, 0, " px", "Tamanho do círculo do degradê radial."),
        F("planos_suavidade", "Suavidade", 300.0, 0, 2000, 1, 0, " px",
          "Largura da passagem entre frente e fundo. 0 = borda seca."),
        B("planos_inverter", "Trocar frente e fundo", False),
        F("planos_frente_exposicao", "Exposição", 0.0, -3, 3, 0.05, 2, " EV"),
        F("planos_frente_temperatura", "Temperatura", 0.0, -100, 100, 1, 0, "", "Negativo esfria, positivo esquenta."),
        F("planos_frente_tonalidade", "Tonalidade", 0.0, -100, 100, 1, 0, "",
          "Negativo puxa para verde, positivo para magenta."),
        F("planos_frente_saturacao", "Saturação", 0.0, -100, 100, 1, 0, " %", "-100% deixa em preto e branco."),
        F("planos_frente_contraste", "Contraste", 0.0, -100, 100, 1, 0, " %"),
        F("planos_fundo_exposicao", "Exposição", 0.0, -3, 3, 0.05, 2, " EV"),
        F("planos_fundo_temperatura", "Temperatura", 0.0, -100, 100, 1, 0, "", "Negativo esfria, positivo esquenta."),
        F("planos_fundo_tonalidade", "Tonalidade", 0.0, -100, 100, 1, 0, "",
          "Negativo puxa para verde, positivo para magenta."),
        F("planos_fundo_saturacao", "Saturação", 0.0, -100, 100, 1, 0, " %", "-100% deixa em preto e branco."),
        F("planos_fundo_contraste", "Contraste", 0.0, -100, 100, 1, 0, " %"),
        B("planos_proteger_pele", "Proteger a pele", True,
          "Os ajustes da frente e do fundo não mexem na pele (ela só muda pelos ajustes da pele)."),
        F("planos_pele_matiz", "Matiz", 0.0, -30, 30, 1, 0, "°",
          "Negativo puxa a pele para o vermelho; positivo para o amarelo."),
        F("planos_pele_saturacao", "Saturação", 0.0, -100, 100, 1, 0, " %"),
        F("planos_pele_luz", "Luz", 0.0, -1.5, 1.5, 0.05, 2, " EV"),
        F("planos_pele_uniformizar", "Uniformizar", 0.0, 0, 1, percent=True,
          tip="Deixa a cor da pele mais uniforme (menos manchas avermelhadas). Só a cor: a textura fica igual."),
        F("planos_pele_centro", "Cor da pele", 64.5, 0, 360, 0.5, 1, "°",
          "Matiz da pele que a máscara procura. O conta-gotas acerta este valor clicando na pele da prévia.",
          advanced=True),
        F("planos_pele_largura", "Largura da cor da pele", 21.0, 5, 60, 0.5, 1, "°",
          "Quanto o matiz pode se afastar da cor da pele. Estreite se madeira ou areia entrarem na máscara.",
          advanced=True),
    ], "Frente, fundo e pele com ajustes próprios"),

    # 1.6 (`tempo_camera.py`, módulo Beta "camera_cinema"): obturador de película a partir de vídeo rápido.
    Section("obturador", "Obturador de película", "obturador_on", [
        B("obturador_on", "Ativo", False),
        C("obturador_angulo", "Ângulo do obturador", "180", ANGULOS,
          "Quanto tempo de cada quadro o obturador fica aberto: 180° = metade (1/48 s a 24 qps), o rastro de "
          "movimento do cinema. Vale quando o vídeo tem pelo menos o dobro dos quadros por segundo da saída "
          "(50, 60 ou 120 qps exportados a 24, 25 ou 30): os quadros dentro da janela aberta são misturados na luz. "
          "No modo Película, a exportação com outra taxa (a prévia da exportação mostra); no modo Edição, cada "
          "clipe rápido numa sequência mais lenta."),
    ], "Rastro de movimento de uma câmera de cinema"),

    # 1.6 (`anamorfico.py`, módulo Beta "anamorfico"): lente anamórfica.
    Section("anamorfico", "Lente anamórfica", "anam_on", [
        B("anam_on", "Ativo", False),
        C("anam_compressao", "Desespremer", "nenhuma", [
            ("nenhuma", "Não (o vídeo já está na proporção certa)"), ("1.33", "1,33× (adaptador em 16:9 → 2,37:1)"),
            ("1.5", "1,5×"), ("1.8", "1,8×"), ("2.0", "2× (cinema em 4:3 → 2,66:1)")],
          "Para vídeo filmado com lente ou adaptador anamórfico, que chega espremido na horizontal: a imagem é "
          "esticada na largura e fica numa caixa de letra (faixas pretas em cima e embaixo)."),
        F("anam_flare", "Risco de luz", 0.5, 0, 1, percent=True,
          tip="A linha horizontal comprida que as luzes fortes fazem numa lente anamórfica."),
        F("anam_flare_limiar", "Limiar do risco", 2.0, 0, 5, 0.1, 1, " stops",
          "Quanto acima do cinza médio a luz precisa estar para riscar."),
        F("anam_flare_comprimento", "Comprimento do risco", 420.0, 40, 1200, 10, 0, " px"),
        COR("anam_flare_cor", "Cor do risco", (0.35, 0.6, 1.0)),
        F("anam_barril", "Barril horizontal", 0.3, 0, 1, percent=True,
          tip="O centro estica um pouco na horizontal, mais na linha do meio (o \"mumps\" das anamórficas)."),
        F("anam_bordas", "Bordas macias", 0.4, 0, 1, percent=True,
          tip="As laterais ficam mais macias que o centro."),
    ], "Desespremer, risco de luz e bordas"),

    # 1.6 (`data_impressa.py`, módulo Beta "data_impressa"): a data laranja das câmeras com data.
    Section("data", "Data impressa", "data_on", [
        B("data_on", "Ativo", False),
        I("data_ano", "Ano", 1998, 1970, 2099),
        I("data_mes", "Mês", 10, 1, 12),
        I("data_dia", "Dia", 29, 1, 31),
        C("data_formato", "Formato", "aa_mm_dd", [
            ("aa_mm_dd", "'98 10 29 (ano, mês, dia)"), ("mm_dd_aa", "10 29 '98 (mês, dia, ano)"),
            ("dd_mm_aa", "29 10 '98 (dia, mês, ano)"), ("aaaa_mm_dd", "1998 10 29")]),
        C("data_canto", "Canto", "inf_dir", [
            ("inf_dir", "Embaixo à direita"), ("inf_esq", "Embaixo à esquerda"),
            ("sup_dir", "Em cima à direita"), ("sup_esq", "Em cima à esquerda")]),
        COR("data_cor", "Cor", (1.0, 0.45, 0.08)),
        F("data_intensidade", "Intensidade", 0.6, 0, 1, percent=True,
          tip="Quanto o mostrador expõe o negativo: forte, ele estoura e brilha em volta (com a halação)."),
        F("data_tamanho", "Tamanho", 34.0, 12, 120, 1, 0, " px", "Altura dos números (num quadro de 1080 linhas)."),
        F("data_margem", "Distância do canto", 60.0, 0, 300, 1, 0, " px", advanced=True),
    ], "A data laranja das câmeras dos anos 80 e 90"),

    # 1.6 (`montagem_filme.py`, módulo Beta "montagem_pelicula"): os cortes da montagem viram emendas na película.
    Section("montagem_filme", "A montagem na película", "mfilme_on", [
        B("mfilme_on", "Ativo", False),
        F("mfilme_emenda", "Emendas visíveis", 0.7, 0, 1, percent=True,
          tip="Em quantos cortes secos da faixa V1 a fita da emenda aparece no primeiro quadro do clipe novo."),
        F("mfilme_clarao", "Clarão no corte", 0.4, 0, 1, percent=True,
          tip="A luz que passa pela junta da emenda: o primeiro quadro depois do corte clareia."),
        F("mfilme_salto", "Pulo no corte", 0.5, 0, 1, percent=True,
          tip="A emenda é mais grossa e pula na janela do projetor por um ou dois quadros."),
        I("mfilme_semente", "Semente", 7, 0, 9999, advanced=True),
        B("rolo_on", "Rolos de Super 8", False,
          "Um rolo de 50 pés tem 3 600 quadros: no fim dele a luz vela a película e a troca de rolo dá um pulo."),
        C("rolo_cadencia", "Cadência do rolo", "18", [
            ("18", "18 qps (3 min 20 s por rolo)"), ("24", "24 qps (2 min 30 s por rolo)")]),
        F("rolo_velamento", "Velamento no fim do rolo", 0.7, 0, 1, percent=True),
        COR("rolo_cor", "Cor do velamento", (1.0, 0.42, 0.12)),
    ], "Emendas nos cortes e rolos de Super 8"),
]

LIST_KINDS = ("color", "wheel")  # valores guardados como lista ([r, g, b] ou [x, y])


def _default_of(p: Param) -> Any:
    return list(p.default) if p.kind in LIST_KINDS else p.default


def _clean(p: Param, v: Any) -> Any:
    """Valor limpo de um parâmetro, ou levanta ValueError/TypeError se for inválido."""
    if p.kind == "float":
        f = float(v)
        if math.isnan(f):
            raise ValueError(v)
        return min(max(f, p.min), p.max)
    if p.kind == "int":
        return int(min(max(int(v), p.min), p.max))
    if p.kind == "bool":
        return bool(v)
    if p.kind == "choice":
        if str(v) not in [c[0] for c in p.choices]:
            raise ValueError(v)
        return str(v)
    if p.kind == "color":
        cols = [float(c) for c in list(v)[:3]]
        if len(cols) != 3 or not all(math.isfinite(c) for c in cols):
            raise ValueError(v)
        return [min(max(c, 0.0), 1.0) for c in cols]
    if p.kind == "wheel":
        # Ponto dentro do disco unitário: direção = matiz, distância = força.
        x, y = (float(c) for c in list(v)[:2])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(v)
        r = math.hypot(x, y)
        return [x / r, y / r] if r > 1.0 else [x, y]
    if p.kind == "file":
        return str(v or "")
    raise ValueError(p.kind)


@dataclass
class Schema:
    """Um conjunto de seções (a interface é gerada a partir dele) com padrões e limpeza dos valores.

    `FILM` é o esquema do look de película; o modo Edição tem os seus em `editparams`.
    """

    sections: list[Section]
    params: dict[str, Param] = field(init=False)

    def __post_init__(self) -> None:
        self.params = {p.key: p for s in self.sections for p in s.params}

    def defaults(self) -> dict[str, Any]:
        return {k: _default_of(p) for k, p in self.params.items()}

    def sanitize(self, values: dict[str, Any] | None) -> dict[str, Any]:
        """Completa com os padrões, descarta chaves desconhecidas e limita à faixa."""
        out = self.defaults()
        for k, v in (values or {}).items():
            p = self.params.get(k)
            if p is None:
                continue
            try:
                out[k] = _clean(p, v)
            except (TypeError, ValueError):
                pass
        return out


FILM = Schema(SECTIONS)
PARAMS: dict[str, Param] = FILM.params

# Chaves de animação no look: todo ajuste numérico contínuo e toda cor (escolhas, liga/desliga, inteiros como
# sementes e eixos, e arquivos ficam de fora). Receita "Tornar um ajuste animável" no AGENTS.md.
ANIMATABLE_KINDS = ("float", "color")
for _p in PARAMS.values():
    if _p.kind in ANIMATABLE_KINDS:
        _p.animatable = True
del _p


def defaults() -> dict[str, Any]:
    return FILM.defaults()


def sanitize(values: dict[str, Any]) -> dict[str, Any]:
    """Completa e limita valores vindos de presets ou arquivos."""
    return FILM.sanitize(values)


# ------------------------------------------------------------------ 1.6: o que a 1.5 lê (formato 4)
# Retrato das chaves e das opções de escolha da 1.5.0, por esquema ("look" = FILM, "video"/"audio" = ajustes de
# clipe). A 1.5 descarta chave desconhecida e opção que não conhece (`Schema.sanitize`), então um projeto que usa
# um ajuste da 1.6 abriria nela sem o efeito: com algo fora do retrato, o projeto vai para o formato 4, que a
# 1.5 recusa com aviso (`project.FEATURES_V4`, `timeline.FEATURES_V4`). Ajuste novo não precisa de registro.
KNOWN_1_5_FILE = Path(__file__).with_name("data") / "conhecidos_1_5.json"


@lru_cache(maxsize=1)
def known_1_5() -> dict[str, dict[str, list[str] | None]]:
    """{"look"|"video"|"audio": {chave: opções da escolha, ou None}} como a 1.5.0 conhecia."""
    data = json.loads(KNOWN_1_5_FILE.read_text(encoding="utf-8"))
    return {k: data[k] for k in ("look", "video", "audio")}


def beyond_1_5(schema: Schema, known: dict[str, list[str] | None], values: dict[str, Any] | None,
               keys: dict[str, Any] | None = None) -> bool:
    """Se os valores usam algo que a 1.5 não lê: um ajuste novo fora do padrão, uma opção nova numa escolha
    ou chaves de animação num ajuste novo."""
    for k, v in (values or {}).items():
        p = schema.params.get(k)
        if p is None:
            continue
        try:
            v = _clean(p, v)
        except (TypeError, ValueError):
            continue
        if k not in known:
            if v != _default_of(p):
                return True
        elif p.kind == "choice" and known[k] is not None and v not in known[k]:
            return True
    return any(k in schema.params and k not in known for k in (keys or {}))

