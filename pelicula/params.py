"""Esquema de todos os parâmetros ajustáveis.

A interface é gerada a partir desta lista, e o motor lê os valores pelas chaves.
Distâncias em "px@1080" são pixels medidos num quadro de 1080 linhas e são
convertidas para a resolução real, então a prévia e o vídeo final ficam iguais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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


@dataclass
class Section:
    key: str
    title: str
    toggle: str | None
    params: list[Param] = field(default_factory=list)
    subtitle: str = ""


BITOLAS = [
    ("nenhuma", "Nenhuma (manual)"),
    ("8mm", "8 mm"),
    ("super8", "Super 8"),
    ("16mm", "16 mm"),
    ("super16", "Super 16"),
    ("35mm", "35 mm"),
    ("65mm", "65 mm"),
    ("imax", "IMAX 70 mm (15/70)"),
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
    ("logc3", "ARRI LogC3 (EI 800)"),
    ("vlog", "Panasonic V-Log"),
    ("log3g10", "RED Log3G10 (RWG) — R3D, Nikon N-RAW e R3D NE"),
    ("dwg", "DaVinci Intermediate (DaVinci Wide Gamut)"),
    ("cineon", "Cineon / DPX log"),
]

LUT_ENTRADAS = [
    ("rec709", "Rec.709 (LUTs criativos, Premiere)"),
    ("cineon", "Cineon log (LUTs de cópia do Resolve)"),
    ("logc3", "ARRI LogC3"),
    ("slog3", "Sony S-Log3"),
    ("nlog", "Nikon N-Log"),
    ("vlog", "Panasonic V-Log"),
    ("log3g10", "RED Log3G10 (RWG)"),
    ("dwg", "DaVinci Intermediate (DWG)"),
    ("linear", "Linear"),
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
        F("bitola_resolucao", "Perda de nitidez da bitola", 1.0, 0, 1, percent=True,
          tip="Quanto da maciez natural da bitola é aplicada."),
        F("bitola_vinheta", "Vinheta da bitola", 1.0, 0, 1, percent=True,
          tip="Escurecimento natural das bordas em bitolas pequenas."),
        F("mix_geral", "Força geral do efeito", 1.0, 0, 1, percent=True,
          tip="Mistura o resultado com o vídeo original."),
    ], "Bitola, sensibilidade e cópia"),

    Section("entrada", "Entrada e exposição", None, [
        C("entrada", "Perfil do vídeo", "rec709", ENTRADAS,
          "Como o vídeo foi gravado. Use o perfil log da câmera se gravou em log."),
        F("exposicao", "Exposição", 0.0, -3, 3, 0.05, 2, " EV"),
        F("temperatura", "Temperatura", 0.0, -100, 100, 1, 0, "", "Negativo esfria, positivo esquenta."),
        F("tint", "Tonalidade", 0.0, -100, 100, 1, 0, "", "Negativo puxa para verde, positivo para magenta."),
    ], "Perfil de cor e balanço"),

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
    ], "Textura da emulsão"),

    Section("halacao", "Halação", "hal_on", [
        B("hal_on", "Ativo", False),
        F("hal_forca", "Intensidade", 0.6, 0, 3, 0.01, 2),
        F("hal_raio", "Raio", 14, 1, 100, 0.5, 1, " px", "Medido num quadro de 1080 linhas."),
        F("hal_limiar", "Limiar", 2.5, 0, 6, 0.05, 2, " EV", "A partir de quantos stops acima do cinza médio brilha."),
        COR("hal_cor", "Cor", (1.0, 0.27, 0.05)),
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
            ("super16", "Super 16"), ("super8", "Super 8")],
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
]

PARAMS: dict[str, Param] = {p.key: p for s in SECTIONS for p in s.params}


def defaults() -> dict[str, Any]:
    return {k: (list(p.default) if p.kind == "color" else p.default) for k, p in PARAMS.items()}


def sanitize(values: dict[str, Any]) -> dict[str, Any]:
    """Completa e limita valores vindos de presets ou arquivos."""
    out = defaults()
    for k, v in (values or {}).items():
        p = PARAMS.get(k)
        if p is None:
            continue
        try:
            if p.kind == "float":
                f = float(v)
                if not math.isnan(f):
                    out[k] = min(max(f, p.min), p.max)
            elif p.kind == "int":
                out[k] = int(min(max(int(v), p.min), p.max))
            elif p.kind == "bool":
                out[k] = bool(v)
            elif p.kind == "choice":
                if str(v) in [c[0] for c in p.choices]:
                    out[k] = str(v)
            elif p.kind == "color":
                cols = [float(c) for c in list(v)[:3]]
                if len(cols) == 3 and all(math.isfinite(c) for c in cols):
                    out[k] = [min(max(c, 0.0), 1.0) for c in cols]
            elif p.kind == "file":
                out[k] = str(v or "")
        except (TypeError, ValueError):
            pass
    return out
