"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.RotatingFileLogger = void 0;
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
class RotatingFileLogger {
    directory;
    filename;
    maxBytes;
    backups;
    constructor(directory, filename = "electron.log", maxBytes = 5 * 1024 * 1024, backups = 5) {
        this.directory = directory;
        this.filename = filename;
        this.maxBytes = maxBytes;
        this.backups = backups;
        node_fs_1.default.mkdirSync(directory, { recursive: true });
    }
    write(level, message) {
        try {
            this.rotateIfNeeded();
            const clean = message.replace(/[\r\n]+$/u, "");
            node_fs_1.default.appendFileSync(this.currentPath(), `${new Date().toISOString()} ${level} ${clean}\n`, "utf8");
        }
        catch {
            // Logging must never terminate instrument control.
        }
    }
    currentPath() {
        return node_path_1.default.join(this.directory, this.filename);
    }
    rotateIfNeeded() {
        const current = this.currentPath();
        if (!node_fs_1.default.existsSync(current) || node_fs_1.default.statSync(current).size < this.maxBytes)
            return;
        for (let index = this.backups - 1; index >= 1; index -= 1) {
            const source = `${current}.${index}`;
            if (node_fs_1.default.existsSync(source))
                node_fs_1.default.renameSync(source, `${current}.${index + 1}`);
        }
        node_fs_1.default.renameSync(current, `${current}.1`);
    }
}
exports.RotatingFileLogger = RotatingFileLogger;
