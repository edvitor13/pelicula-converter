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


# ------------------------------------------------------------------ modo Edição e DaVinci Resolve
def _edit_project(tmp_path, sample_video):
    from pelicula import media, timeline
    src = media.probe_source(sample_video)
    seq = timeline.Sequence.for_source(src)
    seq.split(8)
    v = sorted((c for c in seq.clips if c.kind == timeline.VIDEO), key=lambda c: c.start)
    seq.delete([v[0].id], ripple=True)  # tira os 8 primeiros quadros
    seq.insert_media(src)
    p = project.Project(media_path=sample_video, values=params.defaults(), preset_id="", sequence=seq.to_json(),
                        mode="edicao")
    path = tmp_path / "edicao.plc"
    project.save(p, str(path))
    return path, seq


def test_project_sequence_trivial_and_missing(tmp_path):
    from pelicula import timeline
    media_path = tmp_path / "v.mp4"
    media_path.write_bytes(b"x")
    src = timeline.Source(str(media_path), 320, 180, 24.0, "24/1", 48, 2.0, has_audio=False)
    p = project.Project(media_path=str(media_path), sequence=timeline.Sequence.for_source(src).to_json())
    assert cli.project_sequence(p) is None  # só o arquivo inteiro: usa o arquivo direto
    seq = timeline.Sequence.for_source(src)
    seq.split(10)
    p.sequence = seq.to_json()
    assert cli.project_sequence(p) is not None
    media_path.unlink()
    with pytest.raises(cli.CliError):
        cli.project_sequence(p)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_and_frame_of_an_edit_project(gl_session, ffmpeg_ok, sample_video, tmp_path, capsys):
    plc, seq = _edit_project(tmp_path, sample_video)
    assert seq.duration == 40
    out = tmp_path / "montagem.mp4"
    assert cli.main(["exportar", str(plc), "-o", str(out), "--qualidade", "mp4", "--velocidade", "ultrafast",
                     "-q"]) == 0
    from pelicula import media
    info = media.probe(str(out))
    assert info.frames == 40 and info.has_audio
    png = tmp_path / "q.png"
    assert cli.main(["quadro", str(plc), "-o", str(png), "--tempo", "#30"]) == 0
    assert png.stat().st_size > 1000


class _FakeResolve:
    def __init__(self, tmp):
        self.tmp = tmp
        self.installed = None

    def lut_dirs(self):
        return [self.tmp / "LUT"]

    def build_package(self, dest):
        from pathlib import Path
        Path(dest).mkdir(parents=True, exist_ok=True)
        f = Path(dest) / "PeliculaConverter.dctl"
        f.write_text("x")
        return [f]

    def install(self, target=None):
        self.installed = target or str(self.tmp / "LUT")
        return self.tmp / "LUT" / "PeliculaConverter"


class _FakeResolveOfx(_FakeResolve):
    """Com o plugin OpenFX (nada é instalado de verdade: pastas temporárias)."""

    def __init__(self, tmp):
        super().__init__(tmp)
        self.ofx_installed = False

    def ofx_bundle_version(self):
        return "9.8.7"

    def ofx_install_dir(self):
        return self.tmp / "OFX" / "Plugins"

    def ofx_installed_version(self, folder=None):
        return "9.8.7" if self.ofx_installed else None

    def ofx_install(self, target_dir=None):
        self.ofx_installed = True
        return self.ofx_install_dir() / "PeliculaConverter.ofx.bundle"

    def ofx_save_bundle(self, dest):
        from pathlib import Path
        b = Path(dest) / "PeliculaConverter.ofx.bundle"
        b.mkdir(parents=True)
        return b

    def ofx_generate(self, dest=None):
        from pathlib import Path
        Path(dest).mkdir(parents=True, exist_ok=True)
        return [Path(dest) / "pc_kernels.h", Path(dest) / "pc_params.h"]


