"""CorridorKey 2.0: recorte de fundo verde ou azul por IA (módulo Beta `recorte_ia`). Sem Qt.

O componente é instalado por `tools.py` (receita `tools.CORRIDORKEY_RECIPE`): o código da Corridor
Digital num commit fixo, um ambiente Python próprio (Python 3.12, PyTorch 2.9.1 + CUDA 12.8) e os
modelos. Aqui ficam:

- os requisitos (`requirement_problems`): placa NVIDIA com bfloat16, ou seja capacidade 8.0 ou mais
  (RTX série 30 em diante), lida pelo `nvidia-smi`. Nenhum número de driver é fixado: o teste da
  instalação (`torch.cuda.is_available()` ao carregar o modelo) é que confirma;
- a linha de comando do `infer.py` deles (`command`), o ambiente do processo (`environment`) e a
  leitura do progresso na saída dele (`ProgressParser`);
- o trabalho da fila (`run`): roda **sempre num processo separado**, nunca dentro do app, com o
  ffmpeg do app na frente do PATH, sem rede (`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`), sem janela no
  Windows; cancelar encerra o processo e os filhos. Os arquivos saem numa pasta parcial ao lado do
  destino e só trocam de lugar no fim (receita "Gravar arquivos do usuário" do AGENTS.md);
- o aviso de entrada (`source_warning`): o CorridorKey espera vídeo Rec.709; log, HDR (PQ/HLG) e
  RAW podem sair errados (converter antes fica para depois).

A renderização do app nunca usa este módulo: o recorte só gera arquivos novos para o usuário.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import deps, system, tools
from .i18n import N_, _

MIN_CAPABILITY = 8.0  # bfloat16: NVIDIA RTX série 30 (Ampere) ou mais nova
NVIDIA_SMI: list[str] | None = None  # comando do nvidia-smi (None = procurar); os testes usam um falso

HINTS = ("nenhuma", "mascara", "video")
EXTRAS = ("fg", "checker")  # saídas opcionais além do recorte com alfa e da máscara
HINT_LABELS = {"nenhuma": N_("Nenhuma (automático)"), "mascara": N_("Máscara do primeiro quadro (imagem)"),
               "video": N_("Vídeo de dica (máscara aproximada do clipe todo)")}

# Codecs e extensões de RAW de câmera: o CorridorKey lê vídeo comum (Rec.709).
RAW_CODECS = {"prores_raw", "braw", "r3d", "cinemadng", "arriraw"}
RAW_EXTS = {".braw", ".r3d", ".ari", ".arx", ".crm", ".dng", ".nev", ".mxf_raw"}

Progress = Callable[[str, int, int], None]


class CorridorKeyError(RuntimeError):
    """Falha do recorte (mensagem pronta para o usuário)."""


# ------------------------------------------------------------------ placa de vídeo
@dataclass(frozen=True)
class Gpu:
    index: int
    name: str
    memory_mb: int
    driver: str
    capability: float  # 0 = o nvidia-smi não informou (driver antigo)

    @property
    def ok(self) -> bool:
        return self.capability >= MIN_CAPABILITY


_gpus: list[Gpu] | None = None
_gpus_read = False
_gpus_lock = threading.Lock()


def _smi() -> list[str] | None:
    if NVIDIA_SMI is not None:
        return list(NVIDIA_SMI)
    exe = shutil.which("nvidia-smi")
    if exe is None and sys.platform == "win32":
        for cand in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
                     Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI"
                     / "nvidia-smi.exe"):
            if cand.is_file():
                exe = str(cand)
                break
    return [exe] if exe else None


def parse_gpus(text: str) -> list[Gpu]:
    """Linhas de `nvidia-smi --query-gpu=index,name,memory.total,driver_version,compute_cap
    --format=csv,noheader,nounits` → placas."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            mem = int(float(parts[2]))
        except ValueError:
            mem = 0
        try:
            cc = float(parts[4])
        except ValueError:
            cc = 0.0
        out.append(Gpu(int(parts[0]), parts[1], mem, parts[3], cc))
    return out


