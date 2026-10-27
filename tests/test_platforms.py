"""Exportação por plataforma (platforms.py): o registro é coerente e cada plataforma vira ajustes válidos.

Sem GPU nem ffmpeg: os comandos são montados com um ffmpeg "de mentira" (como em test_export_cmd.py).
"""

from __future__ import annotations

import re

import pytest

from pelicula import export, fit, i18n, media, platforms
from pelicula.export import ExportSettings
from pelicula.platforms import PLATFORMS

# Ids publicados: ficam nas preferências e em scripts do terminal. Nunca renomear nem tirar (só acrescentar).
PUBLISHED_IDS = ("youtube_1080", "youtube_1440", "youtube_4k", "youtube_shorts", "instagram_reels",
                 "instagram_stories", "instagram_feed_45", "instagram_feed_11", "facebook", "tiktok", "kwai", "x",
                 "linkedin", "pinterest", "snapchat", "threads", "bluesky", "whatsapp_status", "whatsapp",
                 "telegram", "discord", "vimeo", "spotify", "compat", "apple", "festival", "arquivo")


@pytest.fixture(autouse=True)
def portuguese():
    i18n.set_language("pt_BR")
    yield
    i18n.set_language("pt_BR")


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(export, "available", lambda key: True)


def _info(w=1920, h=1080, fps=24.0, fps_str="24/1", dur=10.0, audio="aac", **kw) -> media.MediaInfo:
    base = dict(path="C:/videos/entrada.mp4", width=w, height=h, fps=fps, fps_str=fps_str,
                frames=int(round(dur * fps)), duration=dur, pix_fmt="yuv420p", bit_depth=8, codec="h264",
                profile="High", bitrate=20_000_000, color_space="bt709", color_range="tv", color_transfer="bt709",
                color_primaries="bt709", has_audio=bool(audio), audio_codec=audio,
                container="mov,mp4,m4a,3gp,3g2,mj2", is_image=False)
    base.update(kw)
    return media.MediaInfo(**base)


SOURCES = {
    "deitado_1080p": _info(),
    "vertical_1080p": _info(1080, 1920),
    "quadrado": _info(1080, 1080),
    "pequeno_360p": _info(640, 360),
    "uhd_59_94": _info(3840, 2160, fps=60000 / 1001, fps_str="60000/1001"),
    "vertical_impar_sem_som": _info(721, 1281, fps=50.0, fps_str="50/1", audio=""),
    "cinema_scope": _info(2048, 858, fps=24000 / 1001, fps_str="24000/1001", audio="pcm_s24le"),
}


# ------------------------------------------------------------------ registro
def test_published_ids_are_all_there_and_never_renamed():
    ids = [p.id for p in PLATFORMS]
    assert len(ids) == len(set(ids))
    missing = [pid for pid in PUBLISHED_IDS if pid not in ids]
    assert not missing, f"plataformas sumiram ou mudaram de id: {missing}"
    for pid in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", pid), pid
        assert platforms.get(pid) is platforms.BY_ID[pid]
    assert platforms.get("nao_existe") is None and platforms.get("") is None


def test_every_platform_is_consistent():
    groups = {gid for gid, _label in platforms.GROUPS}
    for p in PLATFORMS:
        c = export.CODECS[p.codec]
        assert p.name and p.note and p.group in groups, p.id
        assert p.container in c["exts"] and p.pix in c["pix"], p.id
        assert p.audio in dict(export.AUDIO), p.id
        assert p.audio_rate in (44100, 48000)
        if p.frame:
            w, h = p.size
            assert w % 2 == 0 and h % 2 == 0 and 2 <= w <= 4096 and 2 <= h <= 4096, p.id
        else:
            assert p.resolution == "original" or p.resolution in dict(export.RESOLUTIONS), p.id
        assert p.max_fps == 0 or 24 <= p.max_fps <= 120, p.id
        if c.get("rc") == "crf":
            assert 0 < p.quality <= 30, p.id
        if p.codec == "prores":
            assert p.profile in dict(c["profiles"])
        assert p.bitrate >= 0 and p.maxrate >= 0 and not (p.bitrate and p.maxrate)
        assert p.loudness in (0.0, platforms.SOCIAL, platforms.PODCAST, platforms.BROADCAST), p.id
        assert -3.0 <= p.true_peak <= -1.0
        assert p.min_s >= 0 and p.max_s >= 0 and (not p.max_s or p.min_s < p.max_s)
        assert p.max_mb >= 0 and p.target_mb >= 0
        if p.target_mb:  # tamanho alvo só com x264/x265 e nunca acima do limite
            assert p.codec in export.TWO_PASS_CODECS and (not p.max_mb or p.target_mb <= p.max_mb), p.id
            assert not p.tune_grain
        if p.id in ("x", "linkedin", "bluesky", "threads", "instagram_reels"):  # o teto garante o limite na duração
            # máxima
            kbps = export.AUDIO_KBPS[p.audio]
            assert (p.maxrate * 1000 + kbps) * p.max_s / 8 / 1000 <= p.max_mb, p.id
        assert p.fit in ("",) + fit.MODE_IDS
        assert p.safe in ("",) + tuple(platforms.SAFE_BY_ID), p.id
    # cada grupo tem plataformas, e a ordem de grouped() é a do registro
    flat = [p for _gid, _label, items in platforms.grouped() for p in items]
    assert sorted(p.id for p in flat) == sorted(p.id for p in PLATFORMS)
    assert all(items for _gid, _label, items in platforms.grouped())


