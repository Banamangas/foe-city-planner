"""Build the desktop app for this system: the frontend, then PyInstaller.

Run with a Python that has the app's dependencies plus PyInstaller:
    python desktop/build.py [--skip-frontend]
Output: dist-desktop/FoE-City-Planner-Linux, dist-desktop/FoE-City-Planner-Windows.exe
or "dist-desktop/FoE City Planner.app"."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "desktop", "foe-city-planner.spec")
DIST = os.path.join(ROOT, "dist-desktop")
WORK = os.path.join(ROOT, "build", "pyinstaller")


def artifact_path(platform: str = sys.platform) -> str:
    if platform == "win32":
        name = "FoE-City-Planner-Windows.exe"
    elif platform == "darwin":
        name = "FoE City Planner.app"
    else:
        name = "FoE-City-Planner-Linux"
    return os.path.join(DIST, name)


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(d, f))
               for d, _, files in os.walk(path) for f in files
               if not os.path.islink(os.path.join(d, f)))


def build_frontend() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm not found: install Node.js to build the frontend")
    frontend = os.path.join(ROOT, "frontend")
    if not os.path.isdir(os.path.join(frontend, "node_modules")):
        # fresh checkout: node_modules is gitignored
        subprocess.run([npm, "ci"], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
    if not os.path.exists(os.path.join(ROOT, "webapp", "dist", "index.html")):
        raise SystemExit("the frontend build produced no webapp/dist/index.html")


def build_app() -> str:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", DIST, "--workpath", WORK, SPEC], cwd=ROOT, check=True)
    path = artifact_path()
    if not os.path.exists(path):
        raise SystemExit(f"PyInstaller finished but {path} is missing")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-frontend", action="store_true",
                        help="reuse the existing webapp/dist")
    args = parser.parse_args(argv)
    if not args.skip_frontend:
        build_frontend()
    path = build_app()
    print(f"built {path} ({_size(path) / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
