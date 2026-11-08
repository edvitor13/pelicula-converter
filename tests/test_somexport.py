"""Exportar só o som e os stems (1.8, `somexport.py`, ARQUITETURA §43.6): o WAV de "Só o som" é a mixagem de sempre
(`audiomix.render_mix`), no trecho; os stems somados dão a mixagem; os outros formatos; o volume alvo; o som do arquivo no
modo Película; cancelar não deixa nada; e o terminal (`--so-som`, `--stems`). Nenhum som toca: tudo vai para arquivos."""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest

from pelicula import audiomix, cli, export, media, project, sequence, somexport
from pelicula import timeline as tl

from test_somcache import place, read, seq_of, write_wav

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def wavs(ffmpeg_ok, tmp_path_factory):
    d = tmp_path_factory.mktemp("somexport")
    return [write_wav(d / f"s{k}.wav", f, seed=k) for k, f in enumerate((220.0, 330.0, 523.0))]


def montage(w) -> tl.Sequence:
    seq = seq_of(w)
    seq.tracks[1].name = "Diálogo"           # A1
    seq.track(tl.AUDIO, 1).name = "Música"
    place(seq, w[0], 0, 50, 0.0, volume=-6.0)
    place(seq, w[1], 10, 40, 0.5, track=1, volume=-9.0)
    place(seq, w[2], 30, 30, 0.2, track=2, balanco=0.3)
    seq.track(tl.AUDIO, 1).volume = -3.0
    seq.track(tl.AUDIO, 2).pan = -0.4
    return seq


def job_for(seq, out, mode="som", fmt="pcm24", start=0, end=-1, **kw) -> export.ExportJob:
    s = export.ExportSettings(sound_only=mode, audio=fmt, **kw)
    return export.ExportJob(info=sequence.media_info(seq), values={}, settings=s, out_path=str(out),
                            start_frame=start, end_frame=end, sequence=seq)


def run(job) -> export.ExportJob:
    export.run_job(job, None)   # sem GPU: só o som não abre o contexto OpenGL
    assert job.status == "concluido", job.error
    return job