def test_what_the_brief_asked_for():
    get = platforms.BY_ID
    for pid in ("youtube_shorts", "instagram_reels", "instagram_stories", "tiktok"):
        assert get[pid].frame == "1080x1920"
    assert get["instagram_feed_45"].frame == "1080x1350" and get["instagram_feed_11"].frame == "1080x1080"
    assert [get[k].resolution for k in ("youtube_1080", "youtube_1440", "youtube_4k")] == ["1080", "1440", "2160"]
    assert get["youtube_1080"].frame == "" and get["youtube_4k"].upscale  # mantêm a orientação do vídeo
    assert get["discord"].target_mb == get["discord"].max_mb == 20  # limite sem Nitro (agosto de 2026)
    assert get["whatsapp"].target_mb == 16 and get["whatsapp_status"].max_s == 60
    assert get["spotify"].loudness == -16 and get["spotify"].true_peak == -2 and get["festival"].loudness == -23
    assert get["youtube_1080"].loudness == get["tiktok"].loudness == -14
    assert get["festival"].codec == "prores" and get["festival"].profile == "3"  # ProRes 422 HQ
    assert get["arquivo"].codec == "ffv1" and get["arquivo"].audio == "copy" and not get["arquivo"].loudness
    assert get["apple"].codec == "x265"
    assert get["youtube_shorts"].max_s == 180 and get["x"].max_s == 140 and get["x"].max_mb == 512
    assert not get["kwai"].official  # sem especificação oficial: valores conservadores


# ------------------------------------------------------------------ plataforma → ajustes
@pytest.mark.parametrize("source", list(SOURCES))
@pytest.mark.parametrize("pid", [p.id for p in PLATFORMS])
def test_settings_for_every_platform_and_source_are_valid(fake_ffmpeg, pid, source):
    p, info = platforms.BY_ID[pid], SOURCES[source]
    base = ExportSettings(threads=3, priority="baixa", hwaccel="auto", gpu=1, buffer=9, dither=False)
    s = platforms.settings_for(pid, info, base=base, duration=info.duration)
    assert s.platform == pid
    assert (s.threads, s.priority, s.hwaccel, s.gpu, s.buffer, s.dither) == (3, "baixa", "auto", 1, 9, False)
    assert ExportSettings.from_dict(s.to_dict()) == s
    w, h = export.output_size(info, s)
    if p.frame:
        assert (w, h) == p.size and s.fit in fit.MODE_IDS
    else:
        short = min(w, h)
        assert (w >= h) == (info.width >= info.height)  # mantém a orientação
        if p.resolution != "original" and not p.target_mb:
            want = int(p.resolution)
            src = min(info.width, info.height)
            assert short == (want if (p.upscale or src > want) else src - src % 2)
    if p.codec not in ("ffv1",):
        assert w % 2 == 0 and h % 2 == 0
    fps = info.fps if s.fps == "original" else export.eval_fraction(s.fps)
    assert not p.max_fps or fps <= p.max_fps + 0.01
    assert fps >= min(info.fps, p.max_fps or info.fps) / 2 - 0.01  # nunca menos da metade do possível
    depth = 16 if export.high_depth(s) else 8
    cmd = export.build_encoder_cmd("saida." + s.container, info, s, w, h, s.fps if s.fps != "original"
                                   else info.fps_str, depth, 0.0, info.duration)
    assert cmd[-1] == "saida." + s.container and export.CODECS[s.codec]["enc"] in cmd
    if p.loudness and info.has_audio:
        assert export.wants_loudness(s) and export._audio_mode(s, info) not in ("", "copy")
    if p.target_mb:
        assert export.uses_target(s) and s.target_mb == p.target_mb
    if p.maxrate:
        assert "-maxrate" in cmd and cmd[cmd.index("-maxrate") + 1] == f"{p.maxrate:g}M"


