"""Informações da máquina: processador, memória e placas de vídeo."""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import sys
from functools import lru_cache

from .i18n import _, fmt_decimal

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@lru_cache(maxsize=1)
def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name, _kind = winreg.QueryValueEx(key, "ProcessorNameString")
            return " ".join(str(name).split())
        except OSError:
            pass
    if sys.platform.startswith("linux"):
        try:
            for line in open("/proc/cpuinfo", encoding="utf-8", errors="replace"):
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, timeout=5)
            if out.stdout.strip():
                return out.stdout.decode().strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return platform.processor() or _("Processador")


def open_path(path) -> None:
    """Abre um arquivo ou pasta no gerenciador de arquivos do sistema."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal(path) -> None:
    """Mostra o arquivo selecionado na pasta (no Windows) ou abre a pasta."""
    path = str(path)
    if sys.platform == "win32" and os.path.isfile(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        open_path(path if os.path.isdir(path) else os.path.dirname(path) or ".")


def cpu_threads() -> int:
    return os.cpu_count() or 4


def ram() -> tuple[int, int]:
    """(total, disponível) em bytes."""
    if sys.platform == "win32":
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MS()
        st.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return int(st.ullTotalPhys), int(st.ullAvailPhys)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        avail = os.sysconf("SC_AVPHYS_PAGES")
        return pages * size, avail * size
    except (ValueError, OSError, AttributeError):
        return 8 << 30, 4 << 30


@lru_cache(maxsize=1)
def nvidia_gpus() -> list[tuple[int, str, int]]:
    """[(índice, nome, memória em MB)] das placas NVIDIA."""
    exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    if not os.path.isfile(exe) and not shutil.which("nvidia-smi"):
        return []
    try:
        res = subprocess.run([exe, "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, timeout=8, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in res.stdout.decode("utf-8", "replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0].isdigit():
            try:
                out.append((int(parts[0]), parts[1], int(float(parts[2]))))
            except ValueError:
                continue
    return out


def gb(n: int) -> str:
    return fmt_decimal(n / (1 << 30), 1) + " GB"
