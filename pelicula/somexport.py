"""Exportar só o som (1.8, ARQUITETURA §43.6): "Só o som" grava a mixagem do trecho num arquivo de som; "stems" grava uma
faixa por arquivo (`<nome>_A1_<faixa>.wav`…), todas do mesmo tamanho e no mesmo começo.

Entra pela mesma fila e pelo mesmo `export.run_job` da exportação de vídeo (`ExportSettings.sound_only`); a mixagem é a de
sempre (`somcache.mix`, a prévia e a exportação de vídeo usam a mesma). O formato vem de `ExportSettings.audio` entre
`FORMATS` (as chaves de `export.AUDIO_ARGS`). O volume alvo (`loudness`) vale para "Só o som"; nos stems não (cada faixa
sozinha não tem o loudness da mistura, e quem junta os stems espera o nível de cada uma na mixagem).

No modo Película, com o arquivo inteiro sem montagem (`job.sequence` None), "Só o som" grava o som do próprio arquivo
no trecho; stems não existem ali (o arquivo tem uma faixa de som só).

Gravação segura como a do vídeo: cada arquivo vai para o parcial ao lado (`system.partial_path`) e só troca de nome
quando todos terminaram. O WAV final da mixagem existe em `_mix_to` antes de qualquer codificação: é o ponto de entrada
de um processamento da mixagem inteira (nada é aplicado depois dele além do volume alvo e do codificador).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import media, system, timeline
from .i18n import N_, _

# O que exportar (`ExportSettings.sound_only`): "" vídeo e som (padrão), "som" só o som, "stems" uma faixa por arquivo.
MODES = [("", N_("Vídeo e som")), ("som", N_("Só o som")), ("stems", N_("Só o som, uma faixa por arquivo (stems)"))]
# Formatos do som sozinho: chaves de `export.AUDIO_ARGS` e a extensão de cada um.
FORMATS = [("pcm24", N_("WAV 24 bits (sem perdas)")), ("flac", N_("FLAC (sem perdas)")), ("aac320", N_("AAC 320 kb/s")),
           ("mp3", N_("MP3 320 kb/s"))]
EXT = {"pcm24": "wav", "flac": "flac", "aac320": "m4a", "mp3": "mp3"}
FROM_EXT = {"wav": "pcm24", "flac": "flac", "m4a": "aac320", "aac": "aac320", "mp3": "mp3"}


def wants(s) -> bool:
    """A exportação é só de som (`export.ExportSettings`)?"""
    return getattr(s, "sound_only", "") in ("som", "stems")


def sound_format(s) -> str:
    """O formato do som sozinho: `s.audio` se for um de `FORMATS`; senão WAV 24 bits."""
    return s.audio if s.audio in EXT else "pcm24"


def ext(s) -> str:
    return EXT[sound_format(s)]


def _safe(name: str) -> str:
    """Nome de faixa que serve em nome de arquivo nos dois sistemas."""
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", name.strip()).strip("._")[:60]


def stem_path(out_path: str, kind: str, idx: int, name: str, fmt: str = "pcm24") -> str:
    """`video_A1_Dialogo.wav` ao lado de `out_path` (`video.wav`). O nome padrão da faixa ("A1") não se repete; os tons
    das barras de cor ficam na faixa de vídeo deles (`_V1`)."""
    tag = ("V" if kind == timeline.VIDEO else "A") + str(idx + 1)
    name = _safe(name)
    p = Path(out_path)
    stem = f"{p.stem}_{tag}" + (f"_{name}" if name and name.upper() != tag else "")
    return str(p.with_name(f"{stem}.{EXT.get(fmt, 'wav')}"))


def stem_paths(seq: timeline.Sequence, out_path: str, fmt: str = "pcm24") -> list[str]:
    """Os stems que a sequência pode gerar (uma por faixa de som; a janela mostra; a gravação só cria os que tocam)."""
    return [stem_path(out_path, timeline.AUDIO, i, t.name, fmt) for i, t in enumerate(seq.kind_tracks(timeline.AUDIO))]


def encode_cmd(src: str, out: str, fmt: str, start: float = 0.0, duration: float = 0.0, af: str = "") -> list[str]:
    """ffmpeg: o som de `src` (no trecho, se dado) no formato `fmt`, com o filtro `af` (o volume alvo)."""
    from .export import AUDIO_ARGS
    cmd = [media.ffmpeg(), "-hide_banner", "-nostdin", "-nostats", "-v", "error", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.6f}"]
    if duration > 0:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-i", src, "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1"]
    if af:
        cmd += ["-af", af]
    return cmd + list(AUDIO_ARGS[fmt]) + [out]


def _run(cmd: list[str], cancel: threading.Event, perf: media.Perf) -> bool:
    """Roda o ffmpeg; False se cancelado (o processo é encerrado); erro vira RuntimeError com o fim da mensagem."""
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            **perf.popen_kwargs())
    err = bytearray()

    def drain():
        for line in proc.stderr:
            err.extend(line)
            if len(err) > 200000:
                del err[:100000]

    th = threading.Thread(target=drain, daemon=True)
    th.start()
    while proc.poll() is None:
        if cancel.is_set():
            proc.kill()
            proc.wait()
            th.join(timeout=2)
            return False
        time.sleep(0.05)
    th.join(timeout=2)
    if proc.returncode != 0:
        raise RuntimeError(_("Falha ao gravar o som:\n{erro}").format(
            erro=err.decode("utf-8", "replace").strip()[-1500:]))
    return True


def _temp_wav(tag: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"pelicula_{tag}_", suffix=".wav")
    os.close(fd)
    return path


def _mix_to(job, start: int, end: int, stems: bool, temps: list[str]):
    """Mixa o trecho [start, end) num WAV temporário (e os stems, se pedidos). None se não tem som ou cancelou."""
    from . import somcache
    path = _temp_wav("som")
    temps.append(path)
    fn = None
    if stems:
        def fn(kind, idx):
            p = _temp_wav(f"stem_{kind}{idx + 1}")
            temps.append(p)
            return p
    return somcache.mix(job.sequence, path, start, end, job.cancel, job.settings.perf(), stems=fn)


def run(job) -> None:
    """Exporta só o som (chamado por `export.run_job`): marca o trabalho como concluído, cancelado ou com erro."""
    from . import export, loudnorm
    s, info, seq = job.settings, job.info, job.sequence
    perf = s.perf()
    fmt = sound_format(s)
    job.status = "exportando"
    job.started = time.time()
    start = max(0, job.start_frame)
    end = info.frames - 1 if job.end_frame < 0 else min(job.end_frame, info.frames - 1)
    stems = s.sound_only == "stems"
    job.total = 3
    job.done = 0
    if job.cancel.is_set():
        job.status = "cancelado"
        return
    if stems and seq is None:
        job.status = "erro"
        job.error = _("Stems (uma faixa por arquivo) só existem numa montagem do modo Edição.")
        return
    clash = export.partial_clash(job.out_path, s, export.job_inputs(info, seq))
    if clash:
        job.status = "erro"
        job.error = export.partial_clash_message(clash)
        return
    temps: list[str] = []
    partials: list[tuple[str, str]] = []   # (parcial, destino)
    ok = False
    try:
        # 1. o WAV do trecho: a mixagem (modo Edição) ou o próprio arquivo (modo Película)
        if seq is not None:
            job.stage = _("Mixando o som…")
            try:
                res = _mix_to(job, start, end + 1, stems, temps)
            except RuntimeError as exc:
                job.status = "erro"
                job.error = str(exc)[-1500:]
                return
            if job.cancel.is_set():
                job.status = "cancelado"
                return
            if res is None:
                job.status = "erro"
                job.error = _("O trecho não tem som.")
                return
            src, t0, dur = res.path, 0.0, 0.0
            jobs = [(src, job.out_path)] if not stems else [
                (p, stem_path(job.out_path, kind, idx, (seq.track(kind, idx).name if seq.track(kind, idx) else ""),
                              fmt)) for (kind, idx), p in res.stems.items()]
        else:
            if not info.has_audio:
                job.status = "erro"
                job.error = _("O arquivo não tem som.")
                return
            src, t0, dur = info.path, start / info.fps, (end - start + 1) / info.fps
            jobs = [(src, job.out_path)]
        if not stems:
            # O som de película do look (§45) vale para "Só o som" como vale para o som do vídeo: sai o que a prévia toca.
            # Os stems ficam crus (são faixas de trabalho para outro programa).
            film = export._film_sound(job, info, seq, start, end, src if seq is not None else None, perf)
            if film is False:
                return
            if film:
                temps.append(film)
                src, t0, dur = film, 0.0, 0.0
                jobs = [(src, job.out_path)]
        job.done = 1
        # 2. o volume alvo (só na mistura inteira)
        af = ""
        if export.wants_loudness(s) and not stems:
            job.stage = _("Medindo o volume do som…")
            try:
                measured = loudnorm.measure(src, float(s.loudness), float(s.true_peak), t0, dur, job.cancel, perf)
            except RuntimeError as exc:
                job.status = "erro"
                job.error = str(exc)[-1500:]
                return
            if measured is None or job.cancel.is_set():
                job.status = "cancelado"
                return
            if loudnorm.audible(measured):
                af = loudnorm.filter_for(measured, float(s.loudness), float(s.true_peak))
        job.done = 2
        # 3. gravar cada arquivo no parcial; depois todos trocam de nome
        job.stage = _("Gravando o som…")
        for src_i, dest in jobs:
            part = system.partial_path(dest)
            system.remove_file(part)
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            partials.append((part, dest))
            try:
                if not _run(encode_cmd(src_i, part, fmt, t0, dur, af), job.cancel, perf):
                    job.status = "cancelado"
                    return
            except (RuntimeError, OSError) as exc:
                job.status = "erro"
                job.error = str(exc)[-1500:]
                return
        try:
            for part, dest in partials:
                system.replace_file(part, dest)
        except OSError as exc:
            job.status = "erro"
            job.error = _("O som foi gravado, mas não foi possível substituir {destino} (ele pode estar aberto em outro "
                          "programa): {erro}").format(destino=dest, erro=exc)
            return
        partials.clear()
        job.done = 3
        job.stage = ""
        job.status = "concluido"
        ok = True
        from . import sons_cc0  # 1.8: créditos dos sons CC0 do trecho (§47)
        sons_cc0.export_credits(job, start, end + 1)
    finally:
        for part, _dest in partials:
            system.remove_file(part)
        for t in temps:
            system.remove_file(t)
        if not ok and job.status == "exportando":
            job.status = "erro"
