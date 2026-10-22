"""Presets prontos e presets salvos pelo usuário.

Os nomes de filmes descrevem o estilo que cada preset imita. São aproximações
artísticas, sem relação com os fabricantes.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import params

# Ponto de partida de todos os presets de película.
FILM_BASE: dict[str, Any] = dict(
    cor_on=True, grao_on=True, hal_on=True, bloom_on=True, lente_on=True,
    proj_on=False, desg_on=False, mold_on=False,
    bitola="35mm", iso="250", copia="k2383", copia_forca=1.0,
    contraste=0.9, meio_tom=0.45, preto=0.008, branco=0.99,
    rolagem_luzes=0.45, rolagem_sombras=0.3, saturacao=1.12, densidade=0.3,
    sombras_matiz=195, sombras_forca=0.12, luzes_matiz=38, luzes_forca=0.1,
    grao_forca=1.0, grao_tamanho=1.0, grao_aspereza=0.22, grao_cor=0.3,
    hal_forca=0.6, hal_raio=14, hal_limiar=2.6,
    bloom_forca=0.18, bloom_raio=45, bloom_limiar=2.2,
    vinheta=0.06, maciez=0.0, nitidez=0.0,
)

GROUPS = ["Cinema 35 mm", "Laboratório", "Bitolas e formatos", "Preto e branco", "Fotografia", "Processos e estilos", "Básicos"]

BUILTIN: list[dict[str, Any]] = [
    # ------------------------------------------------------------ cinema 35 mm
    dict(id="vision3_250d", nome="Kodak Vision3 250D", grupo="Cinema 35 mm",
         desc="Negativo diurno clássico do cinema atual: cor natural e grão médio.",
         valores=dict(iso="250")),
    dict(id="vision3_50d", nome="Kodak Vision3 50D", grupo="Cinema 35 mm",
         desc="Grão finíssimo, cores limpas e saturadas. Sol e exteriores.",
         valores=dict(iso="50", contraste=0.95, saturacao=1.08, densidade=0.35, grao_forca=0.9,
                      sombras_forca=0.08, luzes_forca=0.08)),
    dict(id="vision3_200t", nome="Kodak Vision3 200T", grupo="Cinema 35 mm",
         desc="Negativo de tungstênio: sombras levemente frias, pele suave.",
         valores=dict(iso="200", sombras_matiz=205, sombras_forca=0.2, luzes_forca=0.06, saturacao=0.97)),
    dict(id="vision3_500t", nome="Kodak Vision3 500T", grupo="Cinema 35 mm",
         desc="O filme da noite: mais grão, sombras azuladas e luzes quentes com halação.",
         valores=dict(iso="500", contraste=0.88, sombras_matiz=205, sombras_forca=0.3, luzes_matiz=32,
                      luzes_forca=0.18, hal_forca=0.95, hal_limiar=2.2, grao_forca=1.1, bloom_forca=0.25)),
    dict(id="eterna_250d", nome="Fujifilm Eterna 250D", grupo="Cinema 35 mm",
         desc="Contraste baixo e cor contida, com sombras verde-azuladas.",
         valores=dict(copia="f3513", contraste=0.82, saturacao=0.84, densidade=0.2, sombras_matiz=170,
                      sombras_forca=0.25, luzes_matiz=45, luzes_forca=0.05, verdes_matiz=-8)),
    dict(id="eterna_vivid", nome="Fujifilm Eterna Vivid 500", grupo="Cinema 35 mm",
         desc="A Eterna com mais cor e contraste.",
         valores=dict(copia="f3513", iso="500", contraste=0.95, saturacao=1.1, densidade=0.35,
                      sombras_matiz=175, sombras_forca=0.18, grao_forca=1.05)),
    dict(id="blockbuster", nome="Blockbuster (teal & orange)", grupo="Cinema 35 mm",
         desc="Sombras ciano e pele alaranjada, o visual dos filmes de ação.",
         valores=dict(contraste=1.02, saturacao=1.05, densidade=0.4, sombras_matiz=190, sombras_forca=0.45,
                      luzes_matiz=30, luzes_forca=0.32, copia="k2393")),

    # ------------------------------------------------------------ laboratório (modelo de densidade)
    # Negativo, revelação, luzes da copiadora e cópia simulados pela densidade (seção Laboratório).
    # O look paramétrico ("Cor da película") e a cópia antiga ficam desligados para não somar duas curvas.
    dict(id="lab_v3_250d_2383", nome="Laboratório • Vision3 250D → 2383", grupo="Laboratório",
         desc="Negativo diurno copiado em 2383 pelo modelo de densidade, como num laboratório de cinema.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="vision3_250d", lab_copia="2383",
                      iso="250")),
    dict(id="lab_v3_500t_noite", nome="Laboratório • Vision3 500T → 2383 (noite)", grupo="Laboratório",
         desc="Negativo de tungstênio com cópia puxada para o frio pelas luzes da copiadora; halação forte.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="vision3_500t", lab_copia="2383",
                      lab_luz_r=1.0, lab_luz_b=-3.0, iso="500", hal_forca=0.95, hal_limiar=2.2, grao_forca=1.1,
                      bloom_forca=0.25)),
    dict(id="lab_eterna_3513", nome="Laboratório • Eterna 250D → Fuji 3513", grupo="Laboratório",
         desc="Cor contida e sombras esverdeadas da Eterna, copiada na Fuji, mais fria e neutra.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="eterna_250d", lab_copia="3513",
                      iso="250")),
    dict(id="lab_ecn2_anos70", nome="Laboratório • 5247 ECN-II (anos 70)", grupo="Laboratório",
         desc="Negativo dos anos 70: camadas misturadas, cópia quente e grão evidente.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="ecn2_5247", lab_copia="2383",
                      lab_diafonia=1.3, lab_luz_b=2.0, lab_luz_g=0.5, iso="250", grao_forca=1.25,
                      grao_aspereza=0.35, hal_forca=0.7)),
    dict(id="lab_technicolor3", nome="Technicolor 3 tiras (laboratório)", grupo="Laboratório",
         desc="Três registros preto e branco e corantes puros com chave preta: cores densas dos anos 40 e 50.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_processo="tech3", lab_chave=0.35,
                      iso="100", grao_forca=0.8, hal_forca=0.5)),
    dict(id="lab_technicolor2", nome="Technicolor 2 cores (anos 20)", grupo="Laboratório",
         desc="Só vermelho-laranja e verde-azulado: pele rosada, céu ciano e nada de azul puro.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_processo="tech2", iso="100",
                      grao_forca=1.1, proj_on=True, tremor_x=0.8, tremor_y=0.6, cintilacao=0.04,
                      desg_on=True, poeira=0.25, riscos=0.08, mold_on=True, proporcao="1.37")),
    dict(id="lab_prata", nome="Retenção de prata (laboratório)", grupo="Laboratório",
         desc="Bleach bypass pela densidade: a prata fica na cópia, a cor cai e o preto fica profundo.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_processo="prata", lab_processo_forca=0.85,
                      lab_copia="2383", iso="250", grao_forca=1.15)),
    dict(id="lab_double_x_2302", nome="Laboratório • Double-X → 2302 (P&B)", grupo="Laboratório",
         desc="Negativo preto e branco de cinema copiado em filme P&B, com o pé e o ombro das duas curvas.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="double_x", lab_copia="2302",
                      iso="250", grao_forca=1.3, grao_cor=0.0, hal_cor=[1.0, 1.0, 1.0], hal_forca=0.4)),
    dict(id="lab_negativo_scan", nome="Negativo escaneado (sem cópia)", grupo="Laboratório",
         desc="O negativo invertido digitalmente, como num scan: latitude enorme e contraste baixo.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="vision3_250d",
                      lab_copia="nenhuma", iso="250")),
    # O fluxo do tutorial "Three-Strip Technicolor Look": negativo + cópia Eastman, Hue Split, saturação do
    # filme e luzes da copiadora; textura com MTF de close, grão e halação de 35 mm.
    dict(id="lab_technicolor_hue_split", nome="Technicolor (5297 → 5386, Hue Split)", grupo="Laboratório",
         desc="Negativo Eastman 5297 copiado na 5386 com separação de cores: pele quente, céu e sombras frios e "
              "cores densas, como o Technicolor de três tiras.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="ecn2_5297", lab_copia="e5386",
                      exposicao=-0.25, lab_separacao=0.69, lab_saturacao_filme=1.3, lab_luz_r=-1.0, lab_luz_b=1.0,
                      iso="250", mtf="close", mtf_forca=0.5, hal_forca=0.7)),
    dict(id="lab_teal_orange_5201", nome="Teal & orange (5201 → 2393, Hue Split)", grupo="Laboratório",
         desc="Vision2 5201 50D copiado na 2393 com separação de cores e azuis mais densos: o céu se separa da "
              "pele.",
         valores=dict(cor_on=False, copia="nenhuma", lab_on=True, lab_negativo="vision2_5201", lab_copia="2393",
                      lab_separacao=0.69, lab_dens_b=1.4, lab_saturacao_filme=1.1, iso="50", mtf="medio")),

    # ------------------------------------------------------------ bitolas
    dict(id="super8_kodachrome", nome="Super 8 • Kodachrome 40", grupo="Bitolas e formatos",
         desc="Filme caseiro dos anos 70: cor intensa e quente, grão grande e tremor.",
         valores=dict(bitola="super8", iso="50", copia="nenhuma", contraste=1.18, meio_tom=0.43, preto=0.025,
                      saturacao=1.25, densidade=0.55, luzes_matiz=45, luzes_forca=0.25, sombras_matiz=220,
                      sombras_forca=0.08, hal_forca=0.8, vinheta=0.15,
                      proj_on=True, tremor_x=1.4, tremor_y=1.1, cintilacao=0.06,
                      desg_on=True, poeira=0.35, riscos=0.1,
                      mold_on=True, proporcao="bitola", cantos=0.06, borda_irregular=0.25)),
    dict(id="super8_ektachrome", nome="Super 8 • Ektachrome 100D", grupo="Bitolas e formatos",
         desc="Super 8 reversível: frio, saturado e com pretos profundos.",
         valores=dict(bitola="super8", iso="100", copia="nenhuma", contraste=1.15, preto=0.015, saturacao=1.18,
                      densidade=0.45, sombras_matiz=210, sombras_forca=0.22, luzes_matiz=190, luzes_forca=0.06,
                      vinheta=0.12, proj_on=True, tremor_x=1.2, tremor_y=1.0, cintilacao=0.05,
                      desg_on=True, poeira=0.25, riscos=0.06,
                      mold_on=True, proporcao="bitola", cantos=0.05, borda_irregular=0.2)),
    dict(id="8mm_caseiro", nome="8 mm caseiro (anos 60)", grupo="Bitolas e formatos",
         desc="Memória de família: desbotado, tremido, com poeira e luz vazando.",
         valores=dict(bitola="8mm", iso="100", copia="nenhuma", contraste=1.1, saturacao=1.05, densidade=0.4,
                      envelhecimento=0.4, luzes_matiz=40, luzes_forca=0.2, vinheta=0.2,
                      proj_on=True, tremor_x=1.6, tremor_y=1.3, tremor_rot=0.06, cintilacao=0.09,
                      desg_on=True, poeira=0.5, riscos=0.2, vazamento=0.3,
                      mold_on=True, proporcao="bitola", cantos=0.08, borda_irregular=0.5)),
    dict(id="scan_35mm", nome="Scan de 35 mm (com furos)", grupo="Bitolas e formatos",
         desc="A película inteira escaneada: furos iluminados, texto na borda e quadros vizinhos.",
         valores=dict(scan_on=True, scan_formato="35mm", desg_on=True, poeira=0.2, riscos=0.05)),
    dict(id="scan_super8", nome="Scan de Super 8 (com furos)", grupo="Bitolas e formatos",
         desc="Rolo de Super 8 escaneado: furo lateral, cantos arredondados e cor de Kodachrome.",
         valores=dict(bitola="super8", iso="50", copia="nenhuma", contraste=1.18, meio_tom=0.43, preto=0.025,
                      saturacao=1.25, densidade=0.55, luzes_matiz=45, luzes_forca=0.25, hal_forca=0.8,
                      scan_on=True, scan_formato="super8", proj_on=True, tremor_x=0.8, tremor_y=0.6,
                      cintilacao=0.05, desg_on=True, poeira=0.3, riscos=0.08)),
    dict(id="16mm_doc", nome="16 mm • Vision3 500T (documentário)", grupo="Bitolas e formatos",
         desc="Grão evidente e imagem macia, como documentários e séries indie.",
         valores=dict(bitola="16mm", iso="500", contraste=0.9, sombras_matiz=205, sombras_forca=0.2,
                      luzes_forca=0.12, hal_forca=0.8, proj_on=True, tremor_x=0.6, tremor_y=0.5,
                      tremor_rot=0.02, cintilacao=0.025)),
    dict(id="super16_indie", nome="Super 16 • Vision3 250D", grupo="Bitolas e formatos",
         desc="O 16 mm do cinema independente, com mais definição que o 16 mm comum.",
         valores=dict(bitola="super16", iso="250", contraste=0.92, saturacao=0.98)),
    dict(id="35mm_scope", nome="35 mm Scope (2,39)", grupo="Bitolas e formatos",
         desc="Visual de cinema anamórfico com barras pretas em 2,39.",
         valores=dict(bitola="35mm", iso="250", mold_on=True, proporcao="2.39", bloom_forca=0.22)),
    dict(id="65mm_epico", nome="65 mm • Vision3 50D (épico)", grupo="Bitolas e formatos",
         desc="Grande formato: grão quase invisível, nitidez e cor profunda. Proporção 2,20.",
         valores=dict(bitola="65mm", iso="50", contraste=0.98, saturacao=1.05, densidade=0.4,
                      mold_on=True, proporcao="2.20")),
    dict(id="imax_70", nome="IMAX 70 mm", grupo="Bitolas e formatos",
         desc="O maior negativo do cinema: limpo, nítido e com muita latitude.",
         valores=dict(bitola="imax", iso="250", contraste=0.95, rolagem_luzes=0.7, saturacao=1.02)),

    # ------------------------------------------------------------ preto e branco
    dict(id="double_x", nome="Kodak Double-X 5222", grupo="Preto e branco",
         desc="O preto e branco clássico do cinema, de Touro Indomável a Oppenheimer.",
         valores=dict(pb=True, pb_filtro="pan", copia="nenhuma", contraste=1.12, preto=0.02, branco=0.97,
                      grao_forca=1.3, grao_cor=0.0, iso="250", hal_cor=[1.0, 1.0, 1.0], hal_forca=0.4,
                      sombras_forca=0.0, luzes_forca=0.0)),
    dict(id="tri_x", nome="Kodak Tri-X 400", grupo="Preto e branco",
         desc="Contraste forte e grão marcante do fotojornalismo.",
         valores=dict(pb=True, pb_filtro="amarelo", copia="nenhuma", contraste=1.28, preto=0.01,
                      grao_forca=1.45, grao_aspereza=0.5, grao_cor=0.0, iso="400", hal_cor=[1.0, 1.0, 1.0],
                      hal_forca=0.35, sombras_forca=0.0, luzes_forca=0.0)),
    dict(id="hp5", nome="Ilford HP5 Plus", grupo="Preto e branco",
         desc="P&B mais suave, com tons médios ricos.",
         valores=dict(pb=True, pb_filtro="pan", copia="nenhuma", contraste=0.98, preto=0.025, rolagem_luzes=0.75,
                      grao_forca=1.3, grao_cor=0.0, iso="400", hal_cor=[1.0, 1.0, 1.0], hal_forca=0.3,
                      sombras_forca=0.0, luzes_forca=0.0)),
    dict(id="noir", nome="Noir anos 40", grupo="Preto e branco",
         desc="Contraste dramático, vinheta forte e brilho difuso nas luzes.",
         valores=dict(pb=True, pb_filtro="vermelho", copia="nenhuma", contraste=1.4, preto=0.01, branco=0.96,
                      grao_forca=1.2, grao_cor=0.0, hal_cor=[1.0, 1.0, 1.0], hal_forca=0.5,
                      nevoa_forca=0.3, vinheta=0.35, sombras_forca=0.0, luzes_forca=0.0,
                      proj_on=True, tremor_x=0.5, tremor_y=0.4, cintilacao=0.04)),
    dict(id="sepia", nome="Sépia antigo", grupo="Preto e branco",
         desc="Fotografia virada em sépia, com bordas gastas.",
         valores=dict(pb=True, pb_filtro="pan", virada="sepia", virada_forca=0.85, copia="nenhuma",
                      contraste=1.0, preto=0.05, branco=0.93, grao_forca=1.2, grao_cor=0.0, vinheta=0.3,
                      hal_cor=[1.0, 1.0, 1.0], hal_forca=0.3, envelhecimento=0.15,
                      sombras_forca=0.0, luzes_forca=0.0, desg_on=True, poeira=0.3, riscos=0.1)),

    # ------------------------------------------------------------ fotografia
    dict(id="portra_400", nome="Kodak Portra 400", grupo="Fotografia",
         desc="Contraste suave, pele quente e cores em tons pastel.",
         valores=dict(copia="nenhuma", iso="400", contraste=0.86, meio_tom=0.47, preto=0.02, rolagem_luzes=0.8,
                      saturacao=0.95, densidade=0.2, luzes_matiz=40, luzes_forca=0.15, sombras_matiz=200,
                      sombras_forca=0.06, pele_sat=0.08)),
    dict(id="ektar_100", nome="Kodak Ektar 100", grupo="Fotografia",
         desc="Saturado e nítido, com vermelhos fortes e grão fino.",
         valores=dict(copia="nenhuma", iso="100", contraste=1.08, saturacao=1.28, densidade=0.45,
                      luzes_matiz=30, luzes_forca=0.08, sombras_forca=0.04)),
    dict(id="velvia_50", nome="Fujifilm Velvia 50", grupo="Fotografia",
         desc="Cromo de paisagem: saturação extrema e contraste alto.",
         valores=dict(copia="nenhuma", iso="50", contraste=1.25, preto=0.0, saturacao=1.45, densidade=0.6,
                      verdes_matiz=-6, azuis_matiz=6, sombras_matiz=230, sombras_forca=0.1, luzes_forca=0.0)),
    dict(id="superia_400", nome="Fujifilm Superia 400", grupo="Fotografia",
         desc="Filme de consumo dos anos 2000: sombras esverdeadas e cor viva.",
         valores=dict(copia="nenhuma", iso="400", contraste=1.0, saturacao=1.06, sombras_matiz=150,
                      sombras_forca=0.25, luzes_matiz=55, luzes_forca=0.06, verdes_matiz=-8)),
    dict(id="cinestill_800t", nome="CineStill 800T", grupo="Fotografia",
         desc="Néon e noite: tons frios e halação vermelha forte nas luzes.",
         valores=dict(copia="nenhuma", iso="800", contraste=0.95, temperatura=-12, sombras_matiz=200,
                      sombras_forca=0.3, luzes_matiz=25, luzes_forca=0.12, hal_forca=1.7, hal_raio=20,
                      hal_limiar=1.9, hal_cor=[1.0, 0.16, 0.05], grao_forca=1.15)),

    # ------------------------------------------------------------ processos e estilos
    dict(id="bleach_bypass", nome="Bleach bypass", grupo="Processos e estilos",
         desc="Revelação sem branqueamento: pouca cor, muito contraste. O Resgate do Soldado Ryan.",
         valores=dict(copia="k2393", contraste=1.3, saturacao=0.55, densidade=0.3, preto=0.0,
                      sombras_forca=0.08, luzes_forca=0.05, grao_forca=1.15)),
    dict(id="technicolor", nome="Technicolor 3 cores", grupo="Processos e estilos",
         desc="Cores puras e densas do cinema dos anos 50.",
         valores=dict(copia="nenhuma", contraste=1.08, saturacao=1.35, densidade=0.7, preto=0.015,
                      verdes_matiz=-8, luzes_matiz=40, luzes_forca=0.1, sombras_forca=0.05, pele_sat=0.1)),
    dict(id="cross", nome="Revelação cruzada", grupo="Processos e estilos",
         desc="Cromo revelado como negativo: altas luzes amarelo-esverdeadas e contraste alto.",
         valores=dict(copia="nenhuma", contraste=1.3, saturacao=1.2, offset_r=0.08, offset_b=-0.25,
                      contraste_b=1.12, contraste_g=1.05, luzes_matiz=70, luzes_forca=0.4,
                      sombras_matiz=210, sombras_forca=0.3)),
    dict(id="copia_70", nome="Cópia desbotada (anos 70)", grupo="Processos e estilos",
         desc="Cópia de cinema envelhecida: magenta, preto lavado, poeira e riscos.",
         valores=dict(envelhecimento=0.65, contraste=0.92, grao_forca=1.2, proj_on=True, tremor_x=0.6,
                      tremor_y=0.5, cintilacao=0.05, desg_on=True, poeira=0.3, riscos=0.15)),

    # ------------------------------------------------------------ básicos
    dict(id="so_textura", nome="Só textura (cor original)", grupo="Básicos",
         desc="Grão, halação e bloom de 35 mm sem mexer na cor.",
         valores=dict(cor_on=False, copia="nenhuma", hal_forca=0.5, bloom_forca=0.15)),
    dict(id="original", nome="Original (sem efeito)", grupo="Básicos",
         desc="Desliga todos os efeitos.", valores=None),
]

BY_ID = {p["id"]: p for p in BUILTIN}
DEFAULT_ID = "vision3_250d"


def builtin_values(pid: str) -> dict[str, Any]:
    p = BY_ID[pid]
    if p["valores"] is None:
        v = params.defaults()
        v["bitola"] = "nenhuma"
        return v
    return params.sanitize({**FILM_BASE, **p["valores"]})


# ------------------------------------------------------------------ usuário
def user_dir() -> Path:
    from .deps import config_dir
    base = config_dir() / "presets"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", name, flags=re.UNICODE).strip().replace(" ", "_")
    return s[:80] or "preset"


def list_user() -> list[dict[str, Any]]:
    out = []
    for f in sorted(user_dir().glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": "user:" + f.stem, "nome": data.get("nome", f.stem), "grupo": "Meus presets",
                        "desc": data.get("desc", ""), "valores": params.sanitize(data.get("valores", {})),
                        "arquivo": str(f)})
        except (OSError, ValueError):
            continue
    return out


def user_exists(name: str) -> bool:
    return (user_dir() / f"{_slug(name)}.json").exists()


def save_user(name: str, values: dict[str, Any], desc: str = "") -> str:
    path = user_dir() / f"{_slug(name)}.json"
    data = {"nome": name, "desc": desc, "app": "PeliculaConverter", "versao": 1, "valores": values}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return "user:" + path.stem


def delete_user(pid: str) -> None:
    if pid.startswith("user:"):
        f = user_dir() / f"{pid[5:]}.json"
        if f.exists():
            f.unlink()


def import_file(path: str) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    name = data.get("nome") or Path(path).stem
    base = name
    n = 2
    while user_exists(name):
        name = f"{base} ({n})"
        n += 1
    return save_user(name, params.sanitize(data.get("valores", {})), data.get("desc", ""))


def export_file(path: str, name: str, values: dict[str, Any]) -> None:
    from .system import atomic_write
    data = {"nome": name, "app": "PeliculaConverter", "versao": 1, "valores": values}
    with atomic_write(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2))
