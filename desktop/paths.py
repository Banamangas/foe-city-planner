"""Where the desktop app keeps its files (one folder per player)."""
from __future__ import annotations

import os
import sys

_APP = "foe-city-planner"


def data_dir() -> str:
    """The per-OS data folder, created if missing. FOEOPT_DATA_DIR wins."""
    override = os.environ.get("FOEOPT_DATA_DIR")
    if override:
        path = override
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
        path = os.path.join(base, _APP)
    elif sys.platform == "darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", _APP)
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
        path = os.path.join(base, _APP)
    os.makedirs(path, exist_ok=True)
    return path
