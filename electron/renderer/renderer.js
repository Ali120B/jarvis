const backend = {
  async url() {
    if (!this._url) {
      if (window.jarvis) {
        this._url = await window.jarvis.getBackendUrl();
      } else {
        this._url = window.location.origin;
      }
    }
    return this._url;
  },
  async chat(text) {
    const base = await this.url();
    const res = await fetch(`${base}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, tts: true })
    });
    if (!res.ok) throw new Error(`Backend error ${res.status}`);
    return res.json();
  },
  async status() {
    const base = await this.url();
    const res = await fetch(`${base}/api/status`);
    if (!res.ok) throw new Error('status');
    return res.json();
  },
  async clear() {
    const base = await this.url();
    await fetch(`${base}/api/clear`, { method: 'POST' });
  },
  async listen() {
    const base = await this.url();
    const res = await fetch(`${base}/api/listen`, { method: 'POST' });
    if (!res.ok) throw new Error(`Backend error ${res.status}`);
    return res.json();
  },
  async stopListen() {
    const base = await this.url();
    await fetch(`${base}/api/listen/stop`, { method: 'POST' }).catch(() => {});
  },
  async health() {
    const base = await this.url();
    const res = await fetch(`${base}/api/health`);
    if (!res.ok) throw new Error('health');
    return res.json();
  },
  async config() {
    const base = await this.url();
    const res = await fetch(`${base}/api/config`);
    if (!res.ok) throw new Error('config');
    return res.json();
  },
  async saveConfig(payload) {
    const base = await this.url();
    const res = await fetch(`${base}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`Config error ${res.status}`);
    return res.json();
  },
  async models(provider) {
    const base = await this.url();
    const res = await fetch(`${base}/api/models?provider=${encodeURIComponent(provider)}`);
    if (!res.ok) throw new Error('models');
    return res.json();
  }
};

const $ = (id) => document.getElementById(id);
const chatLog = $('chat-log');
const statusLabel = $('status-label');
const coreOrb = $('core-orb');
const coreDot = $('core-dot');
const clockEl = $('clock');
const input = $('text-input');
const sendBtn = $('btn-send');
const micBtn = $('btn-mic');
const clearBtn = $('btn-clear');
const banner = $('task-banner');
const bannerIcon = $('banner-icon');
const bannerTitle = $('banner-title');
const bannerText = $('banner-text');
const backendText = $('backend-text');

const audio = new Audio();

let bannerTimer = null;
let lastTaskKey = '';
let audioEnded = false;

/* ---------------- task banner ---------------- */

function showBanner(kind, title, text) {
  banner.className = kind; // '', 'done', 'error'
  bannerIcon.textContent = kind === 'done' ? '\u2713' : kind === 'error' ? '\u26A0' : '\u2699';
  bannerTitle.textContent = title;
  bannerText.textContent = text;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(hideBanner, 5000);
}

function hideBanner() {
  clearTimeout(bannerTimer);
  banner.classList.add('hidden');
}

function clearBannerNow() {
  hideBanner();
}

function formatDetail(detail) {
  if (!detail) return '';
  try {
    const obj = JSON.parse(detail);
    return Object.entries(obj).map(([k, v]) => `${k}: ${v}`).join(' · ');
  } catch {
    return detail;
  }
}

function handleStatus(data) {
  const state = data.state || 'idle';

  // current task running
  if (state === 'executing' && data.task) {
    const key = `x|${data.ts}`;
    if (key !== lastTaskKey) {
      lastTaskKey = key;
      showBanner('', 'EXECUTING', `${data.task.replace(/_/g, ' ').toUpperCase()} · ${formatDetail(data.detail)}`);
      coreOrb.classList.add('busy');
      statusLabel.textContent = 'EXECUTING';
    }
  } else if (state === 'thinking') {
    statusLabel.textContent = 'THINKING';
    coreOrb.classList.add('busy');
  } else if (state === 'error') {
    statusLabel.textContent = 'ERROR';
    coreOrb.classList.add('error');
    if (data.task) showBanner('error', 'ERROR', data.task.replace(/_/g, ' '));
  } else if (state === 'idle') {
    coreOrb.classList.remove('busy', 'error');

    // finished task: show COMPLETE banner for 5s (or until backtick)
    if (data.last_task && data.last_ts) {
      const key = `done|${data.last_ts}`;
      if (key !== lastTaskKey) {
        lastTaskKey = key;
        const title = data.last_task.replace(/_/g, ' ').toUpperCase();
        showBanner('done', 'COMPLETE', `${title}${data.last_detail ? ' · ' + data.last_detail : ''}`);
      }
    }
    statusLabel.textContent = 'STANDBY';
  }
}

