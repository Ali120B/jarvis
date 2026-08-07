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


def run(cmd: list, cwd: Path):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    py = sys.executable
    run([py, "-m", "PyInstaller", "--version"], ROOT)  # sanity check
    OUT.mkdir(parents=True, exist_ok=True)

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
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "uvicorn.lifespan.off",
        "--hidden-import", "uvicorn.lifespan.auto",
        "--hidden-import", "uvicorn.middleware",
        "--hidden-import", "uvicorn.middleware.proxy_headers",
        "--hidden-import", "uvicorn.middleware.asgi2",
        "--hidden-import", "uvicorn.middleware.wsgi",
        "--hidden-import", "uvicorn.middleware.message_logger",
        "--hidden-import", "anyio._backends._asyncio",
        "--hidden-import", "anyio._backends._threads",
        "--hidden-import", "speech_recognition",
        "--hidden-import", "edge_tts",
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
    print(f"\n✅ Backend binary: {exe} ({size:.1f} MB)")

    # Clean intermediate artifacts
    shutil.rmtree(ROOT / "build" / "pyinstaller-work", ignore_errors=True)
    print("Done.")


if __name__ == "__main__":
    main()
