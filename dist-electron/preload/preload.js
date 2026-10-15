"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
electron_1.contextBridge.exposeInMainWorld("lmrchip", {
    selectResultsDirectory: () => electron_1.ipcRenderer.invoke("dialog:select-results-directory"),
    backend: {
        start: () => electron_1.ipcRenderer.invoke("backend:start"),
        stop: () => electron_1.ipcRenderer.invoke("backend:stop"),
        status: () => electron_1.ipcRenderer.invoke("backend:status"),
        diagnostics: () => electron_1.ipcRenderer.invoke("backend:diagnostics"),
        request: (command, payload = {}) => electron_1.ipcRenderer.invoke("backend:request", command, payload),
        onEvent: (callback) => {
            const listener = (_event, message) => callback(message);
            electron_1.ipcRenderer.on("backend:event", listener);
            return () => electron_1.ipcRenderer.removeListener("backend:event", listener);
        },
        onStateChange: (callback) => {
            const listener = (_event, state) => callback(state);
            electron_1.ipcRenderer.on("backend:state", listener);
            return () => electron_1.ipcRenderer.removeListener("backend:state", listener);
        },
        onLog: (callback) => {
            const listener = (_event, message) => callback(message);
            electron_1.ipcRenderer.on("backend:log", listener);
            return () => electron_1.ipcRenderer.removeListener("backend:log", listener);
        },
    },
});
