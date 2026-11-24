# Newbie app, plan 4 of 4: desktop app and releases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One download per system (Windows first, then macOS and Linux) that opens the wizard in its own window, keeps only the last city and the last result, asks before closing during a run, and gets built and checked automatically on GitHub.

**Architecture:**
- A small `desktop/` package is the app's entry point. It starts the existing Flask app on a free `127.0.0.1` port in a background thread (desktop mode: data in the per-OS app-data folder, one city kept) and opens a pywebview window on it, falling back to the default browser.
- The wizard saves its state to the server after every change (`/api/session`) and offers "Continue where you left off" on the next start.
- PyInstaller bundles Python, OR-Tools, the built frontend and the building list.
- A GitHub Actions workflow builds all three systems, runs a headless self-test of each build, and on a version tag prepares a draft release.

**Tech Stack:** Python 3.12 (build), Flask/werkzeug, pywebview 5 (Windows/macOS), PyInstaller 6, GitHub Actions; React/TS for the wizard changes.

**Spec:** `docs/superpowers/specs/2026-11-24-newbie-desktop-app-design.md` (goals 1, 4, 5, 7; constraints on multiprocessing; decisions: PyInstaller, own window with browser fallback, GitHub Releases, ~100–150 MB, keep last result, closing mid-run asks first).

## Global Constraints

- **One download per system, nothing else to install.** Artifact names:
  - `FoE-City-Planner-Windows.exe` (one-file);
  - `FoE-City-Planner-macOS.zip` (contains `FoE City Planner.app`, Apple Silicon);
  - `FoE-City-Planner-Linux` (one-file, runs in the default browser).
- **The player never sees a terminal window, a Python error or technical words:** Windows and macOS builds are windowed (no console). Errors go to a log file, `<data dir>/app.log`, rotated at 1 MB with 1 backup.
- **The server listens on `127.0.0.1` only**, on a free port chosen at start. The city never leaves the computer; the only network use stays the building-list download.
- **Light on storage.** In desktop mode the app keeps only the last city (with its edits) and one last-session file, overwritten each time (≤ 5 MB, refused above). Nothing else accumulates. Data dir:
  - Windows `%LOCALAPPDATA%\foe-city-planner`;
  - macOS `~/Library/Application Support/foe-city-planner`;
  - Linux `$XDG_DATA_HOME/foe-city-planner` (default `~/.local/share/foe-city-planner`);
  - override with env `FOEOPT_DATA_DIR`.
- **Multiprocessing works when frozen:** the entry point calls `multiprocessing.freeze_support()` first and everything runs under `if __name__ == "__main__":`. Python 3.14 uses forkserver and other platforms use spawn; both re-import the main module, and a missing guard makes every optimizer run fail.
- **Unsigned builds** (no code signing). The download page explains "Windows protected your PC" → More info → Run anyway, and the macOS block → right-click → Open (or System Settings → Privacy & Security → Open anyway).
- **Releases are drafts:** the workflow never publishes a release by itself; the owner reviews and publishes it.
- **The developer setup keeps working unchanged:** running the webapp as today (no data dir) keeps today's behavior: `webapp/cities.db`, all cities kept, no session endpoints.
- **Build only the needed files:** the repo root holds player city files (gitignored); the PyInstaller spec lists exactly which data files to bundle and never globs the repo root.
- **Bundled data:** `foeopt/data/catalog.json` and `foeopt/data/catalog-manifest.json` must both be bundled (without the manifest a stale downloaded list could win over a newer bundled one), plus `webapp/dist/`.

## Review Focus

1. **The app is started twice** (double-click impatience): each copy must start on its own free port, without "port in use" crashes. Task 3 tests `free_port()` returning distinct usable ports.
2. **The last-session file is from an older app version, corrupt, or names a city that's no longer stored:** the wizard ignores it and starts fresh, no crash. Task 2 tests `parseSession` for a wrong version, invalid data, and a city mismatch; Task 1 tests the server refusing oversized or invalid bodies.
3. **The window is closed during a run:** the player is asked first. When they confirm, the run is stopped and the app exits within a few seconds, leaving no stray worker processes. Task 3 tests `confirm_needed` and the shutdown helper.
4. **No native window available** (Linux, or a Windows machine missing WebView2): the app opens the default browser instead, and quits by itself after the page has been closed for a while (no ping for 120 s and no run going). Task 3 tests `should_exit`.
5. **A frozen build where workers fail to start or data files are missing:** caught by the headless `--self-test` in Task 4 (locally) and on every system in CI (Task 5). A real 20-second optimize plus an export must succeed.

