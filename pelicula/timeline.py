"""Linha do tempo do modo Edição: sequência, faixas e clipes (sem Qt).

- O tempo da sequência é contado em **quadros inteiros** no fps da sequência (`Sequence.fps`).
- A posição dentro do arquivo de origem é guardada em **segundos** (`Clip.src_in`), então
  vídeos com fps diferentes e arquivos só de áudio convivem na mesma sequência.
- A faixa 0 é a de baixo (V1/A1); faixas de vídeo maiores ficam por cima na imagem.
- Clipes de vídeo e áudio do mesmo arquivo nascem **ligados** (`Clip.link`): mover, aparar,
  dividir, mudar a velocidade ou apagar um afeta o outro do mesmo jeito.
- Colocar um clipe por cima de outro **sobrescreve** a parte coberta (como nos editores comuns).
- **Marcadores** (`Marker`) ficam no tempo da sequência, não presos a clipes: mover, aparar e dividir
  clipes não os mexe; "excluir e fechar o espaço" da sequência inteira puxa os que vêm depois do
  trecho apagado (os de dentro vão para o ponto do corte); mudar o fps mantém o tempo deles. Os
  marcados como capítulo viram os capítulos do YouTube e do arquivo exportado (`chapters.py`).
- **Som nas emendas**: `Sequence.micro_fade` liga um fade curtíssimo (`MICRO_FADE`) onde um clipe de som
  corta o arquivo no meio (sem estalo); a transição de som entre dois clipes vizinhos da faixa fica no
  clipe que entra (`values["transicao"]`) e o tempo dela sai de `audio_crossfade`. A mixagem em si é
  do `audiomix.py`.
- **Ferramentas de corte** (1.5): inserir em vez de sobrescrever (`open_space`, `insert_media(insert=True)`,
  `move_insert`), aparar até o cursor fechando o espaço (`ripple_trim_start`/`ripple_trim_end`, teclas Q/W),
  cortes J/L (pares ligados com entrada e saída diferentes: `trim_start_only`/`trim_end_only`,
  `split_edit`) e a **faixa principal magnética** (`Sequence.magnetic`: a V1 nunca fica com buracos e o
  resto acompanha a imagem dela; `keep_main`/`settle_main`).

Tudo aqui é determinístico e puro: o mesmo JSON gera sempre a mesma montagem, e a prévia e a
exportação usam as mesmas funções (`src_frame`, `clips_at`, `layers_at`).
"""

from __future__ import annotations

import copy
import json
import math
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable, Iterable

from . import editparams, keyframes
from .i18n import N_, _

VIDEO = "video"
AUDIO = "audio"
KINDS = (VIDEO, AUDIO)
# Versão do bloco "edicao" dentro do projeto .plc: FORMAT é a maior que esta versão lê; uma montagem sem nada da
# 1.5 continua sendo gravada com FORMAT_BASE (o bloco de antes). Veja `features()` e `migrate()`.
FORMAT = 2
FORMAT_BASE = 1
# Tipos de fonte (`Source.kind`, chave "tipo" no JSON). "arquivo" = arquivo de mídia (o de sempre); os outros
# ids estão reservados para clipes sem arquivo (gerados: `sequence.RENDERERS`). Nunca renomear.
SOURCE_FILE = "arquivo"
SOURCE_KINDS = (SOURCE_FILE, "cor", "gerador", "texto", "legenda", "ajuste")
IMAGE_SECONDS = 5.0      # duração inicial de uma imagem parada
MAX_HOLD_SECONDS = 4 * 3600.0  # limite de duração de imagens e quadros congelados
EPS = 1e-6
FPS_CHOICES = ["24000/1001", "24/1", "25/1", "30000/1001", "30/1", "50/1", "60000/1001", "60/1"]

