# Newbie app, plan 2 of 4: building list kept up to date — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New game buildings reach players without a new app release: a daily GitHub job slims the user's API export into the app's building list and publishes it; the app downloads it when newer; a building still unknown is asked of the player instead of failing the load.

**Architecture:** One converter script (`scripts/update_catalog.py`) used both by the GitHub job and to refresh the bundled list. A small app-side store (`foeopt/catalog_store.py`) picks the newer of the bundled and downloaded lists and fetches updates. The loader's single choke point `_bundled_catalog()` reads the active list. Unknown buildings come back as a structured error, and player-supplied definitions ride in the existing `helper_data.CityEntities` mechanism.

**Tech Stack:** Python 3.12 stdlib only (`urllib`, `gzip`, `hashlib`, `json`), Flask, GitHub Actions, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-11-24-newbie-desktop-app-design.md` (section "Building list kept up to date").

## Global Constraints

- The API key is never in the app, never in the repo, never printed: GitHub secret `FOE_API_KEY`, sent only as header `X-API-Key` from the workflow.
- Source: `GET {FOE_API_BASE}/data/download/building_entity_lookup.json` (raw game CityEntities, a JSON list, ~68 MB) and `GET {FOE_API_BASE}/building-names` (id → `{"en","fr"}`); `FOE_API_BASE = https://foe-buildings.duckdns.org`. Not the `/api/v1` endpoints.
- The 68 MB export is never stored on GitHub; only the slim list is published.
- Published as overwritten assets of a release with tag `catalog` (never marked latest): `catalog.json.gz` and `catalog-manifest.json`. Download URL base: `https://github.com/Banamangas/foe-city-planner/releases/download/catalog/`.
- Merge rule: new data wins; entries only in the previous list are kept; an empty new `type` keeps the previous type.
- The app's only network use is a plain GET of those two public files: no city data, no user data, generic User-Agent `foe-city-planner`. Offline or any failure → silently keep the current list.
- Same slim entry format as today's `foeopt/data/catalog.json` (`scripts/build_catalog.py::trim`), plus optional `names: {"en", "fr"}`; `name` stays (French when known, else English).
- City/player files are never printed or committed.

## Review Focus

1. A downloaded file that is truncated, not gzip, or whose sha256 doesn't match the manifest: must be rejected and the current list kept (Task 3 test).
2. A new export that is missing buildings the previous list had (API hiccup, partial file): the job must refuse to publish rather than shrink the list (Task 1 test: sanity check fails when a previous id disappears and is not kept).
3. No network / DNS failure / timeout at app startup: the app starts normally and fast (update check in a background thread with a 10 s timeout) (Task 3 test).
4. A city with several unknown buildings: one load response lists them all, and reloading with the player's answers succeeds (Task 4 test).
5. The workflow running on a day with no change: it must stop after the cheap `/status` call without downloading 68 MB (Task 5: manifest `source_version` comparison, checked by the dry-run step).

---

### Task 1: Converter script

**Files:**
- Create: `scripts/update_catalog.py`
- Modify: `scripts/build_catalog.py` (export `trim` unchanged; no behavior change)
- Test: `tests/test_update_catalog.py`

**Interfaces:**
- Produces: `build(lookup: list[dict], previous: dict, names: dict | None = None) -> dict` — slim each lookup entry with `build_catalog.trim`, merge over `previous` (rules in Global Constraints), attach `names` (`{"en": ..., "fr": ...}` from `names[id]`, else `{"fr": previous name}` + `{"en": lookup name}` when they differ), set `name` = fr if present else en.
- Produces: `sanity(new: dict, previous: dict) -> list[str]` — problems: a previous id missing from new; a building with no positive size (via `foeopt.catalog.Catalog.size`); fewer entries than previous. Empty list = OK.
- Produces: `manifest(catalog: dict, source_version: str | None) -> dict` = `{"schema": 1, "built_at": <UTC ISO seconds>, "source_version", "count", "sha256": <hex of the canonical JSON bytes>}`; canonical JSON = `json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()`.
- Produces: CLI `python scripts/update_catalog.py --lookup L.json [--names N.json] --previous P.json[.gz] --out DIR [--source-version V]` writing `DIR/catalog.json` (canonical), `DIR/catalog.json.gz`, `DIR/catalog-manifest.json`; exits 1 and writes nothing if `sanity` reports problems.

