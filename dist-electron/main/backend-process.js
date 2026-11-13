"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.BackendProcess = void 0;
exports.resolvePythonExecutable = resolvePythonExecutable;
const node_child_process_1 = require("node:child_process");
const node_events_1 = require("node:events");
const node_crypto_1 = require("node:crypto");
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
class BackendProcess extends node_events_1.EventEmitter {
    projectRoot;
    packaged;
    logDirectory;
    process = null;
    state = "stopped";
    lastError = null;
    stdoutBuffer = "";
    pending = new Map();
    constructor(projectRoot, packaged = false, logDirectory) {
        super();
        this.projectRoot = projectRoot;
        this.packaged = packaged;
        this.logDirectory = logDirectory;
    }
    diagnostics() {
        const pythonExecutable = resolvePythonExecutable(this.projectRoot, this.packaged);
        const pythonPackage = node_path_1.default.join(this.projectRoot, "python", "lmrchip", "service.py");
        const pythonFound = !this.packaged || node_fs_1.default.existsSync(pythonExecutable);
        const packageFound = node_fs_1.default.existsSync(pythonPackage);
        return { packaged: this.packaged, pythonExecutable, pythonPackage, pythonFound, packageFound, valid: pythonFound && packageFound };
    }
    snapshot() {
        return {
            state: this.state,
            pid: this.process?.pid ?? null,
            lastError: this.lastError,
        };
    }
    async start() {
        if (this.process) {
            return this.snapshot();
        }
        this.lastError = null;
        const diagnostics = this.diagnostics();
        if (!diagnostics.valid) {
            this.lastError = "Packaged Python resources are incomplete. Reinstall LMRChip Desktop.";
            this.setState("crashed");
            throw new Error(this.lastError);
        }
        this.setState("starting");
        const python = diagnostics.pythonExecutable;
        const pythonPath = node_path_1.default.join(this.projectRoot, "python");
        const child = (0, node_child_process_1.spawn)(python, ["-m", "lmrchip.service"], {
            cwd: this.projectRoot,
            env: {
                ...process.env,
                PYTHONPATH: pythonPath,
                ...(this.logDirectory ? { LMRCHIP_LOG_DIR: this.logDirectory } : {}),
                ...(this.logDirectory ? { LMRCHIP_PROTOCOL_DIR: node_path_1.default.join(this.logDirectory, "protocols") } : {}),
            },
            stdio: ["pipe", "pipe", "pipe"],
            windowsHide: true,
        });
        this.process = child;
        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", (chunk) => this.consumeStdout(chunk));
        child.stderr.on("data", (chunk) => this.emit("log", chunk.trimEnd()));
        child.once("spawn", () => this.setState("running"));
        child.once("error", (error) => {
            this.lastError = error.message;
            this.emit("log", `Backend process error: ${error.message}`);
        });
        child.once("exit", (code, signal) => this.handleExit(child, code, signal));
        await new Promise((resolve, reject) => {
            child.once("spawn", resolve);
            child.once("error", reject);
        });
        return this.snapshot();
    }
    request(command, payload = {}, timeoutMs = 5000) {
        if (!this.process || (this.state !== "running" && this.state !== "stopping")) {
            return Promise.reject(new Error("Python backend is not running."));
        }
        const id = (0, node_crypto_1.randomUUID)();
        const message = JSON.stringify({ version: 1, id, command, payload }) + "\n";
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                this.pending.delete(id);
                reject(new Error(`Backend request timed out: ${command}`));
            }, timeoutMs);
            this.pending.set(id, { resolve, reject, timer });
            this.process?.stdin.write(message, "utf8", (error) => {
                if (error) {
                    clearTimeout(timer);
                    this.pending.delete(id);
                    reject(error);
                }
            });
        });
    }
    async stop() {
        const child = this.process;
        if (!child) {
            this.setState("stopped");
            return this.snapshot();
        }
        this.setState("stopping");
        const exited = new Promise((resolve) => child.once("exit", () => resolve()));
        try {
            await this.request("system.shutdown", {}, 130_000);
        }
        catch (error) {
            this.emit("log", `Graceful shutdown failed: ${formatError(error)}`);
        }
        const closed = await Promise.race([
            exited.then(() => true),
            new Promise((resolve) => setTimeout(() => resolve(false), 130_000)),
        ]);
        if (!closed && this.process === child) {
            child.kill();
            await exited;
        }
        return this.snapshot();
    }
    consumeStdout(chunk) {
        this.stdoutBuffer += chunk;
        let newline = this.stdoutBuffer.indexOf("\n");
        while (newline >= 0) {
            const line = this.stdoutBuffer.slice(0, newline).trim();
            this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1);
            if (line) {
                this.handleMessage(line);
            }
            newline = this.stdoutBuffer.indexOf("\n");
        }
    }
    handleMessage(line) {
        let message;
        try {
            message = JSON.parse(line);
        }
        catch {
            this.lastError = "Backend emitted invalid JSON.";
            this.emit("log", `${this.lastError} ${line}`);
            this.emitSnapshot();
            return;
        }
        if (message.type === "event") {
            this.emit("event", message);
            return;
        }
        if (message.type !== "response" || typeof message.id !== "string") {
            this.emit("log", `Unexpected backend message: ${line}`);
            return;
        }
        const pending = this.pending.get(message.id);
        if (!pending) {
            this.emit("log", `Response received for unknown request: ${message.id}`);
            return;
        }
        clearTimeout(pending.timer);
        this.pending.delete(message.id);
        if (message.ok) {
            pending.resolve(message.data);
        }
        else {
            pending.reject(new Error(`${message.error?.code ?? "BACKEND_ERROR"}: ${message.error?.message ?? "Unknown error"}`));
        }
    }
    handleExit(child, code, signal) {
        if (this.process !== child) {
            return;
        }
        this.process = null;
        this.stdoutBuffer = "";
        const expected = this.state === "stopping";
        if (!expected) {
            this.lastError = `Backend exited unexpectedly (code=${code}, signal=${signal ?? "none"}).`;
        }
        for (const pending of this.pending.values()) {
            clearTimeout(pending.timer);
            pending.reject(new Error(this.lastError ?? "Backend stopped."));
        }
        this.pending.clear();
        this.setState(expected ? "stopped" : "crashed");
    }
    setState(state) {
        this.state = state;
        this.emitSnapshot();
    }
    emitSnapshot() {
        this.emit("state", this.snapshot());
    }
}
exports.BackendProcess = BackendProcess;
function resolvePythonExecutable(projectRoot, packaged = false) {
    if (process.env.LMRCHIP_PYTHON?.trim()) {
        return process.env.LMRCHIP_PYTHON;
    }
    if (packaged) {
        return node_path_1.default.join(projectRoot, "python-runtime", "python.exe");
    }
    const localPython = node_path_1.default.join(projectRoot, ".venv-py314", "Scripts", "python.exe");
    return node_fs_1.default.existsSync(localPython) ? localPython : "python";
}
function formatError(error) {
    return error instanceof Error ? error.message : String(error);
}