def test_settings_without_source_and_fit_choice():
    s = platforms.settings_for("tiktok")
    assert s.frame == "1080x1920" and s.fit == fit.CORTAR and s.fps == "original" and s.resolution == "original"
    deitado, vertical = SOURCES["deitado_1080p"], SOURCES["vertical_1080p"]
    assert platforms.settings_for("tiktok", deitado).fit == fit.DESFOCADO  # 16:9 em 9:16: nada some
    assert platforms.settings_for("tiktok", vertical).fit == fit.CORTAR
    assert platforms.settings_for("tiktok", deitado, fit_mode=fit.BORDAS).fit == fit.BORDAS
    assert platforms.settings_for("tiktok", deitado, fit_mode="???").fit == fit.DESFOCADO
    assert platforms.settings_for("instagram_feed_45", SOURCES["quadrado"]).fit == fit.CORTAR  # 1:1 em 4:5
    assert platforms.settings_for("spotify", vertical).fit == fit.DESFOCADO


@pytest.mark.parametrize("w, h, ow, oh, mode", [
    (1920, 1080, 1080, 1920, "desfocado"), (1080, 1920, 1920, 1080, "desfocado"), (1080, 1080, 1080, 1350, "cortar"),
    (1080, 1920, 1080, 1350, "desfocado"), (1920, 1080, 1080, 1080, "desfocado"), (1440, 1080, 1920, 1080, "desfocado"),
    (1080, 1920, 1080, 1920, "cortar"), (1080, 1350, 1080, 1080, "cortar"), (2048, 858, 1920, 1080, "desfocado"),
    (1998, 1080, 1920, 1080, "cortar")])
def test_auto_fit(w, h, ow, oh, mode):
    assert platforms.auto_fit(w, h, ow, oh) == mode


@pytest.mark.parametrize("fps, fps_str, max_fps, expected", [
    (24.0, "24/1", 60, "original"), (60000 / 1001, "60000/1001", 60, "original"),
    (60000 / 1001, "60000/1001", 30, "30000/1001"), (50.0, "50/1", 30, "25"), (120.0, "120/1", 60, "60"),
    (120.0, "120/1", 30, "30"), (48.0, "48/1", 30, "24"), (100.0, "100/1", 60, "50"), (60.0, "60", 0, "original"),
    (240000 / 1001, "240000/1001", 30, "30000/1001"), (90.0, "90/1", 60, "45"), (50.0, "ruim", 30, "25")])
def test_fps_for_keeps_a_regular_cadence(fps, fps_str, max_fps, expected):
    assert platforms.fps_for(_info(fps=fps, fps_str=fps_str), max_fps) == expected
    assert platforms.fps_for(None, max_fps) == "original"


def test_target_size_picks_the_resolution_the_rate_can_hold():
    rates = [9.0, 4.0, 3.9, 1.8, 1.0, 0.6, 0.59, 0.1]
    shorts = [int(platforms.resolution_for_rate(r)) for r in rates]
    assert shorts == sorted(shorts, reverse=True) and shorts[0] == 1080 and shorts[-1] == 360
    info = SOURCES["deitado_1080p"]
    short_clip = platforms.settings_for("discord", info, duration=5)    # 20 MB em 5 s: sobra taxa
    long_clip = platforms.settings_for("discord", info, duration=600)   # 20 MB em 10 min: pouca
    assert short_clip.resolution == "original" and long_clip.resolution == "360"
    assert platforms.settings_for("discord", info).resolution == "720"  # sem duração: o padrão
    small = platforms.settings_for("discord", SOURCES["pequeno_360p"], duration=5)
    assert small.resolution == "original"  # nunca aumenta


