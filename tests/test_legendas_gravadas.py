"""Legendas gravadas no vídeo pela receita do quadro (`frame.Recipe.burn`) e as opções de legenda da exportação.

"Gravada na cópia" entra antes do look (passa pelo grão e pela cor), "Digital" entra depois (por cima do quadro
final). A prévia da janela de exportação, a exportação e o `pelicula-cli quadro` dão o mesmo quadro bit a bit;
a faixa no arquivo e o .srt/.vtt ao lado saem com o tempo do trecho exportado.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess

import numpy as np
import pytest

from helpers import read_all
from pelicula import cli, export, frame, media, presets, project, subtitles as sb, textrender as tr
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings
from pelicula.subtitles import Cue

CUES = [Cue(0.0, 0.5, "Olá, ação!"), Cue(0.5, 2.0, "segunda fala")]


def burn(mode="digital", cues=CUES, style="youtube"):
    return sb.Burn.make(mode, sb.STYLES[style], cues)


def text_image(rgba: np.ndarray) -> tr.TextImage:
    return tr.TextImage(rgba, 0, 0, None)


# ------------------------------------------------------------------ sem Qt
def test_burn_make_json_and_active_lookup():
    style = sb.STYLES["youtube"]
    assert sb.Burn.make("nao", style, CUES) is None and sb.Burn.make("copia", style, []) is None
    assert sb.Burn.make("outro", style, CUES) is None
    b = burn("copia", [Cue(3, 4, "c"), Cue(0, 10, "longa"), Cue(1, 2, "b")])
    assert [c.text for c in b.cues] == ["longa", "b", "c"]
    again = sb.Burn.from_json(json.loads(json.dumps(b.to_json())))
    assert again == b and sb.Burn.from_json({}) is None and sb.Burn.from_json("x") is None
    for t in (0.0, 0.5, 1.0, 1.999, 2.0, 3.5, 4.0, 9.99, 10.0, 11.0):
        assert b.active(t) == sb.active(b.cues, t), t


def test_composite_is_premultiplied_over_a_copy():
    rgba = np.zeros((2, 2, 4), np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 128
    ov = sb.Overlay(text_image(rgba), 1, 1)
    dst = np.full((4, 4, 3), 100, np.uint8)
    out = sb.composite(dst, ov)
    a = 128 / 255
    assert (dst == 100).all()                                   # o quadro dado não muda
    assert tuple(out[1, 1]) == (round(255 * a + 100 * (1 - a)), round(100 * (1 - a)), round(100 * (1 - a)))
    assert tuple(out[0, 0]) == (100, 100, 100) and tuple(out[3, 3]) == (100, 100, 100)
    out16 = sb.composite(dst.astype(np.uint16) * 257, ov)      # 16 bits: o mesmo, na escala de 65535
    assert out16.dtype == np.uint16 and abs(int(out16[1, 1, 0]) - round(65535 * a + 25700 * (1 - a))) <= 1
    off = sb.Overlay(text_image(rgba), 10, 10)                 # fora do quadro: cópia igual
    assert np.array_equal(sb.composite(dst, off), dst)
    with_alpha = np.zeros((4, 4, 4), np.uint8)                 # RGBA (transparente): alfa direto
    got = sb.composite(with_alpha, ov)
    assert tuple(got[1, 1]) == (255, 0, 0, 128) and tuple(got[0, 0]) == (0, 0, 0, 0)


def test_default_delivery_and_job_fields():
    subs = sb.Subtitles(sources={"a.mp4": list(CUES)}, language="pt")
    assert sb.default_delivery(None, "mp4") == "nao" and sb.default_delivery(sb.Subtitles(), "mp4") == "nao"
    assert sb.default_delivery(subs, "mp4") == "faixa" and sb.default_delivery(subs, "avi") == "srt"
    subs.burn = "digital"
    assert sb.default_delivery(subs, "mp4") == "digital"
    subs.burn, subs.embed = "nao", False
    assert sb.default_delivery(subs, "mp4") == "nao"
    f = sb.delivery_fields("faixa", subs, CUES, "mkv")
    assert f["subtitles"]["idioma"] == "pt" and not f["burn"] and not f["subtitle_file"]
    f = sb.delivery_fields("faixa", subs, CUES, "avi")         # o recipiente não guarda: vai o .srt ao lado
    assert f["subtitle_file"]["formato"] == "srt" and not f["subtitles"]
    f = sb.delivery_fields("copia", subs, CUES, "mp4")
    assert sb.Burn.from_json(f["burn"]) == sb.Burn.make("copia", subs.style, CUES)
    assert sb.delivery_fields("vtt", subs, CUES, "mp4")["subtitle_file"]["formato"] == "vtt"
    assert sb.delivery_fields("nao", subs, CUES, "mp4") == {"subtitles": {}, "burn": {}, "subtitle_file": {}}
    assert sb.delivery_fields("srt", subs, [], "mp4")["subtitle_file"] == {}


def test_job_json_keeps_the_new_fields_only_when_used(make_info):
    info = make_info()
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="none")
    job = ExportJob(info=info, values={}, settings=s, out_path="C:/x/saida.mp4")
    d = job.to_dict()
    assert "legendas_gravadas" not in d and "legendas_arquivo" not in d
    job.burn = burn("copia").to_json()
    job.subtitle_file = sb.sidecar_payload(CUES, "vtt", "pt")
    again = ExportJob.from_dict(json.loads(json.dumps(job.to_dict())))
    assert again.burn == job.burn and again.subtitle_file == job.subtitle_file
    bad = ExportJob.from_dict({**job.to_dict(), "legendas_gravadas": 3, "legendas_arquivo": []})
    assert bad.burn == {} and bad.subtitle_file == {}


def test_sidecar_is_written_in_the_time_of_the_range(tmp_path):
    payload = sb.sidecar_payload([Cue(1.0, 2.0, "dentro"), Cue(5.0, 6.0, "fora"), Cue(0.5, 1.5, "corta")], "srt")
    out = tmp_path / "video.mp4"
    path = sb.write_sidecar(payload, str(out), 24, 96, 24.0)      # trecho de 1 s a 4 s
    assert path == str(tmp_path / "video.srt")
    cues = sb.load(path)
    assert [(c.text, c.start, c.end) for c in cues] == [("corta", 0.0, 0.5), ("dentro", 0.0, 1.0)]
    assert sb.write_sidecar(payload, str(out), 240, 300, 24.0) is None   # nada no trecho
    assert sb.write_sidecar({}, str(out), 0, 24, 24.0) is None


def test_run_job_writes_the_sidecar_next_to_the_video(make_info, tmp_path, monkeypatch):
    monkeypatch.setattr(export, "_encode_passes", lambda job, engine, run, s: True)
    monkeypatch.setattr(export, "_commit_output", lambda path, s: open(path, "wb").close())
    info = make_info(path=str(tmp_path / "entrada.mp4"), frames=480, duration=20.0, has_audio=False)
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="none")
    job = ExportJob(info=info, values={}, settings=s, out_path=str(tmp_path / "saida.mp4"), start_frame=48,
                    end_frame=239, subtitle_file=sb.sidecar_payload([Cue(3.0, 4.0, "dentro")], "vtt"))
    export.run_job(job, None)
    assert job.status == "concluido", job.error
    text = (tmp_path / "saida.vtt").read_text(encoding="utf-8")
    assert text.startswith("WEBVTT") and "00:00:01.000 --> 00:00:02.000\ndentro" in text


def test_run_job_reports_a_sidecar_that_cannot_be_written(make_info, tmp_path, monkeypatch):
    monkeypatch.setattr(export, "_encode_passes", lambda job, engine, run, s: True)
    monkeypatch.setattr(export, "_commit_output", lambda path, s: None)
    monkeypatch.setattr(sb, "save", lambda path, cues: (_ for _ in ()).throw(OSError("disco cheio")))
    info = make_info(path=str(tmp_path / "entrada.mp4"), has_audio=False)
    s = ExportSettings(codec="x264", container="mp4", pix="yuv420p", audio="none")
    job = ExportJob(info=info, values={}, settings=s, out_path=str(tmp_path / "saida.mp4"),
                    subtitle_file=sb.sidecar_payload([Cue(0.0, 1.0, "x")], "srt"))
    export.run_job(job, None)
    assert job.status == "erro" and "disco cheio" in job.error


# ------------------------------------------------------------------ com o Qt (desenho do texto)
def test_recipe_without_look_burns_in_both_places(qapp):
    img = np.full((180, 320, 3), 40, np.uint8)
    outs = {}
    for mode in ("copia", "digital"):
        r = frame.Recipe.for_source(None, 24.0, 8, legal=False, burn=burn(mode))
        out = r.look(None, img, 6)                           # 0,25 s: "Olá, ação!"
        assert out is not img and (out != 40).any() and (img == 40).all()
        assert r.look(None, img, 100) is img                 # 4,2 s: sem legenda, o mesmo quadro
        outs[mode] = out
    assert np.array_equal(outs["copia"], outs["digital"])   # sem look, os dois lugares dão o mesmo
    img16 = img.astype(np.uint16) * 257
    out16 = frame.Recipe.for_source(None, 24.0, 16, legal=False, burn=burn()).look(None, img16, 6)
    assert out16.dtype == np.uint16 and (out16 != img16).any()


def test_overlay_follows_the_time_and_the_style(qapp):
    b = burn("digital")
    a, c = b.overlay(0.25, 320, 180), b.overlay(1.0, 320, 180)
    assert a is not None and c is not None and a.image.layout.lines != c.image.layout.lines
    assert b.overlay(3.0, 320, 180) is None
    top = burn("digital", style="youtube")
    top = sb.Burn(top.mode, dataclasses.replace(top.style, position="cima", margin=10.0), top.cues)
    assert top.overlay(0.25, 320, 180).y < a.y


# ------------------------------------------------------------------ na GPU
@pytest.fixture
def film():
    v = presets.builtin_values("vision3_500t")
    v.update(grao_forca=1.4)
    return v


@pytest.mark.gpu
def test_copia_goes_through_the_look_and_digital_sits_on_top(gl_engine, qapp, test_rgb, film):
    img = np.ascontiguousarray(test_rgb)
    h, w = img.shape[:2]
    base = frame.Recipe.for_source(film, 24.0, 8, legal=False)
    plain = base.look(gl_engine, img, 6)
    dig = base.with_(burn=burn("digital")).look(gl_engine, img, 6)
    assert np.array_equal(dig, sb.composite(plain, burn("digital").overlay(0.25, w, h, 8)))
    cop = base.with_(burn=burn("copia")).look(gl_engine, img, 6)
    assert np.array_equal(cop, base.look(gl_engine, sb.composite(img, burn("copia").overlay(0.25, w, h, 8)), 6))
    assert not np.array_equal(cop, dig) and not np.array_equal(cop, plain)
    assert np.array_equal(base.with_(burn=burn("copia")).look(gl_engine, img, 100), base.look(gl_engine, img, 100))
    # a prévia reaproveita a imagem já enviada (upload=False): com legenda na cópia, a imagem vai de novo
    base.look(gl_engine, img, 6)
    again = base.with_(burn=burn("copia")).look(gl_engine, img, 6, upload=False)
    assert np.array_equal(again, cop)


def _ffv1() -> ExportSettings:
    return ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False)


@pytest.fixture
def gl_session(gl_engine):
    """`pelicula-cli quadro` cria e libera o próprio contexto OpenGL: reativa o da sessão no fim."""
    yield gl_engine
    gl_engine.ctx.__enter__()


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("mode", ["copia", "digital"])
def test_export_preview_and_cli_give_the_same_frame(gl_session, qapp, sample_video, tmp_path, film, mode):
    engine = gl_session
    info = media.probe(sample_video)
    seq = tl.Sequence.for_source(tl.Source.from_info(info))
    seq.subtitles = sb.Subtitles(sources={sample_video: list(CUES)}, burn=mode)
    cues = seq.subtitles.timeline_cues(seq)
    b = sb.Burn.make(mode, seq.subtitles.style, cues)
    s = _ffv1()
    out = tmp_path / f"{mode}.mkv"
    job = ExportJob(info=info, values=film, settings=s, out_path=str(out), start_frame=0, end_frame=7,
                    burn=b.to_json())
    export.run_job(job, engine)
    assert job.status == "concluido", job.error
    o = media.probe(str(out))
    frames = read_all(media.FrameReader(o, o.width, o.height, 16))
    plain = export.preview_frame(engine, info, film, s, 3, depth=16)
    for n in (3, 6):
        pv = export.preview_frame(engine, info, film, s, n, depth=16, burn=b)
        assert np.array_equal(pv, frames[n]), n
        assert not np.array_equal(pv, plain) or n != 3
    plc = tmp_path / f"{mode}.plc"                           # `pelicula-cli quadro`: a legenda que o projeto pede
    project.save(project.Project(media_path=sample_video, values=film, preset_id="vision3_500t",
                                 sequence=seq.to_json()), str(plc))
    png = tmp_path / f"{mode}.png"
    assert cli.main(["quadro", str(plc), "-o", str(png), "--tempo", "#3"]) == 0
    pinfo = media.probe(str(png))
    assert np.array_equal(media.grab_frame(pinfo, 0, pinfo.width, pinfo.height, 16), frames[3])


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_cli_export_track_and_sidecar(gl_session, qapp, sample_video, tmp_path, film):
    info = media.probe(sample_video)
    seq = tl.Sequence.for_source(tl.Source.from_info(info))
    seq.subtitles = sb.Subtitles(sources={sample_video: list(CUES)}, language="pt")
    plc = tmp_path / "leg.plc"
    project.save(project.Project(media_path=sample_video, values=film, preset_id="vision3_500t",
                                 sequence=seq.to_json()), str(plc))
    mkv = tmp_path / "faixa.mkv"                             # padrão do projeto: a faixa (o MKV guarda)
    assert cli.main(["exportar", str(plc), "-o", str(mkv), "--qualidade", "mp4", "--recipiente", "mkv",
                     "--audio", "none", "-q", "-y"]) == 0
    probe = subprocess.run([media.ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(mkv)],
                           capture_output=True, timeout=60)
    streams = json.loads(probe.stdout.decode("utf-8"))["streams"]
    subs = [st for st in streams if st["codec_type"] == "subtitle"]
    assert len(subs) == 1 and subs[0]["codec_name"] == "subrip"
    mp4 = tmp_path / "ao_lado.mp4"
    assert cli.main(["exportar", str(plc), "-o", str(mp4), "--legendas", "srt", "--audio", "none", "-q", "-y"]) == 0
    cues = sb.load(tmp_path / "ao_lado.srt")
    assert [c.text for c in cues] == ["Olá, ação!", "segunda fala"] and cues[-1].end == pytest.approx(1.0, abs=0.05)
    probe = subprocess.run([media.ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(mp4)],
                           capture_output=True, timeout=60)
    assert not [st for st in json.loads(probe.stdout.decode("utf-8"))["streams"] if st["codec_type"] == "subtitle"]
    assert not os.path.exists(tmp_path / "faixa.srt")