def gpus(refresh: bool = False) -> list[Gpu] | None:
    """Placas NVIDIA (None = o nvidia-smi não existe neste computador). Lido uma vez por sessão."""
    global _gpus, _gpus_read
    with _gpus_lock:
        if _gpus_read and not refresh:
            return _gpus
        cmd = _smi()
        found: list[Gpu] | None = None
        if cmd is not None:
            query = "--query-gpu=index,name,memory.total,driver_version,compute_cap"
            try:
                res = subprocess.run([*cmd, query, "--format=csv,noheader,nounits"], capture_output=True, timeout=10,
                                     creationflags=deps.NO_WINDOW)
                found = parse_gpus(res.stdout.decode("utf-8", "replace")) if res.returncode == 0 else []
                if res.returncode != 0 and b"compute_cap" in (res.stdout + res.stderr):
                    found = [Gpu(-1, "", 0, "", 0.0)]  # driver antigo: não conhece o campo compute_cap
            except (OSError, subprocess.SubprocessError):
                found = None
        _gpus, _gpus_read = found, True
        return found


def best_gpu() -> Gpu | None:
    """A placa usada no recorte: a de capacidade 8.0+ com mais memória."""
    ok = [g for g in (gpus() or []) if g.ok]
    return max(ok, key=lambda g: (g.memory_mb, -g.index)) if ok else None


def requirement_problems() -> list[str]:
    """Por que o CorridorKey não roda neste computador (lista vazia = a placa serve)."""
    if deps.platform_key() not in ("win32", "linux"):
        return [_("O CorridorKey só está disponível no Windows e no Linux.")]
    found = gpus()
    if found is None or not found:
        return [_("Não encontrei uma placa de vídeo NVIDIA (o nvidia-smi, que vem com o driver da NVIDIA, não "
                  "respondeu). O CorridorKey precisa de uma NVIDIA RTX série 30 ou mais nova.")]
    if any(g.ok for g in found):
        return []
    if all(g.capability == 0 for g in found):
        return [_("O driver da NVIDIA não informou a capacidade da placa. Atualize o driver da NVIDIA e abra esta "
                  "página de novo.")]
    names = ", ".join(f"{g.name} ({g.capability:.1f})" for g in found if g.name)
    return [_("A placa {placas} não tem o que o CorridorKey precisa (bfloat16, capacidade 8.0 ou mais): ele pede "
              "uma NVIDIA RTX série 30 ou mais nova.").format(placas=names)]


# ------------------------------------------------------------------ instalação
@dataclass(frozen=True)
class Installation:
    folder: Path   # ferramentas/corridorkey/<versão>
    python: Path   # o Python do ambiente
    code: Path     # a pasta do código (cwd do infer.py)
    version: str


def installation(root: str | Path | None = None) -> Installation | None:
    """A instalação em uso (com o Python do ambiente e o infer.py presentes), ou None."""
    tool = tools.get("corridorkey")
    inst = tools.current(tool, root)
    if inst is None:
        return None
    py = tools.env_python(inst.path / tools.ENV_DIR)
    code = inst.path / tool.recipe.workdir
    if not py.is_file() or not (code / "infer.py").is_file():
        return None
    return Installation(inst.path, py, code, inst.version)


def available(root: str | Path | None = None) -> bool:
    return installation(root) is not None


def temp_dir() -> Path:
    """Pasta temporária do recorte (modo de pouca memória e cache das análises) dentro da pasta do app."""
    return deps.app_data_dir() / "cache" / "corridorkey"


# ------------------------------------------------------------------ opções e linha de comando
@dataclass
class Options:
    input: str
    output_dir: str
    hint: str = "nenhuma"             # um de HINTS
    hint_path: str = ""               # imagem (máscara do 1º quadro) ou vídeo de dica
    hint_quality: float = 0.95        # o quanto confiar na dica (0 a 1)
    extras: tuple[str, ...] = ()      # "fg" (cor do primeiro plano) e/ou "checker" (sobre xadrez)
    exr: bool = False                 # sequência EXR linear (sem limite de brilho) em vez de vídeo
    despill: float = 0.5              # tirar o reflexo verde/azul: 0 (nada) a 1 (tudo)
    low_vram: bool = False            # pouca memória: mais lento, usa a pasta temporária

    def outputs(self) -> list[str]:
        return ["cutout", "alpha", *[e for e in EXTRAS if e in self.extras]]


def clip_name(path: str | Path) -> str:
    """Nome que o CorridorKey dá aos arquivos: o nome do arquivo de entrada sem a extensão."""
    return os.path.splitext(os.path.basename(os.path.normpath(str(path))))[0]