def test_new_settings_stay_neutral_for_formats_without_platform():
    for pid in ("compat", "apple", "arquivo"):
        s = platforms.settings_for(pid, SOURCES["deitado_1080p"])
        assert not export.wants_loudness(s) and not export.uses_target(s) and s.frame == ""
        assert s.net_grain is False
    arq = platforms.settings_for("arquivo", SOURCES["cinema_scope"])
    assert export._audio_mode(arq, SOURCES["cinema_scope"]) == "copy"
    assert export._audio_mode(arq, SOURCES["cinema_scope"], start_time=2.0) == "flac"  # trecho: sem perdas


# ------------------------------------------------------------------ textos
def test_limits_text_and_warnings():
    t = platforms.limits_text(platforms.BY_ID["tiktok"])
    assert t.startswith("1080 × 1920 (9:16)") and "até 10 min" in t and "−14 LUFS" in t and "4 GB" in t
    assert "tamanho alvo 20 MB" in platforms.limits_text(platforms.BY_ID["discord"])
    assert "ProRes 422 HQ" in platforms.limits_text(platforms.BY_ID["festival"])
    assert "som original" in platforms.limits_text(platforms.BY_ID["arquivo"])
    assert "de 0,5 s a 2 min 20 s" in platforms.limits_text(platforms.BY_ID["x"])
    st = platforms.BY_ID["instagram_stories"]
    assert platforms.warnings(st, 59.99) == [] and platforms.warnings(st, 60.0) == []
    assert platforms.warnings(st, 75.4) == ["O vídeo tem 75 s e Instagram Stories aceita até 60 s."]
    li = platforms.BY_ID["linkedin"]
    assert platforms.warnings(li, 2) == ["O vídeo tem 2 s e LinkedIn pede pelo menos 3 s."]
    assert platforms.warnings(platforms.BY_ID["x"], 30, 600e6) == [
        "Tamanho estimado: 600 MB; X (Twitter) aceita até 512 MB."]
    assert platforms.warnings(platforms.BY_ID["x"], 30, 500e6) == []
    assert platforms.warnings(platforms.BY_ID["vimeo"], 99999, 9e12) == []  # sem limites publicados


@pytest.mark.parametrize("sec, text", [(0.5, "0,5 s"), (2, "2 s"), (60, "60 s"), (75.4, "75 s"), (90, "90 s"),
                                       (140, "2 min 20 s"), (180, "3 min"), (900, "15 min"), (3600, "1 h"),
                                       (3660, "1 h 1 min"), (43200, "12 h")])
def test_fmt_seconds(sec, text):
    assert platforms.fmt_seconds(sec) == text


def test_texts_are_translated():
    i18n.set_language("en")
    t = platforms.limits_text(platforms.BY_ID["whatsapp"])
    assert "target size 16 MB" in t and "LUFS" in t
    assert platforms.warnings(platforms.BY_ID["instagram_stories"], 75) == [
        "The video is 75 s long and Instagram Stories accepts up to 60 s."]
    assert i18n._(platforms.BY_ID["whatsapp"].name) == "WhatsApp (chat)"
    i18n.set_language("es")
    assert "hasta 60 s" in platforms.limits_text(platforms.BY_ID["instagram_stories"])


# ------------------------------------------------------------------ áreas seguras
def test_safe_areas_match_the_official_templates():
    for area in platforms.SAFE_AREAS:
        assert area.name and area.rects
        for x, y, w, h in area.rects:
            assert 0 <= x < x + w <= 1 and 0 <= y < y + h <= 1
    px = lambda kind: [tuple(round(v) for v in r) for r in platforms.safe_rects(kind, 1080, 1920)]  # noqa: E731
    assert px("tiktok") == [(120, 240, 840, 600), (120, 840, 660, 420)]   # coluna de botões a partir de x = 780
    assert px("reels") == [(65, 269, 950, 979)]                           # 6% / 14% / 35%
    assert px("shorts") == [(48, 288, 840, 960)]                           # 48 / 288 / 192 / 672
    title, action = platforms.safe_rects("titulo", 1920, 1080)
    assert title == pytest.approx((96, 54, 1728, 972)) and action == pytest.approx((67.2, 37.8, 1785.6, 1004.4))
    assert platforms.safe_rects("nada", 100, 100) == []
    for p in PLATFORMS:
        if p.safe and p.safe != "titulo":
            assert p.frame == "1080x1920", p.id  # zonas medidas no quadro vertical
