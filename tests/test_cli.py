"""Modo terminal (pelicula-cli): análise de valores, comandos de listagem, projetos e exportação."""

import json
import os
import subprocess

import pytest

from pelicula import cli, i18n, params, project


@pytest.fixture(autouse=True)
def portuguese():
    i18n.set_language("pt_BR")
    yield
    i18n.set_language("pt_BR")


@pytest.fixture
def gl_session(gl_engine):
    """`quadro` e `lut` criam e liberam o próprio contexto OpenGL na thread atual. No terminal (um
    processo só para o comando) isso não importa, mas aqui a thread principal também guarda o contexto
    da sessão (gl_engine): sem reativá-lo, todos os testes de GPU seguintes falham ("cannot create
    buffer")."""
    yield gl_engine
    gl_engine.ctx.__enter__()


@pytest.mark.parametrize("key, text, expected", [
    ("grao_forca", "1,5", 1.5), ("grao_forca", "2", 2.0), ("grao_semente", "12.4", 12),
    ("scan_on", "true", True), ("scan_on", "não", False), ("bitola", "super8", "super8"),
    ("hal_cor", "#ff8000", [1.0, 128 / 255, 0.0]), ("hal_cor", "255,0,0", [1.0, 0.0, 0.0]),
    ("hal_cor", "0.5 0.25 0", [0.5, 0.25, 0.0]), ("mix_geral", "45%", 0.45),
])
def test_parse_value(key, text, expected):
    assert cli.parse_value(key, text) == pytest.approx(expected) if isinstance(expected, (float, list)) \
        else cli.parse_value(key, text) == expected


@pytest.mark.parametrize("key, text", [("nao_existe", "1"), ("scan_on", "talvez"), ("bitola", "9mm"),
                                       ("grao_forca", "muito"), ("hal_cor", "azul")])
def test_parse_value_errors(key, text):
    with pytest.raises(cli.CliError):
        cli.parse_value(key, text)


@pytest.mark.parametrize("text, frame", [("2", 48), ("1,5", 36), ("00:00:02", 48), ("00:01:00.5", 1452),
                                         ("#120", 120), ("q7", 7)])
def test_parse_time(text, frame):
    assert cli.parse_time(text, 24.0) == frame


def test_build_values_preset_and_sets():
    values, pid = cli.build_values(None, "vision3_500t", ["grao_forca=1.7", "scan_on=true"])
    assert pid == "vision3_500t"
    assert values["grao_forca"] == 1.7 and values["scan_on"] is True
    assert values["iso"] == "500"
    with pytest.raises(cli.CliError):
        cli.build_values(None, "nao_existe", [])
    with pytest.raises(cli.CliError):
        cli.build_values(None, None, ["sem_igual"])


def test_dispatch_from_package_main():
    assert {"exportar", "export", "projeto", "quadro", "lut", "presets", "versao"} <= set(cli.COMMANDS)


def test_version(capsys):
    assert cli.main(["versao"]) == 0
    assert "PeliculaConverter" in capsys.readouterr().out


def test_no_command_shows_help(capsys):
    assert cli.main([]) == 2
    assert "pelicula-cli" in capsys.readouterr().out


def test_presets_json(capsys):
    assert cli.main(["presets", "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert any(i["id"] == "vision3_250d" for i in items)


def test_params_json_filtered(capsys):
    assert cli.main(["parametros", "--secao", "grao", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and all(r["secao"] == "grao" for r in rows)
    assert {r["chave"] for r in rows} <= set(params.PARAMS)


def test_english_messages(capsys):
    os.environ["PELICULA_LANG"] = "en"
    try:
        assert cli.main(["projeto", "nao_existe.plc"]) == 1
    finally:
        del os.environ["PELICULA_LANG"]
    err = capsys.readouterr().err
    assert err.startswith("Error:") and "--criar" in err


@pytest.mark.ffmpeg
def test_project_create_and_edit(ffmpeg_ok, sample_video, tmp_path, capsys):
    plc = tmp_path / "meu"
    assert cli.main(["projeto", str(plc), "--criar", sample_video, "--preset", "super8_kodachrome",
                     "--set", "grao_forca=1.4", "--inicio", "0.25", "--fim", "#20"]) == 0
    p = project.load(str(plc) + ".plc")
    assert p.preset_id == "super8_kodachrome" and p.values["grao_forca"] == 1.4
    assert p.in_point == 6 and p.out_point == 20
    assert cli.main(["projeto", str(plc) + ".plc", "--set", "scan_on=true", "--fim", ""]) == 0
    q = project.load(str(plc) + ".plc")
    assert q.values["scan_on"] is True and q.out_point is None and q.in_point == 6


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_project_range(gl_engine, ffmpeg_ok, sample_video, tmp_path, capsys):
    plc = tmp_path / "p.plc"
    assert cli.main(["projeto", str(plc), "--criar", sample_video, "--preset", "vision3_500t",
                     "--inicio", "#2", "--fim", "#13"]) == 0
    out = tmp_path / "saida.mp4"
    assert cli.main(["exportar", str(plc), "-o", str(out), "--qualidade", "leve", "--trecho", "-q"]) == 0
    from pelicula import media
    info = media.probe(str(out))
    assert info.frames == 12 and info.height == 720  # a qualidade "leve" sempre gera 720p
    # sem -y não sobrescreve
    assert cli.main(["exportar", str(plc), "-o", str(out), "--qualidade", "leve", "-q"]) == 1


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_frame_and_lut(gl_session, ffmpeg_ok, sample_video, tmp_path, capsys):
    png = tmp_path / "q.png"
    assert cli.main(["quadro", sample_video, "-o", str(png), "--tempo", "#5", "--preset", "double_x"]) == 0
    assert png.stat().st_size > 1000
    cube = tmp_path / "x.cube"
    assert cli.main(["lut", "--preset", "vision3_250d", "-o", str(cube), "--tamanho", "17"]) == 0
    lines = [ln for ln in cube.read_text().splitlines() if ln and ln[0].isdigit()]
    assert len(lines) == 17 ** 3


@pytest.mark.ffmpeg
def test_module_entry_point(ffmpeg_ok, tmp_path):
    env = dict(os.environ, PELICULA_LANG="pt_BR")
    r = subprocess.run([__import__("sys").executable, "-m", "pelicula", "versao"], capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), env=env, timeout=60)
    assert r.returncode == 0 and "PeliculaConverter" in r.stdout
