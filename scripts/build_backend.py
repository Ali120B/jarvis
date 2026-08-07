#!/usr/bin/env python3
"""Build the JARVIS backend into a single executable with PyInstaller.

Usage:
    python scripts/build_backend.py

Output: electron/resources/backend/jarvis-backend[.exe]

Size optimizations:
  - onefile build (single binary, no unpacked folder)
  - explicit hiddenimports instead of --collect-all (keeps the bundle lean)
  - no console on Windows release builds (add --console to debug)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = ROOT / "electron" / "resources" / "backend"

NAME = "jarvis-backend"
IS_WIN = sys.platform.startswith("win")

HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.lifespan.auto",
    "uvicorn.middleware",
    "uvicorn.middleware.proxy_headers",
    "uvicorn.middleware.asgi2",
    "uvicorn.middleware.wsgi",
    "uvicorn.middleware.message_logger",
    "anyio._backends._asyncio",
    "anyio._backends._threads",
    "speech_recognition",
    "edge_tts",
]


def importable(mod: str) -> bool:
    """Only pass hidden imports that actually exist on this Python."""
    probe = "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('%s') else 1)" % mod
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True)
    return r.returncode == 0


def run(cmd: list, cwd: Path):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    py = sys.executable
    run([py, "-m", "PyInstaller", "--version"], ROOT)  # sanity check
    OUT.mkdir(parents=True, exist_ok=True)

    hidden = [m for m in HIDDEN_IMPORTS if importable(m)]
    missing = [m for m in HIDDEN_IMPORTS if m not in hidden]
    if missing:
        print("Skipping hidden imports not present on this Python:", ", ".join(missing))

    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", NAME,
        "--paths", str(SRC),
        "--distpath", str(OUT),
        "--workpath", str(ROOT / "build" / "pyinstaller-work"),
        "--specpath", str(ROOT / "build"),
    ]
    for m in hidden:
        cmd += ["--hidden-import", m]
    cmd += [
        "--exclude-module", "PyQt6",
        "--exclude-module", "PyQt5",
        "--exclude-module", "pystray",
        "--exclude-module", "numpy",
        "--exclude-module", "scipy",
        "--exclude-module", "sklearn",
        "--exclude-module", "openwakeword",
        "--exclude-module", "pygame",
        "--exclude-module", "keyboard",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        str(SRC / "server.py"),
    ]
    if not IS_WIN:
        cmd += ["--noupx"]

    run(cmd, ROOT)

    exe = OUT / f"{NAME}{'.exe' if IS_WIN else ''}"
    if not exe.exists():
        print("Build failed: output binary not found")
        sys.exit(1)
    size = exe.stat().st_size / 1024 / 1024
    print(f"\n[OK] Backend binary: {exe} ({size:.1f} MB)")

    # Clean intermediate artifacts
    shutil.rmtree(ROOT / "build" / "pyinstaller-work", ignore_errors=True)
    print("Done.")


if __name__ == "__main__":
    main()
