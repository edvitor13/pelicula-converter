"""Receita de um quadro: o único caminho do quadro decodificado ao quadro final.

Todo lugar que mostra ou grava um quadro passa por aqui: a prévia da janela (modos Película e Edição),
"Salvar quadro", a exportação (`export._encode`), a prévia da janela de exportação (`export.preview_frame`),
a medição de velocidade (`export.measure_speed`, que exporta de verdade) e a linha de comando
(`pelicula-cli quadro` e `exportar`). O fluxo é sempre o mesmo:

1. **Entrada**: a imagem decodificada (h × w × 3) ou as camadas da montagem (`sequence.FrameLayers`).
2. **Montagem** (`Recipe.montage`): com camadas, `Engine.compose` monta a tela no tamanho da receita
   (opcionalmente sem os ajustes de cor dos clipes, a imagem neutra da comparação, e com o recorte do
   encaixe). Uma imagem passa direto.
3. **Valores do look neste quadro** (`Recipe.look_values`): os ajustes com as chaves de animação do look
   avaliadas no tempo do quadro (`keyframes.look_values_at`); sem chaves, os ajustes como estão.
4. **Plano** (`Recipe.plan`): `look.build_plan(..., legal=...)` com a faixa do arquivo, o LUT, o pontilhado e o
   "Grão para redes".
5. **Desenho** (`Recipe.look`): `Engine.render`, ou `Engine.render_fit` quando o encaixe compõe o quadro
   (bordas desfocadas ou coloridas, `fit.py`).

O que muda entre quem chama são só os campos: a prévia usa o tamanho reduzido, 8 bits e o pontilhado do
look; a exportação usa o tamanho e a profundidade da saída. Com os mesmos campos, o quadro é bit a bit o mesmo
(`tests/test_frame.py`). Montar uma receita com a faixa e o LUT certos: `export.frame_pipeline` (com os ajustes
da exportação) ou `Recipe.for_source` (prévia, "Salvar quadro", linha de comando).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from . import look

__all__ = ["Recipe"]


@dataclass
class Recipe:
    """Como um quadro vira o quadro final. `values` None = só a montagem (modo Edição sem película)."""
    values: dict | None
    fps: float                    # quadros por segundo da saída (o tempo do look é `index / fps`)
    depth: int = 8                # 8 ou 16 bits
    dither: bool = False          # pontilhado do look (só faz sentido em 8 bits)
    legal: bool = True            # a fonte chega em faixa legal expandida (`media.legal_range`)
    lut: tuple | None = None      # `engine.lut_info(...)` do LUT do look, ou None
    seq: Any = None               # timeline.Sequence do modo Edição (None = o arquivo)
    fit: Any = None               # fit.Fit da exportação; None = sem encaixe (tamanho da imagem/`size`)
    net_grain: float = 0.0        # "Grão para redes": px da imagem por px da saída (0 = desligado)
    size: tuple[int, int] | None = None  # tamanho da montagem sem encaixe (prévia: o tamanho reduzido)
    keys: dict = field(default_factory=dict)  # chaves de animação do look ({chave: [[tempo, valor, curva]…]})
    src_fps: float = 0.0          # fps do arquivo/sequência, em que as chaves do look estão (0 = `fps`)

    def __post_init__(self) -> None:
        if self.keys:  # JSON do projeto ou chaves já limpas: sempre `keyframes.Key` só de ajustes animáveis
            from . import keyframes, params
            self.keys = keyframes.clean_keys(params.FILM, self.keys)

    # ---------------------------------------------------------------- campos derivados
    @classmethod
    def for_source(cls, values: dict | None, fps: float, depth: int, *, legal: bool, seq=None, dither=False,
                   size: tuple[int, int] | None = None, keys: dict | None = None) -> "Recipe":
        """Receita sem encaixe (prévia, "Salvar quadro", `pelicula-cli quadro`), com o LUT dos ajustes."""
        return cls(values, float(fps), int(depth), bool(dither) and depth == 8, bool(legal), lut_of(values), seq,
                   None, 0.0, size, dict(keys or {}), float(fps))

    def with_(self, **kw) -> "Recipe":
        """Cópia com alguns campos trocados (ex.: a prévia em 16 bits para comparar com a exportação)."""
        return replace(self, **kw)

    def montage_size(self, img=None) -> tuple[int, int]:
        if self.fit is not None:
            return self.fit.dec_w, self.fit.dec_h
        if self.size is not None:
            return int(self.size[0]), int(self.size[1])
        if self.seq is not None:
            from .sequence import canvas_size
            return canvas_size(self.seq)
        h, w = img.shape[:2]
        return w, h

    # ---------------------------------------------------------------- passos
    def montage(self, engine, img, neutral: bool = False):
        """Passo 2: as camadas da montagem viram uma imagem (no tamanho da receita); uma imagem passa direto.
        `neutral`: sem os ajustes de cor dos clipes (a imagem "antes" da comparação no modo Edição)."""
        from .sequence import FrameLayers
        if not isinstance(img, FrameLayers):
            return img
        w, h = self.montage_size()
        crop = self.fit.canvas_crop if self.fit is not None else None
        from .transitions import light_of  # transições da 1.5: misturam na luz da entrada do look
        return engine.compose(img, self.seq, w, h, self.depth, neutral=neutral, crop=crop,
                              light=light_of(self.values, self.legal))

    def look_values(self, index: int) -> dict:
        """Passo 3: os ajustes do look no quadro `index` da saída (com as chaves de animação avaliadas)."""
        if not self.keys:
            return self.values
        from . import keyframes
        src = self.src_fps or self.fps
        return keyframes.look_values_at(self.values, self.keys, index * src / self.fps if self.fps else index)

    def plan(self, w: int, h: int, index: int) -> look.Plan:
        """Passo 4: o plano do look para uma imagem w × h no quadro `index`."""
        return look.build_plan(self.look_values(index), w, h, index, self.fps, self.lut, dither=self.dither,
                               legal=self.legal, net_grain=self.net_grain)

    def look(self, engine, img, index: int, upload: bool = True):
        """Passo 5: aplica o look à imagem montada. `upload=False` quando a imagem já está na entrada do
        `engine` (a prévia reaproveita o envio enquanto só os ajustes mudam)."""
        if self.values is None:
            return img
        if upload:
            engine.set_input(img)
        h, w = img.shape[:2]
        plan = self.plan(w, h, index)
        if self.fit is not None and self.fit.composite:
            return engine.render_fit(plan, self.depth, self.fit)
        return engine.render(plan, self.depth)

    def render(self, engine, img, index: int):
        """O quadro inteiro: montagem (se `img` são camadas) e look. `index` é o número do quadro na saída."""
        return self.look(engine, self.montage(engine, img), index)


def lut_of(values: dict | None) -> tuple | None:
    """O LUT do look (`engine.lut_info`), ou None sem LUT ligado ou se ele não pôde ser lido."""
    if not values or not values.get("lut_on") or not values.get("lut_arquivo"):
        return None
    from .engine import lut_info
    return lut_info(values["lut_arquivo"])
