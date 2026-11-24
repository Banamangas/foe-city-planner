# PyInstaller spec of the desktop app. Build with `python desktop/build.py`.
#
# Privacy: the repo root holds player city files, so DATAS lists the exact
# files to bundle (paths relative to the repo root), never a pattern.
import ast
import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)  # noqa: F821 (SPECPATH is set by PyInstaller)


def _version() -> str:
    """desktop.__version__, read from the file (no import of the app)."""
    with open(os.path.join(ROOT, "desktop", "__init__.py"), encoding="utf-8") as f:
        for node in ast.parse(f.read()).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and getattr(node.targets[0], "id", None) == "__version__"):
                return ast.literal_eval(node.value)
    raise SystemExit("desktop/__init__.py has no __version__")


VERSION = _version()

DATAS = [
    ("webapp/dist", "webapp/dist"),
    ("foeopt/data/catalog.json", "foeopt/data"),
    ("foeopt/data/catalog-manifest.json", "foeopt/data"),
    ("desktop/selftest_city.json", "desktop"),
]

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
WINDOWED = IS_WIN or IS_MAC

if IS_WIN:
    NAME = "FoE-City-Planner-Windows"
elif IS_MAC:
    NAME = "FoE City Planner"
else:
    NAME = "FoE-City-Planner-Linux"

_datas = [(os.path.join(ROOT, src), dest) for src, dest in DATAS]
_binaries = []
# main() imports these inside the function; listed so the analysis can't miss them.
_hidden = ["desktop.paths", "desktop.selftest", "desktop.shell", "webapp.app"]

_d, _b, _h = collect_all("ortools")
_datas += _d
_binaries += _b
_hidden += _h

# The window: pywebview's backend (Linux always opens the browser instead).
if IS_WIN:
    _hidden += ["webview", "webview.platforms.winforms", "webview.platforms.edgechromium",
                "clr"]
elif IS_MAC:
    _hidden += ["webview", "webview.platforms.cocoa"]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "desktop", "main.py")],
    pathex=[ROOT],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hidden,
    # Never exclude numpy or pandas: ortools' cp_model imports both at top level.
    excludes=["tkinter", "torch", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

if IS_MAC:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, [],
        exclude_binaries=True,
        name=NAME,
        console=False,
        upx=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)  # noqa: F821
    app = BUNDLE(  # noqa: F821
        coll,
        name=NAME + ".app",
        bundle_identifier="io.github.foe-city-planner",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
        },
    )
else:
    # One file on Windows and Linux.
    exe = EXE(  # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [],
        name=NAME,
        console=not WINDOWED,
        upx=False,
        runtime_tmpdir=None,
    )