/* ---------------- clock ---------------- */

function tickClock() {
  const now = new Date();
  clockEl.textContent = now.toTimeString().slice(0, 8);
}

setInterval(tickClock, 1000);
tickClock();

/* ---------------- backend polling ---------------- */

let backendOnline = false;

async function pollStatus() {
  try {
    const data = await backend.status();
    if (!backendOnline) {
      backendOnline = true;
      backendText.textContent = 'ONLINE';
      backendText.classList.add('online');
      appendMessage('sys', 'UPLINK ESTABLISHED. ALL SYSTEMS GO.');
    }
    handleStatus(data);
    checkFirstRun();
  } catch {
    if (backendOnline) {
      backendOnline = false;
      backendText.textContent = 'OFFLINE';
      backendText.classList.remove('online');
      coreOrb.classList.remove('busy', 'error');
      statusLabel.textContent = 'OFFLINE';
      appendMessage('error', 'BACKEND OFFLINE');
    }
  }
}

setInterval(pollStatus, 800);
pollStatus();

/* ---------------- chat ---------------- */

function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function playAudio(url) {
  audioEnded = false;
  audio.src = url;
  audio.play().catch((e) => console.warn('playback:', e));
  audio.onended = () => { audioEnded = true; };
}

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  appendMessage('user', text);
  statusLabel.textContent = 'PROCESSING';
  try {
    const { reply, audio: audioFile } = await backend.chat(text);
    appendMessage('jarvis', reply);
    if (audioFile) {
      const base = await backend.url();
      playAudio(`${base}/audio/${audioFile}`);
    }
  } catch (e) {
    appendMessage('error', `ERROR: ${e.message}`);
    statusLabel.textContent = 'ERROR';
  }
}

sendBtn.addEventListener('click', sendMessage);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage();
});

let isListening = false;

micBtn.addEventListener('click', async () => {
  if (!isListening) {
    // START listening
    isListening = true;
    micBtn.classList.add('recording');
    micBtn.textContent = '\u25CF\u25CF\u25CF';
    statusLabel.textContent = 'LISTENING...';
    appendMessage('sys', 'LISTENING... CLICK AGAIN TO STOP');

    try {
      const { text, error } = await backend.listen();
      if (text) {
        appendMessage('user', text);
        input.value = '';
        statusLabel.textContent = 'PROCESSING';
        const { reply, audio: audioFile } = await backend.chat(text);
        appendMessage('jarvis', reply);
        if (audioFile) {
          const base = await backend.url();
          playAudio(`${base}/audio/${audioFile}`);
        }
      } else if (error) {
        appendMessage('error', `MIC ERROR: ${error}`);
      } else {
        appendMessage('sys', 'NO SPEECH DETECTED');
      }
    } catch (e) {
      appendMessage('error', `MIC ERROR: ${e.message}`);
    } finally {
      isListening = false;
      micBtn.classList.remove('recording');
      micBtn.textContent = '\uD83C\uDFA4';
      statusLabel.textContent = 'STANDBY';
    }
  } else {
    // STOP listening early
    await backend.stopListen();
  }
});

clearBtn.addEventListener('click', async () => {
  try {
    await backend.clear();
    chatLog.innerHTML = '';
    appendMessage('sys', 'MEMORY PURGED');
  } catch (e) {
    appendMessage('error', `ERROR: ${e.message}`);
  }
});

$('btn-minimize').addEventListener('click', () => window.jarvis && window.jarvis.minimize());
$('btn-close').addEventListener('click', () => window.jarvis && window.jarvis.close());

/* ---------------- backtick clears task banner (global shortcut) ---------------- */

window.addEventListener('keydown', (e) => {
  if (e.key === '`') {
    clearBannerNow();
    statusLabel.textContent = 'STANDBY';
    input.focus();
  }
});

if (window.jarvis) {
  window.jarvis.onTaskClear(() => {
    clearBannerNow();
    statusLabel.textContent = 'STANDBY';
    input.focus();
  });
}

/* ---------------- settings / first-run setup modal ---------------- */

const settingsOverlay = $('settings-overlay');
const settingsHint = $('settings-hint');
const cfgProvider = $('cfg-provider');
const cfgKey = $('cfg-key');
const cfgKeyToggle = $('cfg-key-toggle');
const cfgModel = $('cfg-model');
const cfgModelOr = $('cfg-model-or');
const cfgStatus = $('cfg-status');
const modelRowGroq = $('cfg-model-row-groq');
const modelRowOr = $('cfg-model-row-openrouter');
const gearBtn = $('btn-settings');

