"""1.9, estabilização do clipe (F3, #68; ARQUITETURA §51.2). Sem GPU nem Qt.

Duas metades, como pede a regra da receita única:

- **Análise** (um trabalho de CPU da fila, `analyze`): o `vidstabdetect` do ffmpeg (biblioteca vid.stab) numa
  decodificação reduzida (`movimento.ANALYSIS_H` linhas) grava os vetores locais de cada quadro num `.trf` em texto
  (`fileformat=ascii`); `parse_trf` os lê e `motions_from_trf` ajusta a semelhança de cada quadro com o ajuste robusto de
  `movimento.fit_similarity`. Sem o filtro (ffmpeg compilado sem a vid.stab), o caminho em numpy (`movimento.estimate`)
  mede o mesmo, mais devagar, e a janela avisa. O resultado é guardado na fonte (`Source.analysis["estabilizacao"]`, JSON
  "analise"): o movimento quadro a quadro em px@1080 (`vfx.pack`, float32 n × 4), o carimbo do arquivo e os parâmetros.
  Arquivo com taxa de quadros variável (o número de quadros lidos não bate com o da fonte) é recusado. O
  `vidstabtransform` nunca é usado: a imagem é sempre a do app.
- **Imagem** (`vfx.GEOMETRY["estabilizar"]`, em `compositor.clip_uniforms`): a correção do quadro do arquivo que a camada
  mostra (`Layer.src_frame`), calculada da análise inteira — trajetória suavizada por `estab_suavizar` segundos do arquivo,
  com ou sem a rotação, e o zoom que esconde as bordas no arquivo inteiro (`estab_bordas` = "ampliar") vezes
  `1 + estab_zoom_extra` — multiplica a matriz do enquadramento: uma reamostragem só, na GPU, no `CLIP` de sempre. Como
  tudo sai do tempo do arquivo, dividir, aparar ou mudar a velocidade não mudam a correção de um quadro.

Desligado (`estab_on` falso, padrão), sem análise ou com "Desligar todos os efeitos", a matriz é a de antes: os uniforms
saem iguais (nada no plano, nenhum passo).
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
import threading
from typing import Any, Callable

import numpy as np

from . import movimento, vfx
from .i18n import _

KIND = "estabilizacao"              # `Source.analysis[KIND]`
EFFECT_ID = "estabilizar"           # `vfx.EFFECTS` / `vfx.GEOMETRY`
MODULE = "movimento"                # `modules.MODULES` (Beta)
KEYS = ("estab_on", "estab_suavizar", "estab_rotacao", "estab_bordas", "estab_zoom_extra")
VERSION = 1
VIDSTAB = {"shakiness": 8, "accuracy": 15, "stepsize": 6}  # da documentação do vidstabdetect; 8 = tremor de mão forte
TRF_NAME = "transformacoes.trf"
FRAME_SLACK = 1  # quadros de diferença aceitos entre a leitura e a fonte (a duração arredondada de um MKV, por exemplo)


class AnalysisError(RuntimeError):
    """A análise não pôde ser feita (mensagem para o usuário)."""


# ------------------------------------------------------------------ vid.stab
def available() -> bool:
    """O ffmpeg desta máquina tem o `vidstabdetect` (o build "essentials" do gyan.dev e o GPL do BtbN têm)."""
    from . import media
    return "vidstabdetect" in media.filters()


_ASCII: bool | None = None


def _ascii_option() -> bool:
    """O `vidstabdetect` aceita `fileformat` (vid.stab 1.1+; as anteriores só gravam o texto)."""
    global _ASCII
    if _ASCII is None:
        from . import media
        try:
            res = subprocess.run([media.ffmpeg(), "-hide_banner", "-h", "filter=vidstabdetect"], capture_output=True,
                                 creationflags=media.NO_WINDOW, timeout=30)
            _ASCII = "fileformat" in res.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            _ASCII = False
    return _ASCII


_FRAME = re.compile(r"^Frame\s+(\d+)\s+\(List\s+(\d+)\s+\[(.*)\]\)\s*$")
_LM = re.compile(r"\(LM\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)")


def parse_trf(text: str) -> list[np.ndarray]:
    """Os vetores locais de um `.trf` em texto da vid.stab ("VID.STAB 1"): um array (m, 7) por quadro, na ordem do
    arquivo — (v.x, v.y, f.x, f.y, f.size, contraste, casamento) — com v o deslocamento da câmera (o campo em f no quadro
    atual está em f + v no anterior). O primeiro quadro não tem vetores. ValueError se não for o formato em texto."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("VID.STAB"):
        raise ValueError("não é um .trf em texto da vid.stab")
    frames: dict[int, np.ndarray] = {}
    for ln in lines[1:]:
        if not ln or ln.startswith("#"):
            continue
        m = _FRAME.match(ln.strip())
        if m is None:
            raise ValueError(f"linha inesperada no .trf: {ln[:60]!r}")
        n, count = int(m.group(1)), int(m.group(2))
        lms = [tuple(float(x) for x in g) for g in _LM.findall(m.group(3))]
        if len(lms) != count:
            raise ValueError(f"quadro {n}: {count} campos anunciados, {len(lms)} lidos")
        frames[n] = np.array(lms, np.float64).reshape(-1, 7)
    if not frames:
        return []
    last = max(frames)
    return [frames.get(i, np.zeros((0, 7))) for i in range(1, last + 1)]


