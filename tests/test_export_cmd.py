"""Exportação sem GPU e sem ffmpeg: tamanhos, áudio, comandos do codificador e qualidades prontas."""

from __future__ import annotations

from pathlib import Path

import pytest

from pelicula import export, media
from pelicula.export import CODECS, ExportSettings

ALL_ENCODERS = {c["enc"] for c in CODECS.values()} | {"mpeg4", "aac", "libmp3lame", "libopus", "pcm_s24le"}
IMAGE_CODECS = [k for k, c in CODECS.items() if c.get("image")]


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """O comando é montado sem procurar o ffmpeg de verdade; todos os codificadores 'existem', GPU não."""
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(media, "encoders", lambda: set(ALL_ENCODERS))
    monkeypatch.setattr(media, "encoder_works", lambda name: False)
    for key in CODECS:
        monkeypatch.setitem(CODECS[key], "enc", CODECS[key]["enc"])  # restaura se available() trocar
    return "ffmpeg"


def values_after(cmd: list[str], flag: str) -> list[str]:
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == flag]


def value_after(cmd: list[str], flag: str) -> str | None:
    vals = values_after(cmd, flag)
    return vals[-1] if vals else None


def settings_for(key: str, **over) -> ExportSettings:
    c = CODECS[key]
    lo, hi = c.get("qrange", (0, 0))
    s = ExportSettings(codec=key, container=c["exts"][0], pix=c["pix"][0], quality=(lo + hi) // 2,
                       preset=(c.get("presets") or [""])[0], profile=(c.get("profiles") or [("", "")])[0][0],
                       audio="none", tune_grain=bool(c.get("grain")))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def build(key, make_info, out="saida", depth=None, has_audio=False, start=0.0, dur=1.0, **over):
    s = settings_for(key, **over)
    info = make_info(width=320, height=180, has_audio=has_audio)
    depth = depth or (16 if export.high_depth(s) else 8)
    path = f"{out}.{s.container}"
    return s, export.build_encoder_cmd(path, info, s, 320, 180, "24/1", depth, start, dur), path


# ------------------------------------------------------------------ tamanho de saída
@pytest.mark.parametrize("codec, res, src, expected", [
    # deitado: a resolução é a altura (como sempre foi)
    ("x264", "original", (1920, 1080), (1920, 1080)),
    ("x264", "720", (1920, 1080), (1280, 720)),
    ("x264", "2160", (1920, 1080), (3840, 2160)),
    ("x264", "480", (1920, 1080), (852, 480)),       # 853,33 -> 853 -> par
    ("x264", "original", (1921, 1081), (1920, 1080)),
    ("x265", "1080", (4096, 2160), (2048, 1080)),
    ("x264", "1080", (3840, 1606), (2582, 1080)),    # 2,39:1
    # vertical: a resolução vale para o lado menor (a largura), como no YouTube e nos celulares
    ("x264", "1080", (1080, 1920), (1080, 1920)),    # "Redes sociais 1080p": antes saía 608 × 1080
    ("x264", "720", (1080, 1920), (720, 1280)),
    ("x264", "2160", (1080, 1920), (2160, 3840)),    # YouTube 4K vertical
    ("x264", "480", (1080, 1920), (480, 852)),       # 853,33 -> 853 -> par
    ("x264", "1080", (2160, 3840), (1080, 1920)),
    ("x264", "1080", (1080, 1350), (1080, 1350)),    # retrato 4:5
    ("x264", "720", (1080, 1350), (720, 900)),
    ("x264", "original", (1080, 1920), (1080, 1920)),
    # quadrado
    ("x264", "720", (1080, 1080), (720, 720)),
    ("x264", "2160", (1080, 1080), (2160, 2160)),
    # tamanhos ímpares: pares nos codecs de vídeo, exatos nos sem perdas e imagens
    ("x264", "720", (1081, 1921), (720, 1278)),      # 1279,48 -> 1279 -> par
    ("x264", "original", (1081, 1921), (1080, 1920)),
    ("ffv1", "720", (1081, 1921), (720, 1279)),
    ("x264", "541", (1920, 1080), (962, 540)),       # resolução ímpar (terminal): 961,78 -> 962; 541 -> 540
    ("ffv1", "original", (1921, 1081), (1921, 1081)),
    ("png", "original", (1921, 1081), (1921, 1081)),
    ("png", "1080", (3000, 4000), (1080, 1440)),     # foto em pé
    ("png_seq", "original", (321, 181), (321, 181)),
    ("png_seq", "90", (181, 321), (90, 160)),
    ("gif", "480", (1920, 1080), (853, 480)),
    ("gif", "480", (1080, 1920), (480, 853)),
    ("x264", "original", (1, 1), (2, 2)),
])
def test_output_size(make_info, codec, res, src, expected):
    info = make_info(width=src[0], height=src[1])
    s = ExportSettings(codec=codec, resolution=res)
    assert export.output_size(info, s) == expected


