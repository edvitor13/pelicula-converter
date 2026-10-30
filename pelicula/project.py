"""Projetos do PeliculaConverter (.plc): o estado da edição para continuar depois.

O arquivo é JSON em UTF-8 com o vídeo de origem (caminho absoluto e relativo ao projeto),
todos os ajustes, o look escolhido, entrada/saída, quadro atual, opções da prévia e uma
miniatura em JPEG (base64) para a lista de projetos recentes.

Com o modo Edição, o projeto também guarda a sequência (`"edicao"`, ver `timeline.Sequence`) e o
modo aberto (`"modo"`).

Formato (`"formato"`): esta versão lê até `FORMAT` (5) e grava o **menor** formato que o projeto precisa, para
abrir nas versões antigas sempre que der: 1 = só o arquivo (sem sequência); 2 = com sequência; 3 = usa algum
recurso da 1.5 (`features()`: os testes de `FEATURES_V3` e de `timeline.FEATURES`); 4 = usa algo da 1.6 (os de
`FEATURES_V4` e de `timeline.FEATURES_V4`: um ajuste ou uma opção que a 1.5 não lê entra sozinho, pelo retrato
`params.known_1_5`); 5 = usa algo da 1.7 (os de `FEATURES_V5` e de `timeline.FEATURES_V5`, pelo retrato
`params.known_1_6`). Os recursos ficam listados em `"recursos"`. Versões antigas recusam formato maior que o
delas com aviso. Abrir um formato antigo passa pelos passos de `MIGRATIONS` (1 → 2 → 3 → 4 → 5), puros e testados
(`tests/test_project_migration.py`).
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME, __version__, keyframes, params
from .i18n import _

EXT = ".plc"
FORMAT = 5          # maior formato que esta versão lê
FORMAT_SIMPLE = 1   # projeto sem sequência do modo Edição
FORMAT_EDIT = 2     # projeto com sequência, sem nada da 1.5
FORMAT_15 = 3       # usa algum recurso da 1.5, nada da 1.6
FORMAT_16 = 4       # usa algo da 1.6, nada da 1.7
MODES = ("pelicula", "edicao")


@dataclass
class Project:
    media_path: str = ""
    values: dict[str, Any] = field(default_factory=params.defaults)
    preset_id: str = ""
    frame: int = 0
    in_point: int | None = None
    out_point: int | None = None
    compare: str = "split"
    preview: str = "720"
    export_quality: str = ""
    name: str = ""
    saved_at: float = 0.0
    app_version: str = __version__
    thumbnail_jpeg: bytes = b""
    sequence: dict[str, Any] | None = None  # JSON de timeline.Sequence (modo Edição)
    mode: str = "pelicula"                  # "pelicula" | "edicao"
    # Chaves de animação do look (`keyframes.to_json`: {ajuste: [[quadro, valor, curva?]…]}), em quadros do
    # arquivo (modo Película) ou da montagem; {} = look fixo. No JSON, "chaves" (só quando há).
    look_keys: dict[str, list] = field(default_factory=dict)
    path: str = ""  # onde o projeto está salvo (não vai para o arquivo)

    def to_json(self) -> dict[str, Any]:
        base = Path(self.path).parent if self.path else None
        rel = _relative(self.media_path, base)
        edicao = None
        if self.sequence:
            edicao = json.loads(json.dumps(self.sequence))
            for src in edicao.get("fontes") or []:
                if isinstance(src, dict) and src.get("tipo", "arquivo") == "arquivo":  # sem arquivo: nada
                    src["relativo"] = _relative(str(src.get("caminho") or ""), base)
        feats = self.features()
        data = {
            "app": APP_NAME,
            "formato": needed_format(feats, bool(edicao)),
            "versao_app": __version__,
            "salvo_em": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.saved_at or time.time())),
            "nome": self.name,
            "midia": {"caminho": self.media_path, "relativo": rel},
            "preset": self.preset_id,
            "valores": self.values,
            "quadro": int(self.frame),
            "entrada": self.in_point,
            "saida": self.out_point,
            "comparacao": self.compare,
            "previa": self.preview,
            "qualidade_exportacao": self.export_quality,
            "miniatura_jpeg": base64.b64encode(self.thumbnail_jpeg).decode("ascii") if self.thumbnail_jpeg else "",
            "modo": self.mode if self.mode in MODES else "pelicula",
        }
        if edicao:
            data["edicao"] = edicao
        keys = keyframes.to_json(keyframes.clean_keys(params.FILM, self.look_keys))
        if keys:
            data["chaves"] = keys
        if feats:
            data["recursos"] = sorted(feats)  # informativo: o que pede o formato 3, 4 ou 5
        return data

    def features(self) -> set[str]:
        """Recursos da 1.5, da 1.6 e da 1.7 que o projeto usa: os de `FEATURES_V3`/`FEATURES_V4`/`FEATURES_V5` e
        os da montagem (`timeline.FEATURES`/`timeline.FEATURES_V4`/`timeline.FEATURES_V5`)."""
        found = {fid for reg in (FEATURES_V3, FEATURES_V4, FEATURES_V5) for fid, check in reg.items() if check(self)}
        if self.sequence:
            from . import timeline
            found |= timeline.Sequence.from_json(self.sequence).features()
        return found


# Recursos da 1.5 fora da montagem: id ASCII (nunca renomear) → teste do projeto. Os da montagem ficam em
# `timeline.FEATURES`. Recurso novo: uma linha num dos dois (o campo dele no JSON só quando usado) e, se o
# formato antigo precisa de algo para abrir nesta versão, um passo em `MIGRATIONS`.
FEATURES_V3: dict[str, Callable[[Project], bool]] = {
    "chaves_look": lambda p: bool(keyframes.clean_keys(params.FILM, p.look_keys)),
}


# Recursos da 1.6 fora da montagem (mesma regra; os da montagem ficam em `timeline.FEATURES_V4`). Um ajuste ou
# uma opção nova do look não precisa de linha: "ajustes_1_6" pega tudo o que a 1.5 não lê (`params.beyond_1_5`).
FEATURES_V4: dict[str, Callable[[Project], bool]] = {
    "ajustes_1_6": lambda p: params.beyond_1_5(params.FILM, params.known_1_5()["look"], p.values, p.look_keys),
}


# Recursos da 1.7 fora da montagem (mesma regra; os da montagem ficam em `timeline.FEATURES_V5`). Um ajuste ou
# uma opção nova do look não precisa de linha: "ajustes_1_7" pega tudo o que a 1.6 não lê (`params.beyond_1_6`).
FEATURES_V5: dict[str, Callable[[Project], bool]] = {
    "ajustes_1_7": lambda p: params.beyond_1_6(params.FILM, params.known_1_6()["look"], p.values, p.look_keys),
}


def needed_format(features: set[str] | frozenset[str], has_sequence: bool) -> int:
    """O menor formato que guarda o projeto: 5 com algo da 1.7, 4 com algo da 1.6, 3 com recursos da 1.5, 2 com
    sequência, 1 só com o arquivo."""
    from . import timeline
    if features & (set(FEATURES_V5) | set(timeline.FEATURES_V5)):
        return FORMAT
    if features & (set(FEATURES_V4) | set(timeline.FEATURES_V4)):
        return FORMAT_16
    if features:
        return FORMAT_15
    return FORMAT_EDIT if has_sequence else FORMAT_SIMPLE


def _v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Formato 1 (projeto simples; até a 1.2 sem `"modo"`) → 2: modo válido e nenhum bloco "edicao" quebrado."""
    out = dict(data)
    if out.get("modo") not in MODES:
        out["modo"] = "pelicula"
    if not isinstance(out.get("edicao"), dict):
        out.pop("edicao", None)
    out["formato"] = 2
    return out


