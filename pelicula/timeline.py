"""Linha do tempo do modo Edição: sequência, faixas e clipes (sem Qt).

- O tempo da sequência é contado em **quadros inteiros** no fps da sequência (`Sequence.fps`).
- A posição dentro do arquivo de origem é guardada em **segundos** (`Clip.src_in`), então
  vídeos com fps diferentes e arquivos só de áudio convivem na mesma sequência.
- A faixa 0 é a de baixo (V1/A1); faixas de vídeo maiores ficam por cima na imagem.
- Clipes de vídeo e áudio do mesmo arquivo nascem **ligados** (`Clip.link`): mover, aparar,
  dividir, mudar a velocidade ou apagar um afeta o outro do mesmo jeito.
- Colocar um clipe por cima de outro **sobrescreve** a parte coberta (como nos editores comuns).

Tudo aqui é determinístico e puro: o mesmo JSON gera sempre a mesma montagem, e a prévia e a
exportação usam as mesmas funções (`src_frame`, `clips_at`, `layers_at`).
"""

from __future__ import annotations

import copy
import json
import math
import os
import uuid
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Iterable

from . import editparams

VIDEO = "video"
AUDIO = "audio"
KINDS = (VIDEO, AUDIO)
FORMAT = 1               # versão do bloco "edicao" dentro do projeto .plc
IMAGE_SECONDS = 5.0      # duração inicial de uma imagem parada
MAX_HOLD_SECONDS = 4 * 3600.0  # limite de duração de imagens e quadros congelados
EPS = 1e-6
FPS_CHOICES = ["24000/1001", "24/1", "25/1", "30000/1001", "30/1", "50/1", "60000/1001", "60/1"]


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def parse_fps(text: str) -> Fraction:
    try:
        fr = Fraction(str(text))
    except (ValueError, ZeroDivisionError):
        return Fraction(24, 1)
    return fr if 0 < fr <= 1000 else Fraction(24, 1)


