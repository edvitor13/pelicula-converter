"""Modo terminal do PeliculaConverter.

Exemplos:
    pelicula-cli exportar video.mp4 --preset vision3_500t --set grao_forca=1.5 --qualidade mp4
    pelicula-cli projeto meu.plc --criar video.mp4 --preset super8_kodachrome --set scan_on=true
    pelicula-cli exportar meu.plc -o final.mov --qualidade prores_hq --inicio 00:00:05 --fim 00:00:12
    pelicula-cli exportar video.mp4 --plataforma instagram_reels --encaixe desfocado --grao-redes
    pelicula-cli exportar video.mp4 --plataforma discord --tamanho-alvo 50   (Nitro Basic)
    pelicula-cli quadro video.mp4 -o quadro.png --tempo 3.5 --preset double_x
    pelicula-cli lut --preset vision3_250d -o 250d.cube
    pelicula-cli resolve --ofx-instalar    (plugin OpenFX: funciona no DaVinci Resolve gratuito)
    pelicula-cli resolve --instalar        (DCTLs do Resolve Studio e LUTs)
    pelicula-cli modulos --perfil criador --ligar laboratorio   (o que aparece na janela)
    pelicula-cli presets | parametros | qualidades | plataformas | info video.mp4 | ffmpeg --baixar | versao

Projetos .plc com uma edição (modo Edição) exportam a montagem: cortes, cor dos clipes e som mixado.

Cada comando tem um apelido em inglês (export, project, frame, list-presets, params,
qualities, platforms, modules, version). O idioma das mensagens segue o app (ou a variável PELICULA_LANG).

Os módulos (recursos opcionais) só mostram ou escondem ferramentas na janela: o modo terminal
nunca os consulta e exporta tudo do mesmo jeito.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

from . import APP_NAME, __version__, i18n
from .i18n import _

COMMANDS = {
    "exportar": "export", "render": "export", "export": "export",
    "projeto": "project", "project": "project",
    "quadro": "frame", "frame": "frame", "still": "frame",
    "lut": "lut",
    "presets": "presets", "list-presets": "presets",
    "parametros": "params", "params": "params",
    "qualidades": "qualities", "qualities": "qualities",
    "plataformas": "platforms", "platforms": "platforms",
    "info": "info",
    "ffmpeg": "ffmpeg",
    "resolve": "resolve", "davinci": "resolve",
    "modulos": "modules", "modules": "modules",
    "versao": "version", "version": "version", "--version": "version",
}


class CliError(Exception):
    pass


# ------------------------------------------------------------------ utilidades
def _setup_language() -> None:
    code = os.environ.get("PELICULA_LANG", "")
    if code not in i18n.LANGUAGES:
        try:
            from .ui import prefs
            code = str(prefs.settings().value("language", "") or "")
        except Exception:  # noqa: BLE001
            code = ""
    if code not in i18n.LANGUAGES:
        code = i18n.system_language()
    i18n.set_language(code)


_QAPP = None


def _gui_app():
    """QGuiApplication sem janela (fontes para o texto de borda do scan)."""
    global _QAPP
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _QAPP = QGuiApplication([sys.argv[0]])
    return QGuiApplication.instance()


def parse_value(key: str, text: str):
    from . import params
    p = params.PARAMS.get(key)
    if p is None:
        raise CliError(_("Parâmetro desconhecido: {chave}. Veja a lista com \"parametros\".").format(chave=key))
    t = text.strip()
    if p.kind == "bool":
        if t.lower() in ("1", "true", "sim", "yes", "si", "on", "ligado"):
            return True
        if t.lower() in ("0", "false", "nao", "não", "no", "off", "desligado"):
            return False
        raise CliError(_("Valor inválido para {chave}: use true ou false.").format(chave=key))
    if p.kind in ("float", "int"):
        try:
            v = float(t.replace(",", ".").rstrip("%"))
        except ValueError as exc:
            raise CliError(_("Valor inválido para {chave}: {valor}").format(chave=key, valor=t)) from exc
        if t.endswith("%") and p.percent:
            v /= 100.0
        return int(round(v)) if p.kind == "int" else v
    if p.kind == "choice":
        valid = [c[0] for c in p.choices]
        if t not in valid:
            raise CliError(_("Valor inválido para {chave}. Opções: {opcoes}").format(chave=key, opcoes=", ".join(valid)))
        return t
    if p.kind == "color":
        parts = [x for x in re.split(r"[ ,;]+", t.lstrip("#")) if x]
        if len(parts) == 1 and len(parts[0]) == 6:
            h = parts[0]
            return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        if len(parts) == 3:
            vals = [float(x) for x in parts]
            return [x / 255.0 if max(vals) > 1 else x for x in vals]
        raise CliError(_("Cor inválida para {chave}: use #RRGGBB ou \"r,g,b\".").format(chave=key))
    return t


def build_values(base: dict | None, preset: str | None, sets: list[str]) -> tuple[dict, str]:
    from . import params, presets
    pid = ""
    values = dict(base) if base else None
    if preset:
        if preset in presets.BY_ID:
            values = presets.builtin_values(preset)
            pid = preset
        else:
            match = [u for u in presets.list_user() if u["id"] == preset or u["nome"] == preset]
            if not match:
                raise CliError(_("Preset desconhecido: {nome}. Veja a lista com \"presets\".").format(nome=preset))
            values = dict(match[0]["valores"])
            pid = match[0]["id"]
        if base:
            values = presets.with_source(values, base)  # o preset troca o look; o perfil do projeto fica
    if values is None:
        values = presets.builtin_values(presets.DEFAULT_ID)
        pid = presets.DEFAULT_ID
    for item in sets or []:
        if "=" not in item:
            raise CliError(_("Use --set chave=valor (recebido: {item})").format(item=item))
        k, v = item.split("=", 1)
        values[k.strip()] = parse_value(k.strip(), v)
    return params.sanitize(values), pid


def parse_resolution(text: str) -> str:
    """'original', '1080' ou '1080p' → chave da resolução de exportação (o número é o lado menor)."""
    t = text.strip().lower()
    if t == "original":
        return t
    num = t[:-1] if t.endswith("p") else t
    if not num.isdigit() or not 2 <= int(num) <= 16384:
        raise CliError(_("Resolução inválida: {valor}. Use original ou o número de pixels do lado menor "
                         "(2160, 1080, 720…).").format(valor=text))
    return str(int(num))


def auto_input_profile(values: dict, sets: list[str] | None, info) -> str | None:
    """Perfil de entrada pelos metadados do vídeo (HLG/PQ), como o app faz ao abrir um arquivo.

    Só quando o perfil não veio de `--set entrada=…` (veja `media.auto_profile`: perfis log nunca mudam).
    Muda `values` e devolve o perfil novo (None = nada mudou).
    """
    from . import media
    if any(item.split("=", 1)[0].strip() == "entrada" for item in sets or [] if "=" in item):
        return None
    prof = media.auto_profile(values.get("entrada", "rec709"), info)
    if prof:
        values["entrada"] = prof
    return prof


def _report_auto_profile(prof: str | None) -> None:
    if not prof:
        return
    from . import params
    name = dict(params.PARAMS["entrada"].choices).get(prof, prof)
    print(_("Perfil do vídeo pelos metadados do arquivo: {perfil} ({nome}). Para escolher outro, use "
            "--set entrada=…").format(perfil=prof, nome=_(name)), file=sys.stderr)


def parse_time(text: str, fps: float) -> int:
    """'12.5' (s), '00:01:02.5', '#120' ou 'q120' (quadro) → número do quadro."""
    t = text.strip().lower()
    if t.startswith(("#", "q")):
        return int(t[1:])
    if ":" in t:
        secs = 0.0
        for part in t.split(":"):
            secs = secs * 60 + float(part.replace(",", "."))
        return int(round(secs * fps))
    return int(round(float(t.replace(",", ".")) * fps))


def _bar(done: int, total: int, rate: float, eta: float, width: int = 28) -> str:
    frac = done / total if total else 0
    fill = int(frac * width)
    eta_txt = time.strftime("%H:%M:%S", time.gmtime(max(0, eta))) if rate > 0 else "--:--:--"
    return (f"[{'#' * fill}{'.' * (width - fill)}] {frac * 100:5.1f}%  {done}/{total}  "
            + _("{q} quadros/s").format(q=f"{rate:.1f}") + "  " + _("faltam {tempo}").format(tempo=eta_txt))


def look_keys(proj, preset, sets) -> dict:
    """Chaves de animação do look do projeto (`Project.look_keys`). Um --preset troca o look inteiro (sai sem
    animação) e um --set fixa o ajuste dado (a chave dele sai)."""
    if proj is None or preset or not proj.look_keys:
        return {}
    fixed = {item.split("=", 1)[0].strip() for item in sets or [] if "=" in item}
    return {k: v for k, v in proj.look_keys.items() if k not in fixed}


def project_sequence(proj):
    """Sequência do modo Edição de um projeto (None se não tem ou se é só o arquivo inteiro)."""
    from . import sequence, timeline
    if not proj or not proj.sequence:
        return None
    seq = timeline.Sequence.from_json(proj.sequence)
    if not seq.clips:
        return None
    trivial = seq.direct_file()  # um arquivo com transparência passa pela montagem
    if trivial and (not proj.media_path or os.path.abspath(trivial) == os.path.abspath(proj.media_path)):
        return None
    missing = sequence.missing_sources(seq)
    if missing:
        raise CliError(_("Arquivos da edição não encontrados:\n{lista}").format(lista="\n".join(missing[:10])))
    return seq


def _source_and_values(path: str, preset, sets):
    """Entrada pode ser vídeo/imagem ou um projeto .plc. Devolve (arquivo, valores, preset, projeto, sequência)."""
    from . import project
    proj = None
    if path.lower().endswith(project.EXT):
        try:
            proj = project.load(path)
        except project.ProjectError as exc:
            raise CliError(_("Projeto inválido: {erro}").format(erro=exc)) from exc
        values, pid = build_values(proj.values, preset, sets)
        seq = project_sequence(proj)
        if seq is not None:
            from . import sequence
            return sequence.media_info(seq).path, values, pid or proj.preset_id, proj, seq
        if not proj.media_path or not _exists(proj.media_path):
            raise CliError(_("O vídeo do projeto não foi encontrado: {caminho}").format(caminho=proj.media_path))
        return proj.media_path, values, pid or proj.preset_id, proj, alpha_sequence(proj.media_path)
    if not _exists(path):
        raise CliError(_("Arquivo não encontrado: {caminho}").format(caminho=path))
    values, pid = build_values(None, preset, sets)
    return path, values, pid, None, alpha_sequence(path)


def _exists(path: str) -> bool:
    """O arquivo existe? (um padrão de sequência de imagens, plano_%04d.png: algum quadro dele)"""
    from .media import path_exists
    return path_exists(path)


def alpha_sequence(path: str):
    """Arquivo com transparência aberto direto: a montagem só com ele (o alfa sai sobre o fundo da montagem,
    como na janela; lido direto, o alfa se perderia). None para os outros arquivos."""
    from . import media, timeline
    try:
        info = media.probe(path)
    except Exception:  # noqa: BLE001 — quem chamou mostra o erro ao ler o arquivo
        return None
    if not info.has_alpha and not info.is_sequence:  # sequência de imagens: também pela montagem
        return None
    return timeline.Sequence.for_source(timeline.Source.from_info(info))


def _need_ffmpeg() -> None:
    from . import media
    if not media.configure():
        raise CliError(_("ffmpeg não encontrado. Rode \"pelicula-cli ffmpeg --baixar\" ou instale o ffmpeg."))


def _platform_arg(a, info):
    """A plataforma de `--plataforma` (None sem ela). Não combina com `--qualidade` nem com imagem."""
    if not a.plataforma:
        return None
    from . import platforms
    p = platforms.get(a.plataforma)
    if p is None:
        raise CliError(_("Plataforma desconhecida: {nome}. Veja a lista com \"plataformas\".").format(
            nome=a.plataforma))
    if a.qualidade:
        raise CliError(_("Use --plataforma ou --qualidade, não os dois."))
    if info.is_image:
        raise CliError(_("As plataformas são para vídeo; para imagem use --qualidade."))
    return p


def _platform_overrides(a, s) -> None:
    """--quadro, --encaixe, --tamanho-alvo, --volume, --pico e --grao-redes (com ou sem --plataforma)."""
    from . import export
    if a.quadro is not None:
        text = a.quadro.strip().lower()
        if text in ("", "auto", "0"):
            s.frame = ""
        elif export.parse_frame(text) is None:
            raise CliError(_("Quadro inválido: {valor}. Use largura x altura, por exemplo 1080x1920.").format(
                valor=a.quadro))
        else:
            w, h = export.parse_frame(text)
            s.frame = f"{w}x{h}"
    if a.encaixe is not None:
        s.fit = a.encaixe
    if a.tamanho_alvo is not None:
        if a.tamanho_alvo < 0:
            raise CliError(_("Tamanho alvo inválido: {valor} (MB; 0 desliga).").format(valor=a.tamanho_alvo))
        s.target_mb = a.tamanho_alvo
    if a.volume is not None:
        if not -70 <= a.volume <= 0:
            raise CliError(_("Volume alvo inválido: {valor}. Use LUFS negativos (ex.: -14) ou 0 para desligar.")
                           .format(valor=a.volume))
        s.loudness = a.volume
    if a.pico is not None:
        if not -9 <= a.pico <= 0:
            raise CliError(_("Pico real inválido: {valor}. Use de -9 a 0 dBTP.").format(valor=a.pico))
        s.true_peak = a.pico
    if a.grao_redes:
        s.net_grain = True


def _export_notes(plat, s, info, duration: float) -> list[str]:
    """Avisos da exportação (os mesmos da janela): limites da plataforma, duas passadas, som recodificado."""
    from . import export, platforms
    out = []
    if plat is not None:
        out.append(_("Plataforma: {nome} ({limites})").format(nome=_(plat.name), limites=platforms.limits_text(plat)))
        out += [_("Aviso: {texto}").format(texto=t) for t in platforms.warnings(plat, duration)]
    if export.uses_target(s):
        out.append(_("Tamanho alvo de {mb} MB: duas passadas, leva cerca do dobro do tempo.").format(
            mb=export.fmt_mb(float(s.target_mb))))
    if export.audio_reencoded_for_volume(s, info):
        out.append(_("O som vai ser recodificado: copiar o original não deixa acertar o volume nem o "
                     "tamanho do arquivo."))
    return out


# ------------------------------------------------------------------ comandos
def cmd_export(a) -> int:
    from . import export, media, platforms
    from .engine import Engine
    resolution = parse_resolution(a.resolucao) if a.resolucao is not None else None
    _need_ffmpeg()
    src, values, pid, proj, seq = _source_and_values(a.entrada, a.preset, a.set)
    if seq is not None:
        from . import sequence
        info = sequence.media_info(seq)
    else:
        info = media.probe(src)
        if proj is None:  # arquivo aberto agora (um projeto salvo guarda o perfil escolhido)
            _report_auto_profile(auto_input_profile(values, a.set, info))
    start = parse_time(a.inicio, info.fps) if a.inicio else (proj.in_point or 0 if proj and a.trecho else 0)
    end = parse_time(a.fim, info.fps) if a.fim else (proj.out_point if proj and a.trecho and proj.out_point else -1)
    duration = ((info.frames - 1 if end < 0 else min(end, info.frames - 1)) - start + 1) / info.fps
    plat = _platform_arg(a, info)
    if plat is not None:
        qkey = plat.id
        s = platforms.settings_for(plat.id, info, duration=duration, fit_mode=a.encaixe)
    else:
        presets_q = {k: s for k, _l, s in export.quality_presets(info)}
        qkey = a.qualidade or (proj.export_quality if proj and proj.export_quality in presets_q else None)
        qkey = qkey or ("img_png" if info.is_image else "mp4")
        if qkey not in presets_q:
            raise CliError(_("Qualidade desconhecida: {nome}. Veja a lista com \"qualidades\".").format(nome=qkey))
        s = export.ExportSettings.from_dict(presets_q[qkey].to_dict())
    overrides = {"codec": a.codec, "container": a.recipiente, "pix": a.pix, "preset": a.velocidade,
                 "profile": a.perfil, "resolution": resolution, "fps": a.fps, "audio": a.audio,
                 "priority": a.prioridade, "hwaccel": a.hwaccel}
    for k, v in overrides.items():
        if v is not None:
            setattr(s, k, v)
    if a.crf is not None:
        s.quality = a.crf
    if a.taxa is not None:
        s.bitrate = a.taxa
    if a.threads is not None:
        s.threads = a.threads
    if a.buffer is not None:
        s.buffer = a.buffer
    _platform_overrides(a, s)
    if s.codec not in export.CODECS or not export.available(s.codec):
        raise CliError(_("Codec indisponível neste computador: {codec}").format(codec=s.codec))
    if s.container not in export.CODECS[s.codec]["exts"]:
        s.container = export.CODECS[s.codec]["exts"][0]
    out = a.saida or str(Path(src).with_name(media.sequence_stem(src) + "_pelicula." + s.container))
    out = str(Path(out).with_suffix("." + s.container))
    if os.path.abspath(out) == os.path.abspath(src):
        raise CliError(_("A saída não pode ser o próprio arquivo de entrada."))
    clash = export.partial_clash(out, s, export.job_inputs(info, seq))
    if clash:
        raise CliError(export.partial_clash_message(clash))
    if export.output_exists(out, s) and not a.sobrescrever:
        if export.is_sequence(s):
            raise CliError(_("A sequência já existe: {caminho} (use -y para substituir)").format(
                caminho=export.output_target(out, s)))
        raise CliError(_("O arquivo já existe: {caminho} (use -y para substituir)").format(caminho=out))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    if values.get("scan_on"):
        _gui_app()
    job = export.ExportJob(info=info, values=values, settings=s, out_path=out, start_frame=start, end_frame=end,
                           name=Path(out).name, sequence=seq, look_keys=look_keys(proj, a.preset, a.set))
    if not a.json:
        w, h = export.output_size(info, s)
        print(_("Exportando {entrada} → {saida}").format(entrada=Path(src).name, saida=out), file=sys.stderr)
        print(_("Look: {preset} • qualidade: {qualidade} • {codec} {pix} • {w}×{h}").format(
            preset=pid or "-", qualidade=qkey, codec=s.codec, pix=s.pix, w=w, h=h), file=sys.stderr)
        for line in _export_notes(plat, s, info, duration):
            print(line, file=sys.stderr)

    def on_sigint(*_args):
        job.cancel.set()

    old = signal.signal(signal.SIGINT, on_sigint)
    done = threading.Event()

    def work():
        # O contexto OpenGL pertence à thread que o cria: o motor nasce e morre aqui.
        engine = None
        try:
            engine = Engine()
            export.run_job(job, engine)
        except Exception as exc:  # noqa: BLE001
            job.status = "erro"
            job.error = str(exc)
        finally:
            if engine is not None:
                engine.release()
            done.set()

    th = threading.Thread(target=work, daemon=True)
    th.start()
    last = 0.0
    while not done.wait(0.25):
        if a.json:
            if time.time() - last > 1:
                last = time.time()
                print(json.dumps({"feito": job.done, "total": job.total, "qps": round(job.fps_rate, 2),
                                  "restante_s": round(job.eta, 1), "etapa": job.stage,
                                  "progresso": round(job.progress, 4)}), flush=True)
        elif not a.silencioso and job.total:
            stage = f"{job.stage}  " if job.stage else ""
            sys.stderr.write("\r" + stage + _bar(job.done, job.total, job.fps_rate, job.eta))
            sys.stderr.flush()
    signal.signal(signal.SIGINT, old)
    th.join(timeout=5)
    if not a.json and not a.silencioso:
        sys.stderr.write("\r" + _bar(job.done, job.total or 1, job.fps_rate, 0) + "\n")
    elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - job.started)) if job.started else "-"
    if a.json:
        print(json.dumps({"status": job.status, "saida": out, "quadros": job.done, "erro": job.error}))
    if job.status == "concluido":
        if not a.json:
            print(_("Pronto: {caminho} ({quadros} quadros em {tempo})").format(
                caminho=export.output_target(out, s), quadros=job.done, tempo=elapsed))
        return 0
    if job.status == "cancelado":
        print(_("Exportação cancelada."), file=sys.stderr)
        return 130
    raise CliError(_("A exportação falhou:\n{erro}").format(erro=job.error))


def cmd_project(a) -> int:
    from . import project
    path = a.arquivo if a.arquivo.lower().endswith(project.EXT) else a.arquivo + project.EXT
    if a.criar:
        if not os.path.exists(a.criar):
            raise CliError(_("Arquivo não encontrado: {caminho}").format(caminho=a.criar))
        values, pid = build_values(None, a.preset, a.set)
        p = project.Project(media_path=str(Path(a.criar).resolve()), values=values, preset_id=pid)
    else:
        if not os.path.exists(path):
            raise CliError(_("Projeto não encontrado: {caminho} (use --criar VIDEO para criar)").format(caminho=path))
        p = project.load(path)
        if a.preset or a.set:
            p.values, pid = build_values(p.values, a.preset, a.set)
            if a.preset:
                p.preset_id = pid
    if a.inicio is not None or a.fim is not None:
        from . import media
        _need_ffmpeg()
        fps = media.probe(p.media_path).fps
        if a.inicio is not None:
            p.in_point = parse_time(a.inicio, fps) if a.inicio else None
        if a.fim is not None:
            p.out_point = parse_time(a.fim, fps) if a.fim else None
    changed = bool(a.criar or a.preset or a.set or a.inicio is not None or a.fim is not None)
    if changed:
        project.save(p, path)
        print(_("Projeto salvo: {caminho}").format(caminho=str(Path(path).resolve())))
    if a.mostrar or not changed:
        print(json.dumps(p.to_json() | {"miniatura_jpeg": "…"}, ensure_ascii=False, indent=2))
    return 0


def cmd_frame(a) -> int:
    from . import export, media
    from .engine import Engine
    from .frame import Recipe
    _need_ffmpeg()
    src, values, _pid, proj, seq = _source_and_values(a.entrada, a.preset, a.set)
    if seq is not None:
        from . import sequence
        info = sequence.media_info(seq)
        legal = sequence.legal_range(seq)
    else:
        info = media.probe(src)
        legal = media.legal_range(info)
        if proj is None:  # arquivo aberto agora (um projeto salvo guarda o perfil escolhido)
            _report_auto_profile(auto_input_profile(values, a.set, info))
    frame = parse_time(a.tempo, info.fps) if a.tempo else (proj.frame if proj else 0)
    frame = max(0, min(frame, info.frames - 1))
    path = a.saida or str(Path(src).with_name(f"{Path(src).stem}_quadro{frame}.png"))
    ext = Path(path).suffix.lower()
    if ext not in export.STILL_ARGS:
        raise CliError(_("Formato de imagem não suportado: {ext} (use .png, .tif ou .jpg)").format(ext=ext))
    if values.get("scan_on"):
        _gui_app()
    w, h = info.width, info.height
    # A receita única do quadro (`frame.Recipe`): a mesma da exportação no tamanho original.
    recipe = Recipe.for_source(values, info.fps, 16, legal=legal, seq=seq, size=(w, h),
                               keys=look_keys(proj, a.preset, a.set))
    engine = Engine()
    try:
        if seq is not None:
            img = sequence.grab(seq, frame, w, h, 16, hq=True)
        else:
            img = media.grab_frame(info, frame, w, h, 16, hq=True)
        out = recipe.render(engine, img, frame)
    finally:
        engine.release()
    try:
        export.save_still(out, path)  # grava num parcial e só troca o arquivo no fim
    except (RuntimeError, OSError) as exc:
        raise CliError(str(exc)) from exc
    print(_("Quadro {n} salvo em {caminho}").format(n=frame, caminho=path))
    return 0


def cmd_lut(a) -> int:
    from . import luts
    from .engine import Engine
    if a.projeto:
        from . import project
        p = project.load(a.projeto)
        values, pid = build_values(p.values, a.preset, a.set)
    else:
        values, pid = build_values(None, a.preset, a.set)
    if values.get("scan_on"):
        _gui_app()
    engine = Engine()
    data = engine.bake_lut(values, a.tamanho)
    engine.release()
    out = a.saida or f"{pid or 'look'}.cube"
    luts.save_cube(out, data, a.tamanho, pid or "PeliculaConverter")
    print(_("LUT salvo em {caminho} ({n} pontos, entrada {entrada})").format(caminho=out, n=a.tamanho,
                                                                          entrada=values["entrada"]))
    return 0


def cmd_presets(a) -> int:
    from . import presets
    items = [{"id": p["id"], "nome": _(p["nome"]), "grupo": _(p["grupo"]), "desc": _(p["desc"])}
             for p in presets.BUILTIN]
    items += [{"id": u["id"], "nome": u["nome"], "grupo": _("Meus presets"), "desc": u.get("desc", "")}
              for u in presets.list_user()]
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    group = None
    for it in items:
        if it["grupo"] != group:
            group = it["grupo"]
            print(f"\n{group.upper()}")
        print(f"  {it['id']:<22} {it['nome']}")
    return 0


def cmd_params(a) -> int:
    from . import params
    rows = []
    for sec in params.SECTIONS:
        if a.secao and a.secao not in (sec.key, _(sec.title)):
            continue
        for p in sec.params:
            if p.kind in ("float", "int"):
                rng = f"{p.min:g} … {p.max:g}"
            elif p.kind == "choice":
                rng = " | ".join(c[0] for c in p.choices)
            elif p.kind == "bool":
                rng = "true | false"
            elif p.kind == "color":
                rng = "#RRGGBB"
            else:
                rng = _("caminho")
            default = p.default if p.kind != "color" else "#%02X%02X%02X" % tuple(int(c * 255) for c in p.default)
            rows.append({"secao": sec.key, "chave": p.key, "nome": _(p.label), "tipo": p.kind, "faixa": rng,
                         "padrao": default})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    sec = None
    for r in rows:
        if r["secao"] != sec:
            sec = r["secao"]
            title = next(_(s.title) for s in params.SECTIONS if s.key == sec)
            print(f"\n{title.upper()} ({sec})")
        print(f"  {r['chave']:<22} {r['nome']:<34} {r['faixa']}  [{r['padrao']}]")
    return 0


def cmd_qualities(a) -> int:
    from . import export, media
    info = None
    if a.entrada:
        _need_ffmpeg()
        info = media.probe(a.entrada)
    else:
        media.configure()
    for k, label, s in export.quality_presets(info):
        print(f"  {k:<12} {_(label)}  ({s.codec}, .{s.container}, {s.pix})")
    return 0


def cmd_platforms(a) -> int:
    from . import platforms
    rows = []
    for gid, glabel, items in platforms.grouped():
        for p in items:
            rows.append({"id": p.id, "nome": _(p.name), "grupo": _(glabel), "grupo_id": gid, "quadro": p.frame,
                         "resolucao": "" if p.frame else p.resolution, "fps_max": p.max_fps, "codec": p.codec,
                         "recipiente": p.container, "pix": p.pix, "crf": p.quality, "teto_mbps": p.maxrate,
                         "audio": p.audio, "duracao_min_s": p.min_s, "duracao_max_s": p.max_s,
                         "tamanho_max_mb": p.max_mb, "tamanho_alvo_mb": p.target_mb, "volume_lufs": p.loudness,
                         "pico_dbtp": p.true_peak if p.loudness else 0.0, "oficial": p.official,
                         "limites": platforms.limits_text(p), "nota": _(p.note) if p.note else ""})
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    group = None
    for r in rows:
        if r["grupo"] != group:
            group = r["grupo"]
            print(f"\n{group.upper()}")
        print(f"  {r['id']:<20} {r['nome']}")
        print(f"  {'':<20} {r['limites']}")
    return 0


def cmd_info(a) -> int:
    from . import media
    _need_ffmpeg()
    info = media.probe(a.entrada)
    data = {"arquivo": info.path, "largura": info.width, "altura": info.height, "fps": round(info.fps, 3),
            "quadros": info.frames, "duracao_s": round(info.duration, 3), "codec": info.codec,
            "pix_fmt": info.pix_fmt, "bits": info.bit_depth, "audio": info.audio_codec or None,
            "imagem": info.is_image, "faixa": "legal" if media.legal_range(info) else "cheia",
            "transferencia": info.color_transfer or None, "perfil_hdr": media.detect_profile(info)}
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(info.summary())
        for k, v in data.items():
            print(f"  {k:<10} {v}")
    return 0


def _resolve_module():
    try:
        from . import resolve
    except ImportError as exc:
        raise CliError(_("O plugin do DaVinci Resolve não está disponível nesta versão.")) from exc
    return resolve


def _ofx_status(resolve) -> None:
    if not hasattr(resolve, "ofx_bundle_version"):
        return
    shipped = resolve.ofx_bundle_version()
    installed = resolve.ofx_installed_version()
    print(_("Plugin OpenFX (funciona no DaVinci Resolve gratuito):"))
    print("  " + (_("neste app: versão {versao}").format(versao=shipped) if shipped
                  else _("não vem neste app (compile com plugins/ofx/build_windows.bat ou build_linux.sh)")))
    print("  " + (_("instalado em {pasta}: versão {versao}").format(pasta=resolve.ofx_install_dir(), versao=installed)
                  if installed else _("não instalado ({pasta})").format(pasta=resolve.ofx_install_dir())))


def cmd_resolve(a) -> int:
    """Plugin do PeliculaConverter para o DaVinci Resolve (OpenFX, DCTLs e LUTs)."""
    resolve = _resolve_module()
    ofx_any = a.ofx_instalar or a.ofx_pasta or a.ofx_fonte
    if a.ofx_fonte:
        files = resolve.ofx_generate(a.ofx_fonte)
        print(_("{n} arquivos do código do plugin OpenFX gravados em {pasta}").format(n=len(files), pasta=a.ofx_fonte))
    if a.ofx_pasta:
        try:
            dest = resolve.ofx_save_bundle(a.ofx_pasta)
        except (OSError, RuntimeError) as exc:
            raise CliError(str(exc)) from exc
        print(_("Plugin OpenFX copiado para {pasta}").format(pasta=dest))
    if a.ofx_instalar:
        try:
            dest = resolve.ofx_install()
        except (OSError, RuntimeError) as exc:
            raise CliError(_("Não foi possível instalar o plugin: {erro}").format(erro=exc)) from exc
        print(_("Plugin OpenFX instalado em {pasta}. Reabra o DaVinci Resolve e use Color > OpenFX > "
                "PeliculaConverter.").format(pasta=dest))
    if ofx_any and not (a.listar or a.instalar or a.pasta):
        return 0
    if a.listar or not (a.instalar or a.pasta):
        _ofx_status(resolve)
        dirs = [d for d in resolve.lut_dirs() if d.is_dir()]
        if dirs:
            print(_("Pastas de LUT do DaVinci Resolve encontradas:"))
            version = getattr(resolve, "installed_version", lambda _d=None: None)
            for d in dirs:
                ver = version(d)
                extra = "  " + _("(plugin instalado: versão {versao})").format(versao=ver) if ver else ""
                print(f"  {d}{extra}")
        else:
            print(_("Nenhuma pasta de LUT do DaVinci Resolve foi encontrada neste computador."))
        if not (a.instalar or a.pasta):
            return 0
    if a.pasta:
        files = resolve.build_package(a.pasta)
        print(_("{n} arquivos do plugin gravados em {pasta}").format(n=len(files), pasta=a.pasta))
    if a.instalar:
        try:
            dest = resolve.install(a.destino)
        except (OSError, RuntimeError) as exc:
            raise CliError(_("Não foi possível instalar o plugin: {erro}").format(erro=exc)) from exc
        print(_("Plugin instalado em {pasta}. Abra o DaVinci Resolve (ou atualize a lista de LUTs).").format(
            pasta=dest))
    return 0


def cmd_modules(a) -> int:
    """Lista os módulos (recursos opcionais da janela) e liga, desliga ou aplica um perfil."""
    from . import modules
    from .ui import prefs
    settings = prefs.settings()
    for module_id in (a.ligar or []) + (a.desligar or []):
        if not modules.exists(module_id):
            raise CliError(_("Módulo desconhecido: {id}. Veja a lista com \"modulos\".").format(id=module_id))
    changed = bool(a.perfil or a.ligar or a.desligar)
    if a.perfil:
        modules.apply_profile(settings, a.perfil)
    for module_id in a.ligar or []:
        modules.set_enabled(settings, module_id, True)
    for module_id in a.desligar or []:
        modules.set_enabled(settings, module_id, False)
    if changed:
        settings.sync()
    profile = modules.current_profile(settings)
    profiles = {pid: name for pid, name, _desc, _ids in modules.PROFILES}
    rows = [{"id": m.id, "nome": _(m.name), "descricao": _(m.description), "grupo": m.group, "estado": m.status,
             "ligado": modules.is_enabled(settings, m.id)} for m in modules.MODULES]
    if a.json:
        print(json.dumps({"perfil": profile, "modulos": rows}, ensure_ascii=False, indent=2))
        return 0
    if changed:
        print(_("Módulos atualizados. A janela aplica a mudança ao abrir."))
    print(_("Perfil: {perfil}").format(perfil=_(profiles[profile]) if profile else _("Personalizado")))
    for gid, gname in modules.GROUPS:
        items = [r for r in rows if r["grupo"] == gid]
        if not items:
            continue
        print(f"\n{_(gname).upper()}")
        for r in items:
            status = _(modules.STATUS_LABELS[r["estado"]])
            state = _("ligado") if r["ligado"] else _("desligado")
            print(f"  {r['id']:<14} {r['nome']:<30} {status:<13} {state}")
    print("\n" + _("Desligar um módulo só esconde a ferramenta na janela; a exportação e o modo terminal não mudam."))
    return 0


def cmd_ffmpeg(a) -> int:
    from . import deps, media
    ok = media.configure()
    if ok:
        inf = deps.inspect(media.ffmpeg())
        print(_("ffmpeg: {caminho} ({versao})").format(caminho=media.ffmpeg(), versao=inf.label if inf else "?"))
        if inf and inf.outdated:
            print(_("Esta versão é antiga; rode com --baixar para atualizar."))
    else:
        print(_("ffmpeg não encontrado."))
    if a.baixar:
        def prog(stage, d, t):
            if t:
                sys.stderr.write(f"\r{stage} {d / 1e6:.0f}/{t / 1e6:.0f} MB")
            else:
                sys.stderr.write(f"\r{stage}" + " " * 20)
            sys.stderr.flush()
        path = deps.download_ffmpeg(prog)
        sys.stderr.write("\n")
        media.configure()
        print(_("ffmpeg instalado em {caminho}").format(caminho=path))
    return 0 if (ok or a.baixar) else 1


# ------------------------------------------------------------------ argumentos
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pelicula-cli", description=_("{app} {versao} — modo terminal: aplica looks de "
                                 "película, edita projetos .plc e exporta vídeos sem abrir a janela.")
                                 .format(app=APP_NAME, versao=__version__))
    sub = ap.add_subparsers(dest="cmd", metavar=_("comando"))

    def look_args(p):
        p.add_argument("--preset", help=_("id ou nome do preset (veja \"presets\")"))
        p.add_argument("--set", action="append", metavar=_("CHAVE=VALOR"),
                       help=_("muda um parâmetro (pode repetir; veja \"parametros\")"))

    p = sub.add_parser("exportar", aliases=["export", "render"], help=_("exporta um vídeo, imagem ou projeto .plc"))
    p.add_argument("entrada", help=_("vídeo, imagem ou projeto .plc"))
    p.add_argument("-o", "--saida", help=_("arquivo de saída (padrão: ao lado da entrada)"))
    look_args(p)
    p.add_argument("--qualidade", help=_("qualidade pronta (veja \"qualidades\"; padrão: mp4)"))
    p.add_argument("--plataforma", metavar="ID",
                   help=_("opções prontas para uma plataforma (veja \"plataformas\"); não combina com --qualidade"))
    p.add_argument("--quadro", metavar=_("LxA"),
                   help=_("quadro fixo, ex.: 1080x1920 (auto = segue --resolucao)"))
    p.add_argument("--encaixe", choices=["cortar", "bordas", "desfocado"],
                   help=_("vídeo de outra proporção no quadro fixo: cortar, bordas pretas ou fundo desfocado"))
    p.add_argument("--tamanho-alvo", type=float, metavar="MB",
                   help=_("tamanho máximo do arquivo em MB, em duas passadas (0 desliga)"))
    p.add_argument("--volume", type=float, metavar="LUFS", help=_("volume alvo do som, ex.: -14 (0 desliga)"))
    p.add_argument("--pico", type=float, metavar="DBTP", help=_("pico real máximo com volume alvo (padrão: -1)"))
    p.add_argument("--grao-redes", action="store_true",
                   help=_("grão com tamanho mínimo no quadro de saída, para sobreviver à recompressão das redes"))
    p.add_argument("--codec")
    p.add_argument("--recipiente", help=_("extensão do arquivo (mp4, mov, mkv…)"))
    p.add_argument("--pix", help=_("formato de cor (yuv420p, yuv422p10le…)"))
    p.add_argument("--crf", type=float, help=_("qualidade constante do codec (menor = melhor)"))
    p.add_argument("--taxa", type=float, help=_("taxa de bits em Mb/s (em vez da qualidade constante)"))
    p.add_argument("--velocidade", help=_("preset de velocidade do codec (slow, p6…)"))
    p.add_argument("--perfil", help=_("perfil do ProRes/DNxHR"))
    p.add_argument("--resolucao", help=_("original ou o lado menor em pixels: 2160, 1080, 720… (vertical em 1080 "
                                         "sai 1080×1920)"))
    p.add_argument("--fps", help=_("original, 24, 24000/1001, 30…"))
    p.add_argument("--audio", help=_("copy, aac320, aac192, mp3, opus, pcm24, none"))
    p.add_argument("--inicio", help=_("início: segundos, 00:01:02.5 ou #quadro"))
    p.add_argument("--fim", help=_("fim: segundos, 00:01:02.5 ou #quadro"))
    p.add_argument("--trecho", action="store_true", help=_("usa a entrada e a saída marcadas no projeto"))
    p.add_argument("--threads", type=int, help=_("núcleos do processador (0 = todos)"))
    p.add_argument("--prioridade", choices=["baixa", "normal", "alta"])
    p.add_argument("--hwaccel", help=_("decodificação por hardware (none, auto, cuda, d3d11va, qsv)"))
    p.add_argument("--buffer", type=int, help=_("quadros na memória entre as etapas"))
    p.add_argument("-y", "--sobrescrever", action="store_true", help=_("substitui a saída se já existir"))
    p.add_argument("--json", action="store_true", help=_("progresso em JSON (uma linha por segundo)"))
    p.add_argument("-q", "--silencioso", action="store_true", help=_("sem barra de progresso"))
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("projeto", aliases=["project"], help=_("cria ou edita um projeto .plc"))
    p.add_argument("arquivo", help=_("projeto .plc"))
    p.add_argument("--criar", metavar=_("VIDEO"), help=_("cria o projeto a partir deste vídeo ou imagem"))
    look_args(p)
    p.add_argument("--inicio", help=_("marca a entrada (vazio para limpar)"))
    p.add_argument("--fim", help=_("marca a saída (vazio para limpar)"))
    p.add_argument("--mostrar", action="store_true", help=_("mostra o conteúdo do projeto"))
    p.set_defaults(func=cmd_project)

    p = sub.add_parser("quadro", aliases=["frame", "still"], help=_("salva um quadro com o look em 16 bits"))
    p.add_argument("entrada", help=_("vídeo, imagem ou projeto .plc"))
    p.add_argument("-o", "--saida", help=_("arquivo .png, .tif ou .jpg"))
    p.add_argument("--tempo", help=_("segundos, 00:01:02.5 ou #quadro"))
    look_args(p)
    p.set_defaults(func=cmd_frame)

    p = sub.add_parser("lut", help=_("grava a cor de um look num LUT .cube"))
    p.add_argument("-o", "--saida", help=_("arquivo .cube"))
    p.add_argument("--projeto", help=_("usa os ajustes de um projeto .plc"))
    p.add_argument("--tamanho", type=int, default=33, choices=[17, 33, 65], help=_("pontos por eixo"))
    look_args(p)
    p.set_defaults(func=cmd_lut)

    p = sub.add_parser("presets", aliases=["list-presets"], help=_("lista os presets"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_presets)

    p = sub.add_parser("parametros", aliases=["params"], help=_("lista os parâmetros ajustáveis"))
    p.add_argument("--secao", help=_("só uma seção (ex.: grao, halacao, scan)"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_params)

    p = sub.add_parser("qualidades", aliases=["qualities"], help=_("lista as qualidades de exportação"))
    p.add_argument("entrada", nargs="?", help=_("vídeo ou imagem (mostra as opções para ele)"))
    p.set_defaults(func=cmd_qualities)

    p = sub.add_parser("plataformas", aliases=["platforms"],
                       help=_("lista as plataformas de exportação (YouTube, Instagram, WhatsApp…)"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_platforms)

    p = sub.add_parser("info", help=_("mostra as informações de um arquivo"))
    p.add_argument("entrada")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("ffmpeg", help=_("mostra, baixa ou atualiza o ffmpeg"))
    p.add_argument("--baixar", action="store_true", help=_("baixa a versão oficial e confere o SHA-256"))
    p.set_defaults(func=cmd_ffmpeg)

    p = sub.add_parser("resolve", aliases=["davinci"],
                       help=_("plugin para o DaVinci Resolve: instala ou grava os DCTLs e LUTs"))
    p.add_argument("--instalar", action="store_true", help=_("instala na pasta de LUTs do DaVinci Resolve"))
    p.add_argument("--destino", help=_("pasta de LUTs do Resolve (padrão: a encontrada automaticamente)"))
    p.add_argument("--pasta", help=_("grava o pacote do plugin nesta pasta (para instalar em outro computador)"))
    p.add_argument("--listar", action="store_true", help=_("mostra as pastas de LUT do Resolve encontradas"))
    p.add_argument("--ofx-instalar", action="store_true",
                   help=_("instala o plugin OpenFX (funciona no Resolve gratuito; pede administrador)"))
    p.add_argument("--ofx-pasta", help=_("copia o plugin OpenFX (.ofx.bundle) para esta pasta"))
    p.add_argument("--ofx-fonte", help=_("gera o código C++ do plugin OpenFX nesta pasta (desenvolvimento)"))
    p.set_defaults(func=cmd_resolve)

    from . import modules
    p = sub.add_parser("modulos", aliases=["modules"],
                       help=_("lista, liga e desliga os recursos opcionais da janela (módulos)"))
    p.add_argument("--ligar", action="append", metavar="ID", help=_("liga um módulo (pode repetir)"))
    p.add_argument("--desligar", action="append", metavar="ID", help=_("desliga um módulo (pode repetir)"))
    p.add_argument("--perfil", choices=[pid for pid, *_rest in modules.PROFILES],
                   help=_("aplica um perfil antes de --ligar/--desligar"))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_modules)

    p = sub.add_parser("versao", aliases=["version"], help=_("mostra a versão"))
    p.set_defaults(func=lambda a: (print(f"{APP_NAME} {__version__}"), 0)[1])
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--version":
        argv[0] = "versao"
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    _setup_language()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return int(args.func(args) or 0)
    except CliError as exc:
        print(_("Erro: {mensagem}").format(mensagem=exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