---

### Task 1: Desktop mode on the server (data dir, one city kept, last session, ping)

**Files:**
- Create: `desktop/__init__.py` (empty), `desktop/paths.py`
- Modify: `webapp/app.py` (`create_app`), `webapp/cache.py` (`keep_only_city`), `webapp/runner.py` (`JobManager.stop_all`, `JobManager.any_running`)
- Test: `tests/test_desktop_paths.py`, `tests/test_api_desktop.py`

**Interfaces:**
- Produces:
  - `desktop.paths.data_dir() -> str`: the per-OS folder from Global Constraints. It is created if missing. `FOEOPT_DATA_DIR` wins; it branches on `sys.platform` (`win32` / `darwin` / other).
  - `create_app(db_path: str | None = None, *, data_dir: str | None = None) -> Flask`. With `data_dir`:
    - db = `<data_dir>/cities.db`;
    - after each successful city load, `cache.keep_only_city(city_id)` deletes every other city and every layout of other cities;
    - `GET /api/session` → 200 with the saved JSON, or 404 with exactly the body `{"error": "no session"}` when there is none (Task 2 uses that body to tell the desktop app from the developer setup, whose 404 has a different body);
    - `PUT /api/session` with a JSON object body ≤ 5 MB → 204, written atomically to `<data_dir>/last-session.json`; a non-object or over-limit body → 400;
    - `DELETE /api/session` → 204;
    - `POST /api/ping` → 204 and records `time.monotonic()` in `app.config["LAST_PING"]`.
    Without `data_dir`, all four routes return 404 and nothing else changes.
  - `app.extensions["foeopt_jobs"]` = the app's `JobManager` (the shell stops jobs on exit).
  - `JobManager.stop_all() -> None` sets the stop event of every job that isn't done; `JobManager.any_running() -> bool`.

- [ ] **Step 1: Write the failing tests**
  - `test_desktop_paths.py`:
    - `FOEOPT_DATA_DIR=<tmp>` → returns it and the folder exists;
    - with the env var unset and `sys.platform` monkeypatched:
      - `"win32"` with `LOCALAPPDATA=<tmp>` → `<tmp>/foe-city-planner`;
      - `"darwin"` with `HOME=<tmp>` → `<tmp>/Library/Application Support/foe-city-planner`;
      - `"linux"` with `XDG_DATA_HOME=<tmp>` → `<tmp>/foe-city-planner`, and without it → `<HOME>/.local/share/foe-city-planner`.
  - `test_api_desktop.py` (with `FOEOPT_NO_UPDATE=1`; synthetic v3 payloads from the existing test helpers):
    - `test_desktop_keeps_only_last_city`: load city A, then city B → `GET /api/cities` lists only B; `<data_dir>/cities.db` exists.
    - `test_session_roundtrip`: GET → 404; PUT `{"version": 1, "step": 3}` → 204; GET → the same object; DELETE → 204; GET → 404.
    - `test_session_rejects_bad_bodies`: PUT a list → 400; PUT an object whose JSON is over 5 MB → 400, and the stored session is unchanged.
    - `test_ping_records_time`: POST → 204, and `app.config["LAST_PING"]` is a float.
    - `test_dev_mode_unchanged`: `create_app(db_path=tmp)` → `/api/session` and `/api/ping` return 404; loading two cities keeps both.
    - `test_stop_all`: with a fake job state in a `JobManager`, `stop_all()` sets its stop event, and `any_running()` is True before the job finishes and False after.
