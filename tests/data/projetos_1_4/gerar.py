"""Gera os projetos de referência da 1.4 (`simples.plc`, `edicao.plc`) e `referencia.json`.

Foi rodado **com o código da 1.4.0** (commit `5743a27`), antes de qualquer mudança da 1.5:

    python tests/data/projetos_1_4/gerar.py

`referencia.json` é o que a 1.4 faz ao **abrir** os arquivos gravados (com a mídia gerada em outra pasta, achada
pelo caminho relativo): os valores, as camadas de cada quadro, os uniforms de cada camada
(`compositor.clip_uniforms`), o plano do look (`look.build_plan`), o grafo do som (`audiomix.build_graph`) e o
JSON da montagem salvo de novo. `tests/test_project_migration.py` abre os mesmos arquivos com o código atual e
confere tudo isso (`references`). Só regenere de propósito, a partir da versão que vira a nova referência.

Atenção: a 1.4 grava `entrada` (início no arquivo) com 6 casas; um clipe cortado em 20/24 s volta como
0,833333 s e o quadro de origem do seu primeiro quadro é o 19, não o 20. A referência é o que a 1.4 mostra depois
de abrir o projeto (a prévia e a exportação usam sempre uma cópia por JSON), e isso não pode mudar.

A mídia não vai para o repositório: `make_media()` gera arquivos com o ffmpeg (`lavfi`) e o teste gera de novo
na pasta temporária (os projetos guardam os metadados das fontes e acham os arquivos pelo caminho relativo).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FAKE_BASE = "/projetos/exemplo"   # caminho absoluto gravado nos projetos (não existe: o relativo é usado)
MEDIA_TOKEN = "<MIDIA>"           # a pasta da mídia nas referências (os caminhos mudam a cada máquina)
W, H, FPS = 320, 180, 24
LOOK_FRAMES = (0, 5, 23, 47, 70)

MEDIA = {
    "amostra.mp4": ["-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k"],
    "barras.mp4": ["-f", "lavfi", "-i", f"smptebars=size={W}x{H}:rate={FPS}:duration=2",
                   "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=2",
                   "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "128k"],
    "cena.png": ["-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=1:duration=1", "-frames:v", "1"],
    "tom.wav": ["-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=2", "-c:a", "pcm_s16le"],
}


def make_media(folder: Path, ffmpeg: str) -> dict[str, str]:
    """Gera a mídia dos projetos em `folder/midia/`; devolve {nome: caminho}."""
    out = {}
    d = Path(folder) / "midia"
    d.mkdir(parents=True, exist_ok=True)
    for name, args in MEDIA.items():
        p = d / name
        if not p.exists():
            subprocess.run([ffmpeg, "-v", "error", "-y", "-nostdin", *args, str(p)], check=True, capture_output=True)
        out[name] = str(p)
    return out


def _num(x):
    if isinstance(x, (tuple, list)):
        return [_num(v) for v in x]
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return x
    return str(x)


def plan_ref(plan) -> dict:
    """O que um `look.Plan` decide (uniforms e passos), em JSON."""
    return {"uniforms": {k: _num(v) for k, v in sorted(plan.uniforms.items())},
            "soft_sigma": plan.soft_sigma, "grain_size": plan.grain_size, "grain_seed": plan.grain_seed,
            "lut_path": plan.lut_path, "edge_text": plan.edge_text,
            "chains": [[c.name, c.threshold, c.limit, c.sigma, int(c.lum_only), int(c.alpha_mask)] for c in plan.chains]}


def sequence_ref(seq, media_dir: str) -> dict:
    """Camadas e uniforms de cada quadro, faixa do look e grafos do som de uma montagem."""
    from pelicula import audiomix, compositor, sequence
    cw, ch = sequence.canvas_size(seq)
    frames = []
    table: list[dict] = []   # uniforms distintos (quadros parecidos repetem os mesmos)
    index: dict[str, int] = {}

    def ref_of(u: dict) -> int:
        d = {k: _num(v) for k, v in sorted(u.items())}
        key = json.dumps(d, sort_keys=True)
        if key not in index:
            index[key] = len(table)
            table.append(d)
        return index[key]

    for t in range(seq.duration):
        layers = []
        for layer in seq.layers_at(t):
            dw, dh = sequence.decode_size(seq, layer.clip, cw, ch)
            u, mip = compositor.clip_uniforms(seq, layer, dw, dh, cw, ch)
            un, _mip = compositor.clip_uniforms(seq, layer, dw, dh, cw, ch, neutral=True)
            layers.append({"clip": layer.clip.id, "src_frame": layer.src_frame, "alpha": layer.alpha,
                           "fade_color": list(layer.fade_color), "fade": layer.fade, "extension": layer.extension,
                           "decode": [dw, dh], "mip": int(mip), "uniforms": ref_of(u), "neutral": ref_of(un)})
        frames.append(layers)

    def graph(a, b):
        g = audiomix.build_graph(seq, a, b)
        if g is None:
            return None
        inputs, text = g
        return [[norm(x, media_dir) for x in inputs], text]

    return {"canvas": [cw, ch], "duration": seq.duration, "legal": int(sequence.legal_range(seq)), "frames": frames,
            "uniforms": table, "audio": graph(0, -1), "audio_trecho": graph(10, 40),
            "trivial": seq.is_trivial() is not None}


def norm(text: str, media_dir: str) -> str:
    """Troca a pasta da mídia desta máquina por `<MIDIA>` (barras normais)."""
    s = str(text)
    for d in sorted({media_dir, os.path.normpath(media_dir), os.path.abspath(media_dir)}, key=len, reverse=True):
        s = s.replace(d, MEDIA_TOKEN)
    return s.replace("\\", "/")


def norm_obj(obj, media_dir: str):
    """`norm` em todos os textos de um JSON."""
    if isinstance(obj, dict):
        return {k: norm_obj(v, media_dir) for k, v in obj.items()}
    if isinstance(obj, list):
        return [norm_obj(v, media_dir) for v in obj]
    if isinstance(obj, str):
        return norm(obj, media_dir)
    return obj


def build(folder: Path, ffmpeg: str):
    """Monta os dois projetos com a mídia de `folder/midia` (API da 1.4). Devolve (simples, edicao, seq)."""
    from pelicula import media, presets, project, timeline
    m = make_media(folder, ffmpeg)
    look = presets.builtin_values("vision3_500t")
    look.update(grao_on=True, grao_forca=1.3, hal_on=True, proj_on=True, desg_on=True, mold_on=True)
    simples = project.Project(media_path=m["amostra.mp4"], values=look, preset_id="vision3_500t", frame=12,
                              in_point=4, out_point=40, compare="side", preview="720", export_quality="mp4")

    amostra = media.probe_source(m["amostra.mp4"])
    barras = media.probe_source(m["barras.mp4"])
    cena = media.probe_source(m["cena.png"])
    tom = media.probe_source(m["tom.wav"])
    seq = timeline.Sequence.for_source(amostra)  # V1/A1 com a amostra inteira; fades curtos ligados
    seq.split(20)
    vids = lambda: sorted((c for c in seq.clips if c.kind == timeline.VIDEO and c.track == 0), key=lambda c: c.start)
    auds = lambda: sorted((c for c in seq.clips if c.kind == timeline.AUDIO and c.track == 0), key=lambda c: c.start)
    right_v, right_a = vids()[1], auds()[1]
    seq.set_values(right_v.id, {**right_v.values, "exposicao": 0.5, "saturacao": -0.3, "roda_meios": [0.2, 0.1],
                                "hsl_vermelho_sat": 0.3, "nitidez": 0.3, "entrada_tipo": "dissolver",
                                "entrada_dur": 0.25})
    seq.set_values(right_a.id, {**right_a.values, "transicao": 0.2})
    made = seq.insert_media(barras)                       # no fim de V1/A1
    bv = next(c for c in made if c.kind == timeline.VIDEO)
    ba = next(c for c in made if c.kind == timeline.AUDIO)
    seq.trim_start(bv.id, bv.start + 6)                   # tira 6 quadros do começo (vídeo e som ligados)
    seq.set_speed(bv.id, 0.5)
    seq.set_values(bv.id, {**bv.values, "escala": 0.8, "pos_x": 0.1, "rotacao": 5.0, "saida_tipo": "preto",
                           "saida_dur": 0.5, "contraste": 0.2, "vinheta": -0.3})
    seq.set_values(ba.id, {**ba.values, "volume": -3.0, "fade_in": 0.3, "graves": 2.0})
    img, = seq.insert_media(cena, at=10, vtrack=1)
    seq.trim_end(img.id, 30)
    seq.set_values(img.id, {**img.values, "escala": 0.4, "pos_x": 0.25, "pos_y": -0.2, "opacidade": 0.7,
                            "mesclagem": "tela", "entrada_tipo": "branco", "entrada_dur": 0.2,
                            "saida_tipo": "transparente", "saida_dur": 0.3})
    t, = seq.insert_media(tom, at=0, atrack=1)
    seq.set_values(t.id, {**t.values, "volume": -6.0, "balanco": 0.3, "fade_out": 0.5})
    frz = seq.insert_media(amostra, vtrack=0, with_audio=False)[0]
    seq.trim_end(frz.id, frz.start + 12)
    seq.set_values(frz.id, {**frz.values, "congelar": True, "temperatura": 20.0})
    seq.track(timeline.AUDIO, 0).volume = -2.0
    seq.add_marker(5, "Início", chapter=True)
    seq.add_marker(30, "Cor", color="azul", note="corrigir")
    edicao = project.Project(media_path=m["amostra.mp4"], values=look, preset_id="vision3_500t", frame=30,
                             in_point=None, out_point=None, sequence=seq.to_json(), mode="edicao")
    return simples, edicao, seq


def _fake_paths(obj, real: str):
    """Troca a pasta real pela falsa em todos os textos e deixa os relativos com barras normais."""
    if isinstance(obj, dict):
        return {k: (v.replace("\\", "/") if k == "relativo" and isinstance(v, str) else _fake_paths(v, real))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fake_paths(v, real) for v in obj]
    if isinstance(obj, str):
        for d in {real, os.path.normpath(real)}:
            obj = obj.replace(d, FAKE_BASE)
        return obj.replace("\\", "/") if obj.startswith(FAKE_BASE) else obj
    return obj


def references(simples, edicao, media_dir: str) -> dict:
    """O que os dois projetos abertos (`project.load`) dão: valores, planos do look, montagem e som."""
    from pelicula import look, sequence, timeline
    ref = {"simples": {"valores": simples.values, "estado": state(simples), "look": {}}, "edicao": {}}
    for f in LOOK_FRAMES:
        ref["simples"]["look"][str(f)] = plan_ref(look.build_plan(simples.values, W, H, f, float(FPS), None,
                                                                  legal=True))
    seq = timeline.Sequence.from_json(edicao.sequence)
    legal = sequence.legal_range(seq)
    ref["edicao"]["valores"] = edicao.values
    ref["edicao"]["estado"] = state(edicao)
    ref["edicao"]["look"] = {str(f): plan_ref(look.build_plan(edicao.values, W, H, f, float(FPS), None, legal=legal))
                             for f in LOOK_FRAMES}
    ref["edicao"]["montagem"] = sequence_ref(seq, media_dir)
    ref["edicao"]["json"] = norm_obj(json.loads(json.dumps(seq.to_json())), media_dir)
    return ref


def state(p) -> dict:
    """Os campos do projeto fora dos valores e da montagem."""
    return {"preset": p.preset_id, "quadro": p.frame, "entrada": p.in_point, "saida": p.out_point,
            "comparacao": p.compare, "previa": p.preview, "qualidade": p.export_quality, "modo": p.mode,
            "midia": os.path.basename(p.media_path)}


def open_copies(folder: Path, ffmpeg: str):
    """Gera a mídia em `folder/midia`, copia os dois projetos para `folder` e os abre (`project.load`)."""
    import shutil
    from pelicula import project
    make_media(folder, ffmpeg)
    out = []
    for name in ("simples", "edicao"):
        shutil.copyfile(HERE / f"{name}.plc", folder / f"{name}.plc")
        out.append(project.load(str(folder / f"{name}.plc")))
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from pelicula import __version__, media, project
    if not media.configure():
        print("ffmpeg não encontrado", file=sys.stderr)
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="pelicula_ref14_"))
    simples, edicao, _seq = build(tmp, media.ffmpeg())
    for name, p in (("simples", simples), ("edicao", edicao)):
        path = tmp / f"{name}.plc"
        project.save(p, str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["miniatura_jpeg"] = ""
        data["salvo_em"] = "2026-10-27T12:00:00"
        data = _fake_paths(data, str(tmp))
        (HERE / f"{name}.plc").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A referência é o que esta versão faz ao abrir os arquivos gravados (com a mídia em outra pasta).
    other = Path(tempfile.mkdtemp(prefix="pelicula_ref14_abrir_"))
    s2, e2 = open_copies(other, media.ffmpeg())
    ref = references(s2, e2, str(other / "midia"))
    ref["versao"] = __version__
    (HERE / "referencia.json").write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                                          + "\n", encoding="utf-8")
    print(f"referência gerada com a versão {__version__} em {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