function openSettings(firstRun) {
  settingsHint.textContent = firstRun
    ? 'No API key detected. Provide a provider and API key to activate JARVIS. Your key is stored locally and never bundled with the app.'
    : 'Update your provider, API key, or model. Your key is stored locally and never bundled with the app.';
  cfgStatus.textContent = '';
  cfgStatus.className = 'modal-status';
  loadSettingsForm();
  settingsOverlay.classList.remove('hidden');
}

function closeSettings() {
  settingsOverlay.classList.add('hidden');
}

async function loadSettingsForm() {
  try {
    const cfg = await backend.config();
    cfgProvider.value = cfg.provider === 'openrouter' ? 'openrouter' : 'groq';
    cfgKey.value = '';
    onProviderChange(cfg.provider, cfg);
  } catch {
    cfgStatus.textContent = 'CONFIG UNAVAILABLE';
    cfgStatus.className = 'modal-status error';
  }
}

async function onProviderChange(provider, cfg) {
  const isOr = provider === 'openrouter';
  modelRowGroq.classList.toggle('hidden', isOr);
  modelRowOr.classList.toggle('hidden', !isOr);
  const target = isOr ? cfgModelOr : cfgModel;
  const list = isOr ? $('cfg-model-or-list') : $('cfg-model-list');
  list.innerHTML = '';
  target.value = '';
  try {
    const { models } = await backend.models(provider);
    for (const m of models) {
      const opt = document.createElement('option');
      opt.value = m.id;
      list.appendChild(opt);
    }
  } catch {
    /* datalist stays empty; typing a model id still works */
  }
  if (cfg) {
    const saved = isOr ? cfg.openrouter_model : cfg.model;
    if (saved) target.value = saved;
  }
}

cfgProvider.addEventListener('change', () => onProviderChange(cfgProvider.value, null));

cfgKeyToggle.addEventListener('click', () => {
  const show = cfgKey.type === 'password';
  cfgKey.type = show ? 'text' : 'password';
});

gearBtn.addEventListener('click', () => openSettings(false));
$('btn-settings-close').addEventListener('click', closeSettings);
settingsOverlay.addEventListener('click', (e) => {
  if (e.target === settingsOverlay) closeSettings();
});

$('btn-settings-save').addEventListener('click', async () => {
  const key = cfgKey.value.trim();
  if (!key) {
    cfgStatus.textContent = 'ENTER AN API KEY';
    cfgStatus.className = 'modal-status error';
    return;
  }
  const payload = {
    provider: cfgProvider.value,
    api_key: key,
    model: cfgModel.value.trim(),
    openrouter_model: cfgModelOr.value.trim()
  };
  cfgStatus.textContent = 'SAVING...';
  cfgStatus.className = 'modal-status';
  try {
    await backend.saveConfig(payload);
    cfgStatus.textContent = 'SAVED';
    cfgKey.value = '';
    appendMessage('sys', 'CONFIG UPDATED. JARVIS ACTIVATED.');
    setTimeout(closeSettings, 700);
  } catch (e) {
    cfgStatus.textContent = 'SAVE FAILED';
    cfgStatus.className = 'modal-status error';
  }
});

/* first-run: auto-open setup when the backend says no key is configured */
let firstRunChecked = false;
async function checkFirstRun() {
  if (firstRunChecked || !backendOnline) return;
  firstRunChecked = true;
  try {
    const h = await backend.health();
    if (!h.configured) {
      openSettings(true);
      appendMessage('sys', 'CONFIGURATION REQUIRED - SET YOUR API KEY');
    }
  } catch { /* backend not ready yet; poll will retry */ }
}

/* ---------------- auto-update status (footer) ---------------- */

const updateState = $('update-state');
const updateText = $('update-text');

if (window.jarvis) {
  window.jarvis.onUpdateAvailable((v) => {
    updateState.classList.remove('hidden');
    updateText.textContent = `v${v} AVAILABLE`;
  });
  window.jarvis.onUpdateProgress((p) => {
    updateState.classList.remove('hidden');
    updateText.textContent = `DOWNLOADING ${p}%`;
  });
  window.jarvis.onUpdateDownloaded((v) => {
    updateState.classList.remove('hidden');
    updateText.textContent = 'READY - CLOSE TO INSTALL';
  });
}