def motions_from_trf(frames: list[np.ndarray], size: tuple[int, int], width: int, height: int) -> np.ndarray:
    """O movimento de cada quadro (n, 4) float32 em px@1080 da fonte (`width` × `height`) a partir dos vetores de
    `parse_trf`, medidos numa imagem de `size` px: pares p0 = f + v (anterior), p1 = f (atual), centros dos pixels,
    ajustados por `movimento.fit_similarity` com o contraste como peso."""
    w, h = size
    sx = 1080.0 * width / max(1, height) / w
    sy = 1080.0 / h
    center = movimento.frame_center(width, height)
    out = np.zeros((len(frames), 4), np.float32)
    for k, lm in enumerate(frames):
        if k == 0 or len(lm) == 0:
            continue
        f = lm[:, 2:4] + 0.5
        p0 = (f + lm[:, 0:2]) * (sx, sy)
        p1 = f * (sx, sy)
        params, _w = movimento.fit_similarity(p0, p1, center, np.maximum(lm[:, 5], 1e-3))
        out[k] = params
    return out


def _vidstab(src, size: tuple[int, int], cancel: threading.Event | None,
             report: Callable[[int, int], None] | None) -> tuple[list[np.ndarray], dict]:
    """Roda o `vidstabdetect` numa pasta temporária e devolve (vetores de cada quadro, parâmetros)."""
    from . import media
    info = src.to_info()
    opts = dict(VIDSTAB)
    filt = f"scale={size[0]}:{size[1]}:flags=bicubic,vidstabdetect=result={TRF_NAME}"
    if _ascii_option():
        filt += ":fileformat=ascii"
    filt += "".join(f":{k}={v}" for k, v in opts.items())
    with tempfile.TemporaryDirectory(prefix="pelicula_estab_") as tmp:
        args = [media.ffmpeg(), "-v", "error", "-nostdin", "-hide_banner"]
        if getattr(info, "seq_start", -1) >= 0:
            args += media.sequence_input(info, 0)
        args += ["-i", info.path, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", filt,
                 "-progress", "pipe:1", "-nostats", "-f", "null", "-"]
        proc = subprocess.Popen(args, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, **media.Perf().popen_kwargs())
        err = bytearray()

        def drain():
            for line in proc.stderr:
                if len(err) < 20000:
                    err.extend(line)

        t = threading.Thread(target=drain, daemon=True)
        t.start()
        try:
            for raw in proc.stdout:
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    break
                line = raw.decode("ascii", "replace").strip()
                if line.startswith("frame=") and report is not None:
                    try:
                        report(int(line[6:]), int(src.frames))
                    except ValueError:
                        pass
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            t.join(timeout=2)
        if cancel is not None and cancel.is_set():
            from .jobs import Cancelled
            raise Cancelled()
        path = os.path.join(tmp, TRF_NAME)
        if proc.returncode != 0 or not os.path.exists(path):
            raise AnalysisError(_("O ffmpeg não conseguiu analisar o movimento: {erro}").format(
                erro=err.decode("utf-8", "replace").strip()[-400:] or proc.returncode))
        with open(path, encoding="ascii", errors="replace") as fh:
            text = fh.read()
    return parse_trf(text), opts


