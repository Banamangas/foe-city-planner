import gzip
import http.server
import json
import threading

import pytest

from foeopt import catalog_store as cs
from foeopt.catalog_build import canonical_bytes, manifest
from foeopt.loader import CATALOG_PATH, _bundled_catalog


def _bundled():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _release(tmp_path, catalog, built_at="2999-01-01T00:00:00Z"):
    d = tmp_path / "srv"
    d.mkdir(exist_ok=True)
    m = manifest(catalog, "test")
    m["built_at"] = built_at
    (d / "catalog-manifest.json").write_text(json.dumps(m))
    (d / "catalog.json.gz").write_bytes(gzip.compress(canonical_bytes(catalog)))
    return d, m


@pytest.fixture
def server(tmp_path):
    state = {"requests": [], "headers": []}
    root = tmp_path / "srv"
    root.mkdir(exist_ok=True)

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def do_GET(self):
            state["requests"].append(self.path)
            state["headers"].append(dict(self.headers))
            super().do_GET()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_port}/"
    yield state
    srv.shutdown()
    srv.server_close()


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("FOEOPT_CACHE_DIR", str(tmp_path / "cache"))
    _bundled_catalog.cache_clear()
    yield tmp_path / "cache"
    _bundled_catalog.cache_clear()


def _newer(tmp_path):
    cat = _bundled()
    cat["Z_NEW_BUILDING"] = dict(next(iter(cat.values())))
    return cat


def test_newer_release_is_installed(tmp_path, server, cache):
    cat = _newer(tmp_path)
    _release(tmp_path, cat)
    assert cs.check_for_update(server["url"]) == "updated"
    assert (cache / "catalog.json").exists() and (cache / "catalog-manifest.json").exists()
    assert cs.active_catalog_path() == cache / "catalog.json"
    assert "Z_NEW_BUILDING" in _bundled_catalog()
    assert cs.check_for_update(server["url"]) == "current"


def test_same_built_at_is_current_without_downloading_gz(tmp_path, server):
    bm = json.loads((CATALOG_PATH.with_name("catalog-manifest.json")).read_text())
    _release(tmp_path, _bundled(), built_at=bm["built_at"])
    assert cs.check_for_update(server["url"]) == "current"
    assert server["requests"] == ["/catalog-manifest.json"]


def test_sha_mismatch_fails_and_leaves_cache(tmp_path, server, cache):
    d, m = _release(tmp_path, _newer(tmp_path))
    m["sha256"] = "0" * 64
    (d / "catalog-manifest.json").write_text(json.dumps(m))
    assert cs.check_for_update(server["url"]) == "failed"
    assert not cache.exists()
    assert cs.active_catalog_path() == CATALOG_PATH


def test_truncated_gz_fails(tmp_path, server, cache):
    d, _ = _release(tmp_path, _newer(tmp_path))
    gz = d / "catalog.json.gz"
    gz.write_bytes(gz.read_bytes()[:50])
    assert cs.check_for_update(server["url"]) == "failed"
    assert not cache.exists()


def test_sanity_failure_fails(tmp_path, server, cache):
    _release(tmp_path, {"only": {"name": "x"}})
    assert cs.check_for_update(server["url"]) == "failed"
    assert not cache.exists()


def test_server_down_fails_quickly():
    assert cs.check_for_update("http://127.0.0.1:1/", timeout=2) == "failed"


def test_corrupted_cache_falls_back_to_bundled(tmp_path, server, cache):
    _release(tmp_path, _newer(tmp_path))
    assert cs.check_for_update(server["url"]) == "updated"
    (cache / "catalog.json").write_bytes(b"{}")
    assert cs.active_catalog_path() == CATALOG_PATH


def test_older_cache_is_ignored(tmp_path, server, cache):
    _release(tmp_path, _newer(tmp_path), built_at="2000-01-01T00:00:00Z")
    assert cs.check_for_update(server["url"]) == "current"
    assert cs.active_catalog_path() == CATALOG_PATH


def test_only_generic_user_agent(tmp_path, server):
    _release(tmp_path, _newer(tmp_path))
    cs.check_for_update(server["url"])
    assert server["headers"]
    for h in server["headers"]:
        assert h["User-Agent"] == "foe-city-planner"
        assert not {"Cookie", "Authorization", "X-API-Key", "Referer"} & set(h)


def test_no_update_env_disables_background_check(monkeypatch):
    monkeypatch.setenv("FOEOPT_NO_UPDATE", "1")
    assert cs.start_background_check() is None


def test_cache_dir_override(tmp_path):
    assert cs.cache_dir() == tmp_path / "cache"


def test_hanging_server_fails_within_timeout():
    import socket
    import time
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)  # accepts connections at the OS level, never answers
    try:
        t0 = time.time()
        assert cs.check_for_update(f"http://127.0.0.1:{srv.getsockname()[1]}/", timeout=1) == "failed"
        assert time.time() - t0 < 5
    finally:
        srv.close()


def test_oversized_decompressed_payload_fails(tmp_path, server, cache, monkeypatch):
    monkeypatch.setattr(cs, "_MAX_UNZIPPED", 1000)
    _release(tmp_path, _newer(tmp_path))
    assert cs.check_for_update(server["url"]) == "failed"
    assert not cache.exists()


def test_remote_manifest_with_other_schema_fails(tmp_path, server, cache):
    d, m = _release(tmp_path, _newer(tmp_path))
    m["schema"] = 2
    (d / "catalog-manifest.json").write_text(json.dumps(m))
    assert cs.check_for_update(server["url"]) == "failed"
    assert not (cache / "catalog.json").exists()


def test_cached_manifest_with_other_schema_is_ignored(tmp_path, server, cache):
    d, m = _release(tmp_path, _newer(tmp_path))
    assert cs.check_for_update(server["url"]) == "updated"
    assert cs.active_catalog_path() == cache / "catalog.json"
    m2 = json.loads((cache / "catalog-manifest.json").read_text())
    m2["schema"] = 2
    (cache / "catalog-manifest.json").write_text(json.dumps(m2))
    assert cs.active_catalog_path() == CATALOG_PATH