@pytest.mark.parametrize("key", [k for k in CODECS if not CODECS[k].get("image")
                                 and k not in ("png_seq", "tiff_seq", "ffv1", "gif")])
@pytest.mark.parametrize("res", [r for r, _ in export.RESOLUTIONS])
def test_output_size_even_for_video_codecs(make_info, key, res):
    for w, h in ((1921, 1081), (1279, 719), (3839, 2161), (1080, 1920), (1081, 1921), (719, 1279), (1080, 1080)):
        ow, oh = export.output_size(make_info(width=w, height=h), ExportSettings(codec=key, resolution=res))
        assert ow % 2 == 0 and oh % 2 == 0
        assert (ow >= oh) == (w >= h), "a orientação do vídeo não pode mudar"
        if res != "original":
            assert min(ow, oh) == int(res) - int(res) % 2  # a resolução é o lado menor


@pytest.mark.parametrize("res", [r for r, _ in export.RESOLUTIONS if r != "original"])
def test_output_size_keeps_the_aspect_ratio(make_info, res):
    for w, h in ((1920, 1080), (1080, 1920), (1080, 1350), (3840, 1606), (1440, 1080), (1080, 1080)):
        ow, oh = export.output_size(make_info(width=w, height=h), ExportSettings(codec="ffv1", resolution=res))
        assert abs(ow / oh - w / h) < 0.01 * (w / h), (w, h, ow, oh)


def test_social_preset_keeps_a_vertical_video_vertical(fake_ffmpeg, make_info):
    """Regressão (issue #35): 1080 × 1920 em "Redes sociais 1080p" saía 608 × 1080."""
    for w, h in ((1080, 1920), (1920, 1080), (1080, 1080)):
        info = make_info(width=w, height=h)
        by = {pid: s for pid, _label, s in export.quality_presets(info)}
        assert export.output_size(info, by["social"]) == (w, h)
        assert export.output_size(info, by["fhd"]) == (w, h)
        assert min(export.output_size(info, by["leve"])) == 720
        assert min(export.output_size(info, by["yt4k_hevc"])) == 2160
        assert min(export.output_size(info, by["gif"])) == 480


# ------------------------------------------------------------------ áudio
@pytest.mark.parametrize("codec, container, audio, src_codec, expected", [
    ("x264", "mp4", "pcm24", "aac", ["-c:a", "aac", "-b:a", "320k"]),
    ("x264", "mp4", "aac192", "aac", ["-c:a", "aac", "-b:a", "192k"]),
    ("x264", "mp4", "copy", "aac", ["-c:a", "copy"]),
    ("x264", "mp4", "copy", "pcm_s16le", ["-c:a", "aac", "-b:a", "320k"]),
    ("x264", "mov", "copy", "pcm_s24le", ["-c:a", "copy"]),
    ("x264", "mov", "copy", "opus", ["-c:a", "pcm_s24le"]),
    ("x264", "mov", "pcm24", "aac", ["-c:a", "pcm_s24le"]),
    ("x264", "mkv", "copy", "truehd", ["-c:a", "copy"]),
    ("vp9", "webm", "aac320", "aac", ["-c:a", "libopus", "-b:a", "192k"]),
    ("vp9", "webm", "copy", "aac", ["-c:a", "libopus", "-b:a", "192k"]),
    ("vp9", "webm", "copy", "opus", ["-c:a", "copy"]),
    ("xvid", "avi", "aac320", "aac", ["-c:a", "libmp3lame", "-b:a", "320k"]),
    ("xvid", "avi", "copy", "aac", ["-c:a", "libmp3lame", "-b:a", "320k"]),
    ("xvid", "avi", "copy", "mp3", ["-c:a", "copy"]),
    ("xvid", "avi", "mp3", "aac", ["-c:a", "libmp3lame", "-b:a", "320k"]),
    ("ffv1", "mkv", "pcm24", "aac", ["-c:a", "pcm_s24le"]),
    ("gif", "gif", "aac320", "aac", ["-an"]),
    ("png_seq", "png", "aac320", "aac", ["-an"]),
    ("tiff_seq", "tif", "copy", "aac", ["-an"]),
    ("png", "png", "copy", "aac", ["-an"]),
    ("jpg", "jpg", "aac320", "aac", ["-an"]),
    ("x264", "mp4", "none", "aac", ["-an"]),
])
def test_audio_args(make_info, codec, container, audio, src_codec, expected):
    s = ExportSettings(codec=codec, container=container, audio=audio)
    assert export._audio_args(s, make_info(audio_codec=src_codec)) == expected


def test_audio_args_without_source_audio(make_info):
    s = ExportSettings(codec="x264", container="mp4", audio="aac320")
    assert export._audio_args(s, make_info(has_audio=False, audio_codec="")) == ["-an"]