# Cores dos marcadores: chave ASCII gravada no projeto (nunca renomear) e rótulo. O tom de cada uma
# na tela fica em `ui/theme.MARKER_COLORS`.
MARKER_COLORS: list[tuple[str, str]] = [
    ("laranja", N_("Laranja")), ("vermelho", N_("Vermelho")), ("amarelo", N_("Amarelo")), ("verde", N_("Verde")),
    ("ciano", N_("Ciano")), ("azul", N_("Azul")), ("roxo", N_("Roxo")), ("rosa", N_("Rosa")),
]
MARKER_COLOR_KEYS = tuple(k for k, _label in MARKER_COLORS)
MARKER_TEXT_MAX = 500   # nome e nota de um marcador (caracteres)
MICRO_FADE = 0.005      # s: fade automático nas emendas de som (some com o estalo e não se ouve como fade)
SPLIT_EDIT_S = 1.0      # s: duração padrão do corte J / corte L criado pelo menu do corte


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
    has_alpha: bool = False   # imagem com transparência (canal alfa); "alfa" no JSON, só quando ligado
    kind: str = SOURCE_FILE   # SOURCE_KINDS; "tipo" no JSON, só quando não é "arquivo"
    # Parâmetros de uma fonte sem arquivo (o que o gerador desenha: cor, texto…); "dados" no JSON, só quando há.
    # Só valores de JSON; chaves sem acento. "nome" é o nome mostrado na Mídia e no clipe.
    data: dict[str, Any] = field(default_factory=dict)
    # Sequência de imagens numeradas: `path` é o padrão do ffmpeg (plano_%04d.png) e este é o número do primeiro
    # quadro (`media.find_sequence`); -1 = arquivo comum. "sequencia" no JSON, só quando é uma sequência.
    seq_start: int = -1

    @property
    def is_file(self) -> bool:
        """Fonte que é um arquivo de mídia (as outras são desenhadas por `sequence.RENDERERS`)."""
        return self.kind == SOURCE_FILE

    @property
    def is_sequence(self) -> bool:
        """Sequência de imagens numeradas (um arquivo por quadro, lidos como um vídeo)."""
        return self.seq_start >= 0

    @classmethod
    def virtual(cls, kind: str, width: int, height: int, fps_str: str = "24/1", seconds: float | None = None,
                data: dict[str, Any] | None = None, alpha: bool = True) -> "Source":
        """Fonte sem arquivo (clipe gerado: título, cor, contagem…), desenhada por `sequence.RENDERERS[kind]`.

        O caminho é um id (`"<tipo>:<hex>"`, nunca um arquivo): é a chave em `Sequence.sources` e `Clip.src`.
        `seconds=None` = sem fim (como uma imagem: entra com `IMAGE_SECONDS` e pode ser esticada até
        `MAX_HOLD_SECONDS`), mas o quadro anda com o tempo (`src_frame`), para geradores animados. `alpha`: o
        gerador desenha com transparência (RGBA); False = opaco. Sem som."""
        if kind not in SOURCE_KINDS or kind == SOURCE_FILE:
            raise ValueError(f"tipo de fonte sem arquivo desconhecido: {kind!r}")
        fr = parse_fps(fps_str)
        secs = MAX_HOLD_SECONDS if seconds is None else max(1.0 / float(fr), float(seconds))
        frames = max(1, int(math.floor(secs * float(fr) + EPS)))
        return cls(path=f"{kind}:{uuid.uuid4().hex[:12]}", width=max(2, int(width)), height=max(2, int(height)),
                   fps=float(fr), fps_str=f"{fr.numerator}/{fr.denominator}", frames=frames,
                   duration=frames / float(fr), has_video=True, has_audio=False, pix_fmt="rgba" if alpha else "rgb24",
                   color_space="gbr", color_range="pc", color_transfer="iec61966-2-1", color_primaries="bt709",
                   has_alpha=bool(alpha), kind=kind, data=copy.deepcopy(dict(data or {})))

    @property
    def unbounded(self) -> bool:
        """Fonte sem fim natural: imagem parada ou gerador sem duração (`virtual(seconds=None)`)."""
        return self.is_image or (not self.is_file and self.length >= MAX_HOLD_SECONDS - 1e-3)

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
        if not self.is_file:
            return str(self.data.get("nome") or self.kind)
        if self.is_sequence:
            from .media import sequence_label
            return sequence_label(self.path, self.seq_start, self.frames)
        return os.path.basename(self.path)

    @classmethod
    def from_info(cls, info) -> "Source":
        """A partir de um `media.MediaInfo` (arquivo com imagem)."""
        return cls(path=info.path, width=info.width, height=info.height, fps=info.fps, fps_str=info.fps_str,
                   frames=info.frames, duration=info.duration, is_image=info.is_image, has_video=True,
                   has_audio=info.has_audio, pix_fmt=info.pix_fmt, bit_depth=info.bit_depth, codec=info.codec,
                   profile=info.profile, bitrate=info.bitrate, color_space=info.color_space,
                   color_range=info.color_range, color_transfer=info.color_transfer,
                   color_primaries=info.color_primaries, audio_codec=info.audio_codec, container=info.container,
                   has_alpha=bool(getattr(info, "has_alpha", False)), seq_start=int(getattr(info, "seq_start", -1)))

    def to_info(self):
        """`media.MediaInfo` equivalente (para o FrameReader e o grab_frame)."""
        from . import media
        return media.MediaInfo(
            path=self.path, width=self.width, height=self.height, fps=self.fps, fps_str=self.fps_str,
            frames=max(1, self.frames), duration=self.duration, pix_fmt=self.pix_fmt, bit_depth=self.bit_depth,
            codec=self.codec, profile=self.profile, bitrate=self.bitrate, color_space=self.color_space,
            color_range=self.color_range, color_transfer=self.color_transfer, color_primaries=self.color_primaries,
            has_audio=self.has_audio, audio_codec=self.audio_codec, container=self.container, is_image=self.is_image,
            has_alpha=self.has_alpha, seq_start=self.seq_start)

    def to_json(self) -> dict[str, Any]:
        out = {"caminho": self.path, "largura": self.width, "altura": self.height, "fps": self.fps_str,
               "quadros": self.frames, "duracao": round(self.duration, 6), "imagem": self.is_image,
               "tem_video": self.has_video, "tem_audio": self.has_audio, "pix_fmt": self.pix_fmt,
               "bits": self.bit_depth, "codec": self.codec, "perfil": self.profile, "taxa": self.bitrate,
               "cor_matriz": self.color_space, "cor_faixa": self.color_range, "cor_transferencia": self.color_transfer,
               "cor_primarias": self.color_primaries, "codec_audio": self.audio_codec, "recipiente": self.container}
        # Campos da 1.5: só quando usados (a fonte de uma montagem antiga grava igual). "alfa" também sai quando
        # o formato de pixel tem alfa e a fonte não usa (a migração do formato 1 deduz pelo formato de pixel).
        from .media import pix_has_alpha
        if self.has_alpha or pix_has_alpha(self.pix_fmt):
            out["alfa"] = self.has_alpha
        if self.kind != SOURCE_FILE:
            out["tipo"] = self.kind
        if self.data:
            out["dados"] = copy.deepcopy(self.data)
        if self.is_sequence:
            out["sequencia"] = {"inicio": self.seq_start}
        return out

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
                   container=str(d.get("recipiente") or ""), has_alpha=d.get("alfa") is True,
                   kind=d.get("tipo") if d.get("tipo") in SOURCE_KINDS else SOURCE_FILE,
                   data=copy.deepcopy(d["dados"]) if isinstance(d.get("dados"), dict) else {},
                   seq_start=_seq_start(d.get("sequencia")))


def _seq_start(value) -> int:
    """"sequencia" do JSON da fonte ({"inicio": n}) → número do primeiro quadro; -1 = não é sequência."""
    try:
        n = int(value.get("inicio")) if isinstance(value, dict) else -1
    except (TypeError, ValueError):
        return -1
    return n if n >= 0 else -1


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
    # Chaves de animação ({ajuste: [keyframes.Key]}), no tempo do clipe τ = t − start + key_off (quadros da
    # sequência; `Sequence.clip_time`). Aparar o começo e dividir mexem só em `key_off` (`shift_head`).
    keys: dict[str, list] = field(default_factory=dict)
    key_off: int = 0

    def __post_init__(self) -> None:
        schema = editparams.SCHEMAS[self.kind]
        self.values = schema.sanitize(self.values)
        self.keys = keyframes.clean_keys(schema, self.keys)
        self.key_off = int(self.key_off)

    def shift_head(self, delta: int) -> None:
        """O começo do clipe andou `delta` quadros com a imagem parada no lugar (aparar o começo, sobrescrever,
        dividir): as chaves ficam onde estavam em relação à imagem."""
        self.key_off += int(delta)

    def rescale_keys(self, ratio: float) -> None:
        """O tempo do clipe esticou `ratio` vezes (velocidade ou fps): as chaves acompanham a imagem."""
        if self.keys:
            self.keys = keyframes.rescale(self.keys, self.key_off, ratio)
        self.key_off = 0

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
        out = {"id": self.id, "tipo": self.kind, "fonte": self.src, "faixa": self.track, "inicio": self.start,
               "duracao": self.dur, "entrada": round(self.src_in, 6), "ligacao": self.link, "nome": self.name,
               "valores": copy.deepcopy(self.values)}
        if self.keys:  # só com animação (o clipe de uma montagem antiga grava igual)
            out["chaves"] = keyframes.to_json(self.keys)
            if self.key_off:
                out["chaves_ref"] = self.key_off
        return out

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
                       values=d.get("valores") if isinstance(d.get("valores"), dict) else {},
                       keys=d.get("chaves") if isinstance(d.get("chaves"), dict) else {},
                       key_off=int(d.get("chaves_ref", 0) or 0))
        except (TypeError, ValueError, OverflowError):
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
    values: dict[str, Any] | None = None  # ajustes neste quadro (`Sequence.values_at`); None = os do clipe


# ------------------------------------------------------------------ marcadores
def _clean_text(v: Any) -> str:
    return str(v if v is not None else "")[:MARKER_TEXT_MAX]


