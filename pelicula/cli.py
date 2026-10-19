"""Modo terminal do PeliculaConverter.

Exemplos:
    pelicula-cli exportar video.mp4 --preset vision3_500t --set grao_forca=1.5 --qualidade mp4
    pelicula-cli projeto meu.plc --criar video.mp4 --preset super8_kodachrome --set scan_on=true
    pelicula-cli exportar meu.plc -o final.mov --qualidade prores_hq --inicio 00:00:05 --fim 00:00:12
    pelicula-cli quadro video.mp4 -o quadro.png --tempo 3.5 --preset double_x
    pelicula-cli lut --preset vision3_250d -o 250d.cube
    pelicula-cli resolve --ofx-instalar    (plugin OpenFX: funciona no DaVinci Resolve gratuito)
    pelicula-cli resolve --instalar        (DCTLs do Resolve Studio e LUTs)
    pelicula-cli presets | parametros | qualidades | info video.mp4 | ffmpeg --baixar | versao

Projetos .plc com uma edição (modo Edição) exportam a montagem: cortes, cor dos clipes e som mixado.

Cada comando tem um apelido em inglês (export, project, frame, list-presets, params,
qualities, version). O idioma das mensagens segue o app (ou a variável PELICULA_LANG).
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
    "info": "info",
    "ffmpeg": "ffmpeg",
    "resolve": "resolve", "davinci": "resolve",
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
    if values is None:
        values = presets.builtin_values(presets.DEFAULT_ID)
        pid = presets.DEFAULT_ID
    for item in sets or []:
        if "=" not in item:
            raise CliError(_("Use --set chave=valor (recebido: {item})").format(item=item))
        k, v = item.split("=", 1)
        values[k.strip()] = parse_value(k.strip(), v)
    return params.sanitize(values), pid


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


def project_sequence(proj):
    """Sequência do modo Edição de um projeto (None se não tem ou se é só o arquivo inteiro)."""
    from . import sequence, timeline
    if not proj or not proj.sequence:
        return None
    seq = timeline.Sequence.from_json(proj.sequence)
    if not seq.clips:
        return None
    trivial = seq.is_trivial()
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
        if not proj.media_path or not os.path.exists(proj.media_path):
            raise CliError(_("O vídeo do projeto não foi encontrado: {caminho}").format(caminho=proj.media_path))
        return proj.media_path, values, pid or proj.preset_id, proj, None
    if not os.path.exists(path):
        raise CliError(_("Arquivo não encontrado: {caminho}").format(caminho=path))
    values, pid = build_values(None, preset, sets)
    return path, values, pid, None, None


def _need_ffmpeg() -> None:
    from . import media
    if not media.configure():
        raise CliError(_("ffmpeg não encontrado. Rode \"pelicula-cli ffmpeg --baixar\" ou instale o ffmpeg."))


# ------------------------------------------------------------------ comandos
def cmd_export(a) -> int:
    from . import export, media
    from .engine import Engine
    _need_ffmpeg()
    src, values, pid, proj, seq = _source_and_values(a.entrada, a.preset, a.set)
    if seq is not None:
        from . import sequence
        info = sequence.media_info(seq)
    else:
        info = media.probe(src)
    presets_q = {k: s for k, _l, s in export.quality_presets(info)}
    qkey = a.qualidade or (proj.export_quality if proj and proj.export_quality in presets_q else None)
    qkey = qkey or ("img_png" if info.is_image else "mp4")
    if qkey not in presets_q:
        raise CliError(_("Qualidade desconhecida: {nome}. Veja a lista com \"qualidades\".").format(nome=qkey))
    s = export.ExportSettings.from_dict(presets_q[qkey].to_dict())
    overrides = {"codec": a.codec, "container": a.recipiente, "pix": a.pix, "preset": a.velocidade,
                 "profile": a.perfil, "resolution": a.resolucao, "fps": a.fps, "audio": a.audio,
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
    if s.codec not in export.CODECS or not export.available(s.codec):
        raise CliError(_("Codec indisponível neste computador: {codec}").format(codec=s.codec))
    if s.container not in export.CODECS[s.codec]["exts"]:
        s.container = export.CODECS[s.codec]["exts"][0]
    out = a.saida or str(Path(src).with_name(Path(src).stem + "_pelicula." + s.container))
    out = str(Path(out).with_suffix("." + s.container))
    if os.path.abspath(out) == os.path.abspath(src):
        raise CliError(_("A saída não pode ser o próprio arquivo de entrada."))
    if os.path.exists(out) and not a.sobrescrever:
        raise CliError(_("O arquivo já existe: {caminho} (use -y para substituir)").format(caminho=out))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    start = parse_time(a.inicio, info.fps) if a.inicio else (proj.in_point or 0 if proj and a.trecho else 0)
    end = parse_time(a.fim, info.fps) if a.fim else (proj.out_point if proj and a.trecho and proj.out_point else -1)
    if values.get("scan_on"):
        _gui_app()
    job = export.ExportJob(info=info, values=values, settings=s, out_path=out, start_frame=start, end_frame=end,
                           name=Path(out).name, sequence=seq)
    if not a.json:
        print(_("Exportando {entrada} → {saida}").format(entrada=Path(src).name, saida=out), file=sys.stderr)
        print(_("Look: {preset} • qualidade: {qualidade} • {codec} {pix}").format(
            preset=pid or "-", qualidade=qkey, codec=s.codec, pix=s.pix), file=sys.stderr)

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
                                  "restante_s": round(job.eta, 1)}), flush=True)
        elif not a.silencioso and job.total:
            sys.stderr.write("\r" + _bar(job.done, job.total, job.fps_rate, job.eta))
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
            print(_("Pronto: {caminho} ({quadros} quadros em {tempo})").format(caminho=out, quadros=job.done,
                                                                             tempo=elapsed))
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
    import subprocess
    from . import look, media
    from .engine import Engine, lut_info
    _need_ffmpeg()
    src, values, _pid, proj, seq = _source_and_values(a.entrada, a.preset, a.set)
    if seq is not None:
        from . import sequence
        info = sequence.media_info(seq)
    else:
        info = media.probe(src)
    frame = parse_time(a.tempo, info.fps) if a.tempo else (proj.frame if proj else 0)
    frame = max(0, min(frame, info.frames - 1))
    if values.get("scan_on"):
        _gui_app()
    w, h = info.width, info.height
    engine = Engine()
    if seq is not None:
        img = engine.compose(sequence.grab(seq, frame, w, h, 16, hq=True), seq, w, h, 16)
    else:
        img = media.grab_frame(info, frame, w, h, 16, hq=True)
    engine.set_input(img)
    li = lut_info(values["lut_arquivo"]) if values.get("lut_on") else None
    out = engine.render(look.build_plan(values, w, h, frame, info.fps, li, dither=False), 16)
    engine.release()
    path = a.saida or str(Path(src).with_name(f"{Path(src).stem}_quadro{frame}.png"))
    ext = Path(path).suffix.lower()
    pix = {".png": ["-pix_fmt", "rgb48be"], ".tif": ["-pix_fmt", "rgb48le", "-compression_algo", "deflate"],
           ".tiff": ["-pix_fmt", "rgb48le"], ".jpg": ["-pix_fmt", "yuvj444p", "-q:v", "2"],
           ".jpeg": ["-pix_fmt", "yuvj444p", "-q:v", "2"]}.get(ext)
    if pix is None:
        raise CliError(_("Formato de imagem não suportado: {ext} (use .png, .tif ou .jpg)").format(ext=ext))
    cmd = [media.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-s", f"{w}x{h}",
           "-i", "pipe:0", *pix, "-frames:v", "1", "-update", "1", path]
    res = subprocess.run(cmd, input=out.tobytes(), capture_output=True, creationflags=media.NO_WINDOW)
    if res.returncode != 0:
        raise CliError(res.stderr.decode("utf-8", "replace"))
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


def cmd_info(a) -> int:
    from . import media
    _need_ffmpeg()
    info = media.probe(a.entrada)
    data = {"arquivo": info.path, "largura": info.width, "altura": info.height, "fps": round(info.fps, 3),
            "quadros": info.frames, "duracao_s": round(info.duration, 3), "codec": info.codec,
            "pix_fmt": info.pix_fmt, "bits": info.bit_depth, "audio": info.audio_codec or None,
            "imagem": info.is_image}
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
    p.add_argument("--codec")
    p.add_argument("--recipiente", help=_("extensão do arquivo (mp4, mov, mkv…)"))
    p.add_argument("--pix", help=_("formato de cor (yuv420p, yuv422p10le…)"))
    p.add_argument("--crf", type=float, help=_("qualidade constante do codec (menor = melhor)"))
    p.add_argument("--taxa", type=float, help=_("taxa de bits em Mb/s (em vez da qualidade constante)"))
    p.add_argument("--velocidade", help=_("preset de velocidade do codec (slow, p6…)"))
    p.add_argument("--perfil", help=_("perfil do ProRes/DNxHR"))
    p.add_argument("--resolucao", help=_("original, 2160, 1080, 720…"))
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