# ------------------------------------------------------------------ análise
def check_source(src) -> None:
    """AnalysisError se a fonte não serve para a análise (imagem, sem arquivo, sem imagem de vídeo)."""
    if src is None or not src.is_file or src.is_image or not src.has_video or src.frames < 2:
        raise AnalysisError(_("Só dá para estabilizar um vídeo (não uma imagem, um título ou uma sequência)."))


def _fit_count(motions: np.ndarray, frames: int) -> np.ndarray:
    """Confere o número de quadros lidos com o da fonte: até `FRAME_SLACK` de diferença completa ou corta no fim; mais
    que isso é taxa de quadros variável (os quadros não cairiam no lugar)."""
    n = len(motions)
    if abs(n - frames) > FRAME_SLACK:
        raise AnalysisError(_("Foram lidos {lidos} quadros, mas o arquivo diz ter {quadros}: parece um vídeo com taxa de "
                              "quadros variável (de celular, por exemplo). Converta-o para uma taxa fixa e analise de "
                              "novo.").format(lidos=n, quadros=frames))
    if n < frames:
        motions = np.vstack([motions, np.zeros((frames - n, 4), np.float32)])
    return np.ascontiguousarray(motions[:frames], dtype=np.float32)


def analyze(src, cancel: threading.Event | None = None, report: Callable[[int, int], None] | None = None,
            method: str = "auto") -> dict[str, Any]:
    """A análise da fonte (o valor de `Source.analysis[KIND]`). `method`: "auto" (vid.stab se houver, senão numpy),
    "vidstab" ou "numpy". `report(feito, total)` dá o progresso; `cancel` interrompe (`jobs.Cancelled`)."""
    check_source(src)
    size = movimento.analysis_size(src.width, src.height)
    use_vidstab = method == "vidstab" or (method == "auto" and available())
    if use_vidstab:
        frames, opts = _vidstab(src, size, cancel, report)
        motions = motions_from_trf(frames, size, src.width, src.height)
        how = "vidstab"
    else:
        info = src.to_info()
        most = int(src.frames) + FRAME_SLACK + 1  # lê um pouco além: um arquivo com mais quadros é recusado também
        reads = movimento.read_gray(info, 0, most, size, (lambda: cancel.is_set()) if cancel else None)
        motions = movimento.estimate(reads, most, 1080.0 / size[1],
                                     (lambda d, _t: report(d, int(src.frames))) if report else None)
        if cancel is not None and cancel.is_set():
            from .jobs import Cancelled
            raise Cancelled()
        opts = {}
        how = "numpy"
    motions = _fit_count(motions, int(src.frames))
    return {"versao": VERSION, "metodo": how, "carimbo": vfx.stamp(src.path), "altura": int(size[1]),
            "quadros": int(len(motions)), "parametros": opts, "movimento": vfx.pack(motions)}


def entry_of(src) -> dict | None:
    """A análise guardada na fonte (ou None)."""
    entry = (getattr(src, "analysis", None) or {}).get(KIND) if src is not None else None
    return entry if isinstance(entry, dict) and isinstance(entry.get("movimento"), dict) else None


