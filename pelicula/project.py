"""Projetos do PeliculaConverter (.plc): o estado da edição para continuar depois.

O arquivo é JSON em UTF-8 com o vídeo de origem (caminho absoluto e relativo ao projeto),
todos os ajustes, o look escolhido, entrada/saída, quadro atual, opções da prévia e uma
miniatura em JPEG (base64) para a lista de projetos recentes.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import APP_NAME, __version__, params
from .i18n import _

EXT = ".plc"
FORMAT = 1


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
    path: str = ""  # onde o projeto está salvo (não vai para o arquivo)

    def to_json(self) -> dict[str, Any]:
        base = Path(self.path).parent if self.path else None
        rel = ""
        if base and self.media_path:
            try:
                rel = os.path.relpath(self.media_path, base)
            except ValueError:  # outro disco no Windows
                rel = ""
        return {
            "app": APP_NAME,
            "formato": FORMAT,
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
        }


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
    if not isinstance(data, dict) or data.get("app") != APP_NAME:
        raise ProjectError(_("O arquivo não é um projeto do PeliculaConverter."))
    if int(data.get("formato", 1)) > FORMAT:
        raise ProjectError(_("O projeto foi salvo por uma versão mais nova do app. Atualize o PeliculaConverter."))
    midia = data.get("midia") or {}
    media = str(midia.get("caminho") or "")
    rel = str(midia.get("relativo") or "")
    if media and not os.path.exists(media) and rel:
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
        name=str(data.get("nome") or Path(path).stem),
        saved_at=saved,
        app_version=str(data.get("versao_app") or ""),
        thumbnail_jpeg=thumb,
        path=str(Path(path).resolve()),
    )


def peek(path: str) -> dict[str, Any] | None:
    """Lê só o que a lista de recentes precisa (nome, data, mídia, miniatura)."""
    try:
        p = load(path)
    except ProjectError:
        return None
    return {"path": p.path, "name": p.name, "saved_at": p.saved_at, "media": p.media_path,
            "media_ok": bool(p.media_path) and os.path.exists(p.media_path), "thumb": p.thumbnail_jpeg}
