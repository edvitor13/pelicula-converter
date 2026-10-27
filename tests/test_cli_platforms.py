"""Modo terminal: lista de plataformas e exportação com --plataforma, --quadro, --encaixe, --tamanho-alvo,
--volume, --pico e --grao-redes."""

import json

import pytest

from pelicula import cli, i18n, platforms


@pytest.fixture(autouse=True)
def portuguese(monkeypatch):
    monkeypatch.setenv("PELICULA_LANG", "pt_BR")
    i18n.set_language("pt_BR")
    yield
    i18n.set_language("pt_BR")


def test_platform_commands_are_known():
    assert cli.COMMANDS["plataformas"] == "platforms" and cli.COMMANDS["platforms"] == "platforms"


def test_platforms_json_lists_every_platform(capsys):
    assert cli.main(["plataformas", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == [p.id for _g, _l, items in platforms.grouped() for p in items]
    reels = next(r for r in rows if r["id"] == "instagram_reels")
    assert reels["quadro"] == "1080x1920" and reels["volume_lufs"] == -14 and reels["teto_mbps"] == 25
    assert reels["grupo"] == "Instagram" and "LUFS" in reels["limites"]
    discord = next(r for r in rows if r["id"] == "discord")
    assert discord["tamanho_alvo_mb"] == 20 and discord["resolucao"] == "720"


def test_platforms_text_in_english(capsys, monkeypatch):
    monkeypatch.setenv("PELICULA_LANG", "en")
    assert cli.main(["platforms"]) == 0
    out = capsys.readouterr().out
    assert "MESSAGING" in out and "whatsapp" in out and "WhatsApp (chat)" in out and "target size 16 MB" in out


def test_export_help_lists_the_platform_options(capsys):
    with pytest.raises(SystemExit):
        cli.main(["exportar", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    for opt in ("--plataforma", "--quadro", "--encaixe", "--tamanho-alvo", "--volume", "--pico", "--grao-redes"):
        assert opt in out


@pytest.mark.ffmpeg
@pytest.mark.parametrize("args, message", [
    (["--plataforma", "orkut"], "Plataforma desconhecida: orkut"),
    (["--plataforma", "tiktok", "--qualidade", "mp4"], "não os dois"),
    (["--quadro", "grande"], "Quadro inválido"),
    (["--volume", "14"], "Volume alvo inválido"),
    (["--pico", "-12"], "Pico real inválido"),
    (["--tamanho-alvo", "-1"], "Tamanho alvo inválido"),
])
def test_export_rejects_bad_platform_options(ffmpeg_ok, sample_video, tmp_path, capsys, args, message):
    assert cli.main(["exportar", sample_video, "-o", str(tmp_path / "x.mp4"), "-q"] + args) == 1
    assert message in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@pytest.mark.ffmpeg
def test_platform_is_only_for_video(ffmpeg_ok, sample_image, tmp_path, capsys):
    assert cli.main(["exportar", sample_image, "-o", str(tmp_path / "x.png"), "--plataforma", "tiktok"]) == 1
    assert "para vídeo" in capsys.readouterr().err


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_with_a_platform(gl_engine, ffmpeg_ok, sample_video, tmp_path, capsys):
    from pelicula import media
    out = tmp_path / "tiktok.mp4"
    assert cli.main(["exportar", sample_video, "-o", str(out), "--plataforma", "tiktok", "--encaixe", "bordas",
                     "--fim", "#5", "-q"]) == 0
    info = media.probe(str(out))
    assert (info.width, info.height) == (1080, 1920) and info.frames == 6 and info.has_audio
    err = capsys.readouterr().err
    assert "Plataforma: TikTok" in err and "1080×1920" in err


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_with_frame_fit_loudness_and_net_grain(gl_engine, ffmpeg_ok, sample_video, tmp_path, capsys):
    from pelicula import media
    out = tmp_path / "quadrado.mp4"
    assert cli.main(["exportar", sample_video, "-o", str(out), "--qualidade", "leve", "--quadro", "240x240",
                     "--encaixe", "desfocado", "--volume", "-16", "--pico", "-2", "--grao-redes", "--fim", "#3",
                     "--velocidade", "ultrafast", "--json"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert lines[-1]["status"] == "concluido"
    assert all("etapa" in x and "progresso" in x for x in lines[:-1])
    info = media.probe(str(out))
    assert (info.width, info.height) == (240, 240) and info.frames == 4