def describe(src) -> str:
    """Uma linha para o cartão: há análise? de que jeito? o arquivo mudou?"""
    entry = entry_of(src)
    if entry is None:
        return _("Ainda sem análise: clique em Analisar.")
    if vfx.stale(src, KIND):
        return _("O arquivo mudou depois da análise: analise de novo.")
    if entry.get("metodo") == "numpy":
        return _("Analisado sem a vid.stab ({n} quadros).").format(n=entry.get("quadros", 0))
    return _("Analisado ({n} quadros).").format(n=entry.get("quadros", 0))


# ------------------------------------------------------------------ correção na imagem
_CACHE: dict[tuple, np.ndarray] = {}
_CACHE_LOCK = threading.Lock()


def corrections_for(src, values: dict) -> np.ndarray | None:
    """As correções de todos os quadros da fonte (n, 3, 3), já no uv do clipe (uv da saída → uv do quadro original),
    com o zoom; None sem análise. Guardadas por análise e ajustes (a prévia e a exportação pedem o mesmo)."""
    entry = entry_of(src)
    motions = vfx.unpack(entry["movimento"]) if entry is not None else None
    if motions is None or motions.ndim != 2 or motions.shape[1] != 4 or len(motions) == 0:
        return None
    fps = float(src.fps) if src.fps and src.fps > 0 else 24.0
    sigma = max(0.0, float(values.get("estab_suavizar", 1.0))) * fps
    rot = bool(values.get("estab_rotacao", True))
    borders = str(values.get("estab_bordas", "ampliar"))
    extra = max(0.0, float(values.get("estab_zoom_extra", 0.0)))
    key = (id(motions), round(sigma, 6), rot, borders, round(extra, 6), int(src.width), int(src.height))
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    w1 = 1080.0 * src.width / max(1, src.height)
    center = movimento.frame_center(src.width, src.height)
    corr = movimento.corrections(motions, center, sigma, rot)
    zoom = movimento.auto_zoom(corr, w1, 1080.0) if borders == "ampliar" else 1.0
    corr = corr @ movimento.zoom_matrix(zoom * (1.0 + extra), center)
    s = np.diag([w1, 1080.0, 1.0])
    s_inv = np.diag([1.0 / w1, 1.0 / 1080.0, 1.0])
    out = s_inv @ corr @ s
    out.setflags(write=False)
    with _CACHE_LOCK:
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[key] = out
    return out


def zoom_of(src, values: dict) -> float:
    """O zoom que a correção usa (1 = nenhum): para o cartão dizer quanto a imagem foi ampliada."""
    corr = corrections_for(src, values)
    if corr is None:
        return 1.0
    return float(1.0 / math.sqrt(abs(np.linalg.det(corr[0][:2, :2]))))


def geometry(seq, layer, m: np.ndarray) -> np.ndarray:
    """Provedor de `vfx.GEOMETRY`: a correção do quadro `layer.src_frame` antes do enquadramento do clipe."""
    v = layer.values if layer.values is not None else layer.clip.values
    if not v.get("estab_on"):
        return m
    src = seq.sources.get(layer.clip.src)
    if src is None or not src.is_file or src.is_image:
        return m
    corr = corrections_for(src, v)
    if corr is None:
        return m
    k = min(max(int(layer.src_frame), 0), len(corr) - 1)
    return corr[k] @ m


def _active(values: dict) -> bool:
    return bool(values.get("estab_on"))


# Sem passos na GPU: a estabilização é só geometria. O efeito registrado serve ao aviso do módulo (`vfx.modules_used`).
vfx.register(vfx.Effect(EFFECT_ID, MODULE, 0, active=_active, passes=lambda ctx: [], keys=KEYS))
vfx.GEOMETRY[EFFECT_ID] = geometry