# ------------------------------------------------------------------ origem
@dataclass
class Source:
    """Metadados de um arquivo usado na sequência (o que o ffprobe informou)."""

    path: str
    width: int = 0
    height: int = 0
    fps: float = 24.0
    fps_str: str = "24/1"
    frames: int = 1
    duration: float = 0.0
    is_image: bool = False
    has_video: bool = True
    has_audio: bool = False
    pix_fmt: str = ""
    bit_depth: int = 8
    codec: str = ""
    profile: str = ""
    bitrate: int = 0
    color_space: str = ""
    color_range: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    audio_codec: str = ""
    container: str = ""

    @property
    def length(self) -> float:
        """Duração útil em segundos (vídeo: quadros/fps; só áudio: duração; imagem: sem limite)."""
        if self.is_image:
            return MAX_HOLD_SECONDS
        if self.has_video and self.fps > 0 and self.frames > 0:
            return self.frames / self.fps
        return max(self.duration, 0.0)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @classmethod
    def from_info(cls, info) -> "Source":
        """A partir de um `media.MediaInfo` (arquivo com imagem)."""
        return cls(path=info.path, width=info.width, height=info.height, fps=info.fps, fps_str=info.fps_str,
                   frames=info.frames, duration=info.duration, is_image=info.is_image, has_video=True,
                   has_audio=info.has_audio, pix_fmt=info.pix_fmt, bit_depth=info.bit_depth, codec=info.codec,
                   profile=info.profile, bitrate=info.bitrate, color_space=info.color_space,
                   color_range=info.color_range, color_transfer=info.color_transfer,
                   color_primaries=info.color_primaries, audio_codec=info.audio_codec, container=info.container)

    def to_info(self):
        """`media.MediaInfo` equivalente (para o FrameReader e o grab_frame)."""
        from . import media
        return media.MediaInfo(
            path=self.path, width=self.width, height=self.height, fps=self.fps, fps_str=self.fps_str,
            frames=max(1, self.frames), duration=self.duration, pix_fmt=self.pix_fmt, bit_depth=self.bit_depth,
            codec=self.codec, profile=self.profile, bitrate=self.bitrate, color_space=self.color_space,
            color_range=self.color_range, color_transfer=self.color_transfer, color_primaries=self.color_primaries,
            has_audio=self.has_audio, audio_codec=self.audio_codec, container=self.container, is_image=self.is_image)

    def to_json(self) -> dict[str, Any]:
        return {"caminho": self.path, "largura": self.width, "altura": self.height, "fps": self.fps_str,
                "quadros": self.frames, "duracao": round(self.duration, 6), "imagem": self.is_image,
                "tem_video": self.has_video, "tem_audio": self.has_audio, "pix_fmt": self.pix_fmt,
                "bits": self.bit_depth, "codec": self.codec, "perfil": self.profile, "taxa": self.bitrate,
                "cor_matriz": self.color_space, "cor_faixa": self.color_range, "cor_transferencia": self.color_transfer,
                "cor_primarias": self.color_primaries, "codec_audio": self.audio_codec, "recipiente": self.container}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Source":
        fr = parse_fps(d.get("fps", "24/1"))

        def num(key, default, typ=float):
            try:
                v = typ(d.get(key, default))
                return v if math.isfinite(v) else default
            except (TypeError, ValueError):
                return default

        return cls(path=str(d.get("caminho") or ""), width=max(0, num("largura", 0, int)),
                   height=max(0, num("altura", 0, int)), fps=float(fr), fps_str=f"{fr.numerator}/{fr.denominator}",
                   frames=max(1, num("quadros", 1, int)), duration=max(0.0, num("duracao", 0.0)),
                   is_image=bool(d.get("imagem", False)), has_video=bool(d.get("tem_video", True)),
                   has_audio=bool(d.get("tem_audio", False)), pix_fmt=str(d.get("pix_fmt") or ""),
                   bit_depth=max(8, num("bits", 8, int)), codec=str(d.get("codec") or ""),
                   profile=str(d.get("perfil") or ""), bitrate=max(0, num("taxa", 0, int)),
                   color_space=str(d.get("cor_matriz") or ""), color_range=str(d.get("cor_faixa") or ""),
                   color_transfer=str(d.get("cor_transferencia") or ""),
                   color_primaries=str(d.get("cor_primarias") or ""), audio_codec=str(d.get("codec_audio") or ""),
                   container=str(d.get("recipiente") or ""))


# ------------------------------------------------------------------ clipes e faixas
@dataclass
class Clip:
    id: str
    kind: str                # "video" | "audio"
    src: str                 # caminho do arquivo (chave de Sequence.sources)
    track: int               # 0 = V1 / A1
    start: int               # primeiro quadro na sequência
    dur: int                 # duração em quadros da sequência (>= 1)
    src_in: float = 0.0      # segundos no arquivo de origem no primeiro quadro
    link: str = ""           # clipes com o mesmo link andam juntos ("" = sozinho)
    name: str = ""
    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = editparams.SCHEMAS[self.kind].sanitize(self.values)

    @property
    def end(self) -> int:
        """Primeiro quadro depois do clipe (exclusivo)."""
        return self.start + self.dur

    @property
    def speed(self) -> float:
        return float(self.values.get("velocidade", 1.0))

    @property
    def frozen(self) -> bool:
        return bool(self.values.get("congelar", False)) and self.kind == VIDEO

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "tipo": self.kind, "fonte": self.src, "faixa": self.track, "inicio": self.start,
                "duracao": self.dur, "entrada": round(self.src_in, 6), "ligacao": self.link, "nome": self.name,
                "valores": copy.deepcopy(self.values)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Clip | None":
        kind = d.get("tipo")
        if kind not in KINDS or not d.get("fonte"):
            return None
        try:
            return cls(id=str(d.get("id") or new_id()), kind=kind, src=str(d["fonte"]),
                       track=max(0, int(d.get("faixa", 0))), start=max(0, int(d.get("inicio", 0))),
                       dur=max(1, int(d.get("duracao", 1))), src_in=max(0.0, float(d.get("entrada", 0.0))),
                       link=str(d.get("ligacao") or ""), name=str(d.get("nome") or ""),
                       values=d.get("valores") if isinstance(d.get("valores"), dict) else {})
        except (TypeError, ValueError):
            return None