def command(python: str | Path, opts: Options, output_dir: str | Path, temp: str | Path) -> list[str]:
    """Linha de comando do `infer.py` (roda com cwd na pasta do código)."""
    cmd = [str(python), "infer.py", "--input", str(opts.input), "--output_dir", str(output_dir),
           "--outputs", *opts.outputs(), "--despill_strength", f"{max(0.0, min(1.0, opts.despill)):.2f}",
           "--temp_dir", str(temp)]
    if opts.exr:
        cmd += ["--output_format", "exr"]
    if opts.hint == "mascara" and opts.hint_path:
        cmd += ["--hint_first_frame", str(opts.hint_path)]
    elif opts.hint == "video" and opts.hint_path:
        cmd += ["--hint_video", str(opts.hint_path)]
    if opts.hint in ("mascara", "video") and opts.hint_path:
        cmd += ["--hint_quality", f"{max(0.0, min(1.0, opts.hint_quality)):.2f}"]
    if opts.low_vram:
        cmd.append("--low_vram")
    return cmd


def environment(ffmpeg_dir: str | Path | None) -> dict[str, str]:
    """Ambiente do processo: sem rede (nada é baixado na hora), o ffmpeg do app primeiro no PATH (eles
    gravam os vídeos com o ffmpeg do PATH) e, com várias placas, só a escolhida visível."""
    extra = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    found = gpus() or []
    best = best_gpu()
    if best is not None and len(found) > 1:
        extra.update(CUDA_DEVICE_ORDER="PCI_BUS_ID", CUDA_VISIBLE_DEVICES=str(best.index))
    return tools.runtime_environ(extra, [str(ffmpeg_dir)] if ffmpeg_dir else ())


# ------------------------------------------------------------------ progresso
_WINDOW = re.compile(r"window\s+(\d+)\s*/\s*(\d+)")
_PROBED = re.compile(r"probed\s+(\d+)\s+frames")
_WROTE = re.compile(r"wrote\s+\d+\s+output")


class ProgressParser:
    """Lê a saída do `infer.py` e devolve (etapa, feito, total) para a fila de tarefas."""

    def __init__(self, low_vram: bool = False):
        self.low_vram = low_vram
        self.frames = 0

    def feed(self, line: str) -> tuple[str, int, int] | None:
        if "Loading CorridorKey" in line:
            return _("Carregando o modelo…"), 0, 0
        m = _PROBED.search(line)
        if m:
            self.frames = int(m.group(1))
            return _("Lendo o vídeo ({n} quadros)…").format(n=self.frames), 0, 0
        if "RVM continuous prepass" in line:
            return _("Analisando o movimento…"), 0, 0
        if "frozen VFM prepass" in line:
            return _("Analisando a cena…"), 0, 0
        if "Hann stage1" in line:
            return _("Recortando…"), 0, 0
        m = _WINDOW.search(line)
        if m:
            i, n = int(m.group(1)), max(1, int(m.group(2)))
            if self.low_vram and i >= n:
                return _("Gravando os arquivos…"), 0, 0
            return _("Recortando…"), i, n
        if _WROTE.search(line):
            return _("Terminando…"), 1, 1
        return None


# ------------------------------------------------------------------ aviso de entrada
def source_warning(info=None, profile: str = "rec709", path: str = "") -> str:
    """Aviso quando a entrada não parece Rec.709 (o CorridorKey espera vídeo comum): log, HDR ou RAW.

    `info`: `media.MediaInfo` (ou `timeline.Source`) do arquivo; `profile`: perfil de entrada do look.
    """
    from . import media, params
    path = path or str(getattr(info, "path", "") or "")
    codec = str(getattr(info, "codec", "") or "").lower()
    if codec in RAW_CODECS or Path(path).suffix.lower() in RAW_EXTS:
        return _("Este arquivo é RAW de câmera. O CorridorKey espera vídeo Rec.709: converta para Rec.709 antes, "
                 "senão o recorte pode sair errado.")
    hdr = media.detect_profile(info) if info is not None else None
    if hdr:
        return _("Este vídeo é HDR ({curva}). O CorridorKey espera vídeo Rec.709: converta para Rec.709 antes, senão "
                 "o recorte pode sair errado.").format(curva="PQ" if hdr == "pq" else "HLG")
    if profile and profile not in ("rec709", "hlg", "pq"):
        label = dict(params.ENTRADAS).get(profile, profile)
        return _("O perfil de entrada do look é {perfil} (log). O CorridorKey espera vídeo Rec.709: converta para "
                 "Rec.709 antes, senão o recorte pode sair errado.").format(perfil=_(label))
    return ""


# ------------------------------------------------------------------ o trabalho
@dataclass
class Result:
    folder: Path
    files: list[Path] = field(default_factory=list)