def _v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """Formato 2 → 3: o bloco "edicao" vai para o formato atual da montagem (`timeline.migrate`: tipo e
    transparência das fontes) e a lista de recursos começa vazia."""
    from . import timeline
    out = dict(data)
    if isinstance(out.get("edicao"), dict):
        out["edicao"] = timeline.migrate(out["edicao"])
    out.setdefault("recursos", [])
    out["formato"] = 3
    return out


def _v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Formato 3 → 4: nada muda (a 1.6 só acrescenta campos); o bloco "edicao" é migrado ao ser lido
    (`timeline.Sequence.from_json`), que recusa um bloco de versão mais nova com o aviso do projeto."""
    out = dict(data)
    out.setdefault("recursos", [])
    out["formato"] = 4
    return out


def _v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    """Formato 4 → 5: nada muda (a 1.7 só acrescenta campos); o bloco "edicao" é migrado ao ser lido
    (`timeline.Sequence.from_json`), que recusa um bloco de versão mais nova com o aviso do projeto."""
    out = dict(data)
    out.setdefault("recursos", [])
    out["formato"] = 5
    return out


# formato de origem → passo para o formato seguinte (puros: devolvem um dicionário novo).
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4,
                                                                     4: _v4_to_v5}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """O JSON de um projeto de qualquer formato até `FORMAT`, levado ao formato atual passo a passo.
    ProjectError se ele é de uma versão mais nova."""
    try:
        fmt = int(data.get("formato", FORMAT_SIMPLE))
    except (TypeError, ValueError):
        fmt = FORMAT_SIMPLE
    if fmt > FORMAT:
        raise ProjectError(_("O projeto foi salvo por uma versão mais nova do app. Atualize o PeliculaConverter."))
    fmt = max(fmt, FORMAT_SIMPLE)
    while fmt < FORMAT:
        data = MIGRATIONS[fmt](data)
        fmt += 1
    return data


def _relative(path: str, base: Path | None) -> str:
    if not base or not path:
        return ""
    try:
        return os.path.relpath(path, base)
    except ValueError:  # outro disco no Windows
        return ""


def _relink_sequence(data: Any, project_path: str) -> dict[str, Any] | None:
    """Sequência do projeto com os arquivos achados pelo caminho relativo quando o absoluto sumiu."""
    if not isinstance(data, dict):
        return None
    from . import timeline
    from .media import path_exists  # sequência de imagens: o primeiro quadro dela
    seq = timeline.Sequence.from_json(data)
    if not project_path:
        return seq.to_json()
    folder = os.path.dirname(os.path.abspath(project_path))
    rels = {str(s.get("caminho") or ""): str(s.get("relativo") or "")
            for s in data.get("fontes") or [] if isinstance(s, dict)}
    for old in list(seq.sources):
        rel = rels.get(old, "")
        start = seq.sources[old].seq_start
        if seq.sources[old].is_file and not path_exists(old, start) and rel:
            cand = os.path.normpath(os.path.join(folder, rel))
            if path_exists(cand, start):
                seq.relink(old, cand)
    return seq.to_json()


class ProjectError(Exception):
    pass


def save(project: Project, path: str) -> None:
    path = str(Path(path).with_suffix(EXT))
    project.path = path
    project.saved_at = time.time()
    if not project.name:
        project.name = Path(path).stem
    data = project.to_json()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load(path: str) -> Project:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectError(str(exc)) from exc
    return from_json(data, path)


def from_json(data: Any, path: str = "") -> Project:
    """Projeto a partir do JSON já lido (o de `Project.to_json`).

    `path`: onde o .plc está (acha arquivos pelo caminho relativo quando o absoluto sumiu); "" = projeto
    sem arquivo (a cópia da recuperação automática, que guarda só caminhos absolutos).
    """
    if not isinstance(data, dict) or data.get("app") != APP_NAME:
        raise ProjectError(_("O arquivo não é um projeto do PeliculaConverter."))
    data = migrate(data)
    midia = data.get("midia") or {}
    media = str(midia.get("caminho") or "")
    rel = str(midia.get("relativo") or "")
    if media and path and not os.path.exists(media) and rel:
        cand = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), rel))
        if os.path.exists(cand):
            media = cand
    thumb = b""
    try:
        thumb = base64.b64decode(data.get("miniatura_jpeg") or "")
    except (ValueError, TypeError):
        thumb = b""
    saved = 0.0
    try:
        saved = time.mktime(time.strptime(str(data.get("salvo_em", "")), "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        saved = 0.0

    def opt_int(v):
        return int(v) if isinstance(v, (int, float)) else None

    from . import timeline
    try:
        sequence = _relink_sequence(data.get("edicao"), path)
    except timeline.FormatError as exc:
        raise ProjectError(str(exc)) from exc
    return Project(
        media_path=media,
        values=params.sanitize(data.get("valores") or {}),
        preset_id=str(data.get("preset") or ""),
        frame=int(data.get("quadro") or 0),
        in_point=opt_int(data.get("entrada")),
        out_point=opt_int(data.get("saida")),
        compare=str(data.get("comparacao") or "split"),
        preview=str(data.get("previa") or "720"),
        export_quality=str(data.get("qualidade_exportacao") or ""),
        name=str(data.get("nome") or (Path(path).stem if path else "")),
        saved_at=saved,
        app_version=str(data.get("versao_app") or ""),
        thumbnail_jpeg=thumb,
        sequence=sequence,
        mode=str(data.get("modo")) if data.get("modo") in MODES else "pelicula",
        look_keys=keyframes.to_json(keyframes.clean_keys(params.FILM, data.get("chaves"))),
        path=str(Path(path).resolve()) if path else "",
    )


def peek(path: str) -> dict[str, Any] | None:
    """Lê só o que a lista de recentes precisa (nome, data, mídia, miniatura)."""
    try:
        p = load(path)
    except ProjectError:
        return None
    return {"path": p.path, "name": p.name, "saved_at": p.saved_at, "media": p.media_path,
            "media_ok": bool(p.media_path) and os.path.exists(p.media_path), "thumb": p.thumbnail_jpeg}