- [ ] **Step 2: Run and fail:** `.venv/bin/python -m pytest tests/test_desktop_paths.py tests/test_api_desktop.py -q`
- [ ] **Step 3: Implement.** Write the session atomically (temp file + `os.replace`). Read the size from `request.content_length`, and also check `len(request.get_data())`.
- [ ] **Step 4: Pass, then the full suite:** `.venv/bin/python -m pytest -q`
- [ ] **Step 5: Commit** `feat: desktop mode on the server (data dir, one city kept, last session, ping)`

---

### Task 2: Wizard continues where you left off, and tells the shell when a run is going

**Files:**
- Create: `frontend/src/wizard/session.ts`, `frontend/src/wizard/session.test.ts`, `frontend/src/wizard/desktop.ts`, `frontend/src/wizard/desktop.test.ts`
- Modify: `frontend/src/wizard/wizardStore.ts`, `frontend/src/wizard/steps/LoadStep.tsx`, `frontend/src/wizard/steps/OptimizeStep.tsx`, `frontend/src/api.ts` (`apiSessionGet/Put/Delete`, `apiPing`), both translation files

**Interfaces:**
- Consumes: Task 1's routes (404 in the developer setup means "not the desktop app": the wizard then skips all of this silently).
- Produces (`session.ts`):
  - `SESSION_VERSION = 1`.
  - `type Session = { version: 1; cityId: string; fileName: string; step: 1|2|3|4|5; edits: Edits; keepUnconnected: number[] | null; layouts: LayoutEntry[]; selectedId: number | "player" | null; runKey: string | null }`.
  - `toSession(): Session | null` reads both stores; it returns null when no city is loaded.
  - `parseSession(raw: unknown, storedCityIds: string[]): Session | null` returns null for a wrong `version`, a wrong shape, or a `cityId` not in `storedCityIds`.
  - `restoreSession(s: Session, lang: string): Promise<boolean>`:
    1. reloads the stored city through `GET /api/cities/<id>` and then `apiLoadResult(payload, { fileName, lang })`;
    2. then sets the edits, `keepUnconnected`, the layouts, the selection, and `run = { state: "done", key: runKey, … }` when there are layouts;
    3. then goes to `step`, clamped to 3 when there are no layouts and the step is above 3.
- Produces (`desktop.ts`):
  - `setRunningFlag(running: boolean, title: string, message: string): void`:
    - calls `window.pywebview?.api?.set_running(running, title, message)` when present;
    - and always adds a `beforeunload` listener (preventDefault + `returnValue = ""`) while running, removing it when not.
  - `startPinging(): () => void`: POSTs `/api/ping` every 30 s, and once right away; returns a stop function.

- [ ] **Step 1: Write the failing tests:**
  - `session.test.ts`:
    - `parseSession` → null for `{version: 2, ...}`, for `"junk"`, and for a valid object whose `cityId` isn't in the list; otherwise it returns the session.
    - `toSession` → null with no city loaded; with a city, edits and two layouts, it round-trips through `parseSession(JSON.parse(JSON.stringify(...)), [cityId])` unchanged.
    - `restoreSession` with the API mocked:
      - it lands on the saved step 4 with the saved selection;
      - with `layouts: []` and step 4, it lands on step 3;
      - the restored run key makes `resultsAreCurrent()` true.
  - `desktop.test.ts` (jsdom):
    - with a fake `window.pywebview.api.set_running` spy, `setRunningFlag(true, "T", "M")` calls it with `(true, "T", "M")`;
    - while running, a dispatched `beforeunload` event is `defaultPrevented`; after `setRunningFlag(false, ...)` it isn't;
    - `startPinging` with fake timers calls fetch at once and again after 30 s, and stops after the returned function is called.
