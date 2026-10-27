"""Encaixe da exportação num quadro de outra proporção (sem Qt e sem GPU).

Uma exportação com **quadro fixo** (`ExportSettings.frame`, por exemplo 1080 × 1920 para Reels) parte de um
vídeo de outra proporção. Este módulo calcula, num lugar só, a geometria que a exportação e a prévia dela
usam (`export.FramePipeline`), para o look de película ser desenhado na imagem que aparece no fim:

- **cortar** (preencher): o vídeo é recortado na proporção do quadro **antes** do look. No modo Película o
  recorte acontece no decodificador (`media.FrameReader(crop=...)`, em pixels do arquivo); no modo Edição a
  montagem é feita numa tela que cobre o quadro e só o centro sai (`Engine.compose(crop=...)`). Vinheta,
  bordas do scan, halação e grão (px@1080) seguem o quadro final.
- **bordas** e **desfocado**: o vídeo inteiro cabe no quadro (`box`), o look é desenhado nesse tamanho e
  `Engine.render_fit()` o põe sobre o fundo — preto, ou uma cópia da própria imagem com o look, ampliada para
  cobrir o quadro, desfocada e escurecida. É uma passada determinística na GPU (nada aleatório).

Sem quadro fixo, ou quando a proporção já é a mesma (diferença de até 1 px), nada muda: o vídeo só é
redimensionado, exatamente como antes (`mode == ""`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import N_

CORTAR = "cortar"
BORDAS = "bordas"
DESFOCADO = "desfocado"
MODES = ((CORTAR, N_("Cortar para preencher")), (BORDAS, N_("Bordas pretas")),
         (DESFOCADO, N_("Fundo desfocado")))
MODE_IDS = tuple(m for m, _label in MODES)

# Fundo desfocado: raio do desfoque em px@1080 do quadro final e quanto ele escurece.
BLUR_PX = 40.0
DIM = 0.55


@dataclass(frozen=True)
class Fit:
    """Geometria de um quadro exportado.

    - `mode`: "" (só redimensiona), `cortar`, `bordas` ou `desfocado`;
    - `out_w`/`out_h`: o quadro gravado;
    - `dec_w`/`dec_h`: o tamanho em que o vídeo é decodificado (modo Película) ou a tela montada (modo Edição);
    - `crop`: recorte no arquivo, em pixels do arquivo (x, y, largura, altura) — Película, `cortar`;
    - `canvas_crop`: recorte da tela montada (x, y, largura, altura) — Edição, `cortar`;
    - `box`: onde a imagem com o look fica no quadro gravado (x, y, largura, altura; y para baixo).
    """

    mode: str
    out_w: int
    out_h: int
    dec_w: int
    dec_h: int
    crop: tuple[int, int, int, int] | None = None
    canvas_crop: tuple[int, int, int, int] | None = None
    box: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def composite(self) -> bool:
        """O look vai para um quadro maior (bordas ou fundo desfocado): precisa de `Engine.render_fit`."""
        return self.mode in (BORDAS, DESFOCADO)

    @property
    def look_size(self) -> tuple[int, int]:
        """Tamanho da imagem em que o look é desenhado."""
        return self.box[2], self.box[3]

    def blur_sigma(self) -> float:
        """Desfoque do fundo em px do quadro final (px@1080, como todo ajuste)."""
        return BLUR_PX * self.out_h / 1080.0


def _even_floor(x: float, limit: int) -> int:
    v = int(x) - int(x) % 2
    return max(2, min(v, limit - limit % 2 if limit >= 2 else limit))


def plan(src_w: int, src_h: int, out_w: int, out_h: int, mode: str = "", edit: bool = False) -> Fit:
    """Geometria para levar um vídeo `src_w` × `src_h` a um quadro `out_w` × `out_h`.

    `edit=True`: a fonte é a montagem do modo Edição (o recorte de `cortar` vale na tela montada).
    Modo desconhecido ou vazio, ou proporções iguais: só redimensiona (o caminho de sempre).
    """
    sw, sh = max(1, int(src_w)), max(1, int(src_h))
    ow, oh = max(2, int(out_w)), max(2, int(out_h))
    plain = Fit("", ow, oh, ow, oh, box=(0, 0, ow, oh))
    if mode not in MODE_IDS:
        return plain
    k = min(ow / sw, oh / sh)
    cw, ch = min(ow, round(sw * k)), min(oh, round(sh * k))
    if abs(cw - ow) <= 1 and abs(ch - oh) <= 1:
        return plain
    if mode == CORTAR:
        if edit:
            kc = max(ow / sw, oh / sh)
            vw, vh = max(ow, round(sw * kc)), max(oh, round(sh * kc))
            return Fit(CORTAR, ow, oh, vw, vh, canvas_crop=((vw - ow) // 2, (vh - oh) // 2, ow, oh),
                       box=(0, 0, ow, oh))
        # Recorte no arquivo com x, y, largura e altura pares (vídeo 4:2:0 não recorta meio pixel de croma).
        aspect = ow / oh
        if sw / sh > aspect:
            rw, rh = _even_floor(sh * aspect + 0.5, sw), _even_floor(sh, sh)
        else:
            rw, rh = _even_floor(sw, sw), _even_floor(sw / aspect + 0.5, sh)
        x = (sw - rw) // 2
        y = (sh - rh) // 2
        return Fit(CORTAR, ow, oh, ow, oh, crop=(x - x % 2, y - y % 2, rw, rh), box=(0, 0, ow, oh))
    # bordas / desfocado: margens iguais dos dois lados (a imagem perde no máximo 1 px para isso).
    cw -= (ow - cw) % 2
    ch -= (oh - ch) % 2
    cw, ch = max(2, cw), max(2, ch)
    return Fit(mode, ow, oh, cw, ch, box=((ow - cw) // 2, (oh - ch) // 2, cw, ch))
