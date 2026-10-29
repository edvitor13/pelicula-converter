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

Legendas gravadas no vídeo (`Recipe.burn`, um `subtitles.Burn`) entram no passo 5: "gravada na cópia" por cima
da imagem montada *antes* do look (no tamanho do conteúdo: grão, halação e tremor passam por elas) e "digital"
por cima do quadro final *depois* do look (no tamanho da saída, com o encaixe). O instante é `index / fps`.

Com `alpha` (saída com transparência: a prévia e o "Salvar quadro" de uma montagem com "Fundo transparente", a
exportação num formato com alfa, `export.wants_alpha`) a montagem sai RGBA de cor direta e o look devolve RGBA:
a cor é a mesma de sempre e o alfa é a cobertura da montagem movida pela geometria do look (veja
`alphashaders`). Sem `alpha`, nada muda.

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
    burn: Any = None              # subtitles.Burn: legendas gravadas no vídeo (antes ou depois do look); None = sem
    alpha: bool = False           # saída RGBA (h × w × 4, cor direta): a transparência da montagem

    def __post_init__(self) -> None:
        if self.keys:  # JSON do projeto ou chaves já limpas: sempre `keyframes.Key` só de ajustes animáveis
            from . import keyframes, params
            self.keys = keyframes.clean_keys(params.FILM, self.keys)

    # ---------------------------------------------------------------- campos derivados
    @classmethod
    def for_source(cls, values: dict | None, fps: float, depth: int, *, legal: bool, seq=None, dither=False,
                   size: tuple[int, int] | None = None, keys: dict | None = None, burn=None,
                   alpha: bool = False) -> "Recipe":
        """Receita sem encaixe (prévia, "Salvar quadro", `pelicula-cli quadro`), com o LUT dos ajustes."""
        return cls(values, float(fps), int(depth), bool(dither) and depth == 8, bool(legal), lut_of(values), seq,
                   None, 0.0, size, dict(keys or {}), float(fps), burn, bool(alpha))

    @property
    def profile(self) -> str | None:
        """O perfil de entrada do look: a leitura do arquivo depende dele (log com super-brancos sai em float32,
        `media.float_input`); None sem look."""
        return (self.values or {}).get("entrada")

    @property
    def shutter(self) -> float:
        """1.6: o ângulo do obturador do look em graus (0 = desligado; `tempo_camera`). Os leitores pedem os quadros
        da janela aberta com ele: `tempo_camera.WindowReader` (arquivo), `sequence.grab`/`SequenceReader` (Edição)."""
        from . import tempo_camera
        return tempo_camera.shutter_angle(self.values)

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
        from .tempo_camera import Stack
        if isinstance(img, Stack):  # 1.6, obturador: os quadros do arquivo misturados na luz linear do look
            return self.blend(engine, img)
        if not isinstance(img, FrameLayers):
            return img
        if any(li.stack is not None for li in img.layers):  # 1.6, obturador por clipe (modo Edição)
            img = FrameLayers(img.frame, [self._blend_layer(engine, li) for li in img.layers])
        w, h = self.montage_size()
        crop = self.fit.canvas_crop if self.fit is not None else None
        from .transitions import light_of  # transições da 1.5: misturam na luz da entrada do look
        kw = {"alpha": True} if self.alpha else {}
        from . import camera
        if camera.uses_profiles(self.seq):  # 1.6: perfis de câmera por clipe (a tela vai ao look em float32)
            # sem look (prévia sem película) o espaço é o Rec.709, o mesmo da exportação "Sem película", que usa o
            # preset "original" (entrada Rec.709)
            kw.update(camera=camera.target_of(self.values, self.legal),
                      float_out=self.values is not None and not self.alpha)
        return engine.compose(img, self.seq, w, h, self.depth, neutral=neutral, crop=crop,
                              light=light_of(self.values, self.legal), **kw)

    def blend(self, engine, stack, curve: tuple[int, bool] | None = None):
        """1.6, obturador: a média ponderada dos quadros (`tempo_camera.Stack`) na luz linear da curva (a entrada do
        look, na faixa da receita), de volta no valor da curva (float32, a imagem que o look lê)."""
        from . import tempo_camera
        if len(stack.images) == 1:
            return stack.images[0]
        cid, cv = curve if curve is not None else tempo_camera.curve_of(self.values, self.legal)
        return engine.temporal_blend(list(stack.images), list(stack.weights), cid, cv)

    def _blend_layer(self, engine, li):
        """Uma camada com os quadros da janela do obturador vira a mistura deles, na curva do próprio clipe (o perfil
        de câmera dele, com a faixa do arquivo; ou a entrada do look)."""
        if li.stack is None:
            return li
        from . import camera, media, tempo_camera
        from .sequence import LayerImage
        clip = li.layer.clip
        legal = self.legal
        values = self.values
        if camera.clip_profile(clip.values) is not None:
            src = self.seq.sources.get(clip.src) if self.seq is not None else None
            legal = media.legal_range(src.to_info()) if src is not None else self.legal
            values = camera.clip_values(clip.values)
        imgs, ws = li.stack
        img = self.blend(engine, tempo_camera.Stack(list(imgs), list(ws)), tempo_camera.curve_of(values, legal))
        return LayerImage(li.layer, img)

    def look_values(self, index: int) -> dict:
        """Passo 3: os ajustes do look no quadro `index` da saída (com as chaves de animação avaliadas)."""
        if not self.keys:
            return self.values
        from . import keyframes
        src = self.src_fps or self.fps
        return keyframes.look_values_at(self.values, self.keys, index * src / self.fps if self.fps else index)

    def plan(self, w: int, h: int, index: int) -> look.Plan:
        """Passo 4: o plano do look para uma imagem w × h no quadro `index`."""
        values = self.look_values(index)
        kw = {}
        if values is not None and values.get("mfilme_on") and self.seq is not None:  # 1.6: os cortes da montagem
            from . import montagem_filme
            kw["edit"] = montagem_filme.edit_info(self.seq, index, self.fps)
        return look.build_plan(values, w, h, index, self.fps, self.lut, dither=self.dither,
                               legal=self.legal, net_grain=self.net_grain, **kw)

    def look(self, engine, img, index: int, upload: bool = True):
        """Passo 5: aplica o look à imagem montada (e as legendas gravadas, antes ou depois dele). `upload=False`
        quando a imagem já está na entrada do `engine` (a prévia reaproveita o envio enquanto só os ajustes
        mudam; com legenda gravada na cópia neste quadro, a imagem é enviada de novo)."""
        burn = self.burn
        if burn is not None and burn.mode == "copia":
            burned = burn.apply(img, self.time(index))
            upload = upload or burned is not img
            img = burned
        if self.values is None:
            out = opaque_alpha(img) if self.alpha else img
        else:
            if upload:
                engine.set_input(img)
            h, w = img.shape[:2]
            plan = self.plan(w, h, index)
            kw = {"alpha": True} if self.alpha else {}
            if self.fit is not None and self.fit.composite:
                out = engine.render_fit(plan, self.depth, self.fit, **kw)
            else:
                out = engine.render(plan, self.depth, **kw)
            if self.alpha:
                out = opaque_alpha(out)
        if burn is not None and burn.mode == "digital":
            out = burn.apply(out, self.time(index))
        return out

    def time(self, index: int) -> float:
        """O instante (s) do quadro `index` da saída: o das legendas gravadas."""
        return index / self.fps if self.fps else 0.0

    def render(self, engine, img, index: int):
        """O quadro inteiro: montagem (se `img` são camadas) e look. `index` é o número do quadro na saída."""
        return self.look(engine, self.montage(engine, img), index)


def opaque_alpha(img):
    """RGBA: um quadro de 3 canais (entrada sem transparência) ganha o alfa todo opaco; 4 canais passam direto."""
    if img.ndim == 3 and img.shape[2] == 4:
        return img
    import numpy as np
    mx = np.iinfo(img.dtype).max
    return np.dstack([img, np.full(img.shape[:2], mx, img.dtype)])


def lut_of(values: dict | None) -> tuple | None:
    """O LUT do look (`engine.lut_info`), ou None sem LUT ligado ou se ele não pôde ser lido."""
    if not values or not values.get("lut_on") or not values.get("lut_arquivo"):
        return None
    from .engine import lut_info
    return lut_info(values["lut_arquivo"])