# ------------------------------------------------------------------ comando do codificador
@pytest.mark.parametrize("key", list(CODECS))
def test_encoder_cmd_structure(fake_ffmpeg, make_info, key):
    s, cmd, path = build(key, make_info)
    c = CODECS[key]
    depth = 16 if export.high_depth(s) else 8
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == path
    i = cmd.index("rawvideo")
    assert cmd[i - 1] == "-f"
    assert cmd[i + 1:i + 9] == ["-pix_fmt", "rgb24" if depth == 8 else "rgb48le", "-s", "320x180",
                                "-framerate", "24/1", "-i", "pipe:0"]
    assert value_after(cmd, "-c:v") == c["enc"]
    assert values_after(cmd, "-pix_fmt")[-1] == s.pix
    assert cmd.index("-pix_fmt", i + 2) > cmd.index("-c:v")
    assert values_after(cmd, "-map") == ["0:v:0"]
    assert "-an" in cmd
    if c.get("image"):
        assert value_after(cmd, "-frames:v") == "1" and value_after(cmd, "-update") == "1"
    else:
        assert "-frames:v" not in cmd
    if s.container in ("mp4", "mov"):
        assert value_after(cmd, "-movflags") == "+faststart"
    else:
        assert "-movflags" not in cmd


@pytest.mark.parametrize("key", list(CODECS))
def test_encoder_cmd_color_handling(fake_ffmpeg, make_info, key):
    for pix in CODECS[key]["pix"]:
        s, cmd, _ = build(key, make_info, pix=pix)
        vf = value_after(cmd, "-vf")
        rgb = pix.startswith(("rgb", "gbr", "pal"))
        if key == "gif":
            assert "palettegen" in vf and "paletteuse" in vf
            assert "-colorspace" not in cmd
        elif rgb:
            assert vf is None
            assert "-colorspace" not in cmd
        else:
            matrix = "bt601" if key in ("jpg", "webp") else "bt709"
            rng = "full" if pix.startswith("yuvj") else "limited"
            assert vf.startswith(f"scale=out_color_matrix={matrix}:out_range={rng}")
            assert vf.endswith(f",format={pix}")
            if pix.startswith("yuvj") or key == "webp":
                assert "-colorspace" not in cmd
            else:
                assert value_after(cmd, "-colorspace") == "bt709"
                assert value_after(cmd, "-color_primaries") == "bt709"
                assert value_after(cmd, "-color_trc") == "bt709"
                assert value_after(cmd, "-color_range") == "tv"


@pytest.mark.parametrize("key, container, tag", [
    ("x265", "mp4", True), ("x265", "mov", True), ("x265", "mkv", False),
    ("hevc_nvenc", "mp4", True), ("hevc_nvenc", "mkv", False), ("hevc_qsv", "mov", True), ("hevc_amf", "mp4", True),
    ("x264", "mp4", False), ("h264_nvenc", "mp4", False),
])
def test_hevc_gets_hvc1_tag_in_mp4_and_mov(fake_ffmpeg, make_info, key, container, tag):
    _, cmd, _ = build(key, make_info, container=container)
    assert (value_after(cmd, "-tag:v") == "hvc1") is tag


@pytest.mark.parametrize("key", ["x264", "x265"])
def test_x26x_crf_preset_and_grain(fake_ffmpeg, make_info, key):
    _, cmd, _ = build(key, make_info, quality=17.5, preset="slower", tune_grain=True)
    assert value_after(cmd, "-crf") == "17.5"
    assert value_after(cmd, "-preset") == "slower"
    assert value_after(cmd, "-tune") == "grain"
    assert "-b:v" not in cmd
    _, cmd, _ = build(key, make_info, tune_grain=False, preset="")
    assert "-tune" not in cmd and value_after(cmd, "-preset") == "slow"
    if key == "x265":
        assert value_after(cmd, "-x265-params").startswith("log-level=error")


def test_x264_bitrate_mode(fake_ffmpeg, make_info):
    _, cmd, _ = build("x264", make_info, bitrate=10.0)
    assert value_after(cmd, "-b:v") == "10.0M"
    assert value_after(cmd, "-maxrate") == "15.0M"
    assert value_after(cmd, "-bufsize") == "20.0M"
    assert "-crf" not in cmd


def test_threads_flags(fake_ffmpeg, make_info):
    _, cmd, _ = build("x264", make_info, threads=4)
    assert value_after(cmd, "-threads") == "4"
    assert "threads=4" in value_after(cmd, "-vf")
    _, cmd, _ = build("x265", make_info, threads=4)
    assert "-threads" not in cmd and value_after(cmd, "-x265-params") == "log-level=error:pools=4"
    _, cmd, _ = build("hevc_nvenc", make_info, threads=4)
    assert "-threads" not in cmd
    _, cmd, _ = build("x264", make_info, threads=0)
    assert "-threads" not in cmd and "threads=0" in value_after(cmd, "-vf")


