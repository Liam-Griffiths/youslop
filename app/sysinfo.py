"""Best-effort read of how much memory this machine has free.

A render that runs the system out of memory does not raise a catchable
exception anywhere in this codebase — the OS simply kills the process
(`systemd-oomd` on Linux, the same idea elsewhere), which looks identical to
the app crashing with no error at all. This is a guess, not a guarantee: a
figure here is only ever used to warn before the heavy part of a render, never
to prove anything.
"""
from __future__ import annotations

import ctypes
import re
import subprocess
import sys


def available_mb() -> float | None:
    """Memory free for new allocations, in MB — None if it cannot be read."""
    try:
        if sys.platform == "linux":
            return _linux_available()
        if sys.platform == "darwin":
            return _darwin_available()
        if sys.platform == "win32":
            return _windows_available()
    except Exception:
        pass
    return None


def swap_pressure() -> float | None:
    """Fraction of swap in use (0..1) — Linux only, None elsewhere or unknown.

    Swap nearly full is the sharper signal: it means the system has nowhere
    left to page memory out to, so the next allocation is what triggers the
    kill rather than merely slowing down.
    """
    if sys.platform != "linux":
        return None
    try:
        total = free = None
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("SwapTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    free = int(line.split()[1])
        if not total:
            return 0.0
        return max(0.0, min(1.0, (total - free) / total))
    except Exception:
        return None


def _linux_available() -> float | None:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    return None


def _darwin_available() -> float | None:
    page_size = int(subprocess.run(
        ["sysctl", "-n", "hw.pagesize"], capture_output=True, text=True, timeout=5,
    ).stdout.strip())
    out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    free_pages = 0
    for key in ("Pages free", "Pages inactive", "Pages speculative"):
        m = re.search(rf"{key}:\s+(\d+)\.", out)
        if m:
            free_pages += int(m.group(1))
    return free_pages * page_size / (1024 * 1024)


def _windows_available() -> float | None:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return stat.ullAvailPhys / (1024 * 1024)
