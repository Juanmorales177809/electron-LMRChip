import { contextBridge, ipcRenderer } from "electron";


contextBridge.exposeInMainWorld("lmrchip", {
  selectResultsDirectory: () => ipcRenderer.invoke("dialog:select-results-directory"),
  backend: {
    start: () => ipcRenderer.invoke("backend:start"),
    stop: () => ipcRenderer.invoke("backend:stop"),
    status: () => ipcRenderer.invoke("backend:status"),
    diagnostics: () => ipcRenderer.invoke("backend:diagnostics"),
    request: (command: string, payload: Record<string, unknown> = {}) =>
      ipcRenderer.invoke("backend:request", command, payload),
    onEvent: (callback: (event: unknown) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, message: unknown) => callback(message);
      ipcRenderer.on("backend:event", listener);
      return () => ipcRenderer.removeListener("backend:event", listener);
    },
    onStateChange: (callback: (state: unknown) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, state: unknown) => callback(state);
      ipcRenderer.on("backend:state", listener);
      return () => ipcRenderer.removeListener("backend:state", listener);
    },
    onLog: (callback: (message: string) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, message: string) => callback(message);
      ipcRenderer.on("backend:log", listener);
      return () => ipcRenderer.removeListener("backend:log", listener);
    },
  },
});
