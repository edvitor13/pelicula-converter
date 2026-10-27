"""CorridorKey (pelicula/corridorkey.py): requisitos, instalação falsa e recorte com um infer.py falso.

Nada de rede nem de GPU: o nvidia-smi é um comando falso, o uv é `tests/uv_falso.py` e o código da
Corridor é trocado por scripts que imitam a saída e os arquivos do `infer.py` deles. A pasta do app
aponta para uma pasta temporária.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

import test_ambiente as ta
from pelicula import corridorkey, deps, media, system, tools

SMI_3060 = "0, NVIDIA GeForce RTX 3060, 12288, 630.20, 8.6"


def smi(*lines: str, code: int = 0) -> list[str]:
    script = "import sys\n" + "".join(f"print({ln!r})\n" for ln in lines) + f"sys.exit({code})\n"
    return [sys.executable, "-c", script]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    local = tmp_path / "local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    monkeypatch.setattr(tools, "uv_command", lambda *a, **k: list(ta.FAKE_UV))
    monkeypatch.setattr(corridorkey, "NVIDIA_SMI", smi(SMI_3060))
    corridorkey.gpus(refresh=True)
    yield
    monkeypatch.undo()
    corridorkey.gpus(refresh=True)


# ------------------------------------------------------------------ placa de vídeo
def test_parse_gpus_and_capability():
    found = corridorkey.parse_gpus("0, NVIDIA GeForce RTX 3060, 12288, 630.20, 8.6\n"
                                   "1, NVIDIA GeForce GTX 1080, 8192, 630.20, 6.1\nlixo\n")
    assert [g.name for g in found] == ["NVIDIA GeForce RTX 3060", "NVIDIA GeForce GTX 1080"]
    assert found[0].ok and not found[1].ok and found[0].memory_mb == 12288 and found[1].capability == 6.1
    assert corridorkey.parse_gpus("0, Placa, [N/A], 1.0, [N/A]")[0].capability == 0


@pytest.mark.skipif(deps.platform_key() not in ("win32", "linux"), reason="CorridorKey só no Windows e no Linux")
def test_requirements_follow_the_gpu(monkeypatch):
    assert corridorkey.requirement_problems() == []
    assert corridorkey.best_gpu().name == "NVIDIA GeForce RTX 3060"
    cases = {
        "GTX 1080 (6.1)": smi("0, NVIDIA GeForce GTX 1080, 8192, 551.23, 6.1"),
        "não respondeu": smi(code=9),
        "Atualize o driver": smi("0, NVIDIA GeForce RTX 3060, 12288, 470.10, [N/A]"),
    }
    for expected, cmd in cases.items():
        monkeypatch.setattr(corridorkey, "NVIDIA_SMI", cmd)
        corridorkey.gpus(refresh=True)
        problems = corridorkey.requirement_problems()
        assert len(problems) == 1 and expected in problems[0], (expected, problems)
    monkeypatch.setattr(corridorkey, "NVIDIA_SMI", [str(Path(sys.executable).parent / "nao-existe.exe")])
    corridorkey.gpus(refresh=True)
    assert "NVIDIA" in corridorkey.requirement_problems()[0]
    # duas placas: vale a que serve; o recorte usa só ela (CUDA_VISIBLE_DEVICES)
    monkeypatch.setattr(corridorkey, "NVIDIA_SMI", smi("0, NVIDIA GeForce GTX 1060, 6144, 551.23, 6.1",
                                                       "1, NVIDIA GeForce RTX 4090, 24564, 551.23, 8.9"))
    corridorkey.gpus(refresh=True)
    assert corridorkey.requirement_problems() == [] and corridorkey.best_gpu().index == 1
    env = corridorkey.environment(None)
    assert env["CUDA_VISIBLE_DEVICES"] == "1" and env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"


def test_corridorkey_status_is_blocked_without_a_suitable_gpu(monkeypatch, tmp_path):
    monkeypatch.setattr(corridorkey, "NVIDIA_SMI", smi("0, NVIDIA GeForce GTX 1080, 8192, 551.23, 6.1"))
    corridorkey.gpus(refresh=True)
    st = tools.status(tools.CORRIDORKEY, root=tmp_path / "f")
    if deps.platform_key() in ("win32", "linux"):
        assert st.state == tools.AUSENTE and not st.downloadable and "RTX série 30" in st.blocked[0]
        with pytest.raises(tools.ToolError):
            tools.download(tools.CORRIDORKEY, root=tmp_path / "f")
        assert not (tmp_path / "f" / "corridorkey").exists(), "bloqueado: nada é baixado"


# ------------------------------------------------------------------ instalação falsa com o formato do CorridorKey
SMOKE = b"""import os, pathlib, sys
assert sys.argv[1:] == ["--load_model"], sys.argv
assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["TRANSFORMERS_OFFLINE"] == "1"
for f in ("weights/corridorkey_v2.safetensors", "vfms/moge/model.pt"):
    assert pathlib.Path(f).is_file(), f
