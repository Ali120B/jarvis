const { app, BrowserWindow, ipcMain, globalShortcut } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const DEV_BACKEND_PORT = 8765;
let mainWindow = null;
let backendProcess = null;
let backendUrl = null;

function resolveBackendCommand() {
  if (app.isPackaged) {
    const exe = process.platform === 'win32' ? 'jarvis-backend.exe' : 'jarvis-backend';
    return { cmd: path.join(process.resourcesPath, 'backend', exe), args: ['--port', '0'] };
  }
  // Dev mode: run from the venv in the repo root
  const repoRoot = path.join(__dirname, '..');
  const venv = process.platform === 'win32'
    ? path.join(repoRoot, 'venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, 'venv', 'bin', 'python');
  const script = path.join(repoRoot, 'src', 'server.py');
  return { cmd: venv, args: ['-u', script, '--port', '0'] };
}

function checkExistingBackend() {
  // Dev convenience: if run.sh (or the user) already started the backend on
  // 8765, reuse it instead of spawning a second instance.
  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(false), 1000);
    const req = require('http').get({ host: '127.0.0.1', port: DEV_BACKEND_PORT, path: '/api/health', timeout: 900 }, (res) => {
      clearTimeout(timeout);
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => {
      clearTimeout(timeout);
      resolve(false);
    });
    req.on('timeout', () => {
      clearTimeout(timeout);
      req.destroy();
      resolve(false);
    });
  });
}

function startBackend() {
  const { cmd, args } = resolveBackendCommand();
  if (!fs.existsSync(cmd)) {
    console.error('Backend not found:', cmd);
    backendUrl = `http://127.0.0.1:${DEV_BACKEND_PORT}`;
    return;
  }
  backendProcess = spawn(cmd, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }
  });

  const onOutput = (buf) => {
    const text = buf.toString();
    console.log('[backend]', text.trim());
    const m = text.match(/JARVIS_PORT=(\d+)/);
    if (m) {
      backendUrl = `http://127.0.0.1:${m[1]}`;
      console.log('Backend ready at', backendUrl);
    }
  };
  backendProcess.stdout.on('data', onOutput);
  backendProcess.stderr.on('data', onOutput);
  backendProcess.on('error', (e) => console.error('Backend spawn error:', e));
  backendProcess.on('exit', (code) => {
    console.log('Backend exited:', code);
    backendProcess = null;
  });
}

app.whenReady().then(async () => {
  if (app.isPackaged || !(await checkExistingBackend())) {
    startBackend();
  } else {
    backendUrl = `http://127.0.0.1:${DEV_BACKEND_PORT}`;
    console.log('Reusing existing backend on 8765');
  }
  createWindow();
  registerGlobalShortcuts();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

function stopBackend() {
  if (!backendProcess) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(backendProcess.pid), '/T', '/F']);
    } else {
      backendProcess.kill('SIGKILL');
    }
  } catch (e) {
    console.warn('Backend stop failed:', e.message);
  }
  backendProcess = null;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 860,
    height: 540,
    minWidth: 720,
    minHeight: 460,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    backgroundColor: '#00000000',
    resizable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function registerGlobalShortcuts() {
  try {
    globalShortcut.register('`', () => {
      if (mainWindow) {
        mainWindow.webContents.send('task:clear');
        mainWindow.focus();
      }
    });
    globalShortcut.register('Escape', () => {
      if (mainWindow) mainWindow.webContents.send('task:clear');
    });
  } catch (e) {
    console.warn('Global shortcut registration failed:', e.message);
  }
}

app.whenReady().then(async () => {
  if (app.isPackaged || !(await checkExistingBackend())) {
    startBackend();
  } else {
    backendUrl = `http://127.0.0.1:${DEV_BACKEND_PORT}`;
    console.log('Reusing existing backend on 8765');
  }
  createWindow();
  registerGlobalShortcuts();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  stopBackend();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('window:minimize', () => {
  if (mainWindow) mainWindow.minimize();
});

ipcMain.handle('window:close', () => {
  if (mainWindow) mainWindow.close();
});

ipcMain.handle('window:focus', () => {
  if (mainWindow) mainWindow.focus();
});

ipcMain.handle('get-backend-url', () => backendUrl || `http://127.0.0.1:${DEV_BACKEND_PORT}`);
