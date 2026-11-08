"""Gera os projetos de referência da 1.8 (`simples.plc`, `edicao.plc`) e `referencia.json`.

Foi rodado **com o código da 1.8** (commit `6de08de`, o main com a 1.8 inteira, antes de qualquer mudança da 1.9):

    python tests/data/projetos_1_8/gerar.py

Os dois projetos são os da referência da 1.6 (`projetos_1_6/gerar.py`, que vêm da 1.4) com recursos da 1.8 por cima, e
por isso foram gravados no formato 6: o look com o som de película (`somf_*`, que a 1.7 não lê) e a montagem com o
balanço da faixa de áudio, o crédito de um som livre, a correção à mão das batidas e o look próprio da sequência (bloco
no formato 5). `referencia.json` é o que a 1.8 faz ao **abrir** esses arquivos, nas mesmas contas da referência da 1.4.
`tests/test_project_migration.py` abre os mesmos arquivos com o código atual e confere tudo e, além disso, que gravar de
novo sem usar nada novo dá o mesmo JSON (`test_a_1_8_project_saved_again_is_the_same_json`). Só regenere de propósito,
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
SAVED_AT = "2026-11-08T12:00:00"
BASE_COMMIT = "6de08de"  # o código que gerou (a 1.8 ainda tinha __version__ = "1.7.0")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"gerar_{name}", HERE.parent / name / "gerar.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _base():
    """O gerador da 1.4: mídia, referências e caminhos falsos são as mesmas contas."""
    return _load("projetos_1_4")


def build(folder: Path, ffmpeg: str):
    """Os dois projetos da 1.6 com recursos da 1.8 por cima. Devolve (simples, edicao)."""
    from pelicula import timeline
    simples, edicao = _load("projetos_1_6").build(folder, ffmpeg)
    simples.values = {**simples.values, "somf_on": True, "somf_trilha": "otica_16", "somf_estalos": 0.8}
    seq = timeline.Sequence.from_json(edicao.sequence)
    seq.track(timeline.AUDIO, 1).pan = -0.4
    tom = next(s for s in seq.sources.values() if s.path.endswith("tom.wav"))
    tom.credit = {"titulo": "Tom", "autor": "Teste", "licenca": "CC0", "url": "https://exemplo.org/tom",
                  "origem": "openverse"}
    tom.beats_fix = {"fator": 2.0}
    seq.look = timeline.SeqLook(values={**edicao.values, "exposicao": 0.3}, preset_id="vision3_500t")
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


def recorded(p, folder: str) -> dict:
    """O JSON que `project.save` grava de `p`, com a hora, a miniatura e a pasta fixas (o que se compara)."""
    from pelicula import project
    path = Path(folder) / "de_novo.plc"
    project.save(p, str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["miniatura_jpeg"] = ""
    data["salvo_em"] = SAVED_AT
    data.pop("versao_app", None)
    data["nome"] = ""
    return _base()._fake_paths(data, str(folder))


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from pelicula import __version__, media, project
    if not media.configure():
        print("ffmpeg não encontrado", file=sys.stderr)
        return 1
    g = _base()
    tmp = Path(tempfile.mkdtemp(prefix="pelicula_ref18_"))
    simples, edicao = build(tmp, media.ffmpeg())
    for name, p in (("simples", simples), ("edicao", edicao)):
        path = tmp / f"{name}.plc"
        project.save(p, str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["formato"] == 6, (name, data["formato"], data.get("recursos"))
        data["miniatura_jpeg"] = ""
        data["salvo_em"] = SAVED_AT
        data = g._fake_paths(data, str(tmp))
        (HERE / f"{name}.plc").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A referência é o que esta versão faz ao abrir os arquivos gravados (com a mídia em outra pasta).
    other = Path(tempfile.mkdtemp(prefix="pelicula_ref18_abrir_"))
    s2, e2 = open_copies(other, media.ffmpeg())
    ref = references(s2, e2, str(other / "midia"))
    ref["versao"] = __version__
    ref["commit"] = BASE_COMMIT
    ref["gravado_de_novo"] = {"simples": recorded(s2, str(other)), "edicao": recorded(e2, str(other))}
    (HERE / "referencia.json").write_text(json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                                          + "\n", encoding="utf-8")
    print(f"referência gerada com a versão {__version__} em {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