- [ ] **Step 2: Run and fail:** `cd frontend && npx vitest run src/wizard/session.test.ts src/wizard/desktop.test.ts`
- [ ] **Step 3: Implement.**
  - **On wizard start:**
    1. `apiSessionGet()`. If it returns a session and `GET /api/cities` lists its city, step 1 shows a card: "Continue where you left off" with the file name, plus buttons "Continue" (calls `restoreSession`) and "Start with another city" (calls `apiSessionDelete`, then the normal drop zone).
    2. Start pinging only when the session route exists, i.e. GET answered 200 or 404 with a JSON body, not a network error. In the developer setup the routes return 404 too, so tell them apart: treat a 404 whose body is `{"error": "no session"}` as desktop mode, and any other 404 as the developer setup. Task 1 must return exactly that body; note this cross-task contract in your report.
  - **Saving:** subscribe to both stores and save `toSession()` with `apiSessionPut`, debounced 1 s, but only in desktop mode and only when the session is non-null.
  - **OptimizeStep:** calls `setRunningFlag(running, t("close.title"), t("close.message"))` whenever `running` changes, and `false` on unmount. English copy: title "A search is running"; message "Closing now stops the search and loses what it found since the last saved step. Close anyway?". Write natural French.
- [ ] **Step 4: Pass:** `cd frontend && npx vitest run && npm run build`
- [ ] **Step 5: Commit** `feat: wizard continues where you left off and flags a running search`

---

### Task 3: Desktop shell (entry point, window or browser, close prompt, idle exit, self-test)

**Files:**
- Create: `desktop/main.py`, `desktop/shell.py`, `desktop/selftest.py`, `desktop/selftest_city.json` (synthetic, generated from the test fixtures), `tests/test_desktop_shell.py`
- Modify: `pyproject.toml` (optional dependency group `desktop = ["pywebview>=5"]`; build tools stay out of runtime deps)

**Interfaces:**
- Consumes: Task 1's `create_app(data_dir=...)`, `app.extensions["foeopt_jobs"]`, `app.config["LAST_PING"]`, `desktop.paths.data_dir()`.
- Produces (`shell.py`):
  - `free_port() -> int`: bind `("127.0.0.1", 0)`, read the port, close.
  - `start_server(app, port: int) -> threading.Thread`: `werkzeug.serving.make_server("127.0.0.1", port, app, threaded=True)`, `serve_forever` on a daemon thread. It returns once the port accepts connections (poll for up to 10 s).
  - `confirm_needed(running: bool) -> bool` (= running).
  - `should_exit(last_ping: float | None, now: float, job_running: bool, timeout: float = 120.0) -> bool`: True only when there is no run and `now - (last_ping or start_time)` exceeds `timeout`. The caller passes the start time as `last_ping` until the first ping.
  - `shutdown(app, wait_s: float = 5.0) -> None`: `stop_all()`, then wait until `any_running()` is False or `wait_s` passes.
  - `class ShellApi` (exposed to the page as `window.pywebview.api`): `set_running(running, title, message)` stores the three values.
  - `run_window(url: str, api: ShellApi, title: str) -> bool`:
    - imports `webview`, creates the window (1280×860, min 900×640) and wires `events.closing`. When `api.running` is set, the handler shows `window.create_confirmation_dialog(api.title, api.message)` and returns False if declined.
    - Then it runs `webview.start()` and returns True after the window closes.
    - It returns False when pywebview is missing or can't start a GUI (any exception before the window shows).
  - `run_browser(url: str, app) -> None`: `webbrowser.open(url)`, then polls `should_exit` every 5 s.
- Produces (`main.py`): `main(argv: list[str] | None = None) -> int`.
  1. `multiprocessing.freeze_support()` first.
  2. Logging to `<data dir>/app.log` (`RotatingFileHandler`, 1 MB, 1 backup).
  3. Flags: `--self-test` (run `selftest.run()` and return its code), `--browser` (skip the window), `--version`.
  4. Otherwise: `create_app(data_dir=data_dir())` → `free_port` → `start_server` → `run_window` (or `run_browser` if that returns False or `--browser` was given) → `shutdown(app)` → return 0.
  The module ends with `if __name__ == "__main__": sys.exit(main())`. The window title is "FoE City Planner".