def partial_dir(opts: Options) -> Path:
    """Pasta parcial ao lado do destino (marca reservada `system.PARTIAL`)."""
    return Path(opts.output_dir) / f"{clip_name(opts.input)}-corridorkey.{system.PARTIAL}"


def _promote(src: Path, dst: Path) -> None:
    """Põe um arquivo (ou pasta EXR) pronto no destino; o antigo só sai quando o novo já está lá."""
    if src.is_dir():
        aside = None
        if dst.exists():
            aside = dst.with_name(f"{dst.name}.{system.PARTIAL}-antigo-{secrets.token_hex(3)}")
            dst.rename(aside)
        try:
            src.rename(dst)
        except OSError:
            if aside is not None:
                aside.rename(dst)
            raise
        if aside is not None:
            shutil.rmtree(aside, ignore_errors=True)
    else:
        system.replace_file(src, dst)


def _failure(res: tools.ProcessResult) -> CorridorKeyError:
    low = "\n".join(res.lines).lower()
    if "out of memory" in low:
        msg = _("A placa de vídeo ficou sem memória. Ligue \"Pouca memória\" e tente de novo, ou feche outros "
                "programas que usam a placa.")
    elif "requires a cuda gpu" in low or "cuda driver" in low or "no cuda gpus" in low:
        msg = _("O CorridorKey não conseguiu usar a placa de vídeo. Atualize o driver da NVIDIA e tente de novo.")
    elif "ffmpeg binary not found" in low:
        msg = _("O ffmpeg não foi encontrado. Baixe o ffmpeg em Configurações › Componentes.")
    else:
        msg = _("O recorte falhou.")
    return CorridorKeyError(msg + "\n\n" + res.tail(12))


def run(opts: Options, progress: Progress | None = None, cancel: threading.Event | None = None,
        root: str | Path | None = None, perf=None) -> Result:
    """Recorta `opts.input` num processo separado e grava os arquivos em `opts.output_dir`.

    Levanta `tools.Cancelled` (cancelado: nada fica no destino) ou `CorridorKeyError`.
    """
    from . import media
    cancel = cancel or threading.Event()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    inst = installation(root)
    if inst is None:
        raise CorridorKeyError(_("O CorridorKey não está instalado. Baixe em Configurações › Componentes."))
    if not Path(opts.input).exists():
        raise CorridorKeyError(_("O arquivo de entrada não existe: {arquivo}").format(arquivo=opts.input))
    if opts.hint in ("mascara", "video") and opts.hint_path and not Path(opts.hint_path).exists():
        raise CorridorKeyError(_("O arquivo da dica não existe: {arquivo}").format(arquivo=opts.hint_path))
    try:
        ffmpeg_dir = Path(media.ffmpeg()).parent
    except RuntimeError as exc:
        raise CorridorKeyError(str(exc)) from exc
    out = Path(opts.output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CorridorKeyError(_("Não foi possível criar a pasta de saída:\n{erro}").format(erro=exc)) from exc
    work = partial_dir(opts)
    shutil.rmtree(work, ignore_errors=True)  # sobra de um recorte interrompido para o mesmo destino
    temp = temp_dir() / secrets.token_hex(4)
    parser = ProgressParser(opts.low_vram)

    def on_line(line: str) -> None:
        step = parser.feed(line)
        if step is not None:
            report(*step)

    report(_("Iniciando o CorridorKey…"))
    try:
        work.mkdir(parents=True)
        temp.mkdir(parents=True, exist_ok=True)
        try:
            res = tools.run_process(command(inst.python, opts, work, temp), cwd=inst.code,
                                    env=environment(ffmpeg_dir), cancel=cancel, on_line=on_line, perf=perf)
        except tools.ToolError as exc:
            raise CorridorKeyError(str(exc)) from exc
        if res.returncode != 0:
            raise _failure(res)
        produced = sorted(work.iterdir())
        if not produced:
            raise CorridorKeyError(_("O CorridorKey terminou sem gravar nenhum arquivo.") + "\n\n" + res.tail(8))
        if cancel.is_set():
            raise tools.Cancelled()
        report(_("Gravando os arquivos…"))
        result = Result(out)
        for item in produced:
            target = out / item.name
            _promote(item, target)
            result.files.append(target)
        report(_("Pronto."), 1, 1)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(temp, ignore_errors=True)


def main_output(result: Result) -> Path | None:
    """O arquivo principal do resultado: o recorte com alfa (vídeo .mov ou pasta EXR)."""
    for f in result.files:
        if "_cutout" in f.name:
            return f
    return result.files[0] if result.files else None
