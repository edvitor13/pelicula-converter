"""Teste manual de ponta a ponta do CorridorKey: download de verdade (~7,6 GB) e recorte na placa NVIDIA.

Só roda com `PELICULA_TESTE_CORRIDORKEY=1`. Instala numa pasta de teste (nunca na pasta do app):
`PELICULA_TESTE_CORRIDORKEY_DIR` (padrão: `pelicula-corridorkey-teste` ao lado da pasta do repositório).
A pasta fica no fim (rodar de novo reaproveita a instalação; um download interrompido continua).
O log com os tempos vai para `<pasta>/teste.log`.

    set PELICULA_TESTE_CORRIDORKEY=1
    set PELICULA_TEST_TIMEOUT=0
    .venv\\Scripts\\python -m pytest -q -s tests/test_corridorkey_real.py

(`PELICULA_TEST_TIMEOUT=0` desliga o vigia de testes travados da conftest: o download passa de 180 s.)

Precisa de internet, de uma NVIDIA RTX série 30 ou mais nova e de uns 25 GB livres.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from pelicula import corridorkey, media, tools

pytestmark = pytest.mark.skipif(os.environ.get("PELICULA_TESTE_CORRIDORKEY") != "1",
                                reason="teste manual: PELICULA_TESTE_CORRIDORKEY=1 (baixa ~7,6 GB)")

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIR = REPO.parent / "pelicula-corridorkey-teste"


@pytest.fixture(scope="module")
def folder() -> Path:
    base = Path(os.environ.get("PELICULA_TESTE_CORRIDORKEY_DIR") or DEFAULT_DIR).resolve()
    assert not base.is_relative_to(REPO), "a pasta de teste fica fora do repositório"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture(scope="module")
def env(folder):
    """Pasta do app dentro da pasta de teste; o ffmpeg do app (já instalado) só é lido."""
    media.configure()
    ffmpeg = media.ffmpeg()
    saved = {k: os.environ.get(k) for k in ("LOCALAPPDATA", "XDG_DATA_HOME")}
    os.environ["LOCALAPPDATA"] = os.environ["XDG_DATA_HOME"] = str(folder / "app")
    media.configure(str(Path(ffmpeg).parent))
    yield folder
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def log(folder: Path, text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {text}"
    print(line, flush=True)
    with open(folder / "teste.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


class Progress:
    def __init__(self, folder: Path):
        self.folder, self.last_stage, self.last_t = folder, None, 0.0

    def __call__(self, stage, done, total):
        now = time.monotonic()
        if stage != self.last_stage or now - self.last_t > 30:
            frac = f" {done / total:.0%} ({tools.fmt_size(done)} de {tools.fmt_size(total)})" if total else ""
            log(self.folder, f"{stage}{frac}")
            self.last_stage, self.last_t = stage, now


def test_install_for_real(env):
    root = env / "ferramentas"
    free = shutil.disk_usage(env).free
    log(env, f"livre no disco: {tools.fmt_size(free)}")
    assert free > 25 * 1024 ** 3, "menos de 25 GB livres"
    problems = tools.requirement_problems(tools.CORRIDORKEY, root)
    assert not problems, problems
    if corridorkey.installation(root) is None:
        t0 = time.monotonic()
        inst = tools.download(tools.CORRIDORKEY, Progress(env), root=root)
        log(env, f"instalado em {time.monotonic() - t0:.0f} s: {inst.path}")
    inst = corridorkey.installation(root)
    assert inst is not None
    marker = json.loads((inst.folder / tools.MARKER).read_text(encoding="utf-8"))
    assert marker["sha256"] == tools.recipe_fingerprint(tools.CORRIDORKEY) and marker["torch"] == "cu128"
    total, cache = tools.recipe_size(tools.CORRIDORKEY, root)
    log(env, f"tamanho no disco: {tools.fmt_size(total)} (versão {tools.fmt_size(tools.dir_size(inst.folder))}, "
             f"Python base {tools.fmt_size(tools.dir_size(root / 'corridorkey' / tools.PYTHON_DIR))}, "
             f"cache {tools.fmt_size(cache)}); ambiente {tools.fmt_size(tools.dir_size(inst.folder / tools.ENV_DIR))}")
    t0 = time.monotonic()
    out = tools.test_installed(tools.CORRIDORKEY, root=root)
    log(env, f"teste da instalação em {time.monotonic() - t0:.0f} s:\n{out}")


def _green_clip(path: Path, seconds: float = 2.0) -> Path:
    """Clipe 1080p de fundo verde com uma figura que se move (pessoa estilizada + padrão de teste)."""
    graph = ("[0][1]overlay=x='560+260*sin(t*2)':y=260[a];"
             "[a]drawbox=x=820:y=120:w=280:h=280:color=0xd9a37c@1:t=fill[b];"
             "[b]drawbox=x=760:y=380:w=400:h=700:color=0x2b3a67@1:t=fill")
    subprocess.run([media.ffmpeg(), "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"color=c=0x00b140:s=1920x1080:r=24:d={seconds}",
                    "-f", "lavfi", "-i", f"testsrc2=s=420x420:r=24:d={seconds}",
                    "-filter_complex", graph, "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", str(path)],
                   check=True)
    return path


def _probe(path: Path) -> dict:
    out = subprocess.run([media.ffprobe(), "-v", "error", "-select_streams", "v:0", "-count_frames",
                          "-show_entries", "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["streams"][0]


def _alpha_range(path: Path) -> tuple[float, float]:
    """Menor e maior valor do alfa (0–255) no quadro do meio."""
    out = subprocess.run([media.ffmpeg(), "-v", "error", "-ss", "1", "-i", str(path), "-frames:v", "1",
                          "-vf", "alphaextract,format=gray,signalstats,metadata=print:file=-", "-f", "null", "-"],
                         capture_output=True, text=True, check=True)
    vals = {}
    for line in out.stdout.splitlines():
        if "lavfi.signalstats.YMIN=" in line or "lavfi.signalstats.YMAX=" in line:
            k, v = line.strip().split("=")
            vals[k.rsplit(".", 1)[1]] = float(v)
    return vals.get("YMIN", -1), vals.get("YMAX", -1)


def test_key_a_green_screen_clip(env):
    root = env / "ferramentas"
    if corridorkey.installation(root) is None:
        pytest.skip("instale primeiro (test_install_for_real)")
    work = env / "recorte"
    work.mkdir(exist_ok=True)
    clip = _green_clip(work / "verde-1080p.mp4")
    out = work / "saida"
    shutil.rmtree(out, ignore_errors=True)
    opts = corridorkey.Options(input=str(clip), output_dir=str(out), extras=("fg", "checker"))
    t0 = time.monotonic()
    res = corridorkey.run(opts, Progress(env), root=root)
    secs = time.monotonic() - t0
    frames = 48
    log(env, f"recorte de {frames} quadros 1080p em {secs:.1f} s ({frames / secs:.2f} quadros/s, com o "
             f"carregamento do modelo): {[f.name for f in res.files]}")
    cutout = corridorkey.main_output(res)
    assert cutout is not None and cutout.name == "verde-1080p_cutout.mov"
    info = _probe(cutout)
    log(env, f"ffprobe do recorte: {info}")
    assert info["codec_name"] == "prores" and info["pix_fmt"].startswith("yuva444p"), info
    assert (info["width"], info["height"]) == (1920, 1080) and int(info["nb_read_frames"]) == frames
    lo, hi = _alpha_range(cutout)
    log(env, f"alfa no quadro do meio: mínimo {lo:.0f}, máximo {hi:.0f}")
    assert lo < 40 and hi > 215, "o alfa precisa ter partes transparentes e opacas"
    assert (out / "verde-1080p_alpha.mp4").is_file() and (out / "verde-1080p_fg.mp4").is_file()
    assert not list(out.glob(f"*{corridorkey.system.PARTIAL}*")), "a pasta parcial sumiu"
    # low VRAM e EXR também funcionam
    out2 = work / "saida-exr"
    shutil.rmtree(out2, ignore_errors=True)
    t0 = time.monotonic()
    res2 = corridorkey.run(corridorkey.Options(input=str(clip), output_dir=str(out2), exr=True, low_vram=True),
                           Progress(env), root=root)
    log(env, f"EXR + pouca memória em {time.monotonic() - t0:.1f} s: {[f.name for f in res2.files]}")
    exr = out2 / "verde-1080p_cutout_exr"
    assert exr.is_dir() and len(list(exr.glob("*.exr"))) == frames