- Produces (`selftest.py`): `run(timeout_s: float = 240.0) -> int`.
  1. A temp data dir; `create_app(data_dir=tmp)`; a free port and `start_server` (no window).
  2. Over HTTP: load `selftest_city.json` (`?lang=en`) → `POST /api/optimize` with `presets.best` and `time_box: 20` → read the stream until `done` → `POST /api/export/v3` with the best layout.
  3. Prints one line `SELFTEST OK roads=<before>-><best> layouts=<n>` and returns 0. It returns 1, printing `SELFTEST FAIL <reason>`, on any failure, including no layout found.
  4. Choose (and commit) a synthetic fixture city that reliably yields at least one layout in 20 s on a CI runner. Build it from the test helpers in `tests/` (e.g. `tests/test_export_v3.py::_v3`), never from a player file.

- [ ] **Step 1: Write the failing tests** (`tests/test_desktop_shell.py`):
  - `free_port` twice → two ints in 1024–65535, each bindable right after.
  - `should_exit`:
    - `(None→start=0, now=121, job_running=False)` → True;
    - `(100, 121, False)` → False;
    - `(0, 500, True)` → False.
  - `confirm_needed(True) is True`, `confirm_needed(False) is False`.
  - `shutdown` with a `create_app(data_dir=tmp)` app whose `JobManager` has a fake running job that finishes when stopped → returns in under 1 s and stop was called.
  - `start_server` + `GET /api/options` over HTTP → 200, all on `127.0.0.1`.
  - `main(["--version"])` → 0.
  - `selftest.run()` (mark it `slow`, but run it once in this task) → 0. This exercises real worker processes under the main guard.
- [ ] **Step 2: Run and fail:** `.venv/bin/python -m pytest tests/test_desktop_shell.py -q`
- [ ] **Step 3: Implement.** Check pywebview's API against the version you install (`pip install "pywebview>=5"` into `.venv`; on this Linux box the window won't open without GTK/Qt, which is expected, since the browser fallback is the Linux path).
- [ ] **Step 4: Pass:** the focused tests, then `.venv/bin/python -m pytest -q`. Also run `.venv/bin/python -m desktop.main --self-test` and get `SELFTEST OK ...`.
- [ ] **Step 5: Commit** `feat: desktop shell with window or browser, close prompt, idle exit and self-test`

---

### Task 4: Packaging with PyInstaller (local Linux build passes the self-test)

**Files:**
- Create: `desktop/foe-city-planner.spec`, `desktop/build.py` (builds the frontend, runs PyInstaller with the spec, prints the artifact path and size), `desktop/README.md` (how to build locally)
- Modify: `.gitignore` (`build/`, `dist-desktop/`)

**Interfaces:**
- Consumes: Task 3's `desktop/main.py` as the entry script.
- Produces:
  - `python desktop/build.py` → `dist-desktop/FoE-City-Planner-Linux` on Linux, `dist-desktop/FoE-City-Planner-Windows.exe` on Windows, and `dist-desktop/FoE City Planner.app` on macOS (CI zips it).
  - The spec's `datas` list exactly: `webapp/dist` → `webapp/dist`, `foeopt/data/catalog.json` → `foeopt/data`, `foeopt/data/catalog-manifest.json` → `foeopt/data`, `desktop/selftest_city.json` → `desktop`.
  - `collect_all("ortools")`; hidden imports for pywebview's platform backend on Windows/macOS; `console=False` on Windows/macOS and `console=True` on Linux (it's launched from a file manager there anyway, and stdout helps).
  - One-file mode on Windows and Linux; a `.app` bundle on macOS.

- [ ] **Step 1: Write a failing check.** `tests/test_desktop_spec.py` parses the spec text: the four `datas` sources above are present, no source is the repo root or a glob over `*.json` at the root, and `catalog-manifest.json` is included.
- [ ] **Step 2: Run and fail**
- [ ] **Step 3: Implement the spec and `build.py`.**
  - Code that reads bundled files must work frozen. Check how `webapp/app.py` (`_DIST`) and `foeopt/loader.py` / `foeopt/catalog_store.py` locate their data. With the `datas` mapping above, the `__file__`-relative paths resolve inside the bundle; verify, don't assume. Fix with a small `_resource_dir()` helper only if needed.
  - Build with Python 3.12 if available (`uv python find 3.12` / `uv run --python 3.12 ...`), otherwise with the venv's Python, and say which in the report.
