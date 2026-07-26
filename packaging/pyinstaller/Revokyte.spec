# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the desktop (PC) app.

Build from the repo root with the project (and its "pc" extra) installed:

    pip install ".[pc]" pyinstaller
    pyinstaller --noconfirm packaging/pyinstaller/Revokyte.spec

Produces a single-file dist/Revokyte executable; on macOS additionally a
dist/Revokyte.app bundle. Builds are unsigned — see the README's desktop
section for the SmartScreen/Gatekeeper first-run notes.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Non-code package files: fonts and images under assets/, the track/car
# databases under db/. Both font loading (importlib.resources) and the track
# db (Path(__file__)-relative) resolve inside the bundled package directory.
datas = collect_data_files("instrument_cluster")

# PluginManager discovers packaged gauges by *listing the plugins directory*,
# so the .py files must exist on disk in the bundle; the discovered names are
# then imported as regular modules, which the hidden imports below cover.
datas += collect_data_files(
    "instrument_cluster", subdir="plugins", include_py_files=True
)

hiddenimports = (
    collect_submodules("instrument_cluster.plugins")
    # Imported lazily (behind the feed descriptor), so spelled out here.
    + collect_submodules("granturismo")
)

a = Analysis(
    # SPECPATH: resolve relative to this spec file, not the caller's CWD.
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Dev-only plotting tools (db/plot_*.py); keep the bundle lean.
        "matplotlib",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Revokyte",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Revokyte.app",
        icon=None,
        bundle_identifier="io.github.chrshdl.revokyte",
        info_plist={
            "NSHighResolutionCapable": True,
            # UDP telemetry from the PS5 on the local network.
            "NSLocalNetworkUsageDescription": (
                "Revokyte reads Gran Turismo 7 telemetry from your "
                "PlayStation over the local network."
            ),
        },
    )
