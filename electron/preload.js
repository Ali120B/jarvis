const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  close: () => ipcRenderer.invoke('window:close'),
  focus: () => ipcRenderer.invoke('window:focus'),
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  onTaskClear: (cb) => ipcRenderer.on('task:clear', () => cb())
});
