"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const node_path_1 = __importDefault(require("node:path"));
const backend_process_1 = require("./backend-process");
const file_logger_1 = require("./file-logger");
let mainWindow = null;
let backend = null;
let logger = null;
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
        width: 1280,
        height: 800,
        minWidth: 960,
        minHeight: 640,
        title: "LMRChip Desktop",
        webPreferences: {
            preload: node_path_1.default.join(__dirname, "../preload/preload.js"),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
        },
    });
    mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
        logger?.write("ERROR", `Renderer failed to load (${errorCode}): ${errorDescription} URL=${validatedURL}`);
    });
    mainWindow.webContents.on("render-process-gone", (_event, details) => {
        logger?.write("ERROR", `Renderer process gone: ${JSON.stringify(details)}`);
    });
    mainWindow.webContents.on("console-message", (_event, level, message, lineNumber, sourceId) => {
        if (level >= 2) {
            logger?.write("ERROR", `Renderer console: ${message} (${sourceId}:${lineNumber})`);
        }
    });
    const developmentUrl = process.env.VITE_DEV_SERVER_URL;
    if (developmentUrl) {
        void mainWindow.loadURL(developmentUrl);
    }
    else {
        void mainWindow.loadFile(node_path_1.default.join(__dirname, "../../dist/renderer/index.html"));
    }
}
function registerIpcHandlers(manager) {
    electron_1.ipcMain.handle("dialog:select-results-directory", async () => {
        const options = {
            title: "Seleccionar carpeta para los resultados",
            properties: ["openDirectory", "createDirectory"],
        };
        const result = mainWindow
            ? await electron_1.dialog.showOpenDialog(mainWindow, options)
            : await electron_1.dialog.showOpenDialog(options);
        return result.canceled ? null : result.filePaths[0] ?? null;
    });
    electron_1.ipcMain.handle("backend:start", () => manager.start());
    electron_1.ipcMain.handle("backend:diagnostics", () => manager.diagnostics());
    electron_1.ipcMain.handle("backend:stop", () => manager.stop());
    electron_1.ipcMain.handle("backend:status", async () => {
        const snapshot = manager.snapshot();
        if (snapshot.state !== "running") {
            return { process: snapshot, service: null };
        }
        return { process: snapshot, service: await manager.request("system.status") };
    });
    electron_1.ipcMain.handle("backend:request", (_event, command, payload) => {
        if (typeof command !== "string" || !command.trim()) {
            throw new TypeError("Command must be a non-empty string.");
        }
        if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
            throw new TypeError("Payload must be an object.");
        }
        return manager.request(command, payload, commandTimeout(command));
    });
}
function commandTimeout(command) {
    const timeouts = {
        "temperature.connect": 15_000,
        "temperature.disconnect": 15_000,
        "temperature.start": 60_000,
        "temperature.stop": 10_000,
        "spectrometer.connect": 15_000,
        "spectrometer.disconnect": 15_000,
        "spectrometer.capture_background": 30_000,
        "spectrometer.capture_reference": 30_000,
        "spectrometer.capture_sample": 30_000,
        "experiment.start": 15_000,
    };
    return timeouts[command] ?? 5_000;
}
electron_1.app.whenReady().then(() => {
    const logDirectory = node_path_1.default.join(electron_1.app.getPath("userData"), "logs");
    logger = new file_logger_1.RotatingFileLogger(logDirectory);
    const projectRoot = electron_1.app.isPackaged ? process.resourcesPath : node_path_1.default.resolve(__dirname, "../..");
    backend = new backend_process_1.BackendProcess(projectRoot, electron_1.app.isPackaged, logDirectory);
    registerIpcHandlers(backend);
    const diagnostics = backend.diagnostics();
    logger.write(diagnostics.valid ? "INFO" : "ERROR", `Resource diagnostics: ${JSON.stringify(diagnostics)}`);
    backend.on("state", (state) => {
        logger?.write("INFO", `Backend state: ${JSON.stringify(state)}`);
        mainWindow?.webContents.send("backend:state", state);
    });
    backend.on("event", (event) => mainWindow?.webContents.send("backend:event", event));
    backend.on("log", (message) => {
        logger?.write("INFO", message);
        mainWindow?.webContents.send("backend:log", message);
    });
    createWindow();
    electron_1.app.on("activate", () => {
        if (electron_1.BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});
electron_1.app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
        electron_1.app.quit();
    }
});
electron_1.app.on("before-quit", (event) => {
    if (backend && backend.snapshot().state !== "stopped") {
        event.preventDefault();
        void backend.stop().finally(() => {
            backend = null;
            electron_1.app.quit();
        });
    }
});
