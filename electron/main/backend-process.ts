import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";


export type BackendState = "stopped" | "starting" | "running" | "stopping" | "crashed";

export interface BackendSnapshot {
  state: BackendState;
  pid: number | null;
  lastError: string | null;
}

export interface ResourceDiagnostics {
  packaged: boolean;
  pythonExecutable: string;
  pythonPackage: string;
  pythonFound: boolean;
  packageFound: boolean;
  valid: boolean;
}

interface PendingRequest {
  resolve: (data: unknown) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

interface BackendMessage {
  type?: string;
  id?: string | null;
  ok?: boolean;
  data?: unknown;
  event?: string;
  error?: { code?: string; message?: string };
}

export class BackendProcess extends EventEmitter {
  private process: ChildProcessWithoutNullStreams | null = null;
  private state: BackendState = "stopped";
  private lastError: string | null = null;
  private stdoutBuffer = "";
  private readonly pending = new Map<string, PendingRequest>();

  constructor(private readonly projectRoot: string, private readonly packaged = false, private readonly logDirectory?: string) {
    super();
  }

  diagnostics(): ResourceDiagnostics {
    const pythonExecutable = resolvePythonExecutable(this.projectRoot, this.packaged);
    const pythonPackage = path.join(this.projectRoot, "python", "lmrchip", "service.py");
    const pythonFound = !this.packaged || fs.existsSync(pythonExecutable);
    const packageFound = fs.existsSync(pythonPackage);
    return { packaged: this.packaged, pythonExecutable, pythonPackage, pythonFound, packageFound, valid: pythonFound && packageFound };
  }

  snapshot(): BackendSnapshot {
    return {
      state: this.state,
      pid: this.process?.pid ?? null,
      lastError: this.lastError,
    };
  }

  async start(): Promise<BackendSnapshot> {
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
    const pythonPath = path.join(this.projectRoot, "python");
    const child = spawn(python, ["-m", "lmrchip.service"], {
      cwd: this.projectRoot,
      env: {
        ...process.env,
        PYTHONPATH: pythonPath,
        ...(this.logDirectory ? { LMRCHIP_LOG_DIR: this.logDirectory } : {}),
        ...(this.logDirectory ? { LMRCHIP_PROTOCOL_DIR: path.join(this.logDirectory, "protocols") } : {}),
      },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.process = child;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => this.consumeStdout(chunk));
    child.stderr.on("data", (chunk: string) => this.emit("log", chunk.trimEnd()));
    child.once("spawn", () => this.setState("running"));
    child.once("error", (error) => {
      this.lastError = error.message;
      this.emit("log", `Backend process error: ${error.message}`);
    });
    child.once("exit", (code, signal) => this.handleExit(child, code, signal));

    await new Promise<void>((resolve, reject) => {
      child.once("spawn", resolve);
      child.once("error", reject);
    });
    return this.snapshot();
  }

  request(command: string, payload: Record<string, unknown> = {}, timeoutMs = 5000): Promise<unknown> {
    if (!this.process || (this.state !== "running" && this.state !== "stopping")) {
      return Promise.reject(new Error("Python backend is not running."));
    }

    const id = randomUUID();
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

  async stop(): Promise<BackendSnapshot> {
    const child = this.process;
    if (!child) {
      this.setState("stopped");
      return this.snapshot();
    }

    this.setState("stopping");
    const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
    try {
      await this.request("system.shutdown", {}, 130_000);
    } catch (error) {
      this.emit("log", `Graceful shutdown failed: ${formatError(error)}`);
    }

    const closed = await Promise.race([
      exited.then(() => true),
      new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 130_000)),
    ]);
    if (!closed && this.process === child) {
      child.kill();
      await exited;
    }
    return this.snapshot();
  }

  private consumeStdout(chunk: string): void {
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

  private handleMessage(line: string): void {
    let message: BackendMessage;
    try {
      message = JSON.parse(line) as BackendMessage;
    } catch {
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
    } else {
      pending.reject(new Error(`${message.error?.code ?? "BACKEND_ERROR"}: ${message.error?.message ?? "Unknown error"}`));
    }
  }

  private handleExit(child: ChildProcessWithoutNullStreams, code: number | null, signal: NodeJS.Signals | null): void {
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

  private setState(state: BackendState): void {
    this.state = state;
    this.emitSnapshot();
  }

  private emitSnapshot(): void {
    this.emit("state", this.snapshot());
  }
}

export function resolvePythonExecutable(projectRoot: string, packaged = false): string {
  if (process.env.LMRCHIP_PYTHON?.trim()) {
    return process.env.LMRCHIP_PYTHON;
  }
  if (packaged) {
    return path.join(projectRoot, "python-runtime", "python.exe");
  }
  const localPython = path.join(projectRoot, ".venv-py314", "Scripts", "python.exe");
  return fs.existsSync(localPython) ? localPython : "python";
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