def probe_audio(path) -> tuple[str, float]:
    out = subprocess.run([media.ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=codec_name:format=duration", "-of", "json", str(path)],
                         capture_output=True, check=True).stdout
    d = json.loads(out)
    return d["streams"][0]["codec_name"], float(d["format"]["duration"])


def test_sound_only_is_the_mix_and_the_range(wavs, tmp_path):
    seq = montage(wavs)
    out = run(job_for(seq, tmp_path / "som.wav")).out_path
    ref = tmp_path / "ref.wav"
    assert audiomix.render_mix(seq, str(ref))
    assert np.array_equal(read(out), read(ref))
    part = run(job_for(seq, tmp_path / "trecho.wav", start=12, end=36)).out_path
    ref2 = tmp_path / "ref2.wav"
    assert audiomix.render_mix(seq, str(ref2), 12, 37)
    got = read(part)
    assert len(got) == 25 * 48000 // 25 and np.array_equal(got, read(ref2))
    assert not list(tmp_path.glob("*parcial-pelicula*"))


def test_stems_sum_to_the_mix(wavs, tmp_path):
    seq = montage(wavs)
    job = run(job_for(seq, tmp_path / "filme.wav", mode="stems", start=5, end=54))
    names = sorted(p.name for p in tmp_path.glob("filme_*.wav"))
    assert names == ["filme_A1_Diálogo.wav", "filme_A2_Música.wav", "filme_A3.wav"]
    assert not (tmp_path / "filme.wav").exists()
    parts = [read(tmp_path / n) for n in names]
    assert len({len(p) for p in parts}) == 1 and len(parts[0]) == 50 * 48000 // 25
    ref = tmp_path / "ref.wav"
    assert audiomix.render_mix(seq, str(ref), 5, 55)
    total = np.sum(parts, axis=0)
    assert np.abs(total - read(ref)).max() < 4 / 8388608.0   # cada stem arredonda para 24 bits sozinho
    assert np.abs(parts[2]).max() > 0.01 and job.done == job.total


def test_formats_and_loudness_target(wavs, tmp_path):
    seq = montage(wavs)
    for fmt, codec in (("flac", "flac"), ("aac320", "aac"), ("mp3", "mp3")):
        out = tmp_path / f"som.{somexport.EXT[fmt]}"
        run(job_for(seq, out, fmt=fmt, start=0, end=49))
        c, dur = probe_audio(out)
        assert c == codec and dur == pytest.approx(2.0, abs=0.08)
    loud = tmp_path / "alto.wav"
    run(job_for(seq, loud, loudness=-16.0, true_peak=-1.0))
    from pelicula import loudnorm
    m = loudnorm.measure(str(loud), -16.0, -1.0)
    assert m is not None and float(m["input_i"]) == pytest.approx(-16.0, abs=1.0)


def test_stem_names():
    assert somexport.stem_path("C:/x/video.wav", tl.AUDIO, 0, "A1") == str(
        __import__("pathlib").Path("C:/x/video_A1.wav"))
    assert somexport.stem_path("video.flac", tl.AUDIO, 2, "Voz / off", "flac").endswith("video_A3_Voz_off.flac")
    assert somexport.stem_path("video.wav", tl.VIDEO, 0, "V1").endswith("video_V1.wav")
    assert somexport.sound_format(export.ExportSettings(audio="copy")) == "pcm24"


def test_film_mode_exports_the_file_sound_and_refuses_stems(ffmpeg_ok, tmp_path):
    src = tmp_path / "clipe.mkv"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=25:d=2",
                    "-f", "lavfi", "-i", "sine=f=440:r=48000:d=2", "-c:v", "ffv1", "-c:a", "pcm_s16le",
                    str(src)], check=True)
    info = media.probe(str(src))
    s = export.ExportSettings(sound_only="som", audio="pcm24")
    job = export.ExportJob(info=info, values={}, settings=s, out_path=str(tmp_path / "som.wav"),
                           start_frame=10, end_frame=34)
    run(job)
    x = read(tmp_path / "som.wav")
    assert abs(len(x) - 48000) < 50 and np.abs(x).max() > 0.05
    s2 = export.ExportSettings(sound_only="stems")
    bad = export.ExportJob(info=info, values={}, settings=s2, out_path=str(tmp_path / "st.wav"))
    export.run_job(bad, None)
    assert bad.status == "erro" and "Edição" in bad.error and not list(tmp_path.glob("st*"))


def test_cancel_leaves_nothing(wavs, tmp_path):
    seq = montage(wavs)
    job = job_for(seq, tmp_path / "som.wav", mode="stems")
    job.cancel.set()
    export.run_job(job, None)
    assert job.status == "cancelado" and list(tmp_path.iterdir()) == []


@pytest.fixture
def keep_language():
    """`cli.main` escolhe o idioma (o do sistema, sem preferência): os testes seguintes continuam no de antes."""
    from pelicula import i18n
    before = i18n.language()
    yield
    i18n.set_language(before)


def test_cli_sound_only_and_stems(wavs, tmp_path, capsys, keep_language):
    seq = montage(wavs)
    plc = tmp_path / "proj.plc"
    project.save(project.Project(values={}, preset_id="", sequence=seq.to_json()), str(plc))
    out = tmp_path / "saida.flac"
    assert cli.main(["exportar", str(plc), "-o", str(out), "--so-som", "--inicio", "#0", "--fim", "#24", "-q"]) == 0
    assert probe_audio(out)[0] == "flac" and probe_audio(out)[1] == pytest.approx(1.0, abs=0.05)
    capsys.readouterr()
    assert cli.main(["exportar", str(plc), "-o", str(tmp_path / "st.wav"), "--stems", "--json"]) == 0
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res["status"] == "concluido" and len(res["arquivos"]) == 3
    with pytest.raises(cli.CliError):
        cli.cmd_export(cli.build_parser().parse_args(["exportar", str(plc), "--so-som", "--stems"]))
    with pytest.raises(cli.CliError, match="-y"):
        cli.cmd_export(cli.build_parser().parse_args(["exportar", str(plc), "-o", str(out), "--so-som"]))
    helptext = cli.build_parser()._subparsers._group_actions[0].choices["exportar"].format_help()
    assert "--so-som" in helptext and "--stems" in helptext and "uma faixa de som por arquivo" in helptext
