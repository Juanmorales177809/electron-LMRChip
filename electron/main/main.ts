import { app, BrowserWindow, dialog, ipcMain } from "electron";
import path from "node:path";

import { BackendProcess } from "./backend-process";
import { RotatingFileLogger } from "./file-logger";


let mainWindow: BrowserWindow | null = null;
let backend: BackendProcess | null = null;
let logger: RotatingFileLogger | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    title: "LMRChip Desktop",
    webPreferences: {
      preload: path.join(__dirname, "../preload/preload.js"),
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
  } else {
    void mainWindow.loadFile(path.join(__dirname, "../../dist/renderer/index.html"));
  }
}

function registerIpcHandlers(manager: BackendProcess): void {
  ipcMain.handle("dialog:select-results-directory", async () => {
    const options: Electron.OpenDialogOptions = {
      title: "Seleccionar carpeta para los resultados",
      properties: ["openDirectory", "createDirectory"],
    };
    const result = mainWindow
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options);
    return result.canceled ? null : result.filePaths[0] ?? null;
  });
  ipcMain.handle("backend:start", () => manager.start());
  ipcMain.handle("backend:diagnostics", () => manager.diagnostics());
  ipcMain.handle("backend:stop", () => manager.stop());
  ipcMain.handle("backend:status", async () => {
    const snapshot = manager.snapshot();
    if (snapshot.state !== "running") {
      return { process: snapshot, service: null };
    }
    return { process: snapshot, service: await manager.request("system.status") };
  });
  ipcMain.handle(
    "backend:request",
    (_event, command: unknown, payload: unknown) => {
      if (typeof command !== "string" || !command.trim()) {
        throw new TypeError("Command must be a non-empty string.");
      }
      if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
        throw new TypeError("Payload must be an object.");
      }
      return manager.request(
        command,
        payload as Record<string, unknown>,
        commandTimeout(command),
      );
    },
  );
}

function commandTimeout(command: string): number {
  const timeouts: Record<string, number> = {
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

app.whenReady().then(() => {
  const logDirectory = path.join(app.getPath("userData"), "logs");
  logger = new RotatingFileLogger(logDirectory);
  const projectRoot = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "../..");
  backend = new BackendProcess(projectRoot, app.isPackaged, logDirectory);
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

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", (event) => {
  if (backend && backend.snapshot().state !== "stopped") {
    event.preventDefault();
    void backend.stop().finally(() => {
      backend = null;
      app.quit();
    });
  }
});