@dataclass
class Marker:
    """Marcador na régua da sequência (quadro da sequência; não pertence a nenhum clipe).

    `chapter` é uma escolha explícita (padrão desligado): marcadores também servem de lembrete
    ("corrigir a cor aqui") e não devem virar capítulo do vídeo sem a pessoa pedir.
    """

    id: str
    frame: int
    color: str = MARKER_COLOR_KEYS[0]
    name: str = ""
    note: str = ""
    chapter: bool = False

    def __post_init__(self) -> None:
        self.frame = max(0, int(self.frame))
        if self.color not in MARKER_COLOR_KEYS:
            self.color = MARKER_COLOR_KEYS[0]
        self.name = _clean_text(self.name)
        self.note = _clean_text(self.note)
        self.chapter = bool(self.chapter)

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "quadro": self.frame, "cor": self.color, "nome": self.name, "nota": self.note,
                "capitulo": self.chapter}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Marker | None":
        try:
            frame = int(d.get("quadro", 0))
        except (TypeError, ValueError, OverflowError):
            return None
        return cls(id=str(d.get("id") or new_id()), frame=frame, color=str(d.get("cor") or ""),
                   name=d.get("nome") or "", note=d.get("nota") or "", chapter=d.get("capitulo") is True)


@dataclass(frozen=True)
class _Span:
    """Um clipe da V1 antes de uma edição (para a faixa principal magnética saber onde a imagem foi parar)."""

    id: str
    start: int
    end: int
    src: str
    src_in: float
    speed: float
    holds: bool   # imagem parada ou quadro congelado: não há tempo de arquivo para acompanhar


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
    markers: list[Marker] = field(default_factory=list)
    micro_fade: bool = False  # fades curtos nas emendas de som (sequências novas ligam; projeto antigo = sem)
    magnetic: bool = False    # faixa principal (V1) magnética: sem buracos (padrão desligado, também em projetos novos)
    # "Fundo transparente": a tela começa transparente em vez da cor do fundo; vale na prévia (xadrez), no "Salvar
    # quadro" em PNG/TIFF e nas exportações com alfa (`export.wants_alpha`). "fundo_transparente" no JSON, só ligado.
    transparent: bool = False

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
        if src.unbounded:  # imagem ou gerador sem fim: começa com IMAGE_SECONDS
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

    def next_on_track(self, clip: Clip) -> Clip | None:
        """Clipe que começa exatamente onde este termina, na mesma faixa."""
        for c in self.clips:
            if c is not clip and c.kind == clip.kind and c.track == clip.track and c.start == clip.end:
                return c
        return None

    def continues(self, a: Clip, b: Clip) -> bool:
        """`b` continua `a` sem emenda: mesma faixa, `b` começa onde `a` termina, mesmo arquivo, do ponto
        exato onde `a` parou e na mesma velocidade (um corte que não foi mexido: não há estalo ali)."""
        if a.kind != b.kind or a.track != b.track or a.end != b.start or a.src != b.src or a.frozen or b.frozen:
            return False
        if abs(a.speed - b.speed) > 1e-9:
            return False
        return abs(a.src_in + a.dur / self.fps * a.speed - b.src_in) < 1e-4

    def audio_crossfade(self, clip: Clip) -> tuple[Clip | None, float, float]:
        """Transição de som (potência constante) entre o clipe anterior da faixa e este, pedida em
        `values["transicao"]` (segundos) no clipe que entra. Devolve (anterior, antes, depois): a parte da
        transição antes do corte (o clipe que entra começa mais cedo, com o arquivo antes do ponto de
        entrada) e depois dele (o que sai continua, com o arquivo depois do ponto de saída).

        Centrada no corte; se um lado não tem sobra de arquivo, o outro fica com o resto, e sem sobra
        nenhuma ela encolhe até zero. Cada lado usa no máximo metade do clipe, para não encostar numa
        transição da outra ponta. Sem clipe anterior colado na faixa: (None, 0, 0).
        """
        d = float(clip.values.get("transicao", 0.0)) if clip.kind == AUDIO else 0.0
        prev = self.previous_on_track(clip) if d > 0 else None
        if prev is None:
            return None, 0.0, 0.0
        fps = self.fps
        head = clip.src_in / clip.speed  # arquivo antes da entrada do que entra (s da sequência)
        src = self.sources.get(prev.src)
        tail = 0.0                       # arquivo depois da saída do que sai
        if src is not None:
            tail = max(0.0, src.length - (prev.src_in + prev.dur / fps * prev.speed)) / prev.speed
        room_a, room_b = prev.dur / fps / 2, clip.dur / fps / 2
        before = min(d / 2, head, room_a)
        after = min(d - before, tail, room_b)
        before = min(d - after, head, room_a)
        return prev, max(0.0, before), max(0.0, after)

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
                        out.append(Layer(prev, self.src_frame(prev, t), 1.0, extension=True,
                                         values=self.values_at(prev, t)))
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
            out.append(Layer(c, self.src_frame(c, t), alpha, color, fade, values=self.values_at(c, t)))
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
                     with_audio: bool = True, insert: bool = False) -> list[Clip]:
        """Põe um arquivo na sequência (vídeo + som ligado). `at=None` coloca no fim da faixa.

        Por padrão sobrescreve o que estiver no lugar; com `insert` (e um ponto `at`) abre o espaço antes
        (`open_space`): o que vem depois anda para a direita."""
        self.add_source(src)
        dur = self.default_dur(src)
        if insert and at is not None:
            targets = set()
            if src.has_video:
                targets.add((VIDEO, vtrack))
            if src.has_audio and with_audio:
                targets.add((AUDIO, atrack))
            self.open_space(max(0, int(at)), dur, targets, all_tracks=not self.magnet_active)
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
                c.shift_head(cut)

    def _cut(self, c: Clip, t: int) -> Clip:
        """Divide o clipe no quadro t; devolve a parte da direita (já na sequência)."""
        right = Clip(new_id(), c.kind, c.src, c.track, t, c.end - t, self.src_time(c, t), "", c.name,
                     copy.deepcopy(c.values), copy.deepcopy(c.keys), c.key_off + (t - c.start))
        c.dur = t - c.start
        # A transição de entrada fica só na parte da esquerda; a de saída, só na da direita.
        if c.kind == VIDEO:
            right.values["entrada_tipo"] = "corte"
            c.values["saida_tipo"] = "corte"
        else:
            right.values["fade_in"] = 0.0
            right.values["transicao"] = 0.0  # a transição de som fica com o corte de entrada (da esquerda)
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
        # Par ligado com entrada/saída diferentes (corte J/L): o ligado que não foi dividido e fica inteiro
        # depois do ponto vai com as partes da direita (os de antes continuam com as da esquerda).
        for c in self.clips:
            if c.link in new_links and c.start >= t:
                c.link = new_links[c.link]
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
            c.shift_head(delta)
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
        if len({(c.start, c.dur) for c in group}) > 1:
            self._set_speed_offset(group, self.find(cid), speed)  # corte J/L: as diferenças acompanham
            return
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
            if abs(c.speed - speed) > 1e-12:
                c.rescale_keys(c.speed / speed)  # a animação acompanha a imagem
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
        if free_everywhere:
            # O tempo da sequência encolheu: os marcadores depois do trecho andam junto e os de dentro
            # ficam no ponto do corte (nada some sem a pessoa pedir).
            for mk in self.markers:
                if mk.frame >= b:
                    mk.frame -= (b - a)
                elif mk.frame > a:
                    mk.frame = a

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

    # -------------------------------------------------------- ferramentas de corte: inserir
    def _holds(self, c: Clip) -> bool:
        """Imagem parada ou quadro congelado (não há tempo de arquivo para acompanhar)."""
        src = self.sources.get(c.src)
        return src is None or src.is_image or c.frozen

    def _head_room(self, c: Clip) -> int:
        """Quadros de arquivo antes da entrada do clipe (o quanto o começo pode voltar)."""
        if self._holds(c):
            return self.frames_for(MAX_HOLD_SECONDS)
        return max(0, int(math.floor(c.src_in / c.speed * self.fps + EPS)))

    def open_space(self, t: int, d: int, targets: Iterable[tuple[str, int]] = (), exclude: Iterable[str] = (),
                   all_tracks: bool = True, split: bool = True) -> None:
        """Abre `d` quadros no quadro `t` (edição de inserir).

        - Nas faixas-alvo (`targets`, pares (tipo, faixa)) o clipe que atravessa `t` é dividido ali (com os
          ligados), menos quando ele anda junto com um ligado que começa depois do ponto (corte J/L);
          `split=False` não divide nada (só empurra).
        - Tudo o que começa em `t` ou depois anda `d` para a direita — em todas as faixas destravadas
          (`all_tracks`, para nada sair de sincronia) ou só nas faixas-alvo — e os ligados vão junto.
        - O que atravessa `t` nas outras faixas (uma música de fundo, um título longo) continua inteiro.
        - Faixas travadas e os clipes de `exclude` não mudam. Com `all_tracks`, os marcadores a partir do
          ponto andam junto quando nenhum clipe travado ficou para trás depois dele. `all_tracks=False` é para
          a faixa principal magnética, que acerta o resto depois (`settle_main`).
        """
        t, d = max(0, int(t)), int(d)
        if d <= 0:
            return
        skip = set(exclude)
        targets = set(targets)

        def eligible(c: Clip) -> bool:
            return c.id not in skip and not self.locked(c) and (all_tracks or (c.kind, c.track) in targets)

        def with_links(ids: set[str]) -> set[str]:
            out = set(ids)
            for c in self.clips:
                if c.id in ids and c.link:
                    out.update(g.id for g in self.group(c) if g.id not in skip and not self.locked(g))
            return out

        movers = with_links({c.id for c in self.clips if eligible(c) and c.start >= t})
        if split:
            crossing = [c.id for c in self.clips if c.id not in skip and c.id not in movers and not self.locked(c)
                        and (c.kind, c.track) in targets and c.start < t < c.end]
            if crossing:
                movers |= with_links(set(self.split(t, crossing)))
        early = []
        for c in self.clips:
            if c.id in movers:
                if c.start < t:
                    early.append(c)
                c.start += d
        if not all_tracks:
            return
        for c in early:  # um ligado que começava antes do ponto (corte J/L) não cobre o que ficou parado
            self._clear_range(c.kind, c.track, c.start, c.end, movers | skip)
        if not any(self.locked(c) and c.start >= t for c in self.clips):
            for mk in self.markers:
                if mk.frame >= t:
                    mk.frame += d

    def move_insert(self, cid: str, new_start: int, new_track: int | None = None) -> int:
        """Move inserindo: no destino o resto abre espaço (`open_space`) em vez de ser coberto; o lugar de onde
        o clipe saiu fica vazio (na faixa principal magnética, ele se fecha). Devolve o deslocamento."""
        group = self._group_for_edit(cid)
        clip = self.find(cid)
        if not group or clip not in group:
            return 0
        delta = max(int(new_start) - clip.start, -min(c.start for c in group))
        track = clip.track
        if new_track is not None and 0 <= new_track != clip.track:
            self.ensure_track(clip.kind, new_track)
            tr = self.track(clip.kind, new_track)
            if tr is not None and not tr.locked:
                track = new_track
        if not delta and track == clip.track:
            return 0
        lo = min(c.start for c in group)
        span = max(c.end for c in group) - lo
        targets = {(c.kind, track if c is clip else c.track) for c in group}
        self.open_space(lo + delta, span, targets, exclude={c.id for c in group}, all_tracks=not self.magnet_active)
        return self.move(cid, clip.start + delta, track if track != clip.track else None)

    # -------------------------------------------------------- ferramentas de corte: aparar só um, Q/W
    def trim_start_only(self, cid: str, new_start: int) -> int:
        """Apara o começo só deste clipe, sem o ligado (Alt ao arrastar a borda): o som pode começar antes ou
        depois da imagem (corte J/L). Cobre o vizinho da faixa, como qualquer aparar."""
        c = self.find(cid)
        if c is None:
            return 0
        link, c.link = c.link, ""
        try:
            return self.trim_start(cid, new_start)
        finally:
            c.link = link

    def trim_end_only(self, cid: str, new_end: int) -> int:
        """Apara o fim só deste clipe, sem o ligado (o som pode continuar depois da imagem: corte L)."""
        c = self.find(cid)
        if c is None:
            return 0
        link, c.link = c.link, ""
        try:
            return self.trim_end(cid, new_end)
        finally:
            c.link = link

    def trim_target(self, frame: int, prefer: tuple[str, int] | None = None) -> Clip | None:
        """Clipe que Q/W aparam: o que está sob o cursor na faixa preferida (a do clipe selecionado); senão o da
        faixa destravada mais de cima (V mais alta → V1 → A1 → …). O cursor precisa estar dentro do clipe (num
        corte não há o que aparar)."""
        frame = int(frame)

        def under(kind: str, idx: int) -> Clip | None:
            tr = self.track(kind, idx)
            if tr is None or tr.locked:
                return None
            return next((c for c in self.clips_on(kind, idx) if c.start < frame < c.end), None)

        if prefer is not None:
            got = under(*prefer)
            if got is not None:
                return got
        order = [(VIDEO, i) for i in reversed(range(len(self.kind_tracks(VIDEO))))]
        order += [(AUDIO, i) for i in range(len(self.kind_tracks(AUDIO)))]
        for kind, idx in order:
            got = under(kind, idx)
            if got is not None:
                return got
        return None

    def _pull(self, thresholds: dict[tuple[str, int], int], a: int, b: int, n: int, group: set[str]) -> None:
        """Fecha `n` quadros depois de aparar: nas faixas do grupo, o que começa a partir do limiar da faixa anda
        para a esquerda; nas outras, só se o trecho [a, b) ficou livre em todas as faixas (como em "Excluir e
        fechar o espaço") — e então os marcadores andam junto."""
        free = not any(c.id not in group and c.start < b and c.end > a for c in self.clips)
        for c in self.clips:
            if self.locked(c):
                continue
            key = (c.kind, c.track)
            if key in thresholds:
                if c.start >= thresholds[key]:
                    c.start -= n
            elif free and c.start >= b:
                c.start -= n
        if free:
            for mk in self.markers:
                if mk.frame >= b:
                    mk.frame -= n
                elif mk.frame > a:
                    mk.frame = a

    def ripple_trim_start(self, cid: str, frame: int) -> int:
        """Q: tira o começo do clipe (e dos ligados) até `frame` e fecha o espaço — o clipe e o que vem depois
        andam para a esquerda. Devolve os quadros tirados."""
        clip = self.find(cid)
        group = self._group_for_edit(cid)
        if clip is None or clip not in group or not clip.start < int(frame) < clip.end:
            return 0
        a = clip.start
        n = self.trim_start(cid, int(frame))
        if n <= 0:
            return 0
        if not self._magnet_owns(group):  # na V1 magnética a faixa se fecha sozinha (settle_main)
            starts: dict[tuple[str, int], int] = {}
            for c in group:
                starts[(c.kind, c.track)] = min(starts.get((c.kind, c.track), c.start), c.start)
            self._pull(starts, a, clip.start, n, {c.id for c in group})
        return n

    def ripple_trim_end(self, cid: str, frame: int) -> int:
        """W: tira o fim do clipe (e dos ligados) a partir de `frame` e fecha o espaço — o que vem depois anda
        para a esquerda. Devolve os quadros tirados."""
        clip = self.find(cid)
        group = self._group_for_edit(cid)
        if clip is None or clip not in group or not clip.start < int(frame) < clip.end:
            return 0
        b = clip.end
        ends: dict[tuple[str, int], int] = {}
        for c in group:
            ends[(c.kind, c.track)] = min(ends.get((c.kind, c.track), c.end), c.end)
        n = -self.trim_end(cid, int(frame))
        if n <= 0:
            return 0
        if not self._magnet_owns(group):
            self._pull(ends, clip.end, b, n, {c.id for c in group})
        return n

    # -------------------------------------------------------- ferramentas de corte: cortes J e L
    def cut_pair(self, clip: Clip, left: bool) -> tuple[Clip, Clip, Clip, Clip] | None:
        """O corte entre dois pares imagem + som ligados, encostados na mesma faixa de vídeo e na mesma de som:
        (imagem e som da esquerda, imagem e som da direita). `clip` é qualquer um dos dois do par; `left` escolhe
        o corte do começo do par (True) ou o do fim. None se ali não há um corte assim (ou se algo está travado).
        """
        def pair(c: Clip | None) -> tuple[Clip, Clip] | None:
            if c is None or not c.link:
                return None
            g = self.group(c)
            vs = [x for x in g if x.kind == VIDEO]
            aus = [x for x in g if x.kind == AUDIO]
            return (vs[0], aus[0]) if len(vs) == 1 and len(aus) == 1 and len(g) == 2 else None

        me = pair(clip)
        if me is None:
            return None
        other = pair(self.previous_on_track(me[0]) if left else self.next_on_track(me[0]))
        if other is None:
            return None
        (pv, pa), (nv, na) = (other, me) if left else (me, other)
        if pa.track != na.track or pa.end != na.start or any(self.locked(x) for x in (pv, pa, nv, na)):
            return None
        return pv, pa, nv, na

    def split_edit(self, cid: str, left: bool, offset: int) -> int | None:
        """Corte J (`offset` < 0: o som da direita começa antes do corte da imagem) ou corte L (`offset` > 0: o
        som da esquerda continua depois dele), com o corte do som a `offset` quadros do corte da imagem; 0 alinha
        de novo. O corte do som rola (um som cresce e o vizinho encolhe) e a imagem não muda. Limitado pelo
        arquivo que sobra além do corte e por 1 quadro de cada som. Devolve o deslocamento que coube, ou None se
        ali não há um corte entre dois pares ligados (`cut_pair`)."""
        c = self.find(cid)
        pair = self.cut_pair(c, left) if c is not None else None
        if pair is None:
            return None
        _pv, pa, nv, na = pair
        here = na.start
        target = nv.start + int(offset)
        if target < here:
            target = max(target, here - self._head_room(na), pa.start + 1)
            if target < here:
                self.trim_start_only(na.id, target)
        elif target > here:
            target = min(target, here + max(0, self.max_dur(pa) - pa.dur), na.end - 1)
            if target > here:
                self.trim_end_only(pa.id, target)
        return na.start - nv.start

    def _set_speed_offset(self, group: list[Clip], clip: Clip | None, speed: float) -> None:
        """Velocidade de um par ligado com entrada ou saída diferentes (corte J/L): a imagem (ou o clipe pedido)
        fica no lugar e as diferenças de começo e de fim mudam na proporção, para o som continuar em sincronia
        com a imagem; o fim de todos encolhe junto se o arquivo acabar ou se encostar no clipe seguinte."""
        anchor = next((c for c in group if c.kind == VIDEO), clip or group[0])
        ratio = anchor.speed / speed
        a0 = anchor.start
        ids = {c.id for c in group}
        plan: dict[str, tuple[int, int]] = {}
        cut = 0
        for c in group:
            ns = max(0, a0 + int(round((c.start - a0) * ratio)))
            ne = max(ns + 1, a0 + int(round((c.end - a0) * ratio)))
            lim = ne
            nxt = min((o.start for o in self.clips_on(c.kind, c.track) if o.id not in ids and o.start >= c.end),
                      default=None)
            if nxt is not None:
                lim = min(lim, max(nxt, ns + 1))
            if not self._holds(c):
                left = max(0.0, self.sources[c.src].length - c.src_in)
                lim = min(lim, ns + max(1, int(math.floor(left / speed * self.fps + EPS))))
            plan[c.id] = (ns, ne)
            cut = max(cut, ne - lim)
        for c in group:
            ns, ne = plan[c.id]
            if abs(c.speed - speed) > 1e-12:
                c.rescale_keys(c.speed / speed)  # a animação acompanha a imagem, como em set_speed
            c.values["velocidade"] = speed
            c.start = ns
            c.dur = max(1, ne - cut - ns)
        for c in group:
            self._clear_range(c.kind, c.track, c.start, c.end, ids)

    # -------------------------------------------------------- faixa principal magnética
    @property
    def magnet_active(self) -> bool:
        """A faixa principal magnética está valendo (ligada e com a V1 destravada)."""
        tr = self.track(VIDEO, 0)
        return self.magnetic and not (tr is not None and tr.locked)

    def _magnet_owns(self, group: Iterable[Clip]) -> bool:
        """A edição deste grupo mexe na V1 magnética (então a V1 se acerta sozinha depois)."""
        return self.magnet_active and any(c.kind == VIDEO and c.track == 0 for c in group)

    def room_for_start(self, cid: str, new_start: int) -> int:
        """V1 magnética: alongar o começo de um clipe da V1 não cobre o clipe de antes — o clipe fica no lugar,
        mostra mais do arquivo e empurra o resto. Abre o espaço e devolve até onde aparar o começo."""
        clip = self.find(cid)
        group = self._group_for_edit(cid)
        new_start = int(new_start)
        if clip is None or clip not in group or new_start >= clip.start or not self._magnet_owns(group):
            return new_start
        d = min([clip.start - new_start] + [self._head_room(c) for c in group])
        here = clip.start
        if d > 0:
            self.open_space(here, d, {(c.kind, c.track) for c in group}, all_tracks=False, split=False)
        return here

    def room_for_end(self, cid: str, new_end: int) -> None:
        """V1 magnética: alongar o fim de um clipe da V1 empurra o que vem depois (em vez de cobrir)."""
        clip = self.find(cid)
        group = self._group_for_edit(cid)
        if clip is None or clip not in group or int(new_end) <= clip.end or not self._magnet_owns(group):
            return
        d = min([int(new_end) - clip.end] + [self.max_dur(c) - c.dur for c in group])
        if d > 0:
            self.open_space(clip.end, d, {(c.kind, c.track) for c in group}, exclude={c.id for c in group},
                            all_tracks=False, split=False)

    def room_for_speed(self, cid: str, speed: float) -> None:
        """V1 magnética: deixar um clipe da V1 mais lento (mais longo) empurra o que vem depois."""
        clip = self.find(cid)
        group = self._group_for_edit(cid)
        if clip is None or clip not in group or not self._magnet_owns(group):
            return
        p = editparams.VIDEO.params["velocidade"]
        speed = min(max(float(speed), p.min), p.max)
        main = next(c for c in group if c.kind == VIDEO and c.track == 0)
        want = max(1, int(round(main.dur * main.speed / speed)))
        if not self._holds(main):
            left = max(0.0, self.sources[main.src].length - main.src_in)
            want = min(want, max(1, int(math.floor(left / speed * self.fps + EPS))))
        if want > main.dur:
            self.open_space(main.end, want - main.dur, {(c.kind, c.track) for c in group},
                            exclude={c.id for c in group}, all_tracks=False, split=False)

    def _snapshot(self) -> dict[str, Any]:
        return {"clips": {c.id: (c.kind, c.track, c.start, c.dur, c.src_in) for c in self.clips},
                "main": [_Span(c.id, c.start, c.end, c.src, c.src_in, c.speed, self._holds(c))
                         for c in self.clips_on(VIDEO, 0)],
                "markers": {m.id: m.frame for m in self.markers}}

    @contextmanager
    def keep_main(self):
        """Bloco de edição: com a faixa principal magnética, no fim a V1 fica sem buracos e o resto acompanha
        (`settle_main`). Sem ela, não faz nada."""
        snap = self._snapshot() if self.magnet_active else None
        yield
        if snap is not None:
            self.settle_main(snap)

    def settle_main(self, snap: dict[str, Any] | None = None) -> None:
        """Faixa principal magnética (regra completa em docs/ARQUITETURA.md, seção 13.1):

        1. a V1 fica de ponta a ponta desde o quadro 0, na mesma ordem; o que é ligado a ela anda junto;
        2. cada clipe das outras faixas (com os ligados a ele) que a edição não mexeu acompanha a imagem da V1
           que estava sob o começo dele (`_main_warp`); se essa imagem sumiu, vai para o ponto do corte. O que a
           edição mexeu (arrastou, aparou, acabou de entrar) fica onde ela deixou;
        3. ninguém cobre ninguém: se o lugar estiver ocupado, o clipe anda para a direita até caber;
        4. os marcadores que a edição não mexeu acompanham a V1 do mesmo jeito.

        Faixas travadas não mudam; com a V1 travada nada acontece (a faixa espera). `snap` é o estado de antes
        da edição (`_snapshot`); sem ele, só acerta a montagem atual (ao ligar a faixa magnética)."""
        if not self.magnet_active:
            return
        snap = snap if snap is not None else self._snapshot()
        before = snap["clips"]
        order = {c.id: i for i, c in enumerate(self.clips)}
        main = [c for c in self.clips if c.kind == VIDEO and c.track == 0]
        main_groups: set[str] = set()
        for c in main:
            main_groups.update(g.id for g in self.group(c))
        units: list[list[Clip]] = []
        seen: set[str] = set()
        for c in self.clips:
            if c.id in main_groups or c.id in seen:
                continue
            members = self.group(c)
            seen.update(g.id for g in members)
            if not any(self.locked(g) for g in members):
                units.append(members)
        unit_ids = {g.id for u in units for g in u}
        self.clips = [c for c in self.clips if c.id not in unit_ids]
        # 1) V1 de ponta a ponta; os ligados a ela andam o mesmo que o primeiro clipe da V1 do grupo.
        shift: dict[str, int] = {}
        pos = 0
        for c in sorted(main, key=lambda c: (c.start, order[c.id])):
            shift[c.id] = pos - c.start
            c.start = pos
            pos = c.end
        moved = []
        for c in self.clips:
            if c.id in main_groups and c.id not in shift and not self.locked(c):
                firsts = [g for g in self.group(c) if g.id in shift]
                d = shift[min(firsts, key=lambda g: g.start).id] if firsts else 0
                if d:
                    c.start = max(0, c.start + d)
                    moved.append(c)
        for c in moved:
            self._clear_range(c.kind, c.track, c.start, c.end, {g.id for g in self.group(c)})
        # 2) e 3) os conectados: primeiro o que a edição mexeu (fica onde ela deixou), depois o resto, na ordem
        # de onde vai ficar.
        warp = self._main_warp(snap["main"], set(before))
        plans = []
        for members in units:
            p0 = min(g.start for g in members)
            untouched = all(before.get(g.id) == (g.kind, g.track, g.start, g.dur, g.src_in) for g in members)
            d = warp(p0) - p0 if untouched else 0
            plans.append((untouched, p0 + d, p0, members, d))
        plans.sort(key=lambda x: (x[0], x[1], x[2]))
        for _untouched, _want, p0, members, d in plans:
            d = self._fit_shift(members, max(d, -p0))
            for g in members:
                g.start += d
            self.clips.extend(members)
        self.clips.sort(key=lambda c: order.get(c.id, len(order)))
        # 4) marcadores
        marks = snap["markers"]
        for mk in self.markers:
            if marks.get(mk.id) == mk.frame:
                mk.frame = max(0, warp(mk.frame))

    def _fit_shift(self, members: list[Clip], d: int) -> int:
        """O menor deslocamento a partir de `d` que põe os clipes sem cobrir nada nas faixas deles."""
        ids = {g.id for g in members}
        while True:
            need = d
            for g in members:
                a, b = g.start + d, g.end + d
                for o in self.clips:
                    if o.id not in ids and o.kind == g.kind and o.track == g.track and o.start < b and o.end > a:
                        need = max(need, o.end - g.start)
            if need == d:
                return d
            d = need

    def _main_warp(self, spans: list[_Span], known: set[str]):
        """f(p): onde foi parar, depois da edição, a imagem que a V1 mostrava no quadro p antes dela.

        Acompanha o conteúdo (o arquivo e o instante dentro dele), então vale para mover, dividir, aparar,
        inserir e mudar a velocidade: procura o mesmo clipe, ou uma parte nova (divisão, clipe inserido), que
        mostre o mesmo instante do mesmo arquivo. Imagem parada e quadro congelado acompanham o próprio clipe.
        Imagem que sumiu (apagada, aparada) leva ao ponto do corte; um buraco da V1 também (ele se fechou);
        depois do fim da V1, a distância até o fim fica."""
        fps = self.fps
        after = self.clips_on(VIDEO, 0)
        by_id = {c.id: c for c in after}
        fresh = [c for c in after if c.id not in known]

        def cut_after(i: int) -> int:
            for j in range(i, -1, -1):
                c = by_id.get(spans[j].id)
                if c is not None:
                    return c.end
            return 0

        def shows(c: Clip, tau: float) -> int | None:
            if self._holds(c):
                return None
            k = int(math.floor((tau - c.src_in) * fps / c.speed + 1e-6))
            return c.start + k if 0 <= k < c.dur else None

        def f(p: int) -> int:
            if not spans:
                return p
            idx = next((i for i, s in enumerate(spans) if s.start <= p < s.end), None)
            if idx is None:
                prev = [i for i, s in enumerate(spans) if s.end <= p]
                if not prev:
                    return 0
                if prev[-1] == len(spans) - 1:
                    return cut_after(prev[-1]) + (p - spans[-1].end)
                return cut_after(prev[-1])
            s = spans[idx]
            same = by_id.get(s.id)
            if s.holds:
                if same is None:
                    return cut_after(idx - 1)
                off = p - s.start
                return same.start + off if off < same.dur else same.end
            tau = s.src_in + (p - s.start) / fps * s.speed
            if same is not None and same.src == s.src:
                got = shows(same, tau)
                if got is not None:
                    return got
            best = None
            for c in fresh:
                got = shows(c, tau) if c.src == s.src else None
                if got is not None and (best is None or abs(got - p) < abs(best - p)):
                    best = got
            if best is not None:
                return best
            if same is not None:
                return same.start if tau < same.src_in else same.end
            return cut_after(idx - 1)

        return f

    # -------------------------------------------------------- marcadores
    def marker(self, mid: str) -> Marker | None:
        return next((m for m in self.markers if m.id == mid), None)

    def sorted_markers(self) -> list[Marker]:
        return sorted(self.markers, key=lambda m: (m.frame, m.id))

    def chapters(self) -> list[Marker]:
        """Marcadores marcados como capítulo, em ordem de tempo."""
        return [m for m in self.sorted_markers() if m.chapter]

    def add_marker(self, frame: int, name: str = "", color: str | None = None, note: str = "",
                   chapter: bool = False) -> Marker:
        """Marcador no quadro; se já existe um ali, devolve o que existe (não duplica)."""
        frame = max(0, int(frame))
        old = next((m for m in self.markers if m.frame == frame), None)
        if old is not None:
            return old
        mk = Marker(new_id(), frame, color or MARKER_COLOR_KEYS[0], name, note, chapter)
        self.markers.append(mk)
        return mk

    def update_marker(self, mid: str, **fields: Any) -> bool:
        """Muda campos de um marcador (frame, color, name, note, chapter). True se mudou algo."""
        mk = self.marker(mid)
        if mk is None:
            return False
        before = mk.to_json()
        for k, v in fields.items():
            if k not in ("frame", "color", "name", "note", "chapter"):
                raise KeyError(k)
            setattr(mk, k, v)
        mk.__post_init__()
        return mk.to_json() != before

    def move_marker(self, mid: str, frame: int) -> bool:
        return self.update_marker(mid, frame=frame)

    def remove_marker(self, mid: str) -> bool:
        n = len(self.markers)
        self.markers = [m for m in self.markers if m.id != mid]
        return len(self.markers) != n

    def next_marker(self, frame: int) -> Marker | None:
        """Primeiro marcador depois do quadro."""
        return next((m for m in self.sorted_markers() if m.frame > frame), None)

    def previous_marker(self, frame: int) -> Marker | None:
        """Último marcador antes do quadro."""
        before = [m for m in self.sorted_markers() if m.frame < frame]
        return before[-1] if before else None

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

    # -------------------------------------------------------- chaves de animação (keyframes.py)
    def clip_time(self, clip: Clip, t: float) -> float:
        """Tempo das chaves do clipe no quadro t da sequência (τ = t − start + key_off)."""
        return t - clip.start + clip.key_off

    def seq_time(self, clip: Clip, tau: float) -> float:
        """Quadro da sequência de um tempo de chave do clipe (o inverso de `clip_time`)."""
        return tau - clip.key_off + clip.start

    def values_at(self, clip: Clip, t: float) -> dict[str, Any]:
        """Ajustes do clipe no quadro t: o único lugar onde as chaves viram valores (imagem e som).
        Sem chaves, devolve o próprio `clip.values`."""
        if not clip.keys:
            return clip.values
        return keyframes.values_at(editparams.SCHEMAS[clip.kind], clip.values, clip.keys, self.clip_time(clip, t))

    def keys_of(self, clip: Clip, key: str) -> list[tuple[float, Any, str]]:
        """Chaves de um ajuste do clipe em quadros da sequência: [(quadro, valor, curva)]."""
        return [(self.seq_time(clip, k.t), keyframes._copy(k.v), k.e) for k in clip.keys.get(key, [])]

    def _animatable(self, clip: Clip, key: str):
        p = keyframes.animatable(editparams.SCHEMAS[clip.kind]).get(key)
        if p is None:
            raise KeyError(key)
        return p

    def set_key(self, cid: str, key: str, t: float, value: Any = None, easing: str = keyframes.LINEAR) -> bool:
        """Chave no quadro t da sequência (`value` None = o valor que o ajuste tem ali). True se mudou."""
        from .params import _clean
        c = self.find(cid)
        if c is None or self.locked(c):
            return False
        p = self._animatable(c, key)
        if value is None:
            value = self.values_at(c, t)[key]
        track = keyframes.set_key(c.keys.get(key), float(self.clip_time(c, t)), _clean(p, value), easing)
        return self._set_track(c, key, track)

    def remove_key(self, cid: str, key: str, t: float) -> bool:
        c = self.find(cid)
        if c is None or self.locked(c):
            return False
        return self._set_track(c, key, keyframes.remove_key(c.keys.get(key), float(self.clip_time(c, t))))

    def move_key(self, cid: str, key: str, t_from: float, t_to: float) -> bool:
        c = self.find(cid)
        if c is None or self.locked(c):
            return False
        track = keyframes.move_key(c.keys.get(key), float(self.clip_time(c, t_from)), float(self.clip_time(c, t_to)))
        return self._set_track(c, key, track)

    def clear_keys(self, cid: str, key: str | None = None) -> bool:
        """Tira as chaves de um ajuste (ou todas, com `key` None); o valor fixo do ajuste volta a valer."""
        c = self.find(cid)
        if c is None or self.locked(c) or not c.keys:
            return False
        if key is None:
            c.keys = {}
        elif key in c.keys:
            c.keys = {k: v for k, v in c.keys.items() if k != key}
        else:
            return False
        return True

    def _set_track(self, c: Clip, key: str, track: list) -> bool:
        if track == c.keys.get(key, []):
            return False
        keys = dict(c.keys)
        if track:
            keys[key] = track
        else:
            keys.pop(key, None)
        c.keys = keys
        return True

    def local_keys(self, clip: Clip, names: Iterable[str] | None = None) -> dict[str, list]:
        """Chaves no tempo a partir do começo do clipe (para copiar para outro clipe: `paste_keys`)."""
        keys = clip.keys if names is None else keyframes.keys_in(clip.keys, names)
        return keyframes.shift(keys, -clip.key_off)

    def paste_keys(self, cid: str, local: dict[str, list], names: Iterable[str]) -> bool:
        """Troca as chaves dos ajustes `names` do clipe pelas de `local` (de `local_keys`), presas ao começo
        deste clipe. Ajustes de `names` sem chave em `local` ficam sem animação."""
        c = self.find(cid)
        if c is None or self.locked(c):
            return False
        names = set(names)
        keys = {k: v for k, v in c.keys.items() if k not in names}
        keys.update(keyframes.shift(keyframes.keys_in(local, names), c.key_off))
        keys = keyframes.clean_keys(editparams.SCHEMAS[c.kind], keys)
        if keys == c.keys:
            return False
        c.keys = keys
        return True

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
        if src is None or v.start != 0 or v.src_in > EPS or not editparams.is_neutral(VIDEO, v.values) or v.keys:
            return None
        if not src.is_file:  # clipe sem arquivo (gerador, texto…): não há o que ler direto
            return None
        if self.transparent:  # "Fundo transparente" é uma escolha da montagem (o projeto precisa guardá-la)
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
                    or not editparams.is_neutral(AUDIO, a.values) or a.keys or not self.has_audio):
                return None
            if any(abs(t.volume) > 1e-9 for t in self.kind_tracks(AUDIO)):
                return None
        elif src.has_audio:
            return None
        return src.path

    def direct_file(self) -> str | None:
        """O arquivo que o modo Película lê direto, sem montar: o de `is_trivial`, se ele não tem transparência
        (com alfa a imagem passa pela montagem e sai sobre o fundo dela; lido direto, o alfa se perderia). Um
        arquivo com alfa sem mudanças continua "sem edição" para o projeto (`is_trivial`)."""
        path = self.is_trivial()
        src = self.sources.get(path) if path else None
        # Sequência de imagens também passa pela montagem: a velocidade dela (escolhida ao importar) só existe na
        # fonte da montagem, não no arquivo.
        return path if src is not None and not src.has_alpha and not src.is_sequence else None

    def copy(self) -> "Sequence":
        return Sequence.from_json(self.to_json())

    def features(self) -> set[str]:
        """Recursos da 1.5 que esta montagem usa (`FEATURES`): com algum, o projeto vai para o formato 3."""
        return {fid for fid, check in FEATURES.items() if check(self)}

    def used_sources(self) -> list[Source]:
        """As fontes que algum clipe usa (na ordem de `sources`)."""
        used = {c.src for c in self.clips}
        return [s for p, s in self.sources.items() if p in used]

    def to_json(self) -> dict[str, Any]:
        used = {c.src for c in self.clips}
        out = {
            "formato": FORMAT if self.features() else FORMAT_BASE,
            "largura": self.width, "altura": self.height, "fps": self.fps_str, "nome": self.name,
            "fundo": [float(x) for x in self.background],
            "faixas": [t.to_json() for t in self.tracks],
            "fontes": [s.to_json() for p, s in self.sources.items() if p in used],
            "clipes": [c.to_json() for c in sorted(self.clips, key=lambda c: (c.kind, c.track, c.start))],
        }
        # Campos opcionais: só aparecem quando usados (o JSON de uma montagem antiga não muda, e versões
        # antigas do app ignoram chaves que não conhecem).
        if self.markers:
            out["marcadores"] = [m.to_json() for m in self.sorted_markers()]
        if self.micro_fade:
            out["micro_fades"] = True
        if self.magnetic:
            out["faixa_magnetica"] = True
        if self.transparent:
            out["fundo_transparente"] = True
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any] | None) -> "Sequence":
        """Montagem a partir do JSON de `to_json` (de qualquer formato até `FORMAT`: passa por `migrate`).
        `FormatError` se o bloco foi gravado por uma versão mais nova."""
        d = migrate(d if isinstance(d, dict) else {})
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
                  background=bg, tracks=tracks, micro_fade=d.get("micro_fades") is True,
                  magnetic=d.get("faixa_magnetica") is True, transparent=d.get("fundo_transparente") is True)
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
        seen: set[str] = set()
        raw = d.get("marcadores")
        for md in raw if isinstance(raw, list) else []:
            mk = Marker.from_json(md) if isinstance(md, dict) else None
            if mk is None or mk.id in seen:
                continue
            seen.add(mk.id)
            seq.markers.append(mk)
        return seq

    def relink(self, old: str, new: str, seq_start: int | None = None) -> None:
        """Troca o caminho de um arquivo (projeto aberto em outro computador ou pasta). Fontes sem arquivo
        (`Source.is_file` falso) não mudam. Numa sequência de imagens, `new` é o padrão novo e `seq_start` o
        número do primeiro quadro na pasta nova (None = o mesmo)."""
        if old not in self.sources or not self.sources[old].is_file:
            return
        if seq_start is not None and self.sources[old].is_sequence:
            self.sources[old].seq_start = max(0, int(seq_start))
        if old == new:
            return
        src = self.sources.pop(old)
        src.path = new
        self.sources[new] = src
        for c in self.clips:
            if c.src == old:
                c.src = new

    @classmethod
    def for_source(cls, src: Source, with_media: bool = True) -> "Sequence":
        """Sequência nova no formato do arquivo (resolução e fps), já com ele dentro se `with_media`."""
        w, h = (src.width, src.height) if src.has_video and src.width and src.height else (1920, 1080)
        fps = src.fps_str if (src.has_video and not src.is_image) else "24/1"
        seq = cls(width=w, height=h, fps_str=fps, micro_fade=True)
        if with_media:
            seq.insert_media(src, 0)
        return seq