def test_nvenc_flags(fake_ffmpeg, make_info):
    _, cmd, _ = build("hevc_nvenc", make_info, quality=17, preset="p6", gpu=1)
    assert value_after(cmd, "-gpu") == "1"
    assert value_after(cmd, "-cq") == "17" and value_after(cmd, "-b:v") == "0"
    assert value_after(cmd, "-rc") == "vbr" and value_after(cmd, "-tune") == "hq"
    assert value_after(cmd, "-spatial-aq") == "1" and value_after(cmd, "-temporal-aq") == "1"
    _, cmd, _ = build("h264_nvenc", make_info, bitrate=8.0)
    assert value_after(cmd, "-b:v") == "8.0M" and value_after(cmd, "-maxrate") == "12.0M" and "-cq" not in cmd


def test_qsv_and_amf_flags(fake_ffmpeg, make_info):
    _, cmd, _ = build("hevc_qsv", make_info, quality=20)
    assert value_after(cmd, "-global_quality") == "20"
    _, cmd, _ = build("h264_amf", make_info, quality=20, preset="quality")
    assert value_after(cmd, "-rc") == "cqp" and value_after(cmd, "-quality") == "quality"
    assert value_after(cmd, "-qp_i") == value_after(cmd, "-qp_p") == value_after(cmd, "-qp_b") == "20"
    _, cmd, _ = build("hevc_amf", make_info, quality=20)
    assert "-qp_b" not in cmd


@pytest.mark.parametrize("key, flags", [
    ("av1", {"-crf": "31", "-preset": "13"}),
    ("vp9", {"-crf": "31", "-b:v": "0", "-row-mt": "1", "-deadline": "good", "-cpu-used": "8"}),
    ("xvid", {"-q:v": "16", "-vtag": "XVID"}),
    ("prores", {"-profile:v": "0", "-vendor": "apl0"}),
    ("dnxhr", {"-profile:v": "dnxhr_lb"}),
    ("ffv1", {"-level": "3", "-g": "1", "-slicecrc": "1"}),
    ("gif", {"-loop": "0"}),
    ("jpg", {"-q:v": "16"}),
    ("webp", {"-quality": "50"}),
    ("tiff", {"-compression_algo": "deflate"}),
    ("tiff_seq", {"-compression_algo": "deflate"}),
])
def test_codec_specific_flags(fake_ffmpeg, make_info, key, flags):
    _, cmd, _ = build(key, make_info)
    for flag, val in flags.items():
        assert value_after(cmd, flag) == val, flag


@pytest.mark.parametrize("key, profile", [("prores", "3"), ("prores", "5"), ("dnxhr", "dnxhr_hqx")])
def test_profiles(fake_ffmpeg, make_info, key, profile):
    _, cmd, _ = build(key, make_info, profile=profile)
    assert value_after(cmd, "-profile:v") == profile


def test_audio_inputs_and_trim(fake_ffmpeg, make_info):
    s = settings_for("x264", audio="aac320")
    info = make_info(width=320, height=180, path="C:/v/entrada.mp4")
    cmd = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 2.5, 4.0, input_path=r"\\.\pipe\x")
    assert values_after(cmd, "-i") == [r"\\.\pipe\x", "C:/v/entrada.mp4"]
    assert value_after(cmd, "-ss") == "2.500000" and value_after(cmd, "-t") == "4.000000"
    assert cmd.index("-ss") < cmd.index("C:/v/entrada.mp4")
    assert values_after(cmd, "-map") == ["0:v:0", "1:a:0?"]
    assert value_after(cmd, "-c:a") == "aac" and value_after(cmd, "-b:a") == "320k"
    assert "-an" not in cmd
    cmd0 = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 0.0, 4.0)
    assert "-ss" not in cmd0


def test_16bit_input_pixel_format(fake_ffmpeg, make_info):
    _, cmd, _ = build("prores", make_info, depth=16)
    assert cmd[cmd.index("rawvideo") + 2] == "rgb48le"


def test_sequence_path(tmp_path):
    p = export.sequence_path(str(tmp_path / "saida.png"))
    assert (tmp_path / "saida").is_dir()
    assert Path(p) == tmp_path / "saida" / "saida_%06d.png"