- [ ] **Step 1: Failing tests** in `tests/test_update_catalog.py` with tiny synthetic entries in the raw format (copy the shape of one raw CityEntity: `id`, `name`, `type`, `width`, `length`, `requirements.street_connection_level`, and one components-style entry with `components.AllAge.placement.size` + `streetConnectionRequirement`): new size wins over previous; a previous-only id is kept; empty new type keeps previous type; names from `names` win, else fr from previous + en from lookup; `name` is fr; `sanity` flags a dropped id and a zero size; `manifest` sha256 equals sha256 of the canonical bytes; CLI writes the three files and the gz decompresses to the canonical JSON; CLI exit 1 on a sanity failure leaves `--out` empty.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_update_catalog.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: building-list converter (slim, merge, names, sanity, manifest)`.

### Task 2: Refresh the bundled list and names by language

**Files:**
- Modify: `foeopt/data/catalog.json` (regenerated), Create: `foeopt/data/catalog-manifest.json`
- Modify: `foeopt/catalog.py` (`name`)
- Test: `tests/test_catalog.py`, existing `tests/test_loader_v3.py`, `tests/test_editing.py`

**Interfaces:**
- Consumes: Task 1 CLI.
- Produces: `Catalog.name(cityentity_id: str, lang: str | None = None) -> str` — `names[lang]` when present, else `name`, else the id.

- [ ] **Step 1: Failing test** in `tests/test_catalog.py`: an entry with `names {"en": "Holo Park", "fr": "Parc holo"}` and `name "Parc holo"` → `name(cid) == "Parc holo"`, `name(cid, "en") == "Holo Park"`, `name(cid, "de") == "Parc holo"`.
- [ ] **Step 2: Implement** `Catalog.name`; run the test — PASS.
- [ ] **Step 3: Regenerate:** `.venv/bin/python scripts/update_catalog.py --lookup /home/born/Downloads/cities/building_entity_lookup.json --previous foeopt/data/catalog.json --out <scratch dir>` (no `--names`: the key isn't available locally). Expected from the 2026-11-24 check: about 2,937 entries (2,894 + 43 previous-only), sanity OK. Copy `catalog.json` and `catalog-manifest.json` into `foeopt/data/`. Never print the lookup file's contents.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` — all pass (the loader/edit/export tests read the bundled list).
- [ ] **Step 5: Commit** `feat: refresh the bundled building list (+50 buildings, English names)`.

### Task 3: App-side update

**Files:**
- Create: `foeopt/catalog_store.py`
- Modify: `foeopt/loader.py` (`_bundled_catalog`), `webapp/app.py` (`create_app` starts the check)
- Test: `tests/test_catalog_store.py`

**Interfaces:**
- Produces: `cache_dir() -> Path` — Windows `%LOCALAPPDATA%\foe-city-planner`, macOS `~/Library/Caches/foe-city-planner`, else `$XDG_CACHE_HOME/foe-city-planner` or `~/.cache/foe-city-planner`; overridable by env `FOEOPT_CACHE_DIR`.
- Produces: `active_catalog_path() -> Path` — the cached `catalog.json` when its manifest's `built_at` is later than the bundled manifest's and its sha256 verifies; else `foeopt/data/catalog.json`.
- Produces: `check_for_update(base_url: str = RELEASE_BASE, timeout: float = 10.0) -> str` returning `"updated" | "current" | "failed"`; downloads `catalog-manifest.json`, returns `"current"` if not newer than the active one, else downloads `catalog.json.gz`, verifies gzip + sha256 + JSON + `sanity(new, active)` from Task 1, writes atomically (temp file + `os.replace`) into `cache_dir()`, calls `foeopt.loader._bundled_catalog.cache_clear()`. Never raises. Request header only `User-Agent: foe-city-planner`.
- Produces: `start_background_check() -> threading.Thread | None` — daemon thread; no-op (None) when env `FOEOPT_NO_UPDATE=1`. `create_app` calls it unless `app.testing`/`FOEOPT_NO_UPDATE`.
- `_bundled_catalog()` reads `active_catalog_path()`.