# ------------------------------------------------------------------ formato do bloco "edicao" (1.5)
class FormatError(ValueError):
    """Montagem gravada por uma versão mais nova do app (o bloco "edicao" tem `formato` maior que `FORMAT`)."""


# Recursos da 1.5 que uma montagem pode usar: id ASCII (nunca renomear) → teste. Usar qualquer um grava o
# bloco "edicao" no formato 2 e o projeto no formato 3 (`project.needed_format`), que as versões antigas
# recusam com aviso em vez de abrir sem o recurso. Recurso novo: uma linha aqui (ou `FEATURES[id] = teste`
# no módulo do recurso) e o campo dele no JSON só quando usado.
FEATURES: dict[str, Callable[[Sequence], bool]] = {
    "alfa": lambda seq: any(s.has_alpha for s in seq.used_sources()),
    "chaves": lambda seq: any(c.keys for c in seq.clips),
    "gerador": lambda seq: any(not s.is_file for s in seq.used_sources()),
    "sequencia_imagens": lambda seq: any(s.is_sequence for s in seq.used_sources()),
    "fundo_transparente": lambda seq: seq.transparent,
}


def _seq_v1_to_v2(d: dict[str, Any]) -> dict[str, Any]:
    """Bloco da 1.4 (formato 1) → formato 2: toda fonte é um arquivo ("tipo") e a transparência ("alfa") sai
    do formato de pixel que o ffprobe informou (a 1.4 não guardava; `media.pix_has_alpha`)."""
    from .media import pix_has_alpha
    out = dict(d)
    fontes = []
    for s in d.get("fontes") or []:
        if isinstance(s, dict):
            s = dict(s)
            s.setdefault("tipo", SOURCE_FILE)
            s.setdefault("alfa", pix_has_alpha(str(s.get("pix_fmt") or "")))
        fontes.append(s)
    out["fontes"] = fontes
    out["formato"] = 2
    return out


# formato de origem → passo para o formato seguinte (puros: devolvem um dicionário novo).
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _seq_v1_to_v2}


def migrate(d: dict[str, Any]) -> dict[str, Any]:
    """O JSON de uma montagem de qualquer formato até `FORMAT`, levado ao formato atual passo a passo.
    `FormatError` se ele é de uma versão mais nova."""
    try:
        fmt = int(d.get("formato", FORMAT_BASE))
    except (TypeError, ValueError):
        fmt = FORMAT_BASE
    if fmt > FORMAT:
        raise FormatError(_("A montagem foi salva por uma versão mais nova do app. Atualize o PeliculaConverter."))
    fmt = max(fmt, FORMAT_BASE)
    while fmt < FORMAT:
        d = MIGRATIONS[fmt](d)
        fmt += 1
    return d


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
