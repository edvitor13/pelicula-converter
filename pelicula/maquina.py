"""Máquina do tempo (1.6, módulo "maquina_tempo"): um ano e um lugar viram valores do look, com o motivo de cada um.

Um clique preenche ajustes comuns do look (bitola, sensibilidade, preto e branco, cor, cópia, grão, projeção,
desgaste, moldura e halação) a partir de uma tabela escrita à mão, uma linha por época e lugar (cinema, televisão
ou filme caseiro), cada linha com a razão histórica. Tudo continua editável: a máquina só escreve valores nos
controles de sempre, num passo só de desfazer (`ParamStore.set_all`), e a janela mostra antes o que vai mudar.

Toda linha escreve as mesmas chaves (`KEYS`), então o resultado não depende do look que estava antes nessas chaves;
as outras ficam como estão. A cadência da manivela (16 ou 18 qps) é tempo da montagem, por clipe (modo Edição): a
linha só sugere (`Row.cadence`), não aplica.

Fontes das datas (conhecimento público da história do cinema): filme ortocromático até meados dos anos 1920;
som e quadro Academy 1,37 a partir de 1932; CinemaScope (2,35) em 1953 e 1,85 nos EUA nos anos 50; Eastmancolor e
o fim do Technicolor de três tiras nos anos 50; 16 mm amador da Kodak em 1923, 8 mm em 1932, Kodachrome em 1935,
Super 8 em 1965 (filmado a 18 qps); 16 mm de reportagem na TV dos anos 60 e 70; Super 16 nas séries dos anos 90;
Vision (1996) e a cópia 2383 no fim dos anos 90; Vision3 em 2007 e a projeção digital na década de 2010.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .i18n import N_

YEAR_MIN, YEAR_MAX = 1920, 2020
VENUES = (("cinema", N_("Cinema")), ("tv", N_("Televisão")), ("caseiro", N_("Filme caseiro")))

# As chaves que toda linha escreve (o resto do look fica como está); `BASE` = o valor de quem a linha não fala.
BASE = dict(
    bitola="35mm", iso="250", pb=False, pb_filtro="pan", virada="nenhuma", virada_forca=0.5,
    cor_on=True, saturacao=1.0, contraste=1.0, envelhecimento=0.0, copia="nenhuma",
    grao_on=True, grao_forca=1.0,
    proj_on=False, tremor_x=1.2, tremor_y=0.9, cintilacao=0.05,
    desg_on=False, poeira_on=True, poeira=0.3, riscos_on=True, riscos=0.15,
    mold_on=True, proporcao="1.33", hal_on=True, hal_forca=0.6,
)
KEYS = tuple(BASE)


@dataclass(frozen=True)
class Row:
    venue: str
    start: int
    end: int           # inclusive
    title: str
    reason: str
    values: dict = field(default_factory=dict)
    cadence: str = ""  # sugestão para a manivela do modo Edição ("16", "18"; "" = a da sequência)

    def full_values(self) -> dict:
        return {**BASE, **self.values}


ROWS: tuple[Row, ...] = (
    # ------------------------------------------------------------------ cinema
    Row("cinema", 1920, 1931, N_("Cinema mudo"),
        N_("Filme ortocromático (enxerga quase só o azul), cópias viradas em sépia e projeção com cintilação e "
           "tremor; quadro 1,33 do cinema mudo, filmado a 16–18 qps na manivela."),
        dict(iso="50", pb=True, pb_filtro="azul", virada="sepia", virada_forca=0.45, cor_on=False,
             contraste=1.2, grao_forca=1.4, proj_on=True, tremor_x=2.4, tremor_y=1.8, cintilacao=0.16,
             desg_on=True, poeira=0.5, riscos=0.4, proporcao="1.33", hal_forca=0.8), cadence="18"),
    Row("cinema", 1932, 1952, N_("Cinema falado em preto e branco"),
        N_("Película pancromática e o quadro Academy 1,37 (o som ocupa a lateral); contraste alto das cópias "
           "de nitrato e acetato."),
        dict(iso="100", pb=True, cor_on=False, contraste=1.15, grao_forca=1.2, proj_on=True, tremor_x=1.4,
             tremor_y=1.0, cintilacao=0.06, desg_on=True, poeira=0.3, riscos=0.15, proporcao="1.37",
             hal_forca=0.5)),
    Row("cinema", 1953, 1969, N_("Cor e tela larga"),
        N_("Eastmancolor no lugar do Technicolor de três tiras e o CinemaScope (2,35, desde 1953); filme lento "
           "(ASA 50) e cores saturadas, que desbotam com o tempo."),
        dict(iso="50", saturacao=1.3, contraste=1.1, envelhecimento=0.3, grao_forca=1.1, proj_on=True,
             tremor_x=1.0, tremor_y=0.8, cintilacao=0.04, desg_on=True, poeira=0.2, riscos=0.1,
             proporcao="2.39", hal_forca=0.6)),
    Row("cinema", 1970, 1989, N_("Nova Hollywood"),
        N_("Negativos mais rápidos (100 a 400 ASA) e granulados, luz natural, quadro 1,85; cópias que já "
           "ficaram magenta e esmaecidas."),
        dict(iso="400", saturacao=1.05, envelhecimento=0.15, grao_forca=1.25, proj_on=True, tremor_x=0.8,
             tremor_y=0.6, cintilacao=0.03, desg_on=True, poeira=0.15, riscos=0.05, proporcao="1.85",
             hal_forca=0.7)),
    Row("cinema", 1990, 2009, N_("Vision e a cópia 2383"),
        N_("Kodak Vision (1996) com grão fino e a cópia 2383 do fim dos anos 90; tela larga 2,39 nos "
           "lançamentos."),
        dict(iso="500", copia="k2383", contraste=1.05, grao_forca=0.9, proj_on=True, tremor_x=0.5, tremor_y=0.4,
             cintilacao=0.02, desg_on=True, poeira=0.08, riscos=0.0, proporcao="2.39", hal_forca=0.5)),
    Row("cinema", 2010, 2020, N_("Vision3 e projeção digital"),
        N_("Negativo Vision3 (desde 2007) escaneado para o digital e projetado sem cópia: grão fino, sem "
           "tremor nem sujeira."),
        dict(iso="250", grao_forca=0.6, proporcao="2.39", hal_forca=0.4)),
    # ------------------------------------------------------------------ televisão
    Row("tv", 1920, 1964, N_("Começo da TV"),
        N_("Antes do videoteipe, a TV passava filme em 16 mm preto e branco pelo telecine (ou gravava a tela, o "
           "cinescópio): imagem macia, contrastada e 1,33."),
        dict(bitola="16mm", iso="200", pb=True, cor_on=False, contraste=1.25, grao_forca=1.3, proporcao="1.33",
             hal_forca=0.9)),
    Row("tv", 1965, 1989, N_("Reportagem em 16 mm"),
        N_("Jornalismo e documentário de TV em 16 mm colorido reversível, revelado às pressas: cor forte, grão "
           "visível e quadro 1,33."),
        dict(bitola="16mm", iso="125", saturacao=1.15, contraste=1.1, envelhecimento=0.2, grao_forca=1.3,
             desg_on=True, poeira=0.15, riscos=0.05, proporcao="1.33", hal_forca=0.7)),
    Row("tv", 1990, 2009, N_("Séries em Super 16"),
        N_("Séries e telefilmes em Super 16 (negativo Vision 500T), passados no telecine; 16:9 a partir dos "
           "anos 2000."),
        dict(bitola="super16", iso="500", grao_forca=1.1, proporcao="1.78", hal_forca=0.6)),
    Row("tv", 2010, 2020, N_("Série com cara de filme"),
        N_("As poucas séries ainda em Super 16 com Vision3, escaneadas em 2K ou 4K: grão presente, mas limpo."),
        dict(bitola="super16", iso="250", grao_forca=0.9, proporcao="1.78", hal_forca=0.5)),
    # ------------------------------------------------------------------ filme caseiro
    Row("caseiro", 1920, 1931, N_("16 mm amador"),
        N_("O 16 mm reversível da Kodak (1923) nas mãos das famílias: preto e branco, câmera de corda e "
           "projetor de casa."),
        dict(bitola="16mm", iso="50", pb=True, cor_on=False, contraste=1.15, grao_forca=1.3, proj_on=True,
             tremor_x=2.5, tremor_y=2.0, cintilacao=0.12, desg_on=True, poeira=0.4, riscos=0.3,
             proporcao="1.33", hal_forca=0.8), cadence="16"),
    Row("caseiro", 1932, 1964, N_("8 mm e Kodachrome"),
        N_("O 8 mm (1932) e o Kodachrome (1935): cores fortes que duram, filme lento e o projetor da sala."),
        dict(bitola="8mm", iso="50", saturacao=1.25, contraste=1.15, envelhecimento=0.1, grao_forca=1.3,
             proj_on=True, tremor_x=2.0, tremor_y=1.6, cintilacao=0.1, desg_on=True, poeira=0.35, riscos=0.2,
             proporcao="1.33", hal_forca=0.8), cadence="16"),
    Row("caseiro", 1965, 1989, N_("Super 8"),
        N_("Super 8 (1965) em cartucho, Kodachrome 40 e Ektachrome 160, filmado a 18 qps; as cópias "
           "Ektachrome puxam para o magenta com os anos."),
        dict(bitola="super8", iso="200", saturacao=1.15, envelhecimento=0.3, grao_forca=1.4, proj_on=True,
             tremor_x=1.8, tremor_y=1.4, cintilacao=0.08, desg_on=True, poeira=0.3, riscos=0.15,
             proporcao="1.33", hal_forca=0.9), cadence="18"),
    Row("caseiro", 1990, 2020, N_("Super 8 de agora"),
        N_("O Super 8 que voltou com negativo Vision3 e o Ektachrome 100D (2018), escaneado quadro a quadro: "
           "o tremor da janela da câmera, sem o projetor."),
        dict(bitola="super8", iso="200", saturacao=1.05, grao_forca=1.2, proj_on=True, tremor_x=1.0,
             tremor_y=0.8, cintilacao=0.02, proporcao="1.33", hal_forca=0.7), cadence="18"),
)


def row_for(year: int, venue: str) -> Row:
    year = min(max(int(year), YEAR_MIN), YEAR_MAX)
    for r in ROWS:
        if r.venue == venue and r.start <= year <= r.end:
            return r
    raise KeyError((year, venue))


def apply(base: dict, year: int, venue: str) -> dict:
    """O look `base` com os valores da época e do lugar (as chaves `KEYS`; o resto como estava)."""
    from . import params
    return params.sanitize({**base, **row_for(year, venue).full_values()})


def changes(before: dict, after: dict) -> list[tuple[str, object, object]]:
    """(chave, antes, depois) do que muda, na ordem de `KEYS`."""
    return [(k, before.get(k), after.get(k)) for k in KEYS if before.get(k) != after.get(k)]