def test_resolve_command_ofx(tmp_path, capsys, monkeypatch):
    import sys
    fake = _FakeResolveOfx(tmp_path)
    monkeypatch.setitem(sys.modules, "pelicula.resolve", fake)
    import pelicula
    monkeypatch.setattr(pelicula, "resolve", fake, raising=False)
    assert cli.main(["resolve", "--listar"]) == 0
    out = capsys.readouterr().out
    assert "OpenFX" in out and "9.8.7" in out
    assert cli.main(["resolve", "--ofx-pasta", str(tmp_path / "copia")]) == 0
    assert (tmp_path / "copia" / "PeliculaConverter.ofx.bundle").is_dir()
    assert cli.main(["resolve", "--ofx-instalar"]) == 0 and fake.ofx_installed
    assert fake.installed is None  # só o OpenFX: os DCTLs não foram instalados
    assert cli.main(["resolve", "--ofx-fonte", str(tmp_path / "fonte")]) == 0
    assert "2" in capsys.readouterr().out


def test_resolve_command(tmp_path, capsys, monkeypatch):
    import sys
    fake = _FakeResolve(tmp_path)
    monkeypatch.setitem(sys.modules, "pelicula.resolve", fake)
    import pelicula
    monkeypatch.setattr(pelicula, "resolve", fake, raising=False)
    assert cli.main(["resolve"]) == 0
    assert "LUT" in capsys.readouterr().out
    assert cli.main(["davinci", "--pasta", str(tmp_path / "pacote")]) == 0
    assert (tmp_path / "pacote" / "PeliculaConverter.dctl").exists()
    assert cli.main(["resolve", "--instalar", "--destino", str(tmp_path / "X")]) == 0
    assert fake.installed == str(tmp_path / "X")
    assert "resolve" in cli.COMMANDS and cli.COMMANDS["davinci"] == "resolve"


def test_resolve_command_without_module(capsys, monkeypatch):
    import sys
    import pelicula
    monkeypatch.setitem(sys.modules, "pelicula.resolve", None)
    monkeypatch.delattr(pelicula, "resolve", raising=False)
    assert cli.main(["resolve", "--listar"]) == 1
    assert "DaVinci" in capsys.readouterr().err


def test_modules_command(tmp_path, capsys, monkeypatch):
    """`modulos` lista, liga e desliga os recursos da janela (preferências num .ini temporário)."""
    from pelicula import modules
    from pelicula.ui import prefs
    monkeypatch.setenv("PELICULA_SETTINGS_DIR", str(tmp_path))
    monkeypatch.setenv("PELICULA_LANG", "pt_BR")
    assert cli.COMMANDS["modulos"] == "modules" and cli.COMMANDS["modules"] == "modules"
    assert cli.main(["modulos", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["perfil"] == "tudo"
    assert [r["id"] for r in data["modulos"]] == [m.id for m in modules.MODULES]
    assert all(r["ligado"] == (r["estado"] == modules.ESTAVEL) for r in data["modulos"])

    assert cli.main(["modulos", "--perfil", "simples", "--ligar", "scopes", "--desligar", "edicao"]) == 0
    out = capsys.readouterr().out
    assert "Personalizado" in out and "scopes" in out and "desligado" in out
    s = prefs.settings()
    assert modules.is_enabled(s, "scopes") and not modules.is_enabled(s, "edicao")
    assert not modules.is_enabled(s, "laboratorio") and modules.is_enabled(s, "recuperacao")

    assert cli.main(["modules", "--perfil", "criador"]) == 0
    assert "Perfil: Criador" in capsys.readouterr().out
    assert modules.current_profile(prefs.settings()) == "criador"

    assert cli.main(["modulos", "--ligar", "nao_existe", "--desligar", "scopes"]) == 1
    assert "nao_existe" in capsys.readouterr().err
    assert modules.is_enabled(prefs.settings(), "scopes")  # id errado: nada muda
    with pytest.raises(SystemExit):
        cli.main(["modulos", "--perfil", "nao_existe"])