- [ ] **Step 1: Failing tests** in `tests/test_catalog_store.py`, serving files from a temp dir with `http.server` on `127.0.0.1` (no internet): newer valid release → `"updated"`, cache files present, `active_catalog_path()` is the cache, `_bundled_catalog()` returns the new content; same `built_at` → `"current"`, no download of the gz (count requests); sha mismatch → `"failed"`, cache untouched; truncated gz → `"failed"`; server down / timeout → `"failed"` quickly; `FOEOPT_NO_UPDATE=1` → `start_background_check()` is None; the request carries only the generic User-Agent (inspect the handler's headers). Use `FOEOPT_CACHE_DIR` = tmp dir; set `FOEOPT_NO_UPDATE=1` for the whole suite in `tests/conftest.py` so no test hits GitHub.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_catalog_store.py -q` — FAIL.
- [ ] **Step 3: Implement** the module, the loader change and the `create_app` hook.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` — all pass.
- [ ] **Step 5: Commit** `feat: download newer building lists in the background`.

### Task 4: Unknown buildings are asked, not fatal

**Files:**
- Modify: `foeopt/loader.py` (`_build_v3`), `webapp/app.py` (`api_load`, `api_load_raw`, `_parse_and_cache`)
- Test: `tests/test_loader_v3.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `class UnknownBuildings(ValueError)` in `foeopt/loader.py` with `.ids: list[str]` (sorted), raised by `_build_v3` instead of the plain ValueError (message unchanged).
- Produces: `/api/load` and `/api/load/raw` answer HTTP 422 `{"error": ..., "unknown_buildings": [{"cityentity_id": cid, "count": n}]}` on `UnknownBuildings`.
- Produces: both endpoints accept `custom_buildings` (JSON body key for `/api/load`; a form field holding JSON for `/api/load/raw`): `{cid: {"width": int, "length": int, "road": 0 | 1 | 2}}`, validated (1 ≤ width, length ≤ 20; road in 0/1/2; cid must be one of the unknown ones or already present in the city), converted to CityEntities entries `{"id": cid, "name": cid, "type": "custom", "width", "length", "requirements": {"street_connection_level": road}}` (omit requirements when road is 0) and merged into the payload's `helper_data.CityEntities`, so cached reloads, optimize and export keep resolving them.

- [ ] **Step 1: Failing tests:** loader — a v3 dict (build it like the existing tests in `tests/test_loader_v3.py`) with two made-up cityentity ids raises `UnknownBuildings` with both ids; API — posting it returns 422 with both ids and their counts; reposting with `custom_buildings` for both returns 200 and the buildings appear in `buildings` with the given sizes; a bad size (0 or 21) or road 3 → 400.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_loader_v3.py tests/test_api.py -q` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS, then the full suite.
- [ ] **Step 5: Commit** `feat: ask the player for buildings the list doesn't know`.

### Task 5: Daily GitHub job

**Files:**
- Create: `.github/workflows/catalog.yml`, `docs/building-list.md`
- Test: manual dry run (below); no unit test.

**Interfaces:**
- Consumes: Task 1 CLI; secret `FOE_API_KEY`; release tag `catalog`.

Workflow: `on: schedule: cron "17 4 * * *"` + `workflow_dispatch` (input `force: boolean`, default false); `permissions: contents: write`; one job on `ubuntu-latest`, `concurrency: catalog`. Steps (bash, `set -euo pipefail`, never `set -x`, the key only via `env:` and `-H "X-API-Key: $FOE_API_KEY"`):
1. checkout; setup-python 3.12.
2. `status=$(curl -fsS -H ... "$FOE_API_BASE/status")`; `src=$(jq -r '.last_update // .data_updated_at // empty' <<<"$status")`.
3. `gh release download catalog -p catalog-manifest.json -p catalog.json.gz -D prev || true` (first run: none). If `prev/catalog-manifest.json` has `source_version == $src`, `src` is non-empty and `force` is false → print "no change" and stop successfully.
4. `curl -fsS -H ... -o lookup.json "$FOE_API_BASE/data/download/building_entity_lookup.json"`; `curl -fsS -H ... -o names.json "$FOE_API_BASE/building-names"` (names optional: on failure continue without `--names`).
5. previous = `prev/catalog.json.gz` if present else `foeopt/data/catalog.json`; run the converter with `--source-version "$src"` into `dist/`.
6. `gh release view catalog || gh release create catalog --title "Building list" --notes "Updated daily from the game data. Used by the app; not a download for players." --latest=false`; `gh release upload catalog dist/catalog.json.gz dist/catalog-manifest.json --clobber`.
`GH_TOKEN: ${{ github.token }}` for `gh`.

`docs/building-list.md` (English, short): what the job does, the two one-time setup steps for the owner (create a dedicated read-only key in the API; add it as repository secret `FOE_API_KEY` under Settings → Secrets and variables → Actions), how to run it by hand (Actions → "Building list" → Run workflow), and how to check it worked (release "catalog" assets updated).

- [ ] **Step 1: Write** the workflow and the doc.
- [ ] **Step 2: Check:** parse the YAML (`.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/catalog.yml'))"` if PyYAML is installed; never install or download tools for this), grep the file to confirm `FOE_API_KEY` appears only in `env:`/header positions and there is no `set -x`; then run step 5's exact converter command locally against `/home/born/Downloads/cities/building_entity_lookup.json` into a scratch dir (proves the arguments).
- [ ] **Step 3: Commit** `feat: daily GitHub job that publishes the building list`.

### Task 6: Verification

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` — all pass.
- [ ] **Step 2:** Start the webapp without `FOEOPT_NO_UPDATE` and with `FOEOPT_CACHE_DIR` set to a scratch dir: it starts at once; until the owner has run the job, the release doesn't exist, so the check logs nothing and returns `"failed"` silently (verify with a one-off `python -c "from foeopt.catalog_store import check_for_update; print(check_for_update())"` → `failed`, no traceback).
- [ ] **Step 3:** Review section in `tasks/todo.md` including the owner's next steps (create key, add secret, Run workflow once, then `check_for_update()` → `updated`); commit `docs: plan N2 review`.
