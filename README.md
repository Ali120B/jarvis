# J.A.R.V.I.S. Assistant

A futuristic HUD voice assistant. Electron UI + Python (FastAPI) backend.

- Voice input (mic), speech output (edge-tts), text chat
- AI tool use (Groq / OpenRouter, function calling): open/close apps, open websites,
  volume control, lock screen, screenshots, screen vision, close windows/tabs,
  web search, find files, current time
- Cross-platform: Linux + Windows 11
- Works as an app (Electron) or in a browser (UI served by the backend)

## Structure

```
├── src/                  Python backend (FastAPI)
│   ├── server.py         API server (port 8765 / dynamic in packaged mode)
│   ├── jarvis_core.py    AI logic, tools, TTS, status
│   ├── platform_ops.py   Cross-platform system operations
│   ├── config.py         User config (API key/provider/model) - NOT bundled
│   └── audio/            Generated TTS files (gitignored)
├── electron/             Electron UI (HUD)
│   ├── main.js           Window, global shortcuts, spawns backend, settings IPC
│   ├── preload.js
│   └── renderer/         HUD UI (index.html / styles.css / renderer.js)
├── scripts/              Build helpers
├── legacy/               Old standalone script (reference only)
├── requirements.txt
└── run.sh                Dev: start backend + Electron in one command
```

## Setup (development)

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt   # Windows: venv\Scripts\pip install ...
cd electron && npm install
cd ..
./run.sh                                   # Windows: run the steps manually
```

On first launch the app shows a configuration dialog (Groq or OpenRouter, API key,
model choice). **The key is stored in the user config dir, never in the repo or exe:**

- Linux:   `~/.config/jarvis/config.json`
- Windows: `%APPDATA%\Jarvis\config.json`

Click the gear icon (bottom right) any time to change the provider/key/model.

## Packaging (installer)

The Python backend is compiled to a single binary with PyInstaller, then bundled
with the Electron app via electron-builder into a lightweight NSIS wizard installer.

```bash
# 1. Build the backend binary (Linux or Windows - run on the target OS)
venv/bin/pip install pyinstaller
venv/bin/python scripts/build_backend.py

# 2. Build the installer (Windows: NSIS wizard; Linux: AppImage)
cd electron && npm install && npm run dist
```

Output: `electron/dist/`.

### Release / publish (one command)

```bash
cd electron
npm run publish
```

This compiles the backend, builds the native installer (AppImage on Linux,
NSIS .exe on Windows), tags the release (`v<version>`), pushes the tag, and
drafts a GitHub release with the installer attached.

On Linux, the Windows installer is built automatically by GitHub Actions
(`.github/workflows/build-windows.yml`) on a real Windows runner and attached to
the same draft release. Requires the `gh` CLI to be authenticated.

## API key note

Never commit a real API key. `src/config.py` reads everything from the user config
file; the key never leaves the user's machine and is never part of the installer.
