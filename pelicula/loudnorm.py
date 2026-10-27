"""Volume alvo da exportação (LUFS e pico real) com o filtro `loudnorm` do ffmpeg, em duas passadas (sem Qt).

1. `measure()` mede o som que **vai mesmo para o arquivo** — o trecho do vídeo original no modo Película ou o
   WAV da mixagem (`audiomix`) no modo Edição — com `loudnorm=...:print_format=json` e devolve os valores
   medidos (`input_i`, `input_tp`, `input_lra`, `input_thresh`, `target_offset`).
2. `filter_for()` monta o filtro da segunda passada com esses valores e `linear=true`: um ganho só para o
   trecho inteiro (a dinâmica não muda). Se esse ganho levaria o pico acima do limite, o próprio `loudnorm`
   passa para o modo dinâmico, com limitador de pico real.

Os alvos ficam em `platforms.py` (−14 LUFS nas redes e serviços de streaming, −16 em podcasts, −23 com pico
real −1 dBTP na TV e no festival, EBU R 128). Só vale quando o som é recodificado: com "Copiar original" a
exportação passa a recodificar (`export._audio_mode`) e a janela avisa. Este módulo não é o medidor de volume
da interface: só prepara a exportação.
"""

from __future__ import annotations

import json
import math
import subprocess
import threading
import time

from . import media
from .i18n import _

RATE = 48000      # o loudnorm trabalha internamente a 192 kHz; a saída volta para 48 kHz
SILENCE = -70.0   # abaixo disso (LUFS integrados) não há som para normalizar
LRA_MIN = 11.0
LRA_MAX = 20.0    # faixa aceita por todas as versões do ffmpeg

_FIELDS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def _fmt(x: float) -> str:
    return f"{x:.2f}"


def _lra(measured: dict | None) -> float:
    """LRA alvo: nunca abaixo da medida (senão o `linear=true` vira modo dinâmico e mexe na dinâmica)."""
    lra = LRA_MIN
    if measured:
        lra = max(lra, float(measured.get("input_lra", 0.0)) + 1.0)
    return min(LRA_MAX, lra)


def measure_filter(target: float, true_peak: float) -> str:
    """Filtro da primeira passada (só mede e imprime o JSON)."""
    return f"loudnorm=I={_fmt(target)}:TP={_fmt(true_peak)}:LRA={_fmt(LRA_MIN)}:print_format=json"


def filter_for(measured: dict, target: float, true_peak: float) -> str:
    """Filtro da segunda passada (ganho linear calculado da medida) seguido da volta para 48 kHz."""
    def clamp(key: str, lo: float, hi: float) -> str:
        return _fmt(min(hi, max(lo, float(measured[key]))))

    return (f"loudnorm=I={_fmt(target)}:TP={_fmt(true_peak)}:LRA={_fmt(_lra(measured))}"
            f":measured_I={clamp('input_i', -99, 0)}:measured_TP={clamp('input_tp', -99, 99)}"
            f":measured_LRA={clamp('input_lra', 0, 99)}:measured_thresh={clamp('input_thresh', -99, 0)}"
            f":offset={clamp('target_offset', -99, 99)}:linear=true:print_format=none,aresample={RATE}")


def parse(stderr: str) -> dict | None:
    """Valores do bloco JSON que o `loudnorm` imprime no fim (None se não achou)."""
    end = stderr.rfind("}")
    start = stderr.rfind("{", 0, end)
    if start < 0 or end < 0:
        return None
    try:
        raw = json.loads(stderr[start:end + 1])
        return {k: float(raw[k]) for k in _FIELDS}
    except (ValueError, KeyError, TypeError):
        return None


def audible(measured: dict | None) -> bool:
    """Há som para normalizar? (silêncio total mede −inf)."""
    if not measured:
        return False
    i = measured["input_i"]
    return math.isfinite(i) and i > SILENCE


def measure_cmd(path: str, target: float, true_peak: float, start: float = 0.0, duration: float = 0.0) -> list[str]:
    """Comando da primeira passada: o mesmo trecho (`-ss`/`-t`) que a exportação grava."""
    cmd = [media.ffmpeg(), "-hide_banner", "-nostdin", "-nostats", "-v", "info"]
    if start > 0:
        cmd += ["-ss", f"{start:.6f}"]
    if duration > 0:
        cmd += ["-t", f"{duration:.6f}"]
    return cmd + ["-i", path, "-map", "0:a:0", "-vn", "-sn", "-dn", "-af", measure_filter(target, true_peak),
                  "-f", "null", "-"]


def measure(path: str, target: float, true_peak: float, start: float = 0.0, duration: float = 0.0,
            cancel: threading.Event | None = None, perf: media.Perf | None = None) -> dict | None:
    """Primeira passada: mede o som de `path` (no trecho, se dado). None se cancelado.

    Erro do ffmpeg vira RuntimeError com o final da mensagem dele.
    """
    proc = subprocess.Popen(measure_cmd(path, target, true_peak, start, duration), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **(perf or media.Perf()).popen_kwargs())
    err = bytearray()

    def drain():
        for line in proc.stderr:
            err.extend(line)
            if len(err) > 200000:
                del err[:100000]

    th = threading.Thread(target=drain, daemon=True)
    th.start()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            proc.kill()
            proc.wait()
            th.join(timeout=2)
            return None
        time.sleep(0.03)
    th.join(timeout=5)
    text = err.decode("utf-8", "replace")
    found = parse(text) if proc.returncode == 0 else None
    if found is None:
        raise RuntimeError(_("Não foi possível medir o volume do som:\n{erro}").format(erro=text.strip()[-1500:]))
    return found