@dataclass
class Track:
    kind: str
    name: str = ""
    muted: bool = False      # vídeo: faixa escondida; áudio: sem som
    locked: bool = False     # travada: nenhuma edição mexe nela
    solo: bool = False       # áudio: só as faixas em solo tocam
    volume: float = 0.0      # dB (áudio)

    def to_json(self) -> dict[str, Any]:
        return {"tipo": self.kind, "nome": self.name, "mudo": self.muted, "travada": self.locked, "solo": self.solo,
                "volume": self.volume}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Track | None":
        if d.get("tipo") not in KINDS:
            return None
        try:
            vol = min(max(float(d.get("volume", 0.0)), -60.0), 12.0)
        except (TypeError, ValueError):
            vol = 0.0
        return cls(kind=d["tipo"], name=str(d.get("nome") or ""), muted=bool(d.get("mudo", False)),
                   locked=bool(d.get("travada", False)), solo=bool(d.get("solo", False)), volume=vol)


@dataclass
class Layer:
    """Uma camada de imagem num quadro da sequência (de baixo para cima)."""

    clip: Clip
    src_frame: int            # quadro do arquivo a mostrar
    alpha: float = 1.0        # opacidade da transição (multiplica a opacidade do clipe)
    fade_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fade: float = 0.0         # 0 = imagem; 1 = só a cor do fade (surgir/sumir no preto ou branco)
    extension: bool = False   # True = cauda do clipe anterior mostrada por baixo de um "dissolver"


