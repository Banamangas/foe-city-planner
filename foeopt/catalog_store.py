"""Keeps the building list up to date: a plain GET of two public release files.

No city or user data is sent; the only request header is a generic User-Agent.
Any failure leaves the current list untouched.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

from foeopt.catalog_build import sanity

RELEASE_BASE = "https://github.com/Banamangas/foe-city-planner/releases/download/catalog/"
_DATA = Path(__file__).with_name("data")
_MAX_BYTES = 20 * 1024 * 1024
_MAX_UNZIPPED = 50 * 1024 * 1024
_APP = "foe-city-planner"


def cache_dir() -> Path:
    override = os.environ.get("FOEOPT_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / _APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _APP
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / _APP


def _read_manifest(path: Path) -> dict | None:
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
        return m if isinstance(m, dict) and m.get("built_at") and m.get("sha256") else None
    except (OSError, ValueError):
        return None


def _cached_valid() -> tuple[Path, dict] | None:
    """The cached catalog and its manifest, if present and intact."""
    d = cache_dir()
    manifest = _read_manifest(d / "catalog-manifest.json")
    path = d / "catalog.json"
    if manifest is None:
        return None
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
            return None
    except OSError:
        return None
    return path, manifest


def _bundled_built_at() -> str:
    m = _read_manifest(_DATA / "catalog-manifest.json")
    return m["built_at"] if m else ""


def _active() -> tuple[Path, str]:
    cached = _cached_valid()
    if cached and cached[1]["built_at"] > _bundled_built_at():
        return cached[0], cached[1]["built_at"]
    return _DATA / "catalog.json", _bundled_built_at()


def active_catalog_path() -> Path:
    return _active()[0]


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _APP})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError("response too large")
    return data


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def check_for_update(base_url: str = RELEASE_BASE, timeout: float = 10.0) -> str:
    """Returns "updated", "current" or "failed". Never raises."""
    try:
        active_path, active_built = _active()
        remote = json.loads(_get(base_url + "catalog-manifest.json", timeout))
        if not isinstance(remote, dict) or not remote.get("built_at") or not remote.get("sha256"):
            return "failed"
        if remote["built_at"] <= active_built:
            return "current"
        with gzip.GzipFile(fileobj=io.BytesIO(_get(base_url + "catalog.json.gz", timeout))) as gz:
            raw = gz.read(_MAX_UNZIPPED + 1)
        if len(raw) > _MAX_UNZIPPED:
            return "failed"
        if hashlib.sha256(raw).hexdigest() != remote["sha256"]:
            return "failed"
        new = json.loads(raw)
        previous = json.loads(active_path.read_text(encoding="utf-8"))
        if not isinstance(new, dict) or sanity(new, previous):
            return "failed"
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        # catalog first: the manifest is what makes the cache count as valid
        _write_atomic(d / "catalog.json", raw)
        _write_atomic(d / "catalog-manifest.json", json.dumps(remote).encode("utf-8"))
        from foeopt.loader import _bundled_catalog
        _bundled_catalog.cache_clear()
        return "updated"
    except Exception:
        return "failed"


def start_background_check() -> threading.Thread | None:
    if os.environ.get("FOEOPT_NO_UPDATE") == "1":
        return None
    t = threading.Thread(target=check_for_update, name="catalog-update", daemon=True)
    t.start()
    return t