print("smoke ok")
"""

# infer.py falso: imprime as mesmas linhas do infer.py deles e grava os arquivos com os mesmos nomes.
INFER = b'''import argparse, os, pathlib, sys, time
p = argparse.ArgumentParser()
p.add_argument("--input"); p.add_argument("--output_dir"); p.add_argument("--outputs", nargs="+")
p.add_argument("--output_format", default="video"); p.add_argument("--despill_strength", type=float)
p.add_argument("--temp_dir"); p.add_argument("--hint_first_frame"); p.add_argument("--hint_video")
p.add_argument("--hint_quality", type=float); p.add_argument("--low_vram", action="store_true")
a = p.parse_args()
pathlib.Path(os.environ["PCTEST_ARGS"]).write_text(repr(sys.argv[1:]) + "\\n" + os.environ["PATH"], encoding="utf-8")
assert os.environ["HF_HUB_OFFLINE"] == "1"
if os.environ.get("PCTEST_FALHAR"):
    print("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB", flush=True)
    sys.exit(1)
name = os.path.splitext(os.path.basename(a.input))[0]
print("Loading CorridorKey v2 runtime weights", flush=True)
print(f"[{name}] probed 48 frames @ 1920x1080", flush=True)
print(f"[{name}] RVM continuous prepass", flush=True)
print(f"[{name}] frozen VFM prepass", flush=True)
print(f"[{name}] Hann stage1: chunk=24 overlap=8 stride=16 windows=3", flush=True)
for i in range(1, 4):
    print(f"      window {i}/3 [{(i - 1) * 16}:{(i - 1) * 16 + 24}]", flush=True)
    time.sleep(float(os.environ.get("PCTEST_DEMORAR", "0") or 0))
out = pathlib.Path(a.output_dir)
suffix = {"cutout": "_cutout.mov", "alpha": "_alpha.mp4", "fg": "_fg.mp4", "checker": "_checker_comp_despill050.mp4"}
for o in a.outputs:
    if a.output_format == "exr":
        d = out / f"{name}_{o}_exr"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}_{o}_00000.exr").write_bytes(b"exr")
    else:
        (out / (name + suffix[o])).write_bytes(o.encode())
(out / f"{name}_settings.txt").write_text("ok", encoding="utf-8")
print(f"[{name}] wrote {len(a.outputs)} output video(s)", flush=True)
'''


def fake_corridorkey(tmp_path: Path, infer: bytes = INFER) -> tools.Tool:
    """O CORRIDORKEY de verdade com a receita trocada por uma falsa no mesmo formato (código em codigo/)."""
    tool = ta.fake_recipe(tmp_path, check=SMOKE, tool_id="corridorkey",
                          files={"codigo/weights/corridorkey_v2.safetensors": b"pesos" * 100,
                                 "codigo/vfms/moge/model.pt": b"moge" * 100})
    rec = tool.recipe
    code = {"infer.py": infer, "scripts/smoke_test_runtime.py": SMOKE}
    code_zip = ta.make_zip(tmp_path / "ck.zip", {f"CorridorKey2.0-abc/{k}": v for k, v in code.items()})
    src = replace(rec.code[0], url=code_zip.as_uri(), manifest=str(ta.manifest(tmp_path / "ck.sha256", code)))
    rec = replace(rec, code=(src, rec.code[1]), check=tools.CORRIDORKEY_RECIPE.check,
                  check_env=tools.CORRIDORKEY_RECIPE.check_env, workdir="codigo")
    return replace(tools.CORRIDORKEY, recipe=rec)


@pytest.fixture
def installed_ck(monkeypatch, tmp_path):
    fake = fake_corridorkey(tmp_path / "fontes")
    monkeypatch.setattr(tools, "TOOLS", tuple(fake if t.id == "corridorkey" else t for t in tools.TOOLS))
    if deps.platform_key() not in fake.recipe.platforms():
        pytest.skip("sem receita para este sistema")
    tools.download(fake)
    return fake


def test_fake_install_has_the_corridorkey_layout(installed_ck):
    inst = corridorkey.installation()
    assert inst is not None and corridorkey.available()
    assert inst.code == inst.folder / "codigo" and (inst.code / "infer.py").is_file()
    assert (inst.code / "weights" / "corridorkey_v2.safetensors").is_file()
    assert inst.python == tools.executable(installed_ck) == tools.env_python(inst.folder / "venv")
    assert "smoke ok" in tools.test_installed(installed_ck)
    st = tools.status(installed_ck)
    assert st.installed and st.verified and st.size > 0 and st.folder == str(inst.folder)
    assert tools.disk_usage(include_ffmpeg=False) >= st.size
    tools.remove(installed_ck)
    assert corridorkey.installation() is None and not corridorkey.available()


def test_installation_needs_python_and_infer(installed_ck):
    inst = corridorkey.installation()
    (inst.code / "infer.py").unlink()
    assert corridorkey.installation() is None


# ------------------------------------------------------------------ linha de comando, progresso e aviso de entrada
def test_command_maps_every_option():
    o = corridorkey.Options(input="C:/v/clipe.mp4", output_dir="C:/saida")
    cmd = corridorkey.command("py", o, "C:/parcial", "C:/tmp")
    assert cmd[:2] == ["py", "infer.py"] and cmd[cmd.index("--input") + 1] == "C:/v/clipe.mp4"
    assert cmd[cmd.index("--output_dir") + 1] == "C:/parcial" and cmd[cmd.index("--temp_dir") + 1] == "C:/tmp"
    outs = cmd[cmd.index("--outputs") + 1:cmd.index("--despill_strength")]
    assert outs == ["cutout", "alpha"] and cmd[cmd.index("--despill_strength") + 1] == "0.50"
    assert not {"--output_format", "--hint_first_frame", "--hint_video", "--hint_quality", "--low_vram"} & set(cmd)
    o = corridorkey.Options(input="a.mov", output_dir="s", hint="mascara", hint_path="m.png", hint_quality=0.8,
                            extras=("checker", "fg"), exr=True, despill=1.7, low_vram=True)
    cmd = corridorkey.command("py", o, "p", "t")
    assert cmd[cmd.index("--outputs") + 1:cmd.index("--despill_strength")] == ["cutout", "alpha", "fg", "checker"]
    assert cmd[cmd.index("--despill_strength") + 1] == "1.00" and cmd[cmd.index("--output_format") + 1] == "exr"
    assert cmd[cmd.index("--hint_first_frame") + 1] == "m.png" and cmd[cmd.index("--hint_quality") + 1] == "0.80"
    assert "--low_vram" in cmd and "--hint_video" not in cmd
    o.hint, o.hint_path = "video", "dica.mp4"
    cmd = corridorkey.command("py", o, "p", "t")
    assert cmd[cmd.index("--hint_video") + 1] == "dica.mp4" and "--hint_first_frame" not in cmd
    assert corridorkey.clip_name("C:/v/meu clipe.final.mov") == "meu clipe.final"


def test_progress_parser_reads_their_output():
    p = corridorkey.ProgressParser()
    seen = [p.feed(line) for line in (
        "Loading CorridorKey v2 runtime weights", "[clipe] probed 120 frames @ 1920x1080",
        "[clipe] RVM continuous prepass", "[clipe] frozen VFM prepass", "[clipe] Hann stage1: chunk=24 windows=7",
        "      window 3/7 [32:56]", "algo que não interessa", "[clipe] wrote 2 output video(s)")]
    assert seen[0][0] == "Carregando o modelo…" and seen[1][0] == "Lendo o vídeo (120 quadros)…" and p.frames == 120
    assert seen[5] == ("Recortando…", 3, 7) and seen[6] is None and seen[7] == ("Terminando…", 1, 1)
    assert p.feed("      window 7/7 [96:120]") == ("Gravando os arquivos…", 0, 0), "depois da última janela"


def test_source_warning_for_log_hdr_and_raw():
    from pelicula import timeline as tl
    plain = tl.Source("clipe.mp4", 1920, 1080, color_transfer="bt709")
    assert corridorkey.source_warning(plain, "rec709") == ""
    assert "HDR (PQ)" in corridorkey.source_warning(tl.Source("a.mov", color_transfer="smpte2084"), "pq")
    assert "HDR (HLG)" in corridorkey.source_warning(tl.Source("a.mp4", color_transfer="arib-std-b67"), "rec709")
    assert "RAW" in corridorkey.source_warning(tl.Source("a.braw", codec="braw"), "rec709")
    assert "RAW" in corridorkey.source_warning(None, "rec709", "C:/cartao/A001.R3D")
    warn = corridorkey.source_warning(plain, "slog3")
    assert "Sony S-Log3" in warn and "log" in warn and "Rec.709" in warn


# ------------------------------------------------------------------ o recorte (infer.py falso, processo de verdade)
@pytest.fixture
def ffmpeg_dir(monkeypatch, tmp_path):
    folder = tmp_path / "ffmpeg-do-app"
    folder.mkdir()
    exe = folder / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    exe.write_bytes(b"")
    monkeypatch.setattr(media, "ffmpeg", lambda: str(exe))
    return folder


@pytest.fixture
def clip(tmp_path):
    src = tmp_path / "filmagem" / "tela verde.mp4"
    src.parent.mkdir()
    src.write_bytes(b"video")
    return src


def key(clip, out, monkeypatch, tmp_path, **kw):
    args = tmp_path / "args.txt"
    monkeypatch.setenv("PCTEST_ARGS", str(args))
    stages = []
    res = corridorkey.run(corridorkey.Options(input=str(clip), output_dir=str(out), **kw),
                          lambda s, d, t: stages.append((s, d, t)))
    return res, stages, args.read_text(encoding="utf-8")


def test_run_keys_in_a_separate_process_and_moves_the_files(installed_ck, ffmpeg_dir, clip, monkeypatch, tmp_path):
    out = tmp_path / "saida"
    res, stages, seen = key(clip, out, monkeypatch, tmp_path, extras=("fg",))
    argv, path = seen.split("\n", 1)
    assert path.split(os.pathsep)[0] == str(ffmpeg_dir), "o ffmpeg do app vem primeiro no PATH"
    assert "--temp_dir" in argv and str(corridorkey.temp_dir()) in argv.replace("\\\\", "\\")
    assert sorted(p.name for p in out.iterdir()) == ["tela verde_alpha.mp4", "tela verde_cutout.mov",
                                                     "tela verde_fg.mp4", "tela verde_settings.txt"]
    assert corridorkey.main_output(res) == out / "tela verde_cutout.mov" and res.folder == out
    assert ("Recortando…", 2, 3) in stages and ("Gravando os arquivos…", 0, 0) in stages
    assert stages[-1][0] == "Pronto."
    assert stages[0][0] == "Iniciando o CorridorKey…" and any(s[0] == "Carregando o modelo…" for s in stages)
    assert not list(corridorkey.temp_dir().iterdir()), "a pasta temporária é apagada"
    # de novo, em EXR, por cima: os arquivos e as pastas antigas são trocados
    (out / "tela verde_cutout_exr").mkdir()
    (out / "tela verde_cutout_exr" / "velho.exr").write_bytes(b"velho")
    res, stages, _seen = key(clip, out, monkeypatch, tmp_path, exr=True)
    exr = out / "tela verde_cutout_exr"
    assert [p.name for p in exr.iterdir()] == ["tela verde_cutout_00000.exr"]
    assert corridorkey.main_output(res) == exr
    assert not [p for p in out.iterdir() if system.PARTIAL in p.name]


def test_failure_explains_and_leaves_the_old_files(installed_ck, ffmpeg_dir, clip, monkeypatch, tmp_path):
    out = tmp_path / "saida"
    out.mkdir()
    (out / "tela verde_cutout.mov").write_bytes(b"recorte antigo")
    monkeypatch.setenv("PCTEST_FALHAR", "1")
    with pytest.raises(corridorkey.CorridorKeyError) as err:
        key(clip, out, monkeypatch, tmp_path)
    assert "Pouca memória" in str(err.value) and "out of memory" in str(err.value)
    assert [p.name for p in out.iterdir()] == ["tela verde_cutout.mov"]
    assert (out / "tela verde_cutout.mov").read_bytes() == b"recorte antigo"


def test_cancel_kills_the_process_and_writes_nothing(installed_ck, ffmpeg_dir, clip, monkeypatch, tmp_path):
    out = tmp_path / "saida"
    monkeypatch.setenv("PCTEST_ARGS", str(tmp_path / "args.txt"))
    monkeypatch.setenv("PCTEST_DEMORAR", "60")
    cancel = threading.Event()

    def progress(stage, done, total):
        if stage == "Recortando…" and done:
            cancel.set()

    t0 = time.monotonic()
    with pytest.raises(tools.Cancelled):
        corridorkey.run(corridorkey.Options(input=str(clip), output_dir=str(out)), progress, cancel)
    assert time.monotonic() - t0 < 30, "cancelar encerra o processo na hora"
    assert list(out.iterdir()) == [] and not list(corridorkey.temp_dir().iterdir())


def test_run_needs_the_component(ffmpeg_dir, clip, tmp_path):
    with pytest.raises(corridorkey.CorridorKeyError) as err:
        corridorkey.run(corridorkey.Options(input=str(clip), output_dir=str(tmp_path / "s")))
    assert "não está instalado" in str(err.value)


def test_run_checks_input_and_hint(installed_ck, ffmpeg_dir, clip, tmp_path):
    with pytest.raises(corridorkey.CorridorKeyError, match="não existe"):
        corridorkey.run(corridorkey.Options(input=str(tmp_path / "nada.mp4"), output_dir=str(tmp_path / "s")))
    with pytest.raises(corridorkey.CorridorKeyError, match="dica não existe"):
        corridorkey.run(corridorkey.Options(input=str(clip), output_dir=str(tmp_path / "s"), hint="mascara",
                                            hint_path=str(tmp_path / "nada.png")))
