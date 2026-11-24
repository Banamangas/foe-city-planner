"""Size the solver's parallelism to the machine it runs on."""
from __future__ import annotations

import os

MAX_THREADS = 12
FULL_THREADS = 12


def total_memory_gb() -> float | None:
    """Physical memory in GB, or None when it cannot be determined."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.ullTotalPhys / 1024 ** 3
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return pages * page_size / 1024 ** 3
    except Exception:
        return None


def pick_parallelism(logical_cpus: int | None, mem_gb: float | None = None) -> dict:
    """Workers / probe workers that leave the machine some headroom."""
    n = 2 if logical_cpus is None else max(1, logical_cpus)
    headroom = max(2, n // 4) if n > 2 else 1
    budget = max(1, min(MAX_THREADS, n - headroom))
    probe_workers = 2 if budget >= 2 else 1
    workers = budget // probe_workers
    threads = workers * probe_workers
    return {
        "workers": workers,
        "probe_workers": probe_workers,
        "threads": threads,
        "logical_cpus": logical_cpus,
        "reduced": threads < FULL_THREADS,
        "warn": n < 4 or (mem_gb is not None and mem_gb < 4),
    }


def machine_info() -> dict:
    return pick_parallelism(os.cpu_count(), total_memory_gb())
