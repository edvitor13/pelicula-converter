"""Leitura e escrita de LUTs .cube e busca de LUTs já instalados no computador."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .i18n import _


@dataclass
class Lut3D:
    path: str
    size: int
    data: np.ndarray  # (size**3, 3) float32, ordem .cube (R mais rápido)
    dmin: tuple
    dmax: tuple
    title: str = ""


def load_cube(path: str) -> Lut3D:
    size = 0
    dmin = [0.0, 0.0, 0.0]
    dmax = [1.0, 1.0, 1.0]
    title = ""
    values: list[list[float]] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            up = line.upper()
            if up.startswith("TITLE"):
                title = line[5:].strip().strip('"')
            elif up.startswith("LUT_3D_SIZE"):
                size = int(line.split()[1])
            elif up.startswith("LUT_1D_SIZE"):
                raise ValueError(_("LUT 1D não é suportado; use um LUT 3D."))
            elif up.startswith("DOMAIN_MIN"):
                dmin = [float(x) for x in line.split()[1:4]]
            elif up.startswith("DOMAIN_MAX"):
                dmax = [float(x) for x in line.split()[1:4]]
            elif up.startswith("LUT_3D_INPUT_RANGE"):
                lo, hi = (float(x) for x in line.split()[1:3])
                dmin, dmax = [lo] * 3, [hi] * 3
            elif up[0].isdigit() or up[0] in "-.+":
                parts = line.split()
                if len(parts) >= 3:
                    values.append([float(parts[0]), float(parts[1]), float(parts[2])])
    if size < 2:
        raise ValueError(_("Arquivo .cube sem LUT_3D_SIZE."))
    if len(values) < size ** 3:
        raise ValueError(_("LUT incompleto: {lidos} de {total} valores.").format(lidos=len(values), total=size ** 3))
    data = np.asarray(values[: size ** 3], dtype=np.float32)
    return Lut3D(path, size, data, tuple(dmin), tuple(dmax), title)


def save_cube(path: str, data: np.ndarray, size: int, title: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f'TITLE "{title}"\n')
        fh.write("# Gerado pelo PeliculaConverter\n")
        fh.write(f"LUT_3D_SIZE {size}\n")
        fh.write("DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n")
        for r, g, b in np.clip(data, 0.0, 1.0):
            fh.write(f"{r:.6f} {g:.6f} {b:.6f}\n")


def guess_input(path: str) -> str:
    """Palpite do espaço de entrada pelo nome e pasta do LUT."""
    p = path.replace("\\", "/").lower()
    name = os.path.basename(p)
    if "/film looks/" in p or "cineon" in name:
        return "cineon"
    words = set(re.split(r"[^a-z0-9]+", name))
    compact = re.sub(r"[^a-z0-9]+", "", name)
    if "logc4" in compact or "awg4" in compact:
        return "logc4"
    if "applelog" in compact or ("apple" in words and "log" in words):
        return "applelog"
    if "gen5" in compact or "bmdfilm" in compact or "blackmagicfilm" in compact:
        return "bmd_gen5"
    if "logc" in name or "arri" in words or "alexa" in words:
        return "logc3"
    if "slog3" in name or "s-log3" in name:
        return "slog3"
    if "n-log" in name or "nlog" in name:
        return "nlog"
    if "v-log" in name or "vlog" in name:
        return "vlog"
    return "rec709"


def user_dir() -> Path:
    from .deps import config_dir
    d = config_dir() / "luts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def install(paths: list[str]) -> tuple[list[str], list[str]]:
    """Copia LUTs .cube para a pasta do app. Devolve (instalados, erros)."""
    import shutil
    done, errors = [], []
    dest_dir = user_dir()
    for src in paths:
        name = os.path.basename(src)
        try:
            load_cube(src)
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        dest = dest_dir / name
        if dest.exists() and os.path.abspath(dest) != os.path.abspath(src):
            stem, n = dest.stem, 2
            while dest.exists():
                dest = dest_dir / f"{stem} ({n}).cube"
                n += 1
        if os.path.abspath(dest) != os.path.abspath(src):
            shutil.copy2(src, dest)
        done.append(str(dest))
    return done, errors


def find_system_luts() -> list[tuple[str, str]]:
    """LUTs de película que já vêm com o Premiere, After Effects e Resolve."""
    found: list[tuple[str, str]] = []
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    roots = []
    adobe = Path(pf) / "Adobe"
    if adobe.is_dir():
        for app in sorted(adobe.glob("Adobe Premiere Pro*"), reverse=True):
            roots.append((app / "Lumetri" / "LUTs" / "Creative", f"{app.name.replace('Adobe ', '')}"))
            roots.append((app / "Resources" / "LUTs" / "FilmEmulation",
                          _("{programa} (emulação)").format(programa=app.name.replace("Adobe ", ""))))
            break
        for app in sorted(adobe.glob("Adobe After Effects*"), reverse=True):
            roots.append((app / "Support Files" / "Lumetri" / "LUTs" / "Creative", f"{app.name.replace('Adobe ', '')}"))
            break
    roots.append((Path(pd) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT" / "Film Looks", "DaVinci Resolve"))
    roots.append((Path("/opt/resolve/LUT/Film Looks"), "DaVinci Resolve"))
    roots.append((Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/Film Looks"), "DaVinci Resolve"))
    roots.insert(0, (user_dir(), _("Meus LUTs")))
    for folder, label in roots:
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.cube")):
            found.append((f"{label} — {f.stem}", str(f)))
    return found
