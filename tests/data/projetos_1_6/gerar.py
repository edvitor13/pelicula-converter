"""Gera os projetos de referência da 1.6 (`simples.plc`, `edicao.plc`) e `referencia.json`.

Foi rodado **com o código da 1.6.0** (tag `v1.6.0`): esta pasta foi copiada para um worktree da tag e os três
arquivos gerados voltaram para cá:

    git worktree add <pasta> v1.6.0
    cp -r tests/data/projetos_1_6 <pasta>/tests/data/ && cd <pasta>
    python tests/data/projetos_1_6/gerar.py

Os dois projetos usam algo da 1.6 e por isso foram gravados no formato 4: o look com ajustes e opções que a 1.5 não
lê (`entrada` "clog3", Laboratório, lente anamórfica) e a montagem com perfil de câmera, pele natural, luz por plano
e grupo de cor nos clipes (bloco no formato 3). `referencia.json` é o que a 1.6 faz ao **abrir** esses arquivos, nas
mesmas contas da referência da 1.4 (`projetos_1_4/gerar.py`, de onde vêm a montagem, a mídia e as funções).
`tests/test_project_migration.py` abre os mesmos arquivos com o código atual e confere tudo. Só regenere de propósito,
a partir da versão que vira a nova referência.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _base():
    """O gerador da 1.4: mídia, montagem e referências são as mesmas contas."""
    spec = importlib.util.spec_from_file_location("gerar_projetos_1_4", HERE.parent / "projetos_1_4" / "gerar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(folder: Path, ffmpeg: str):
    """Os dois projetos da 1.4 com recursos da 1.6 por cima. Devolve (simples, edicao)."""
    from pelicula import timeline
    simples, edicao, seq = _base().build(folder, ffmpeg)
    simples.values = {**simples.values, "entrada": "clog3", "proteger_cores": 0.4, "lab_on": True,
                      "lab_processo": "reversivel", "lab_grao": 0.5, "grao_estrutura": 0.5, "hal_modelo": "fisica",
                      "anam_on": True, "anam_compressao": "1.33", "anam_flare": 0.3}
    edicao.values = {**edicao.values, "entrada": "clog3", "proteger_cores": 0.4}
    vids = sorted((c for c in seq.clips if c.kind == timeline.VIDEO and c.track == 0), key=lambda c: c.start)
    seq.set_values(vids[0].id, {**vids[0].values, "camera_entrada": "clog3", "pele_natural": 0.4})
    seq.set_values(vids[1].id, {**vids[1].values, "luz_r": 2.0, "luz_densidade": -1.0, "degrade_tipo": "linear",
                                "degrade_exposicao": -0.5})
    vids[0].color_group = vids[1].color_group = "g1"
    edicao.sequence = seq.to_json()
    return simples, edicao


def open_copies(folder: Path, ffmpeg: str):
    """Gera a mídia em `folder/midia`, copia os dois projetos para `folder` e os abre (`project.load`)."""
    from pelicula import project
    _base().make_media(folder, ffmpeg)
    out = []
    for name in ("simples", "edicao"):
        shutil.copyfile(HERE / f"{name}.plc", folder / f"{name}.plc")
        out.append(project.load(str(folder / f"{name}.plc")))
    return out


def references(simples, edicao, media_dir: str) -> dict:
    return _base().references(simples, edicao, media_dir)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from pelicula import __version__, media, project
    if not media.configure():
        print("ffmpeg não encontrado", file=sys.stderr)
        return 1
    g = _base()
    tmp = Path(tempfile.mkdtemp(prefix="pelicula_ref16_"))
    simples, edicao = build(tmp, media.ffmpeg())
    for name, p in (("simples", simples), ("edicao", edicao)):
        path = tmp / f"{name}.plc"
        project.save(p, str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["formato"] == 4, (name, data["formato"], data.get("recursos"))
        data["miniatura_jpeg"] = ""
        data["salvo_em"] = "2026-10-29T12:00:00"
        data = g._fake_paths(data, str(tmp))
        (HERE / f"{name}.plc").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A referência é o que esta versão faz ao abrir os arquivos gravados (com a mídia em outra pasta).
    other = Path(tempfile.mkdtemp(prefix="pelicula_ref16_abrir_"))
    s2, e2 = open_copies(other, media.ffmpeg())
    ref = references(s2, e2, str(other / "midia"))
    ref["versao"] = __version__
    (HERE / "referencia.json").write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                                          + "\n", encoding="utf-8")
    print(f"referência gerada com a versão {__version__} em {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
