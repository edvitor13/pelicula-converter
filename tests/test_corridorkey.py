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
