import fs from "node:fs";
import path from "node:path";


export class RotatingFileLogger {
  constructor(
    private readonly directory: string,
    private readonly filename = "electron.log",
    private readonly maxBytes = 5 * 1024 * 1024,
    private readonly backups = 5,
  ) {
    fs.mkdirSync(directory, { recursive: true });
  }

  write(level: "INFO" | "ERROR", message: string): void {
    try {
      this.rotateIfNeeded();
      const clean = message.replace(/[\r\n]+$/u, "");
      fs.appendFileSync(this.currentPath(), `${new Date().toISOString()} ${level} ${clean}\n`, "utf8");
    } catch {
      // Logging must never terminate instrument control.
    }
  }

  private currentPath(): string {
    return path.join(this.directory, this.filename);
  }

  private rotateIfNeeded(): void {
    const current = this.currentPath();
    if (!fs.existsSync(current) || fs.statSync(current).size < this.maxBytes) return;
    for (let index = this.backups - 1; index >= 1; index -= 1) {
      const source = `${current}.${index}`;
      if (fs.existsSync(source)) fs.renameSync(source, `${current}.${index + 1}`);
    }
    fs.renameSync(current, `${current}.1`);
  }
}