# ------------------------------------------------------------------ gravação segura (sem ffmpeg)
VIDEO = ExportSettings(codec="x264", container="mp4")
PNG_SEQ = ExportSettings(codec="png_seq", container="png", pix="rgb48be")


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def fake_frames(folder: Path, stem: str, ext: str, n: int, tag: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for k in range(1, n + 1):
        (folder / f"{stem}_{k:06d}{ext}").write_text(f"{tag}{k}")


def test_partial_names_keep_the_real_extension_last():
    """`video.parcial-pelicula.mp4`: o ffmpeg escolhe o formato pela extensão, igual ao do arquivo final."""
    assert Path(export.partial_output("C:/v/saida.mp4", VIDEO)) == Path("C:/v/saida.parcial-pelicula.mp4")
    assert Path(export.partial_output("C:/v/meu.filme.mov", VIDEO)) == Path("C:/v/meu.filme.parcial-pelicula.mov")
    assert Path(export.partial_output("C:/v/quadros.png", PNG_SEQ)) == Path("C:/v/quadros.parcial-pelicula")
    assert export.output_target("C:/v/saida.mp4", VIDEO) == "C:/v/saida.mp4"
    assert Path(export.output_target("C:/v/quadros.png", PNG_SEQ)) == Path("C:/v/quadros")
    assert export.is_sequence(PNG_SEQ) and export.is_sequence(ExportSettings(codec="tiff_seq"))
    assert not export.is_sequence(VIDEO) and not export.is_sequence(ExportSettings(codec="png"))


def test_encoder_writes_to_the_partial_and_the_name_changes_at_the_end(tmp_path):
    out = tmp_path / "saida.mp4"
    out.write_bytes(b"antigo")
    stale = tmp_path / "saida.parcial-pelicula.mp4"
    stale.write_bytes(b"sobra de uma exportacao interrompida")
    target = export._prepare_output(str(out), VIDEO)
    assert Path(target) == stale and not stale.exists()  # o parcial velho foi apagado
    Path(target).write_bytes(b"novo")
    assert out.read_bytes() == b"antigo"  # até o fim, o antigo continua lá
    export._commit_output(str(out), VIDEO)
    assert out.read_bytes() == b"novo" and names(tmp_path) == ["saida.mp4"]


def test_discard_keeps_the_old_file(tmp_path):
    out = tmp_path / "saida.mp4"
    out.write_bytes(b"antigo")
    Path(export._prepare_output(str(out), VIDEO)).write_bytes(b"pela metade")
    export._discard_output(str(out), VIDEO)
    assert out.read_bytes() == b"antigo" and names(tmp_path) == ["saida.mp4"]


def test_output_exists_for_files_and_sequences(tmp_path):
    out = str(tmp_path / "quadros.png")
    assert not export.output_exists(out, PNG_SEQ) and not export.output_exists(out, VIDEO)
    (tmp_path / "quadros").mkdir()
    (tmp_path / "quadros" / "outra_coisa.png").write_text("x")
    assert not export.output_exists(out, PNG_SEQ)  # pasta sem quadros desta sequência
    fake_frames(tmp_path / "quadros", "quadros", ".png", 1, "v")
    assert export.output_exists(out, PNG_SEQ)
    Path(out).write_text("x")
    assert export.output_exists(out, VIDEO)


def test_new_sequence_folder_appears_in_one_step(tmp_path):
    out = str(tmp_path / "quadros.png")
    target = export._prepare_output(out, PNG_SEQ)
    assert Path(target) == tmp_path / "quadros.parcial-pelicula" / "quadros_%06d.png"
    assert names(tmp_path) == ["quadros.parcial-pelicula"]
    fake_frames(tmp_path / "quadros.parcial-pelicula", "quadros", ".png", 3, "novo")
    export._commit_output(out, PNG_SEQ)
    assert names(tmp_path) == ["quadros"]
    assert names(tmp_path / "quadros") == [f"quadros_{k:06d}.png" for k in (1, 2, 3)]


def test_sequence_replaces_old_frames_only_at_the_end(tmp_path):
    """Quadros antigos ficam intactos até o fim; os que sobram de uma exportação mais longa saem, e
    arquivos da pessoa na mesma pasta nunca são apagados."""
    out = str(tmp_path / "quadros.png")
    final = tmp_path / "quadros"
    fake_frames(final, "quadros", ".png", 6, "velho")
    (final / "notas.txt").write_text("minhas notas")
    (final / "quadros_final.png").write_text("da pessoa")
    export._prepare_output(out, PNG_SEQ)
    fake_frames(tmp_path / "quadros.parcial-pelicula", "quadros", ".png", 4, "novo")
    assert (final / "quadros_000001.png").read_text() == "velho1"
    export._commit_output(out, PNG_SEQ)
    assert names(final) == ["notas.txt", "quadros_000001.png", "quadros_000002.png", "quadros_000003.png",
                            "quadros_000004.png", "quadros_final.png"]
    assert [(final / f"quadros_{k:06d}.png").read_text() for k in (1, 4)] == ["novo1", "novo4"]
    assert names(tmp_path) == ["quadros"]


def test_partial_marker_is_not_a_common_word(tmp_path):
    """`entrevista.parcial.mp4` pode ser um arquivo da pessoa: a exportação para `entrevista.mp4` não o apaga."""
    mine = tmp_path / "entrevista.parcial.mp4"
    mine.write_bytes(b"corte parcial da pessoa")
    out = tmp_path / "entrevista.mp4"
    Path(export._prepare_output(str(out), VIDEO)).write_bytes(b"novo")
    export._commit_output(str(out), VIDEO)
    assert mine.read_bytes() == b"corte parcial da pessoa" and out.read_bytes() == b"novo"
    assert names(tmp_path) == ["entrevista.mp4", "entrevista.parcial.mp4"]


def test_partial_clash_with_an_input(tmp_path, make_info):
    out = str(tmp_path / "x.mp4")
    part = export.partial_output(out, VIDEO)
    assert export.partial_clash(out, VIDEO, [part]) == part
    assert export.partial_clash(out, VIDEO, [str(tmp_path / "x.mp4"), str(tmp_path / "y.mp4"), ""]) == ""
    seq_out = str(tmp_path / "q.png")
    inside = str(Path(export.partial_output(seq_out, PNG_SEQ)) / "q_000001.png")
    assert export.partial_clash(seq_out, PNG_SEQ, [inside]) == inside
    assert export.partial_clash(seq_out, VIDEO, [inside]) == ""
    info = make_info(path=part)
    assert export.job_inputs(info) == [part]


def test_run_job_refuses_to_delete_an_input_named_like_its_partial(tmp_path, make_info):
    """A pessoa abriu o parcial que sobrou (`x.parcial-pelicula.mp4`) e exporta para `x.mp4`: nada é apagado."""
    src = tmp_path / "x.parcial-pelicula.mp4"
    src.write_bytes(b"o resultado que tinha ficado no parcial")
    job = export.ExportJob(info=make_info(path=str(src)), values={}, settings=VIDEO, out_path=str(tmp_path / "x.mp4"))
    export.run_job(job, None)  # recusa antes de usar a GPU ou o ffmpeg
    assert job.status == "erro" and str(src) in job.error
    assert src.read_bytes() == b"o resultado que tinha ficado no parcial"
    assert names(tmp_path) == ["x.parcial-pelicula.mp4"]


def test_sequence_discard_and_stale_partial_folder(tmp_path):
    out = str(tmp_path / "quadros.tif")
    s = ExportSettings(codec="tiff_seq", container="tif", pix="rgb48le")
    final = tmp_path / "quadros"
    fake_frames(final, "quadros", ".tif", 2, "velho")
    fake_frames(tmp_path / "quadros.parcial-pelicula", "quadros", ".tif", 5, "sobra")  # exportação interrompida
    export._prepare_output(out, s)
    assert names(tmp_path / "quadros.parcial-pelicula") == []  # o parcial velho foi limpo
    fake_frames(tmp_path / "quadros.parcial-pelicula", "quadros", ".tif", 3, "pela metade")
    export._discard_output(out, s)
    assert names(tmp_path) == ["quadros"]
    assert [(final / n).read_text() for n in names(final)] == ["velho1", "velho2"]
    # algo que não é desta sequência na pasta parcial nunca é apagado
    fake_frames(tmp_path / "quadros.parcial-pelicula", "quadros", ".tif", 2, "x")
    (tmp_path / "quadros.parcial-pelicula" / "outro.txt").write_text("x")
    export._discard_output(out, s)
    assert names(tmp_path / "quadros.parcial-pelicula") == ["outro.txt"]


# ------------------------------------------------------------------ profundidade e configurações
@pytest.mark.parametrize("codec, pix, expected", [
    ("x264", "yuv420p", False), ("x264", "yuv444p", False), ("x264", "yuv420p10le", True),
    ("x265", "yuv420p12le", True), ("hevc_nvenc", "p010le", True), ("hevc_nvenc", "yuv444p16le", True),
    ("png", "rgb48be", True), ("png", "rgb24", False), ("prores", "yuv422p10le", True), ("ffv1", "yuv420p", True),
    ("gif", "pal8", False), ("jpg", "yuvj444p", False),
])
def test_high_depth(codec, pix, expected):
    assert export.high_depth(ExportSettings(codec=codec, pix=pix)) is expected


@pytest.mark.parametrize("codec", ["h264_qsv", "hevc_qsv", "h264_amf"])
def test_high_depth_nv12_is_8bit(codec):
    """Regressão: 'nv12' contém "12" mas é 8 bits (antes ligava o caminho de 16 bits e desligava o dither)."""
    assert export.high_depth(ExportSettings(codec=codec, pix="nv12")) is False


PIX_BITS = {"yuv420p": 8, "yuv422p": 8, "yuv444p": 8, "yuvj444p": 8, "nv12": 8, "pal8": 8, "rgb24": 8,
            "yuv420p10le": 10, "yuv422p10le": 10, "yuv444p10le": 10, "p010le": 10, "yuv420p12le": 12,
            "yuv444p16le": 16, "rgb48le": 16, "rgb48be": 16, "rgba": 8, "rgba64be": 16, "rgba64le": 16,
            "yuva420p": 8, "yuva444p10le": 10}


@pytest.mark.parametrize("pix", sorted({p for c in CODECS.values() for p in c["pix"]}))
def test_pix_depth_of_every_codec_format(pix):
    if not hasattr(export, "pix_depth"):
        pytest.skip("export.pix_depth não existe nesta versão")
    if pix not in PIX_BITS:
        pytest.skip(f"formato novo sem valor esperado: {pix}")
    assert export.pix_depth(pix) == PIX_BITS[pix]
    assert export.high_depth(ExportSettings(codec="x264", pix=pix)) is (PIX_BITS[pix] > 8)


def test_export_settings_dict_roundtrip():
    s = ExportSettings(codec="x265", container="mkv", pix="yuv420p10le", quality=20, threads=6, priority="baixa")
    d = s.to_dict()
    assert d["codec"] == "x265" and d["threads"] == 6
    assert ExportSettings.from_dict(d) == s
    t = ExportSettings.from_dict({"codec": "vp9", "nao_existe": 1})
    assert t.codec == "vp9" and not hasattr(t, "nao_existe")
    assert ExportSettings.from_dict(None) == ExportSettings()


def test_export_settings_perf():
    p = ExportSettings(threads="3", priority="alta", hwaccel="cuda", gpu="1", buffer="6").perf()
    assert (p.threads, p.priority, p.hwaccel, p.gpu, p.buffer) == (3, "alta", "cuda", 1, 6)


@pytest.mark.parametrize("txt, val", [("24", 24.0), ("24000/1001", 23.976023976), ("30000/1001", 29.97002997),
                                      ("12.5", 12.5)])
def test_eval_fraction(txt, val):
    assert export.eval_fraction(txt) == pytest.approx(val)


@pytest.mark.parametrize("fps, start, end, expected", [
    ("original", 0, -1, 240), ("original", 10, 19, 10), ("original", 0, 9999, 240), ("original", -5, 9, 10),
    ("12", 0, -1, 120), ("60", 0, 23, 60), ("30000/1001", 0, -1, 300), ("24000/1001", 0, -1, 240),
])
def test_job_frames(make_info, fps, start, end, expected):
    info = make_info(frames=240, fps=24.0, fps_str="24/1")
    assert export.job_frames(info, ExportSettings(fps=fps), start, end) == expected


def test_job_frames_image(make_info):
    assert export.job_frames(make_info(is_image=True, frames=1), ExportSettings(codec="png")) == 1


def test_export_job_progress(make_info):
    job = export.ExportJob(info=make_info(), values={}, settings=ExportSettings(), out_path="x.mp4")
    assert job.progress == 0.0 and job.status == "aguardando" and len(job.id) == 8
    job.total, job.done = 40, 10
    assert job.progress == 0.25
    other = export.ExportJob(info=make_info(), values={}, settings=ExportSettings(), out_path="y.mp4")
    assert other.id != job.id and other.cancel is not job.cancel


# ------------------------------------------------------------------ qualidades prontas
def assert_coherent(pid: str, s: ExportSettings):
    assert s.codec in CODECS, pid
    c = CODECS[s.codec]
    assert s.container in c["exts"], f"{pid}: {s.container} não está em {c['exts']}"
    assert s.pix in c["pix"], f"{pid}: {s.pix} não está em {c['pix']}"
    if "qrange" in c:
        lo, hi = c["qrange"]
        assert lo <= s.quality <= hi, pid
    if c.get("presets") and s.preset:
        assert s.preset in c["presets"], pid
    if c.get("profiles"):
        assert s.profile in [p for p, _ in c["profiles"]], pid
    assert s.resolution in [r for r, _ in export.RESOLUTIONS], pid
    assert s.fps in [f for f, _ in export.FPS], pid
    assert s.audio in [a for a, _ in export.AUDIO], pid


def test_quality_presets_for_image(fake_ffmpeg, make_info):
    out = export.quality_presets(make_info(path="C:/f/foto.png", is_image=True, frames=1, codec="png",
                                           pix_fmt="rgb24", has_audio=False))
    ids = [pid for pid, _, _ in out]
    assert ids == ["img_png", "img_tiff", "img_jpg", "img_webp"]
    for pid, label, s in out:
        assert label
        assert s.audio == "none"
        assert CODECS[s.codec].get("image"), pid
        assert_coherent(pid, s)
    by = {pid: s for pid, _, s in out}
    assert by["img_png"].pix == "rgb48be" and export.high_depth(by["img_png"])


def test_quality_presets_for_video(fake_ffmpeg, make_info):
    out = export.quality_presets(make_info())
    ids = [pid for pid, _, _ in out]
    assert ids[0] == "original"
    assert len(ids) == len(set(ids))
    for must in ("mp4", "mov", "mkv", "yt4k_hevc", "fhd", "leve", "webm", "avi", "gif", "prores_hq", "ffv1", "png_seq"):
        assert must in ids
    assert not {"gpu", "gpu_intel", "gpu_amd"} & set(ids)
    for pid, label, s in out:
        assert label
        assert not CODECS[s.codec].get("image"), pid
        assert_coherent(pid, s)
    assert "original" not in [pid for pid, _, _ in export.quality_presets(None)]


def test_quality_presets_include_gpu_when_encoders_work(fake_ffmpeg, make_info, monkeypatch):
    monkeypatch.setattr(media, "encoder_works", lambda name: True)
    ids = [pid for pid, _, s in export.quality_presets(make_info())]
    assert {"gpu", "gpu_intel", "gpu_amd"} <= set(ids)
    for pid, _, s in export.quality_presets(make_info()):
        assert_coherent(pid, s)


def test_available_falls_back_to_mpeg4_without_libxvid(fake_ffmpeg, monkeypatch):
    monkeypatch.setattr(media, "encoders", lambda: ALL_ENCODERS - {"libxvid"})
    assert export.available("xvid")
    assert CODECS["xvid"]["enc"] == "mpeg4"
    monkeypatch.setattr(media, "encoders", lambda: {"libx264"})
    assert export.available("x264") and not export.available("vp9")
    assert not export.available("hevc_nvenc")


@pytest.mark.parametrize("src, codec, container, pix, profile", [
    (dict(codec="h264", pix_fmt="yuv420p", path="a.mp4"), "x264", "mp4", "yuv420p", ""),
    (dict(codec="h264", pix_fmt="yuv422p", path="a.mov"), "x264", "mov", "yuv422p", ""),
    (dict(codec="h264", pix_fmt="yuv420p", path="a.avi"), "x264", "mp4", "yuv420p", ""),
    (dict(codec="hevc", pix_fmt="yuv420p", path="a.mkv"), "x265", "mkv", "yuv420p", ""),
    (dict(codec="hevc", pix_fmt="yuv422p10le", bit_depth=10, path="a.mov"), "x265", "mov", "yuv422p10le", ""),
    (dict(codec="h264", pix_fmt="yuv444p10le", bit_depth=10, path="a.mp4"), "x265", "mp4", "yuv444p10le", ""),
    (dict(codec="prores", profile="HQ", pix_fmt="yuv422p10le", bit_depth=10, path="a.mov"), "prores", "mov",
     "yuv422p10le", "3"),
    (dict(codec="prores", profile="4444", pix_fmt="yuva444p10le", bit_depth=10, path="a.mov"), "prores", "mov",
     "yuv444p10le", "4"),
    (dict(codec="prores", profile="XQ", pix_fmt="yuv444p12le", bit_depth=12, path="a.mov"), "prores", "mov",
     "yuv444p10le", "5"),
    (dict(codec="dnxhd", pix_fmt="yuv422p", path="a.mxf"), "dnxhr", "mov", "yuv422p", "dnxhr_hq"),
    (dict(codec="dnxhd", pix_fmt="yuv422p10le", bit_depth=10, path="a.mxf"), "dnxhr", "mov", "yuv422p10le",
     "dnxhr_hqx"),
    (dict(codec="vp9", pix_fmt="yuv420p", path="a.webm"), "vp9", "webm", "yuv420p", ""),
])
def test_original_preset_matches_source(fake_ffmpeg, make_info, src, codec, container, pix, profile):
    s = export._original(make_info(**src))
    assert (s.codec, s.container, s.pix, s.profile) == (codec, container, pix, profile)
    assert_coherent("original", s)


def test_sequence_audio_input_has_no_seek(fake_ffmpeg, make_info):
    """Modo Edição: o som já vem mixado e recortado num WAV; entra sem -ss, com a duração do trecho."""
    info = make_info(audio_codec="pcm_s24le")
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="aac192")
    cmd = export.build_encoder_cmd("o.mp4", info, s, 320, 180, "24/1", 8, 2.5, 4.0, audio_path="mix.wav")
    i = cmd.index("mix.wav")
    assert cmd[i - 1] == "-i" and cmd[i - 3:i - 1] == ["-t", "4.000000"]
    assert "-ss" not in cmd and info.path not in cmd
    assert value_after(cmd, "-c:a") == "aac"
    s.container, s.codec, s.audio = "mkv", "x264", "copy"
    cmd = export.build_encoder_cmd("o.mkv", info, s, 320, 180, "24/1", 8, 2.5, 4.0, audio_path="mix.wav")
    assert value_after(cmd, "-c:a") == "copy"  # PCM cabe no MKV; sem recorte no arquivo, sem recodificar
