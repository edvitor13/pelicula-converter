"""Transcrição de fala no próprio computador (módulo Beta "legendas_auto"). Sem Qt.

Nada sai do computador: o som vai para o whisper.cpp (`whisper-cli`, componente `whisper_cpp`, compilado
pelo CI do PeliculaConverter a partir do código oficial) com um modelo de fala (`whisper_small` ou
`whisper_turbo`) e o Silero VAD (`silero_vad`), todos baixados em Configurações › Componentes.

Caminho:

1. o som vira um WAV de 16 kHz mono (ffmpeg): o trecho de um arquivo (`transcribe_file`, legendas presas
   ao arquivo, que acompanham a montagem) ou a mixagem da sequência (`transcribe_sequence`, pelo
   `audiomix`, legendas no tempo da sequência);
2. o `whisper-cli` roda com o VAD ligado (pula os silêncios e não inventa texto neles), uma palavra por
   segmento (`-ml 1 -sow`: os tempos de segmento já vêm corrigidos pelo VAD) e saída JSON; o progresso vem
   das linhas "progress = N%" (`-pp`);
3. as palavras viram legendas (`subtitles.cues_from_words`).

Placa de vídeo: o pacote do whisper.cpp tem o Vulkan como módulo carregado na hora; sem driver Vulkan ele
roda na CPU sozinho. `job_kind` põe o trabalho na fila da GPU quando há o carregador do Vulkan no sistema.
Se a tentativa com a placa falhar (driver com defeito, memória), a transcrição recomeça uma vez no
processador (`-ng`). Cancelar encerra o processo (`tools.run_process`).
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import deps, jobs, subtitles, tools
from .i18n import N_, _
from .subtitles import Cue, Word

ENGINE_ID = "whisper_cpp"
VAD_ID = "silero_vad"
MODELS = {"small": "whisper_small", "turbo": "whisper_turbo"}     # modelo → id da ferramenta
MODEL_LABELS = {"small": N_("Rápido (small)"), "turbo": N_("Preciso (turbo)")}
DEFAULT_MODEL = "small"
LANGUAGES = {"auto": N_("Detectar o idioma"), "pt": N_("Português"), "en": N_("Inglês"), "es": N_("Espanhol")}
SAMPLE_RATE = 16_000
JOB_KEY = "legendas_auto"

# Comando do motor nos testes (um whisper-cli falso em Python); None = o do componente instalado.
WHISPER_CMD: list[str] | None = None

Progress = Callable[[str, int, int], None]


class TranscribeError(RuntimeError):
    """Falha com mensagem para o usuário (PT-BR)."""


@dataclass
class Options:
    model: str = DEFAULT_MODEL          # chave de MODELS
    language: str = "auto"              # chave de LANGUAGES (ou outro código ISO 639-1 do whisper)
    gpu: bool = True                    # tentar a placa de vídeo (Vulkan)
    threads: int = 0                    # 0 = automático
    max_chars: int = 42                 # legendas: caracteres por linha
    max_lines: int = 2


@dataclass
class Result:
    words: list[Word]
    cues: list[Cue]
    language: str                       # o idioma reconhecido ("pt", "en"...)
    device: str                         # "gpu" ou "cpu": onde rodou
    path: str | None = None             # arquivo de origem (tempos do arquivo); None = tempo da sequência
    start: float = 0.0                  # trecho transcrito (s do arquivo ou da sequência)
    end: float = 0.0


@dataclass(frozen=True)
class Engine:
    cmd: tuple[str, ...]                # o whisper-cli (ou o falso dos testes)
    model: Path
    vad: Path


# ------------------------------------------------------------------ componentes
def components(model: str = DEFAULT_MODEL) -> list[tools.Tool]:
    """As ferramentas que a transcrição com este modelo precisa."""
    return [tools.get(ENGINE_ID), tools.get(VAD_ID), tools.get(MODELS.get(model, MODELS[DEFAULT_MODEL]))]


def missing(model: str = DEFAULT_MODEL, root: str | Path | None = None) -> list[tools.Tool]:
    """As que ainda não estão instaladas (vazio = pronto para transcrever)."""
    out = []
    for t in components(model):
        if t.id == ENGINE_ID and WHISPER_CMD is not None:
            continue
        if tools.executable(t, root=root) is None:
            out.append(t)
    return out


def available(root: str | Path | None = None) -> bool:
    """O motor e o VAD instalados e pelo menos um modelo."""
    return any(not missing(m, root) for m in MODELS)


def installed_models(root: str | Path | None = None) -> list[str]:
    return [m for m in MODELS if tools.executable(tools.get(MODELS[m]), root=root) is not None]


def engine(model: str = DEFAULT_MODEL, root: str | Path | None = None) -> Engine:
    """Os caminhos do motor, do modelo e do VAD. TranscribeError diz o que falta baixar."""
    lack = missing(model, root)
    if lack:
        names = ", ".join(_(t.name) for t in lack)
        raise TranscribeError(_("Para transcrever, baixe em Configurações › Componentes: {lista}.").format(lista=names))
    exe = list(WHISPER_CMD) if WHISPER_CMD is not None else [str(tools.executable(tools.get(ENGINE_ID), root=root))]
    model_path = tools.executable(tools.get(MODELS.get(model, MODELS[DEFAULT_MODEL])), root=root)
    vad_path = tools.executable(tools.get(VAD_ID), root=root)
    return Engine(tuple(exe), Path(model_path), Path(vad_path))


# ------------------------------------------------------------------ placa de vídeo
def vulkan_available() -> bool:
    """Se há o carregador do Vulkan no sistema (vem com o driver de vídeo)."""
    if sys.platform == "win32":
        root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
        return (Path(root) / "System32" / "vulkan-1.dll").is_file()
    for p in ("/usr/lib/x86_64-linux-gnu/libvulkan.so.1", "/usr/lib64/libvulkan.so.1", "/usr/lib/libvulkan.so.1",
              "/lib/x86_64-linux-gnu/libvulkan.so.1"):
        if os.path.exists(p):
            return True
    import ctypes.util
    return bool(ctypes.util.find_library("vulkan"))


def job_kind(opts: Options) -> str:
    """Fila do trabalho: GPU quando vai usar a placa (uma por vez, como a exportação); senão CPU."""
    return jobs.GPU if opts.gpu and vulkan_available() else jobs.CPU


# ------------------------------------------------------------------ som
def temp_dir() -> Path:
    return deps.app_data_dir() / "cache" / "transcricao"


def _short(path: str | Path) -> str:
    """Caminho que o whisper-cli consegue abrir no Windows (ele recebe a linha de comando na página de código
    do sistema): o nome curto 8.3 quando há acentos ou outros caracteres fora do ASCII."""
    from .corridorkey import short_path
    return short_path(path)


def _run_ffmpeg(cmd: list[str], what: str, cancel: threading.Event | None, perf) -> None:
    res = tools.run_process(cmd, cancel=cancel, perf=perf)
    if res.returncode != 0:
        text = res.tail()
        low = text.lower()
        if "matches no streams" in low or "does not contain any stream" in low or "output file is empty" in low:
            raise TranscribeError(_("{arquivo} não tem som para transcrever.").format(arquivo=what))
        raise TranscribeError(_("Não foi possível ler o som de {arquivo}:\n{erro}").format(arquivo=what,
                                                                                           erro=text[-1500:]))


def extract_audio(path: str, wav: str | Path, start: float = 0.0, duration: float = 0.0,
                  cancel: threading.Event | None = None, perf=None) -> None:
    """O som do trecho [start, start + duration) do arquivo num WAV de 16 kHz mono (16 bits)."""
    from . import media
    cmd = [media.ffmpeg(), "-v", "error", "-nostdin", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.6f}"]
    cmd += ["-i", path]
    if duration > 0:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(wav)]
    _run_ffmpeg(cmd, os.path.basename(path), cancel, perf)


# ------------------------------------------------------------------ whisper-cli
def cpu_env() -> dict[str, str]:
    """Ambiente da tentativa no processador: além do `-ng`, o módulo Vulkan do ggml não abre nenhuma placa
    (`GGML_VK_VISIBLE_DEVICES` vazio), para um driver com defeito não derrubar o processo ao carregar."""
    return dict(os.environ, GGML_VK_VISIBLE_DEVICES="")


def threads_for(opts: Options, gpu: bool) -> int:
    if opts.threads > 0:
        return opts.threads
    n = os.cpu_count() or 4
    return 4 if gpu else max(1, min(8, n - 1))


def command(eng: Engine, wav: str | Path, out_base: str | Path, opts: Options, gpu: bool) -> list[str]:
    """Linha de comando do whisper-cli (veja o cabeçalho do módulo)."""
    lang = opts.language if re.fullmatch(r"[a-z]{2,3}|auto", opts.language or "") else "auto"
    cmd = [*eng.cmd, "-m", _short(eng.model), "-f", _short(wav), "-of", _short(out_base), "-oj",
           "-l", lang, "-t", str(threads_for(opts, gpu)), "-ml", "1", "-sow", "-sns", "-pp",
           "--vad", "-vm", _short(eng.vad)]
    if not gpu:
        cmd.append("-ng")
    return cmd


_PROGRESS = re.compile(r"progress\s*=\s*(\d+)\s*%")
# o whisper.cpp escreve isto quando o modelo vai para a placa (sem placa: "no GPU found")
_USING_GPU = re.compile(r"whisper_backend_init_gpu: using \S+ backend")
_SPECIAL = re.compile(r"\[[A-Z_ ]+\]|\[_[A-Z]+_\]")       # [BLANK_AUDIO], [MUSIC], [_BEG_]...
_OPENING = ("¿", "¡", "«", "“", "‘", "(", "[", "\"", "'", "—", "–")


def parse_progress(line: str) -> int | None:
    m = _PROGRESS.search(line)
    return min(100, int(m.group(1))) if m else None


def parse_output(data: dict, offset: float = 0.0, limit: float | None = None) -> tuple[list[Word], str]:
    """JSON do whisper-cli (`-ml 1 -sow -oj`) → palavras com tempo (`offset` + tempo no WAV) e o idioma.

    Pontuação solta vai para a palavra de antes ("!"), a que abre ("¿") para a seguinte; marcadores como
    [BLANK_AUDIO] saem; um segmento com espaços é dividido pelo tamanho de cada palavra."""
    words: list[Word] = []
    pending = ""
    items = data.get("transcription") if isinstance(data, dict) else None
    for seg in items if isinstance(items, list) else []:
        try:
            a = float(seg["offsets"]["from"]) / 1000.0 + offset
            b = float(seg["offsets"]["to"]) / 1000.0 + offset
        except (KeyError, TypeError, ValueError):
            continue
        text = subtitles.clean_text(seg.get("text", ""), 200).replace("\n", " ")
        if not text or _SPECIAL.fullmatch(text):
            continue
        if limit is not None:
            a, b = min(a, limit), min(b, limit)
        b = max(a, b)
        parts = text.split()
        if all(not any(ch.isalnum() for ch in p) for p in parts):
            joined = "".join(parts)
            if joined.endswith(_OPENING) or (joined and joined[0] in _OPENING and len(joined) == 1):
                pending += joined
            elif words:
                last = words[-1]
                words[-1] = Word(last.start, max(last.end, b), last.text + joined)
            else:
                pending += joined
            continue
        total = sum(len(p) for p in parts) or 1
        t = a
        for i, p in enumerate(parts):
            e = b if i == len(parts) - 1 else t + (b - a) * len(p) / total
            words.append(Word(t, e, (pending + p) if i == 0 else p))
            t = e
        pending = ""
    res = data.get("result") if isinstance(data, dict) else None
    lang = res.get("language") if isinstance(res, dict) and isinstance(res.get("language"), str) else ""
    return words, lang


def _failure(res: tools.ProcessResult, model: str) -> TranscribeError:
    text = res.tail()
    low = text.lower()
    if "failed to allocate" in low or "out of memory" in low or "outofdevicememory" in low.replace("_", ""):
        return TranscribeError(_("Faltou memória para o modelo {modelo}. Feche outros programas ou use o modelo "
                                 "Rápido (small).").format(modelo=model))
    return TranscribeError(_("A transcrição falhou (código {codigo}):\n{saida}").format(
        codigo=res.returncode, saida=text[-1500:]))


def run_engine(eng: Engine, wav: str | Path, opts: Options, workdir: str | Path, offset: float = 0.0,
               limit: float | None = None, progress: Progress | None = None,
               cancel: threading.Event | None = None, perf=None) -> tuple[list[Word], str, str]:
    """Roda o whisper-cli no WAV. Devolve (palavras, idioma, "gpu"/"cpu"). Tenta a placa e, se falhar, o
    processador. Levanta TranscribeError ou tools.Cancelled."""
    cancel = cancel or threading.Event()
    stage = _("Transcrevendo…")

    def report(stage_text: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage_text, done, total)

    used_gpu = []

    def on_line(line: str) -> None:
        pct = parse_progress(line)
        if pct is not None:
            report(stage, pct, 100)
        elif _USING_GPU.search(line):
            used_gpu.append(True)

    attempts = [True, False] if opts.gpu else [False]
    last: tools.ProcessResult | None = None
    for gpu in attempts:
        out_base = Path(workdir) / ("saida-gpu" if gpu else "saida-cpu")
        out_json = out_base.with_suffix(".json")
        out_json.unlink(missing_ok=True)
        report(stage, 0, 100)
        res = tools.run_process(command(eng, wav, out_base, opts, gpu), cwd=workdir, cancel=cancel,
                                on_line=on_line, perf=perf, env=None if gpu else cpu_env())
        if res.returncode == 0 and out_json.is_file():
            try:
                data = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
            except ValueError as exc:
                raise TranscribeError(_("A transcrição terminou, mas o resultado não pôde ser lido: {erro}").format(
                    erro=exc)) from exc
            words, lang = parse_output(data, offset, limit)
            return words, lang, "gpu" if gpu and used_gpu else "cpu"
        last = res
        if gpu:
            stage = _("A placa de vídeo falhou; transcrevendo no processador…")
    assert last is not None
    raise _failure(last, opts.model)


def _workdir() -> Path:
    base = temp_dir()
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="t-", dir=base))


def _finish(words: list[Word], lang: str, device: str, opts: Options, path: str | None, start: float,
            end: float) -> Result:
    cues = subtitles.cues_from_words(words, max_chars=opts.max_chars, max_lines=opts.max_lines)
    return Result(words, cues, lang, device, path, start, end)


def transcribe_file(path: str, opts: Options | None = None, start: float = 0.0, end: float = 0.0,
                    progress: Progress | None = None, cancel: threading.Event | None = None, perf=None,
                    root: str | Path | None = None) -> Result:
    """Transcreve o trecho [start, end) segundos do arquivo (end 0 = até o fim). Tempos do arquivo: as
    legendas ficam presas a ele (`Subtitles.sources[path]`) e acompanham a montagem."""
    opts = opts or Options()
    eng = engine(opts.model, root)
    work = _workdir()
    try:
        if progress:
            progress(_("Lendo o som…"), 0, 0)
        wav = work / "som.wav"
        extract_audio(path, wav, start, max(0.0, end - start) if end > start else 0.0, cancel, perf)
        words, lang, device = run_engine(eng, wav, opts, work, offset=start, limit=end if end > start else None,
                                         progress=progress, cancel=cancel, perf=perf)
        return _finish(words, lang, device, opts, path, start, end)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def transcribe_sequence(seq, opts: Options | None = None, start: int = 0, end: int = -1,
                        progress: Progress | None = None, cancel: threading.Event | None = None, perf=None,
                        root: str | Path | None = None) -> Result:
    """Transcreve o som mixado da sequência nos quadros [start, end) (end -1 = até o fim). Tempos da
    sequência (`Subtitles.cues`): não acompanham mudanças na montagem."""
    from . import audiomix
    opts = opts or Options()
    eng = engine(opts.model, root)
    fps = seq.fps
    end = seq.duration if end < 0 else end
    work = _workdir()
    try:
        if progress:
            progress(_("Mixando o som…"), 0, 0)
        mix = work / "mixagem.wav"
        try:
            ok = audiomix.render_mix(seq, str(mix), start, end, cancel, perf)
        except RuntimeError as exc:
            raise TranscribeError(str(exc)[-1500:]) from exc
        if cancel is not None and cancel.is_set():
            raise tools.Cancelled()
        if not ok:
            raise TranscribeError(_("A sequência não tem som para transcrever neste trecho."))
        wav = work / "som.wav"
        extract_audio(str(mix), wav, 0.0, 0.0, cancel, perf)
        t0, t1 = start / fps, end / fps
        words, lang, device = run_engine(eng, wav, opts, work, offset=t0, limit=t1, progress=progress,
                                         cancel=cancel, perf=perf)
        return _finish(words, lang, device, opts, None, t0, t1)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def merge(doc: subtitles.Subtitles, result: Result) -> None:
    """Põe o resultado nas legendas do projeto, trocando as que já havia no trecho transcrito."""
    def keep(c: Cue) -> bool:
        return c.end <= result.start + 1e-6 or (result.end > result.start and c.start >= result.end - 1e-6)

    if result.path is not None:
        old = [c for c in doc.sources.get(result.path, []) if keep(c)]
        doc.sources[result.path] = subtitles.sort_cues(old + result.cues)
    else:
        doc.cues = subtitles.sort_cues([c for c in doc.cues if keep(c)] + result.cues)
    if result.language and not doc.language:
        doc.language = result.language


def make_job(opts: Options, title: str, *, path: str | None = None, seq=None, start: float | int = 0,
             end: float | int = 0, root: str | Path | None = None, perf=None) -> jobs.Job:
    """Trabalho para a fila (`jobs.shared().submit(job)`): transcreve o arquivo `path` (segundos) ou a
    sequência `seq` (quadros). O resultado (`Result`) fica em `job.result`."""
    def fn(job: jobs.Job) -> Result:
        cb = job.progress_callback()
        if path is not None:
            return transcribe_file(path, opts, float(start), float(end), cb, job.cancel_event, perf, root)
        return transcribe_sequence(seq, opts, int(start), int(end) if end else -1, cb, job.cancel_event, perf, root)

    return jobs.Job(fn, title, kind=job_kind(opts), key=JOB_KEY)
