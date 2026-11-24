# Desktop app build

The desktop app is the webapp plus a small shell (`desktop/main.py`), frozen
with PyInstaller into one download per system:

| System  | Output in `dist-desktop/`        |
|---------|----------------------------------|
| Linux   | `FoE-City-Planner-Linux` (one file, opens the default browser) |
| Windows | `FoE-City-Planner-Windows.exe` (one file, own window) |
| macOS   | `FoE City Planner.app` (CI zips it as `FoE-City-Planner-macOS.zip`) |

## Build locally

Needs Node.js (for the frontend) and a build Python (3.12 recommended) with the
app's dependencies plus PyInstaller. Keep PyInstaller out of the project's own
dependencies: use a throwaway venv under `build/` (gitignored).

```sh
cd frontend && npm install && cd ..
uv venv --python 3.12 build/venv312
uv pip install --python build/venv312/bin/python pyinstaller flask ortools
# Windows / macOS also need the window:
#   uv pip install --python <build python> pywebview
build/venv312/bin/python desktop/build.py      # --skip-frontend reuses webapp/dist
```

`build.py` runs `npm run build` (→ `webapp/dist`), then PyInstaller with
`desktop/foe-city-planner.spec`, and prints the artifact path and size.

## Check the build

```sh
FOEOPT_NO_UPDATE=1 ./dist-desktop/FoE-City-Planner-Linux --self-test   # SELFTEST OK roads=...
./dist-desktop/FoE-City-Planner-Linux --version
```

The self-test runs a real 20 s search on a synthetic city over HTTP, without
opening a window or browser.

## Bundled files

The spec's `DATAS` list names exactly what goes in: `webapp/dist`,
`foeopt/data/catalog.json`, `foeopt/data/catalog-manifest.json` and
`desktop/selftest_city.json`. Never add a pattern or the repo root: the root
holds player city files (`tests/test_desktop_spec.py` checks this).
