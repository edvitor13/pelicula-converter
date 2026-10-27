"""Exportação por plataforma: alvos prontos (YouTube, Instagram, WhatsApp…) que preenchem a exportação (sem Qt).

Cada `Platform` tem um **id ASCII que nunca muda** (fica nas preferências e nos scripts do modo terminal), um
nome e um grupo, e o alvo: quadro fixo (ex.: 1080 × 1920) ou o lado menor mantendo a orientação do vídeo, fps
máximo, codec, recipiente e formato de cor, qualidade constante (CRF) ou taxa e teto de taxa, som (codec, taxa,
amostragem), duração e tamanho máximos, tamanho alvo (Discord, WhatsApp), volume alvo (LUFS e pico real) e uma
nota. `settings_for()` transforma uma plataforma (+ o vídeo de origem) em `ExportSettings`; depois disso tudo
continua editável na janela de exportação. Nada aqui envia arquivo para a plataforma.

As especificações vêm das páginas oficiais, conferidas em 2026-10 (fonte em comentário em cada entrada). Quando
a plataforma não publica especificação, os valores são conservadores e compatíveis (H.264 + AAC em MP4, 30
quadros/s) e `official=False` — a nota diz isso na janela.

Volume alvo (EBU R 128 / ITU-R BS.1770, medido pelo `loudnorm` do ffmpeg em duas passadas, veja `loudnorm.py`):
−14 LUFS nas redes e no streaming (referência do Spotify e valor que o YouTube aplica na prática; o YouTube não
publica número), −16 LUFS em podcast, −23 LUFS na TV e no festival (EBU R 128); pico real −1 dBTP, e −2 dBTP no
Spotify (o limite que ele pede para podcast).

Áreas seguras (`SAFE_AREAS`): onde a interface do app cobre o vídeo vertical, para a prévia da janela principal
(desenhadas só pelo visualizador, nunca exportadas).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from . import fit as fitmod
from .export import AUDIO, ExportSettings, parse_frame, target_bitrate
from .i18n import N_, _, fmt_decimal

# Grupos na ordem da lista (rótulos traduzidos com _() ao mostrar).
GROUPS = (("youtube", "YouTube"), ("instagram", "Instagram"), ("redes", N_("Outras redes sociais")),
          ("mensagens", N_("Mensagens")), ("streaming", N_("Vídeo e podcast")),
          ("geral", N_("Geral e profissional")))

PERF_KEYS = ("threads", "priority", "hwaccel", "gpu", "buffer", "dither")


@dataclass(frozen=True)
class Platform:
    """Alvo de uma plataforma. Tamanhos em MB = 1.000.000 bytes; durações em segundos (0 = sem limite publicado)."""

    id: str                  # ASCII, nunca renomear
    name: str                # nome da marca fica como está; partes em português vêm com N_()
    group: str               # id de GROUPS
    frame: str = ""          # quadro fixo "LxA"; "" = mantém a orientação do vídeo (lado menor = `resolution`)
    resolution: str = "1080"  # lado menor sem quadro fixo ("original" = o do vídeo)
    upscale: bool = False    # aumenta vídeo menor até `resolution` (YouTube 1440p/4K: o YouTube dá mais qualidade)
    max_fps: float = 60.0    # 0 = qualquer
    codec: str = "x264"
    container: str = "mp4"
    pix: str = "yuv420p"
    quality: float = 18.0    # CRF do x264/x265
    preset: str = "slow"
    profile: str = ""        # perfil do ProRes
    bitrate: float = 0.0     # Mb/s fixos (0 = qualidade constante)
    maxrate: float = 0.0     # teto de taxa (Mb/s) com qualidade constante; 0 = sem teto
    audio: str = "aac192"    # chave de export.AUDIO
    audio_rate: int = 48000  # amostragem recomendada (o volume alvo já grava em 48 kHz)
    loudness: float = 0.0    # LUFS integrados (0 = o som não muda de volume)
    true_peak: float = -1.0  # dBTP
    min_s: float = 0.0
    max_s: float = 0.0
    max_mb: float = 0.0
    target_mb: float = 0.0   # tamanho alvo padrão (duas passadas; o usuário pode mudar)
    fit: str = ""            # encaixe padrão no quadro fixo ("" = automático, veja `auto_fit`)
    safe: str = ""           # área segura da prévia que combina (SAFE_AREAS)
    tune_grain: bool = True
    official: bool = True    # False: a plataforma não publica especificação (valores conservadores)
    note: str = ""           # N_()

    @property
    def size(self) -> tuple[int, int] | None:
        return parse_frame(self.frame)


SOCIAL = -14.0     # LUFS: redes e streaming
PODCAST = -16.0    # LUFS: podcast
BROADCAST = -23.0  # LUFS: TV e festival (EBU R 128)

PLATFORMS: tuple[Platform, ...] = (
    # ---------------------------------------------------------------- YouTube
    # Fonte (conferido em 2026-10): support.google.com/youtube/answer/1722171 — MP4, H.264 High progressivo,
    # 4:2:0, fps original; AAC-LC 48 kHz, estéreo 384 kb/s (aqui 320, o maior AAC do app); taxas SDR
    # recomendadas 1080p 8/12 Mb/s, 1440p 16/24, 2160p 35–45/53–68 (24–30/48–60 fps): o CRF fica acima delas.
    # support.google.com/youtube/answer/71673 — até 256 GB ou 12 horas. Volume: o YouTube não publica alvo;
    # −14 LUFS é o nível que ele aplica na prática (sem especificação oficial).
    Platform("youtube_1080", "YouTube 1080p", "youtube", resolution="1080", quality=17, audio="aac320",
             loudness=SOCIAL, max_s=12 * 3600, max_mb=256_000,
             note=N_("H.264 High e som AAC 48 kHz, como o YouTube recomenda. Vídeo vertical sai 1080 × 1920.")),
    Platform("youtube_1440", "YouTube 1440p", "youtube", resolution="1440", upscale=True, quality=17,
             audio="aac320", loudness=SOCIAL, max_s=12 * 3600, max_mb=256_000,
             note=N_("Enviar em 1440p, mesmo um vídeo 1080p, faz o YouTube usar uma taxa de bits maior e preserva "
                     "melhor o grão.")),
    Platform("youtube_4k", "YouTube 4K", "youtube", resolution="2160", upscale=True, quality=16, audio="aac320",
             loudness=SOCIAL, max_s=12 * 3600, max_mb=256_000,
             note=N_("4K dá ao vídeo a maior taxa de bits do YouTube; o grão sobrevive melhor. Exportação mais "
                     "lenta e arquivo grande.")),
    # support.google.com/youtube/answer/15424877 — Shorts: vertical ou quadrado, até 3 minutos.
    # Área segura: support.google.com/google-ads/answer/13547298 (modelo vertical 1080 × 1920: margens de 288 px
    # em cima, 672 embaixo, 48 à esquerda e 192 à direita).
    Platform("youtube_shorts", "YouTube Shorts", "youtube", frame="1080x1920", quality=17, audio="aac320",
             loudness=SOCIAL, max_s=180, max_mb=256_000, safe="shorts",
             note=N_("Vertical 9:16 de até 3 minutos. Mais longo que isso vira vídeo comum no YouTube.")),
    # ---------------------------------------------------------------- Instagram (Meta)
    # facebook.com/business/ads-guide/update/video/instagram-reels — 9:16, H.264, AAC estéreo ≥ 128 kb/s, até
    # 4 GB, 0 s a 15 min; área segura: 14% em cima, 35% embaixo e 6% dos lados livres.
    # developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media — HEVC ou H.264,
    # 4:2:0, 23 a 60 quadros/s, taxa variável de no máximo 25 Mb/s, AAC até 48 kHz e 128 kb/s (pela API: até
    # 15 min e 300 MB; stories até 60 s e 100 MB). help.instagram.com/2720958398006062 — o app grava até 20 min,
    # mas reels com mais de 3 min não são recomendados para quem não segue a conta.
    Platform("instagram_reels", "Instagram Reels", "instagram", frame="1080x1920", maxrate=25, loudness=SOCIAL,
             max_s=15 * 60, max_mb=4000, safe="reels",
             note=N_("Vertical 9:16. Reels com mais de 3 minutos não são recomendados para quem não segue a "
                     "conta.")),
    # about.instagram.com/features/stories — vídeo de até 60 s vira um story só; mais longo é dividido em
    # partes. Especificação técnica: facebook.com/business/ads-guide/update/video/instagram-story (9:16, H.264,
    # AAC ≥ 128 kb/s, até 4 GB).
    Platform("instagram_stories", "Instagram Stories", "instagram", frame="1080x1920", maxrate=25, loudness=SOCIAL,
             max_s=60, max_mb=4000,
             note=N_("Até 60 segundos aparecem como um story só; mais longo é dividido em partes.")),
    # facebook.com/business/ads-guide/update/video/instagram-feed — até 4 GB, 1 s a 60 min, H.264 + AAC.
    # 4:5 (1080 × 1350) e 1:1 (1080 × 1080) são as proporções do feed.
    Platform("instagram_feed_45", "Instagram Feed 4:5", "instagram", frame="1080x1350", maxrate=25, loudness=SOCIAL,
             min_s=1, max_s=60 * 60, max_mb=4000,
             note=N_("Retrato 4:5 (1080 × 1350): ocupa mais tela no feed que o quadrado.")),
    Platform("instagram_feed_11", "Instagram Feed 1:1", "instagram", frame="1080x1080", maxrate=25, loudness=SOCIAL,
             min_s=1, max_s=60 * 60, max_mb=4000,
             note=N_("Quadrado 1:1 (1080 × 1080).")),
    # ---------------------------------------------------------------- outras redes
    # facebook.com/help/276515126152168 — desde setembro de 2025 todo vídeo postado vira reel, sem limite de
    # duração nem de orientação. facebook.com/business/ads-guide/update/video/facebook-feed — H.264, AAC
    # estéreo ≥ 128 kb/s, até 4 GB, a partir de 1 s.
    Platform("facebook", "Facebook", "redes", resolution="1080", loudness=SOCIAL, min_s=1, max_mb=4000,
             note=N_("Todo vídeo no Facebook vira reel, de qualquer duração e orientação. Mantém a orientação do "
                     "vídeo.")),
    # developers.tiktok.com/doc/content-posting-api-media-transfer-guide — MP4/H.264 recomendados, 23 a 60
    # quadros/s, 360 a 4096 px, até 4 GB, até 10 min (todos podem postar 3 min; algumas contas 5 ou 10).
    # Área segura: modelo oficial "In-Feed" de ads.tiktok.com/help/article/tiktok-auction-in-feed-ads
    # (PNG 2880 × 5120 medido e convertido para 1080 × 1920).
    Platform("tiktok", "TikTok", "redes", frame="1080x1920", loudness=SOCIAL, max_s=10 * 60, max_mb=4000,
             safe="tiktok",
             note=N_("Vertical 9:16. Todas as contas postam até 3 minutos; algumas, até 10.")),
    # Kwai: sem especificação oficial de envio publicada (procurado em 2026-10). Valores conservadores.
    Platform("kwai", "Kwai", "redes", frame="1080x1920", max_fps=30, quality=20, audio="aac128", loudness=SOCIAL,
             official=False,
             note=N_("O Kwai não publica especificação de envio: vertical 9:16, H.264 e AAC a 30 quadros/s, que "
                     "qualquer celular toca.")),
    # docs.x.com/x-api/media/quickstart/best-practices — H.264 High, 30 ou 60 quadros/s (no máximo 60),
    # 1280 × 720 (720 × 1280 em pé), AAC-LC ≥ 128 kb/s, vídeo ≥ 5 Mb/s, mínimo 0,5 s.
    # help.x.com/en/using-x/x-videos — sem Premium: até 2 min 20 s (140 s) e 512 MB. Teto de 25 Mb/s: 140 s
    # cabem em 512 MB.
    Platform("x", "X (Twitter)", "redes", resolution="720", quality=19, maxrate=25, loudness=SOCIAL, min_s=0.5,
             max_s=140, max_mb=512,
             note=N_("Sem Premium: até 2 min 20 s e 512 MB. O X recomenda 1280 × 720 (720 × 1280 em pé).")),
    # linkedin.com/help/linkedin/answer/a548372 — 75 KB a 5 GB, 3 s (2 s no celular) a 15 min, 256 × 144 a
    # 4096 × 2304, proporção 1:2,4 a 2,4:1, 10 a 60 quadros/s, 192 kb/s a 30 Mb/s.
    Platform("linkedin", "LinkedIn", "redes", resolution="1080", quality=19, maxrate=25, loudness=SOCIAL, min_s=3,
             max_s=15 * 60, max_mb=5000,
             note=N_("Até 15 minutos e 5 GB, taxa de até 30 Mb/s. Mantém a orientação do vídeo.")),
    # help.pinterest.com/en/article/review-pin-specs — vídeo H.264/H.265 em MP4, MOV ou M4V, de 4 s a 5 min,
    # 9:16 (1080 × 1920) recomendado. help.pinterest.com/en/business/article/pinterest-product-specs — até 2 GB.
    # Quadros/s: sem especificação oficial.
    Platform("pinterest", "Pinterest", "redes", frame="1080x1920", quality=19, loudness=SOCIAL, min_s=4,
             max_s=5 * 60, max_mb=2000,
             note=N_("Vertical 9:16 de 4 segundos a 5 minutos.")),
    # developers.snap.com/marketing-api/Public-Profile-API/ProfileAssetManagement — Spotlight e Story: MP4,
    # 5 a 60 s, pelo menos 540 × 960, até 1 GB. help.snapchat.com (Spotlight): a partir de 5 s.
    Platform("snapchat", "Snapchat", "redes", frame="1080x1920", quality=19, loudness=SOCIAL, min_s=5, max_s=60,
             max_mb=1000,
             note=N_("Spotlight e Stories: vertical, de 5 a 60 segundos.")),
    # developers.facebook.com/docs/threads/posts — MOV/MP4, HEVC ou H.264 4:2:0, 23 a 60 quadros/s, até 1920 px
    # de largura, 9:16 recomendado, AAC até 48 kHz, 128 kb/s, taxa variável até 100 Mb/s, até 5 min e 1 GB. Teto
    # de 25 Mb/s: 5 min cabem em 1 GB.
    Platform("threads", "Threads", "redes", frame="1080x1920", quality=19, maxrate=25, audio="aac128",
             loudness=SOCIAL, max_s=5 * 60, max_mb=1000,
             note=N_("Até 5 minutos e 1 GB; vertical 9:16 recomendado.")),
    # bsky.app/profile/bsky.app (post oficial de 2026-08-25) — vídeos de até 10 minutos e arquivo de até 300 MB.
    # Codec: sem especificação oficial (H.264 + AAC em MP4). Teto de 3,5 Mb/s: 10 min cabem em 300 MB.
    Platform("bluesky", "Bluesky", "redes", resolution="1080", quality=20, maxrate=3.5, audio="aac128",
             loudness=SOCIAL, max_s=10 * 60, max_mb=300,
             note=N_("Até 10 minutos e 300 MB. Teto de 3,5 Mb/s para caber no limite.")),
    # ---------------------------------------------------------------- mensagens
    # WhatsApp: a central de ajuda não deu para conferir (página só com script). Status: 60 s por vídeo (o limite
    # que vale para todos desde 2024; 90 s ainda em teste) — conservador. O WhatsApp recomprime o vídeo; 720p
    # a 30 quadros/s evita uma redução a mais.
    Platform("whatsapp_status", N_("WhatsApp (status)"), "mensagens", frame="720x1280", max_fps=30, quality=22,
             preset="medium", audio="aac128", loudness=SOCIAL, max_s=60, official=False,
             note=N_("Status de até 60 segundos, vertical. O WhatsApp recomprime o vídeo; valores conservadores "
                     "(o WhatsApp não publica a especificação).")),
    # developers.facebook.com/docs/whatsapp/cloud-api/reference/media — vídeo MP4 só H.264 + AAC, até 16 MB (o
    # limite histórico de mídia do app). blog.whatsapp.com/reactions-2gb-file-sharing-512-groups — arquivos
    # (documento) de até 2 GB.
    Platform("whatsapp", N_("WhatsApp (conversa)"), "mensagens", resolution="720", max_fps=30, preset="medium",
             audio="aac128", loudness=SOCIAL, max_mb=2000, target_mb=16, tune_grain=False,
             note=N_("Tamanho alvo de 16 MB, o limite de vídeo do WhatsApp Business e dos aparelhos antigos; como "
                     "documento vão até 2 GB.")),
    # telegram.org/faq e telegram.org/blog/700-million-and-premium — arquivos de até 2 GB (4 GB no Premium).
    # Vídeo: sem especificação oficial (H.264 + AAC em MP4 toca em todos os aparelhos e permite assistir
    # enquanto baixa).
    Platform("telegram", "Telegram", "mensagens", resolution="1080", quality=20, loudness=SOCIAL, max_mb=2000,
             note=N_("Arquivos de até 2 GB (4 GB com Premium). Mantém a orientação do vídeo.")),
    # support.discord.com/hc/en-us/articles/25444343291031-File-Attachments-FAQ (atualizado em 2026-09-30) —
    # sem Nitro, até 20 MB (desde agosto de 2026; antes 10 MB); Nitro Basic 50 MB; Nitro até 1 GB. MP4 com
    # H.264, HEVC ou AV1.
    Platform("discord", "Discord", "mensagens", resolution="720", max_fps=30, preset="medium", audio="aac128",
             loudness=SOCIAL, max_mb=20, target_mb=20, tune_grain=False,
             note=N_("Sem Nitro, até 20 MB (Nitro Basic: 50 MB; Nitro: até 1 GB). Mude o tamanho alvo se a sua "
                     "conta aceita mais.")),
    # ---------------------------------------------------------------- vídeo e podcast
    # help.vimeo.com/hc/en-us/articles/12426043233169-Video-and-audio-compression-guidelines — H.264 High (ou
    # ProRes 422 HQ, H.265), fps original constante (acima de 60 o Vimeo reduz), taxa variável: 1080p 10–20
    # Mb/s, 4K 30–60; AAC-LC 320 kb/s, 48 kHz.
    Platform("vimeo", "Vimeo", "streaming", resolution="1080", quality=17, maxrate=20, audio="aac320",
             loudness=SOCIAL,
             note=N_("H.264 High até 20 Mb/s e AAC 320 kb/s, como o Vimeo recomenda para 1080p.")),
    # support.spotify.com/us/creators/article/video-specs — MP4 (H.264 ou H.265), 16:9, 1080p ou mais, 24/25/30/
    # 50/60 quadros/s, 25 Mb/s em 1080p; AAC-LC ≥ 128 kb/s estéreo; até 12 h e 60 GB (recomendado: menos de 4 h e
    # 10 GB). Volume: o Spotify não publica alvo para o episódio; usa o dos anúncios em podcast
    # (ads.spotify.com/en-US/guide-to-creating-audio-ads/podcast-ads-minimum-requirements: −16 LUFS ± 1,5 e pico
    # real de no máximo −2 dBTP).
    Platform("spotify", N_("Spotify (videocast)"), "streaming", frame="1920x1080", maxrate=25, loudness=PODCAST,
             true_peak=-2.0, max_s=12 * 3600, max_mb=60_000,
             note=N_("Videocast 16:9 em 1080p, som a −16 LUFS (podcast). Recomendado: menos de 4 horas e 10 GB.")),
    # ---------------------------------------------------------------- geral e profissional
    # Sem plataforma por trás: H.264 High 8 bits até 1080p e 30 quadros/s com teto de 20 Mb/s (nível 4.1, o
    # que TVs, celulares e players antigos aceitam), AAC 48 kHz em MP4 com o índice no começo.
    Platform("compat", N_("Compatível com tudo"), "geral", resolution="1080", max_fps=30, quality=20, maxrate=20,
             note=N_("H.264 8 bits até 1080p e 30 quadros/s, AAC em MP4: toca em TVs, celulares, projetores e "
                     "players antigos.")),
    # HEVC Main 10 com a marca hvc1 (o QuickTime, o iPhone e a Apple TV exigem); export.py já põe -tag:v hvc1.
    Platform("apple", "Apple (HEVC)", "geral", resolution="original", max_fps=0, codec="x265", pix="yuv420p10le",
             quality=20, audio="aac320",
             note=N_("H.265 10 bits que abre no iPhone, iPad, Mac e Apple TV, com metade do tamanho do H.264.")),
    # Master para festival: ProRes 422 HQ 10 bits + PCM 24 bits, volume −23 LUFS e pico −1 dBTP (EBU R 128,
    # tech.ebu.ch/publications/r128). O DCP (cinema) fica fora do app: gere-o a partir deste master num programa
    # próprio (ex.: DCP-o-matic).
    Platform("festival", "Festival (ProRes 422 HQ)", "geral", resolution="original", max_fps=0, codec="prores",
             container="mov", pix="yuv422p10le", quality=0, preset="", profile="3", audio="pcm24",
             loudness=BROADCAST, tune_grain=False,
             note=N_("Master ProRes 422 HQ com som PCM a −23 LUFS (EBU R 128). O DCP não é gerado aqui: use este "
                     "arquivo num programa de DCP.")),
    # Preservação: FFV1 nível 3 sem perdas (-g 1, fatias com CRC; o padrão IETF/CELLAR usado por arquivos e
    # cinematecas), RGB 16 bits (exatamente o resultado do processamento) em MKV; o som original é copiado sem
    # recodificar (em trechos vira FLAC, também sem perdas). Volume intocado.
    Platform("arquivo", N_("Arquivo (preservação)"), "geral", resolution="original", max_fps=0, codec="ffv1",
             container="mkv", pix="rgb48le", quality=0, preset="", audio="copy", tune_grain=False,
             note=N_("FFV1 sem perdas em 16 bits com verificação (CRC) e o som original sem recodificar. Arquivos "
                     "muito grandes.")),
)

BY_ID: dict[str, Platform] = {p.id: p for p in PLATFORMS}


def get(pid: str) -> Platform | None:
    return BY_ID.get(str(pid or ""))


def grouped() -> list[tuple[str, str, list[Platform]]]:
    """[(id do grupo, rótulo em português, plataformas)] na ordem da lista."""
    return [(gid, label, [p for p in PLATFORMS if p.group == gid]) for gid, label in GROUPS]


# ------------------------------------------------------------------ plataforma → ExportSettings
def auto_fit(src_w: int, src_h: int, out_w: int, out_h: int) -> str:
    """Encaixe automático: cortar quando a proporção é parecida (até 25%); senão, fundo desfocado (nada some)."""
    r = (src_w / max(src_h, 1)) / (out_w / max(out_h, 1))
    return fitmod.CORTAR if 0.8 <= r <= 1.25 else fitmod.DESFOCADO


def fps_for(info, max_fps: float) -> str:
    """"original", ou o fps de origem dividido pelo menor inteiro que o deixa até `max_fps` (59,94 → 29,97;
    50 → 25; 120 → 60): a cadência continua regular."""
    if not max_fps or info is None or getattr(info, "is_image", False) or info.fps <= max_fps + 0.01:
        return "original"
    try:
        src = Fraction(info.fps_str)
    except (ValueError, ZeroDivisionError, TypeError):
        src = Fraction(info.fps).limit_denominator(1001)
    k = math.ceil(float(src) / max_fps - 1e-6)
    f = (src / k).limit_denominator(1001)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


# Tamanho alvo: o lado menor que a taxa de vídeo disponível sustenta (Mb/s de vídeo, H.264).
TARGET_STEPS = ((1080, 4.0), (720, 1.8), (540, 1.0), (480, 0.6))


def resolution_for_rate(rate: float) -> str:
    for short, need in TARGET_STEPS:
        if rate >= need:
            return str(short)
    return "360"


def settings_for(pid: str, info=None, base: ExportSettings | None = None, duration: float = 0.0,
                 fit_mode: str | None = None) -> ExportSettings:
    """Ajustes de exportação da plataforma `pid` para o vídeo `info` (opcional).

    `base`: ajustes atuais (desempenho e pontilhado continuam como o usuário deixou). `duration` (s): com
    tamanho alvo, escolhe a resolução que a taxa sustenta. `fit_mode`: encaixe no quadro fixo (None =
    o da plataforma ou o automático).
    """
    p = BY_ID[pid]
    s = ExportSettings()
    if base is not None:
        for k in PERF_KEYS:
            setattr(s, k, getattr(base, k))
    s.platform = p.id
    s.codec, s.container, s.pix = p.codec, p.container, p.pix
    s.quality, s.preset, s.profile = p.quality, p.preset, p.profile
    s.bitrate, s.maxrate = p.bitrate, p.maxrate
    s.audio = p.audio
    s.tune_grain = p.tune_grain and p.codec in ("x264", "x265")
    s.loudness, s.true_peak = p.loudness, p.true_peak
    s.target_mb = p.target_mb
    s.frame = p.frame
    s.fps = fps_for(info, p.max_fps)
    if p.frame:
        w, h = p.size
        if fit_mode in fitmod.MODE_IDS:
            s.fit = fit_mode
        elif p.fit:
            s.fit = p.fit
        elif info is not None:
            s.fit = auto_fit(info.width, info.height, w, h)
        return s
    res = p.resolution
    if p.target_mb and info is not None and duration > 0:
        res = resolution_for_rate(target_bitrate(s, info, duration))
    if res != "original" and info is not None and not p.upscale and min(info.width, info.height) <= int(res):
        res = "original"  # não aumenta vídeo menor (só o YouTube 1440p/4K, de propósito)
    s.resolution = res
    return s


# ------------------------------------------------------------------ textos da janela e do terminal
ASPECTS = {(9, 16): "9:16", (4, 5): "4:5", (1, 1): "1:1", (16, 9): "16:9", (3, 4): "3:4", (4, 3): "4:3"}


def aspect_name(w: int, h: int) -> str:
    g = math.gcd(w, h)
    known = ASPECTS.get((w // g, h // g))
    if known:
        return known
    return f"{fmt_decimal(w / h, 2)}:1" if w >= h else f"1:{fmt_decimal(h / w, 2)}"


def fmt_seconds(sec: float) -> str:
    """0.5 → "0,5 s", 60 → "60 s", 140 → "2 min 20 s", 900 → "15 min", 43200 → "12 h"."""
    sec = max(0.0, float(sec))
    if sec < 10 and not sec.is_integer():
        return _("{n} s").format(n=fmt_decimal(sec, 1))
    s = int(round(sec))
    if s <= 90:
        return _("{n} s").format(n=s)
    h, m, r = s // 3600, s % 3600 // 60, s % 60
    if h:
        return _("{h} h").format(h=h) if not m else _("{h} h {m} min").format(h=h, m=m)
    return _("{m} min").format(m=m) if not r else _("{m} min {s} s").format(m=m, s=r)


def fmt_size(mb: float) -> str:
    """MB (1.000.000 bytes) → "512 MB", "4 GB", "1,5 GB"."""
    if mb >= 1000:
        gb = mb / 1000
        return _("{n} GB").format(n=fmt_decimal(gb, 0 if gb.is_integer() else 1))
    return _("{n} MB").format(n=fmt_decimal(mb, 0 if float(mb).is_integer() else 1))


def fmt_lufs(value: float) -> str:
    return fmt_decimal(value, 0 if float(value).is_integer() else 1).replace("-", "−")


CODEC_NAMES = {"x264": "H.264", "x265": "H.265", "prores": "ProRes", "ffv1": "FFV1"}
PRORES_NAMES = {"0": "ProRes Proxy", "1": "ProRes LT", "2": "ProRes 422", "3": "ProRes 422 HQ", "4": "ProRes 4444",
                "5": "ProRes 4444 XQ"}


def codec_name(p: Platform) -> str:
    if p.codec == "prores":
        return PRORES_NAMES.get(p.profile, "ProRes")
    return CODEC_NAMES.get(p.codec, p.codec)


def limits_text(p: Platform) -> str:
    """Resumo das opções e limites: "1080 × 1920 (9:16) • H.264 + AAC 192 kb/s • até 60 quadros/s • …"."""
    parts = []
    size = p.size
    if size:
        parts.append(f"{size[0]} × {size[1]} ({aspect_name(*size)})")
    elif p.resolution == "original":
        parts.append(_("resolução do vídeo"))
    else:
        parts.append(_("{res}p no lado menor").format(res=p.resolution))
    audio = _("som original") if p.audio == "copy" else _(dict(AUDIO).get(p.audio, p.audio))
    parts.append(f"{codec_name(p)} + {audio}")
    if p.max_fps:
        parts.append(_("até {fps} quadros/s").format(fps=fmt_decimal(p.max_fps, 0)))
    if p.min_s and p.max_s:
        parts.append(_("de {min} a {max}").format(min=fmt_seconds(p.min_s), max=fmt_seconds(p.max_s)))
    elif p.max_s:
        parts.append(_("até {dur}").format(dur=fmt_seconds(p.max_s)))
    elif p.min_s:
        parts.append(_("pelo menos {dur}").format(dur=fmt_seconds(p.min_s)))
    if p.target_mb:
        parts.append(_("tamanho alvo {tam}").format(tam=fmt_size(p.target_mb)))
    elif p.max_mb:
        parts.append(_("arquivo até {tam}").format(tam=fmt_size(p.max_mb)))
    if p.loudness:
        parts.append(_("som a {lufs} LUFS").format(lufs=fmt_lufs(p.loudness)))
    return "  •  ".join(parts)


def warnings(p: Platform, duration: float, size_bytes: float = 0.0) -> list[str]:
    """Avisos da janela: duração fora dos limites e tamanho estimado acima do máximo (lista vazia = tudo certo)."""
    out = []
    name = _(p.name)
    if p.max_s and duration > p.max_s + 0.05:
        out.append(_("O vídeo tem {dur} e {plataforma} aceita até {max}.").format(
            dur=fmt_seconds(duration), plataforma=name, max=fmt_seconds(p.max_s)))
    if p.min_s and 0 < duration < p.min_s - 0.05:
        out.append(_("O vídeo tem {dur} e {plataforma} pede pelo menos {min}.").format(
            dur=fmt_seconds(duration), plataforma=name, min=fmt_seconds(p.min_s)))
    if p.max_mb and size_bytes > p.max_mb * 1e6:
        out.append(_("Tamanho estimado: {tam}; {plataforma} aceita até {max}.").format(
            tam=fmt_size(size_bytes / 1e6), plataforma=name, max=fmt_size(p.max_mb)))
    return out


# ------------------------------------------------------------------ áreas seguras da prévia (só na tela)
@dataclass(frozen=True)
class SafeArea:
    """Parte do quadro que a interface do app não cobre: retângulos em frações do quadro (x, y, largura, altura;
    y para baixo). Com `dim`, o visualizador escurece o resto (onde ficam botões, legenda e nome)."""

    id: str
    name: str
    rects: tuple[tuple[float, float, float, float], ...]
    dim: bool = True


SAFE_AREAS: tuple[SafeArea, ...] = (
    # Modelo In-Feed do TikTok Ads (ads.tiktok.com/help/article/tiktok-auction-in-feed-ads, conferido em
    # 2026-10), medido em 1080 × 1920: 120 px livres de cada lado, 240 em cima e 660 embaixo, e a coluna dos
    # botões (curtir, comentar, compartilhar) ocupa x ≥ 780 a partir de y = 840.
    SafeArea("tiktok", "TikTok", ((120 / 1080, 240 / 1920, 840 / 1080, 600 / 1920),
                                  (120 / 1080, 840 / 1920, 660 / 1080, 420 / 1920))),
    # Meta Ads Guide, Instagram Reels (conferido em 2026-10): 14% em cima, 35% embaixo e 6% de cada lado livres.
    SafeArea("reels", "Instagram Reels", ((0.06, 0.14, 0.88, 0.51),)),
    # Google Ads, modelo vertical 1080 × 1920 (support.google.com/google-ads/answer/13547298, conferido em
    # 2026-10): margens de 288 px em cima, 672 embaixo, 48 à esquerda e 192 à direita.
    SafeArea("shorts", "YouTube Shorts", ((48 / 1080, 288 / 1920, 840 / 1080, 960 / 1920),)),
    # EBU R 95 (tech.ebu.ch/publications/r095): título/gráficos a 5% de cada borda, ação a 3,5%.
    SafeArea("titulo", N_("Título e ação (TV)"), ((0.05, 0.05, 0.90, 0.90), (0.035, 0.035, 0.93, 0.93)),
             dim=False),
)
SAFE_BY_ID: dict[str, SafeArea] = {a.id: a for a in SAFE_AREAS}


def safe_rects(kind: str, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Retângulos da área segura `kind` num quadro de `w` × `h` (vazio se desconhecida)."""
    area = SAFE_BY_ID.get(kind)
    if area is None:
        return []
    return [(x * w, y * h, rw * w, rh * h) for x, y, rw, rh in area.rects]