- [ ] **Step 4: Build locally and self-test the binary:**
  1. `python desktop/build.py`;
  2. `./dist-desktop/FoE-City-Planner-Linux --self-test` → `SELFTEST OK ...`;
  3. `./dist-desktop/FoE-City-Planner-Linux --version` → 0.
  Report the artifact size in MB.
- [ ] **Step 5: Commit** `feat: PyInstaller packaging for the desktop app`

---

### Task 5: GitHub workflow builds all systems, self-tests them, drafts a release; download page

**Files:**
- Create: `.github/workflows/desktop.yml`, `docs/download.md`
- Modify: `README.md` (a short "Download the app" section linking to the Releases page and `docs/download.md`)

**Interfaces:**
- Consumes: Task 4's `desktop/build.py`, the artifact names and `--self-test`.
- Produces:
  - **Triggers:** `workflow_dispatch` (build and self-test, upload artifacts only) and `push: tags: ["v*"]` (also create a draft release named after the tag, with the three files attached).
  - **Matrix:** `windows-latest`, `macos-latest` (Apple Silicon), `ubuntu-latest`.
  - **Steps per OS:**
    1. checkout;
    2. setup-python 3.12;
    3. setup-node 20, then `npm ci` in `frontend/`;
    4. `pip install . pyinstaller "pywebview>=5"` (skip pywebview on Linux);
    5. `python desktop/build.py`;
    6. the self-test: `FOEOPT_NO_UPDATE=1 <artifact> --self-test` (on macOS, run the binary inside the `.app`);
    7. on macOS, `ditto -c -k --keepParent "FoE City Planner.app" FoE-City-Planner-macOS.zip`;
    8. upload the artifact.
  - **Release job:** needs all three builds and only runs on tags. It downloads the artifacts, then runs `gh release create "$TAG" --draft --title "FoE City Planner $TAG" --notes-file docs/download.md <files>`.
  - **Permissions:** `contents: write` only on the release job; the build jobs get `contents: read`.
  - **`docs/download.md`** (plain words, English): which file to pick, then three short walkthroughs:
    - **Windows:** "Windows protected your PC" → More info → Run anyway;
    - **macOS:** unzip → right-click the app → Open → Open; or System Settings → Privacy & Security → Open anyway;
    - **Linux:** make the file executable (right-click → Properties → Allow executing, or `chmod +x`) and double-click.
  - Picture placeholders as `![...](download/<os>-<n>.png)`, plus a line telling the owner which screenshots to add (also appended to `tasks/todo.md` in Task 6).

- [ ] **Step 1:** Write the workflow and the doc.
- [ ] **Step 2:** Validate the workflow YAML (`/usr/bin/python3 -c "import yaml; yaml.safe_load(open('.github/workflows/desktop.yml'))"`). Check that every job's permissions are minimal and that no secret is used. Check the artifact names match Global Constraints.
- [ ] **Step 3:** Run the Linux job's steps locally where possible (`npm ci`, `python desktop/build.py`, the self-test) and report.
- [ ] **Step 4: Commit** `feat: GitHub workflow that builds, self-tests and drafts desktop releases; download page`

---

### Task 6: Verification and review notes

**Files:**
- Modify: `tasks/todo.md` (append "Review (plan N4)" and the owner's to-dos)

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` and `cd frontend && npx vitest run && npm run build` → all pass.
- [ ] **Step 2:** Build the Linux artifact again from a clean tree (`git stash -u` is not allowed: work from a fresh `git worktree` of the branch in the scratchpad) and run `--self-test` → OK. Report the size.
- [ ] **Step 3:** Append "Review (plan N4)" to `tasks/todo.md`:
  - what was built and the test totals;
  - the Linux artifact size;
  - what CI will do;
  - the owner's next steps:
    1. push the branch or main;
    2. Actions → "Desktop app" → Run workflow, and check all three self-tests pass;
    3. download the Windows build and try it on a real Windows PC (the SmartScreen walkthrough);
    4. add the screenshots for `docs/download.md`;
    5. when happy, tag `v0.1.0` and push the tag, then review and publish the draft release.
  Commit `docs: plan N4 review`.