# ------------------------------------------------------------------ sequência
@dataclass
class Sequence:
    width: int = 1920
    height: int = 1080
    fps_str: str = "24/1"
    name: str = ""
    background: tuple[float, float, float] = (0.0, 0.0, 0.0)
    tracks: list[Track] = field(default_factory=list)
    clips: list[Clip] = field(default_factory=list)
    sources: dict[str, Source] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fr = parse_fps(self.fps_str)
        self.fps_str = f"{fr.numerator}/{fr.denominator}"
        self.width = max(16, int(self.width))
        self.height = max(16, int(self.height))
        if not any(t.kind == VIDEO for t in self.tracks):
            self.tracks.insert(0, Track(VIDEO, "V1"))
        if not any(t.kind == AUDIO for t in self.tracks):
            self.tracks.append(Track(AUDIO, "A1"))

    # -------------------------------------------------------- básico
    @property
    def fps(self) -> float:
        return float(parse_fps(self.fps_str))

    @property
    def duration(self) -> int:
        """Quadros da sequência (do 0 até o fim do último clipe)."""
        return max((c.end for c in self.clips), default=0)

    def kind_tracks(self, kind: str) -> list[Track]:
        return [t for t in self.tracks if t.kind == kind]

    def track(self, kind: str, idx: int) -> Track | None:
        ts = self.kind_tracks(kind)
        return ts[idx] if 0 <= idx < len(ts) else None

    def add_track(self, kind: str) -> int:
        n = len(self.kind_tracks(kind))
        self.tracks.append(Track(kind, ("V" if kind == VIDEO else "A") + str(n + 1)))
        return n

    def remove_track(self, kind: str, idx: int) -> None:
        """Apaga a faixa e os clipes dela; as faixas acima descem uma posição."""
        ts = self.kind_tracks(kind)
        if len(ts) <= 1 or not 0 <= idx < len(ts):
            return
        self.tracks.remove(ts[idx])
        self.clips = [c for c in self.clips if not (c.kind == kind and c.track == idx)]
        for c in self.clips:
            if c.kind == kind and c.track > idx:
                c.track -= 1
        for i, t in enumerate(self.kind_tracks(kind)):
            t.name = ("V" if kind == VIDEO else "A") + str(i + 1)

    def ensure_track(self, kind: str, idx: int) -> None:
        while len(self.kind_tracks(kind)) <= idx:
            self.add_track(kind)

    def find(self, cid: str) -> Clip | None:
        return next((c for c in self.clips if c.id == cid), None)

    def group(self, clip: Clip) -> list[Clip]:
        """O clipe e os ligados a ele."""
        if not clip.link:
            return [clip]
        return [c for c in self.clips if c.link == clip.link]

    def expand(self, ids: Iterable[str]) -> list[Clip]:
        """Clipes dos ids pedidos mais os ligados, sem repetir, na ordem da sequência."""
        want = set()
        for cid in ids:
            c = self.find(cid)
            if c is not None:
                want.update(x.id for x in self.group(c))
        return [c for c in self.clips if c.id in want]

    def clips_on(self, kind: str, track: int) -> list[Clip]:
        return sorted((c for c in self.clips if c.kind == kind and c.track == track), key=lambda c: c.start)

    def locked(self, clip: Clip) -> bool:
        t = self.track(clip.kind, clip.track)
        return bool(t and t.locked)

    def source(self, clip: Clip) -> Source:
        return self.sources[clip.src]

    def add_source(self, src: Source) -> Source:
        self.sources[src.path] = src
        return src

    # -------------------------------------------------------- tempo
    def frames_for(self, seconds: float) -> int:
        return max(1, int(math.floor(seconds * self.fps + EPS)))

    def src_time(self, clip: Clip, t: int) -> float:
        """Segundos no arquivo de origem mostrados no quadro t da sequência."""
        if clip.frozen:
            return clip.src_in
        return clip.src_in + (t - clip.start) / self.fps * clip.speed

    def src_frame(self, clip: Clip, t: int) -> int:
        """Quadro do arquivo de origem para o quadro t da sequência (o mesmo na prévia e na exportação)."""
        src = self.sources.get(clip.src)
        if src is None or src.is_image:
            return 0
        f = int(math.floor(self.src_time(clip, t) * src.fps + EPS))
        return min(max(f, 0), max(0, src.frames - 1))

    def max_dur(self, clip: Clip, src_in: float | None = None) -> int:
        """Maior duração (quadros) que o arquivo permite a partir de `src_in`."""
        src = self.sources.get(clip.src)
        if src is None:
            return clip.dur
        if src.is_image or clip.frozen:
            return self.frames_for(MAX_HOLD_SECONDS)
        a = clip.src_in if src_in is None else src_in
        left = max(0.0, src.length - a)
        return max(1, int(math.floor(left / clip.speed * self.fps + EPS)))

    def default_dur(self, src: Source) -> int:
        if src.is_image:
            return self.frames_for(IMAGE_SECONDS)
        return self.frames_for(src.length)

    # -------------------------------------------------------- consulta
    def clips_at(self, t: int, kind: str | None = None) -> list[Clip]:
        """Clipes ativos no quadro t (faixas mudas/escondidas de fora), da faixa de baixo para a de cima."""
        out = []
        for c in self.clips:
            if (kind and c.kind != kind) or not (c.start <= t < c.end):
                continue
            tr = self.track(c.kind, c.track)
            if tr is not None and tr.muted:
                continue
            out.append(c)
        return sorted(out, key=lambda c: (c.kind != VIDEO, c.track, c.start))

    def previous_on_track(self, clip: Clip) -> Clip | None:
        """Clipe que termina exatamente onde este começa, na mesma faixa (para o "dissolver")."""
        for c in self.clips:
            if c is not clip and c.kind == clip.kind and c.track == clip.track and c.end == clip.start:
                return c
        return None

    def layers_at(self, t: int) -> list[Layer]:
        """Camadas de imagem do quadro t, de baixo para cima, já com as transições resolvidas."""
        fps = self.fps
        out: list[Layer] = []
        for c in self.clips_at(t, VIDEO):
            v = c.values
            alpha, fade, color = 1.0, 0.0, (0.0, 0.0, 0.0)
            pos = t - c.start
            n_in = max(1, int(round(v["entrada_dur"] * fps)))
            n_out = max(1, int(round(v["saida_dur"] * fps)))
            if v["entrada_tipo"] != "corte" and pos < n_in:
                k = (pos + 1) / (n_in + 1)
                if v["entrada_tipo"] == "dissolver":
                    prev = self.previous_on_track(c)
                    if prev is not None:
                        out.append(Layer(prev, self.src_frame(prev, t), 1.0, extension=True))
                    alpha = k
                else:
                    fade = 1.0 - k
                    color = (1.0, 1.0, 1.0) if v["entrada_tipo"] == "branco" else (0.0, 0.0, 0.0)
            rest = c.end - 1 - t
            if v["saida_tipo"] != "corte" and rest < n_out:
                k = (rest + 1) / (n_out + 1)
                if v["saida_tipo"] == "transparente":
                    alpha *= k
                else:
                    color = (1.0, 1.0, 1.0) if v["saida_tipo"] == "branco" else (0.0, 0.0, 0.0)
                    fade = max(fade, 1.0 - k)
            out.append(Layer(c, self.src_frame(c, t), alpha, color, fade))
        return out

    def audio_clips(self) -> list[Clip]:
        """Clipes de som que tocam (respeita mudo e solo das faixas e o mudo do clipe)."""
        tracks = self.kind_tracks(AUDIO)
        solo = any(t.solo for t in tracks)
        out = []
        for c in self.clips:
            if c.kind != AUDIO or c.values.get("mudo"):
                continue
            tr = self.track(AUDIO, c.track)
            if tr is None or tr.muted or (solo and not tr.solo):
                continue
            out.append(c)
        return sorted(out, key=lambda c: (c.track, c.start))

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_clips())

    # -------------------------------------------------------- montagem
    def insert_media(self, src: Source, at: int | None = None, vtrack: int = 0, atrack: int = 0,
                     with_audio: bool = True) -> list[Clip]:
        """Põe um arquivo na sequência (vídeo + som ligado). `at=None` coloca no fim da faixa."""
        self.add_source(src)
        dur = self.default_dur(src)
        made: list[Clip] = []
        link = new_id() if (src.has_video and src.has_audio and with_audio) else ""
        if src.has_video:
            self.ensure_track(VIDEO, vtrack)
            start = self._end_of(VIDEO, vtrack) if at is None else max(0, int(at))
            made.append(Clip(new_id(), VIDEO, src.path, vtrack, start, dur, 0.0, link, src.name))
        if src.has_audio and with_audio:
            self.ensure_track(AUDIO, atrack)
            if made:
                start = made[0].start
            else:
                start = self._end_of(AUDIO, atrack) if at is None else max(0, int(at))
            made.append(Clip(new_id(), AUDIO, src.path, atrack, start, dur, 0.0, link, src.name))
        for c in made:
            self._clear_range(c.kind, c.track, c.start, c.end, {x.id for x in made})
            self.clips.append(c)
        return made

    def _end_of(self, kind: str, track: int) -> int:
        return max((c.end for c in self.clips_on(kind, track)), default=0)

    def _clear_range(self, kind: str, track: int, a: int, b: int, keep: set[str]) -> None:
        """Sobrescreve [a, b) da faixa: corta, encurta ou apaga os outros clipes."""
        if b <= a:
            return
        for c in list(self.clips):
            if c.id in keep or c.kind != kind or c.track != track or c.end <= a or c.start >= b:
                continue
            if c.start >= a and c.end <= b:
                self.clips.remove(c)
            elif c.start < a and c.end > b:
                right = self._cut(c, b)
                right.link = ""
                c.dur = a - c.start
            elif c.start < a:
                c.dur = a - c.start
            else:
                cut = b - c.start
                c.src_in = self.src_time(c, b)
                c.start = b
                c.dur -= cut

    def _cut(self, c: Clip, t: int) -> Clip:
        """Divide o clipe no quadro t; devolve a parte da direita (já na sequência)."""
        right = Clip(new_id(), c.kind, c.src, c.track, t, c.end - t, self.src_time(c, t), "", c.name,
                     copy.deepcopy(c.values))
        c.dur = t - c.start
        # A transição de entrada fica só na parte da esquerda; a de saída, só na da direita.
        if c.kind == VIDEO:
            right.values["entrada_tipo"] = "corte"
            c.values["saida_tipo"] = "corte"
        else:
            right.values["fade_in"] = 0.0
            c.values["fade_out"] = 0.0
        self.clips.append(right)
        return right

    def split(self, t: int, ids: Iterable[str] | None = None) -> list[str]:
        """Divide no quadro t os clipes pedidos (ou todos sob o cursor). Devolve os ids das partes novas."""
        if ids is None:
            targets = [c for c in self.clips if c.start < t < c.end]
        else:
            targets = [c for c in self.expand(ids) if c.start < t < c.end]
        targets = [c for c in targets if not self.locked(c)]
        new_links: dict[str, str] = {}
        made = []
        for c in targets:
            right = self._cut(c, t)
            if c.link:
                right.link = new_links.setdefault(c.link, new_id())
            made.append(right.id)
        return made

    def _group_for_edit(self, cid: str) -> list[Clip]:
        c = self.find(cid)
        if c is None:
            return []
        return [g for g in self.group(c) if not self.locked(g)]

    def move(self, cid: str, new_start: int, new_track: int | None = None) -> int:
        """Move o clipe (e os ligados) para `new_start`; a faixa só muda no clipe arrastado.

        Devolve o deslocamento aplicado em quadros.
        """
        group = self._group_for_edit(cid)
        clip = self.find(cid)
        if not group or clip not in group:
            return 0
        delta = int(new_start) - clip.start
        delta = max(delta, -min(c.start for c in group))
        if new_track is not None and new_track != clip.track and clip in group:
            if new_track < 0:
                new_track = clip.track
            self.ensure_track(clip.kind, new_track)
            tr = self.track(clip.kind, new_track)
            if tr is not None and not tr.locked:
                clip.track = new_track
        for c in group:
            c.start += delta
        keep = {c.id for c in group}
        for c in group:
            self._clear_range(c.kind, c.track, c.start, c.end, keep)
        return delta

    def trim_start(self, cid: str, new_start: int) -> int:
        """Apara o começo (o fim fica onde está). Devolve o deslocamento aplicado."""
        group = self._group_for_edit(cid)
        clip = self.find(cid)
        if not group or clip not in group:
            return 0
        delta = int(new_start) - clip.start
        for c in group:
            src = self.sources.get(c.src)
            hold = src is None or src.is_image or c.frozen
            lo = -c.start
            if not hold:
                # Não dá para voltar antes do começo do arquivo.
                lo = max(lo, -int(math.floor(c.src_in / c.speed * self.fps + EPS)))
            hi = c.dur - 1
            delta = min(max(delta, lo), hi)
        for c in group:
            if not c.frozen:
                c.src_in = max(0.0, self.src_time(c, c.start + delta))
            c.start += delta
            c.dur -= delta
        keep = {c.id for c in group}
        for c in group:
            self._clear_range(c.kind, c.track, c.start, c.end, keep)
        return delta

    def trim_end(self, cid: str, new_end: int) -> int:
        """Apara o fim (o começo fica onde está). Devolve o deslocamento aplicado."""
        group = self._group_for_edit(cid)
        clip = self.find(cid)
        if not group or clip not in group:
            return 0
        delta = int(new_end) - clip.end
        for c in group:
            delta = min(max(delta, 1 - c.dur), self.max_dur(c) - c.dur)
        for c in group:
            c.dur += delta
        keep = {c.id for c in group}
        for c in group:
            self._clear_range(c.kind, c.track, c.start, c.end, keep)
        return delta

    def set_speed(self, cid: str, speed: float) -> None:
        """Muda a velocidade do clipe e dos ligados; a duração acompanha (sem invadir o clipe seguinte)."""
        group = self._group_for_edit(cid)
        if not group or self.find(cid) not in group:
            return
        p = editparams.VIDEO.params["velocidade"]
        speed = min(max(float(speed), p.min), p.max)
        new_durs = []
        for c in group:
            used = c.dur / self.fps * c.speed
            nd = max(1, int(round(used / speed * self.fps)))
            nxt = min((o.start for o in self.clips_on(c.kind, c.track) if o.start >= c.end and o.id not in
                       {g.id for g in group}), default=None)
            if nxt is not None:
                nd = min(nd, nxt - c.start)
            new_durs.append(nd)
        nd = min(new_durs)
        for c in group:
            c.values["velocidade"] = speed
            c.dur = max(1, min(nd, self.max_dur(c)))

    def set_values(self, cid: str, values: dict[str, Any]) -> None:
        """Troca os ajustes de um clipe (a velocidade passa por `set_speed` para manter os ligados juntos)."""
        c = self.find(cid)
        if c is None:
            return
        clean = editparams.SCHEMAS[c.kind].sanitize(values)
        speed = clean.get("velocidade", 1.0)
        if abs(speed - c.speed) > 1e-9:
            self.set_speed(cid, speed)
        clean["velocidade"] = c.speed
        c.values = clean
        if c.kind == VIDEO and c.frozen:
            c.dur = min(c.dur, self.max_dur(c))

    def delete(self, ids: Iterable[str], ripple: bool = False) -> None:
        """Apaga os clipes (e os ligados). Com `ripple`, fecha o espaço puxando o que vem depois."""
        gone = [c for c in self.expand(ids) if not self.locked(c)]
        if not gone:
            return
        gone_ids = {c.id for c in gone}
        self.clips = [c for c in self.clips if c.id not in gone_ids]
        if not ripple:
            return
        a = min(c.start for c in gone)
        b = max(c.end for c in gone)
        tracks = {(c.kind, c.track) for c in gone}
        # Se o espaço [a, b) ficou livre em todas as faixas, puxa a sequência inteira; senão só as afetadas.
        free_everywhere = not any(c.start < b and c.end > a for c in self.clips)
        for c in self.clips:
            if self.locked(c) or c.start < b:
                continue
            if free_everywhere or (c.kind, c.track) in tracks:
                c.start -= (b - a)

    def unlink(self, cid: str) -> None:
        c = self.find(cid)
        if c is None:
            return
        for g in self.group(c):
            g.link = ""

    def link(self, ids: Iterable[str]) -> None:
        clips = [self.find(i) for i in ids]
        clips = [c for c in clips if c is not None]
        if len(clips) < 2:
            return
        lid = new_id()
        for c in clips:
            c.link = lid

    def close_gaps(self, kind: str, track: int) -> None:
        """Junta os clipes da faixa, sem espaços entre eles."""
        tr = self.track(kind, track)
        if tr is None or tr.locked:
            return
        pos = 0
        for c in self.clips_on(kind, track):
            if c.start > pos:
                self.move(c.id, pos)
            pos = c.end

    # -------------------------------------------------------- estado
    def is_trivial(self) -> str | None:
        """Caminho do arquivo se a sequência é só "o arquivo inteiro, sem mudanças" (senão None).

        Nesse caso o modo Película lê o arquivo direto, exatamente como antes do modo Edição.
        """
        vids = [c for c in self.clips if c.kind == VIDEO]
        auds = [c for c in self.clips if c.kind == AUDIO]
        if len(vids) != 1 or len(auds) > 1:
            return None
        v = vids[0]
        src = self.sources.get(v.src)
        if src is None or v.start != 0 or v.src_in > EPS or not editparams.is_neutral(VIDEO, v.values):
            return None
        if src.width != self.width or src.height != self.height or abs(src.fps - self.fps) > 1e-6:
            return None
        if not src.is_image and v.dur != src.frames:
            return None
        if any(t.muted for t in self.kind_tracks(VIDEO)):
            return None
        if auds:
            a = auds[0]
            if (a.src != v.src or a.start != 0 or a.dur != v.dur or a.src_in > EPS
                    or not editparams.is_neutral(AUDIO, a.values) or not self.has_audio):
                return None
            if any(abs(t.volume) > 1e-9 for t in self.kind_tracks(AUDIO)):
                return None
        elif src.has_audio:
            return None
        return src.path

    def copy(self) -> "Sequence":
        return Sequence.from_json(self.to_json())

    def to_json(self) -> dict[str, Any]:
        used = {c.src for c in self.clips}
        return {
            "formato": FORMAT,
            "largura": self.width, "altura": self.height, "fps": self.fps_str, "nome": self.name,
            "fundo": [float(x) for x in self.background],
            "faixas": [t.to_json() for t in self.tracks],
            "fontes": [s.to_json() for p, s in self.sources.items() if p in used],
            "clipes": [c.to_json() for c in sorted(self.clips, key=lambda c: (c.kind, c.track, c.start))],
        }

    @classmethod
    def from_json(cls, d: dict[str, Any] | None) -> "Sequence":
        d = d if isinstance(d, dict) else {}
        try:
            bg = tuple(min(max(float(x), 0.0), 1.0) for x in list(d.get("fundo") or (0, 0, 0))[:3])
            if len(bg) != 3:
                raise ValueError
        except (TypeError, ValueError):
            bg = (0.0, 0.0, 0.0)
        try:
            w, h = int(d.get("largura", 1920)), int(d.get("altura", 1080))
        except (TypeError, ValueError):
            w, h = 1920, 1080
        tracks = [t for t in (Track.from_json(x) for x in d.get("faixas") or [] if isinstance(x, dict)) if t]
        seq = cls(width=w, height=h, fps_str=str(d.get("fps") or "24/1"), name=str(d.get("nome") or ""),
                  background=bg, tracks=tracks)
        for sd in d.get("fontes") or []:
            if isinstance(sd, dict) and sd.get("caminho"):
                src = Source.from_json(sd)
                seq.sources[src.path] = src
        for cd in d.get("clipes") or []:
            if not isinstance(cd, dict):
                continue
            c = Clip.from_json(cd)
            if c is None or c.src not in seq.sources:
                continue
            seq.ensure_track(c.kind, c.track)
            seq.clips.append(c)
        return seq

    def relink(self, old: str, new: str) -> None:
        """Troca o caminho de um arquivo (projeto aberto em outro computador ou pasta)."""
        if old == new or old not in self.sources:
            return
        src = self.sources.pop(old)
        src.path = new
        self.sources[new] = src
        for c in self.clips:
            if c.src == old:
                c.src = new

    @classmethod
    def for_source(cls, src: Source, with_media: bool = True) -> "Sequence":
        """Sequência no formato do arquivo (resolução e fps), já com ele dentro se `with_media`."""
        w, h = (src.width, src.height) if src.has_video and src.width and src.height else (1920, 1080)
        fps = src.fps_str if (src.has_video and not src.is_image) else "24/1"
        seq = cls(width=w, height=h, fps_str=fps)
        if with_media:
            seq.insert_media(src, 0)
        return seq


class History:
    """Desfazer/refazer da sequência por instantâneos JSON (até `limit` passos)."""

    def __init__(self, seq: Sequence, limit: int = 200):
        self.limit = limit
        self._states = [self._dump(seq)]
        self._pos = 0

    @staticmethod
    def _dump(seq: Sequence) -> str:
        return json.dumps(seq.to_json(), sort_keys=True, ensure_ascii=False)

    def reset(self, seq: Sequence) -> None:
        self._states = [self._dump(seq)]
        self._pos = 0

    def push(self, seq: Sequence) -> bool:
        """Grava o estado atual se mudou. Devolve True se gravou."""
        s = self._dump(seq)
        if s == self._states[self._pos]:
            return False
        self._states = self._states[: self._pos + 1] + [s]
        if len(self._states) > self.limit:
            self._states.pop(0)
        self._pos = len(self._states) - 1
        return True

    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._states) - 1

    def undo(self) -> Sequence | None:
        if not self.can_undo():
            return None
        self._pos -= 1
        return Sequence.from_json(json.loads(self._states[self._pos]))

    def redo(self) -> Sequence | None:
        if not self.can_redo():
            return None
        self._pos += 1
        return Sequence.from_json(json.loads(self._states[self._pos]))
