import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { BackendProcess } from "../electron/main/backend-process";


const projectRoot = path.resolve(__dirname, "..");
const python = process.env.LMRCHIP_PYTHON || path.join(projectRoot, ".venv-py314", "Scripts", "python.exe");
const processes: ChildProcessWithoutNullStreams[] = [];

afterEach(() => {
  for (const child of processes) {
    if (!child.killed) child.kill();
  }
  processes.length = 0;
});

describe("Python service integration", () => {
  it("exchanges JSON Lines and exits after shutdown", async () => {
    const child = spawn(python, ["-m", "lmrchip.service"], {
      cwd: projectRoot,
      env: { ...process.env, PYTHONPATH: path.join(projectRoot, "python") },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    processes.push(child);
    child.stdout.setEncoding("utf8");

    const stdout: string[] = [];
    child.stdout.on("data", (chunk: string) => stdout.push(chunk));
    child.stdin.write('{"version":1,"id":"ping","command":"system.ping","payload":{}}\n');
    child.stdin.write('{"version":1,"id":"stop","command":"system.shutdown","payload":{}}\n');

    const exitCode = await new Promise<number | null>((resolve, reject) => {
      child.once("exit", resolve);
      child.once("error", reject);
    });
    const messages = stdout.join("").trim().split("\n").map((line) => JSON.parse(line));

    expect(exitCode).toBe(0);
    expect(messages.map((message) => message.id)).toEqual(["ping", "stop"]);
    expect(messages.every((message) => message.ok)).toBe(true);
  });

  it("is managed through the same lifecycle used by Electron", async () => {
    const previousPython = process.env.LMRCHIP_PYTHON;
    process.env.LMRCHIP_PYTHON = python;
    const backend = new BackendProcess(projectRoot);

    try {
      const started = await backend.start();
      const status = await backend.request("system.status") as { protocol_version: number };
      const stopped = await backend.stop();

      expect(started.state).toBe("running");
      expect(status.protocol_version).toBe(1);
      expect(stopped.state).toBe("stopped");
      expect(stopped.pid).toBeNull();
    } finally {
      await backend.stop();
      if (previousPython === undefined) {
        delete process.env.LMRCHIP_PYTHON;
      } else {
        process.env.LMRCHIP_PYTHON = previousPython;
      }
    }
  });

  it("streams simulated temperature events through the Electron manager", async () => {
    const previousPython = process.env.LMRCHIP_PYTHON;
    const previousSimulation = process.env.LMRCHIP_SIMULATE_TEMPERATURE;
    process.env.LMRCHIP_PYTHON = python;
    process.env.LMRCHIP_SIMULATE_TEMPERATURE = "1";
    const backend = new BackendProcess(projectRoot);

    try {
      await backend.start();
      const ports = await backend.request("temperature.list_ports") as { ports: string[] };
      const sampleReceived = new Promise<{ event: string }>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("Temperature sample event timed out.")), 3000);
        backend.on("event", (message: { event: string }) => {
          if (message.event === "temperature.sample") {
            clearTimeout(timer);
            resolve(message);
          }
        });
      });

      await backend.request("temperature.connect", { port: "SIMULATED" });
      await sampleReceived;
      const running = await backend.request("temperature.start", { setpoint: 37 }) as { control_state: string };
      const stopped = await backend.request("temperature.stop") as { control_state: string };
      const disconnected = await backend.request("temperature.disconnect") as { connection_state: string };

      expect(ports.ports).toEqual(["SIMULATED"]);
      expect(running.control_state).toBe("running");
      expect(stopped.control_state).toBe("stopped");
      expect(disconnected.connection_state).toBe("disconnected");
    } finally {
      await backend.stop();
      if (previousPython === undefined) delete process.env.LMRCHIP_PYTHON;
      else process.env.LMRCHIP_PYTHON = previousPython;
      if (previousSimulation === undefined) delete process.env.LMRCHIP_SIMULATE_TEMPERATURE;
      else process.env.LMRCHIP_SIMULATE_TEMPERATURE = previousSimulation;
    }
  });

  it("calibrates and tracks the simulated spectrometer through Electron", async () => {
    const previousPython = process.env.LMRCHIP_PYTHON;
    const previousSimulation = process.env.LMRCHIP_SIMULATE_SPECTROMETER;
    process.env.LMRCHIP_PYTHON = python;
    process.env.LMRCHIP_SIMULATE_SPECTROMETER = "1";
    const backend = new BackendProcess(projectRoot);

    try {
      await backend.start();
      const devices = await backend.request("spectrometer.list_devices") as { devices: Array<{ id: string }> };
      await backend.request("spectrometer.connect", { device_id: "SIMULATED" });
      await backend.request("spectrometer.configure", { scans_to_average: 1, delay: 0, boxcar_width: 0 });
      await backend.request("spectrometer.capture_background");
      await backend.request("spectrometer.capture_reference");
      await backend.request("spectrometer.capture_sample");
      const transmission = await backend.request("spectrometer.calculate_transmission") as { values: unknown[] };
      const trackingEvent = new Promise<{ event: string; data: { result: { valid: boolean } } }>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("Spectrometer tracking event timed out.")), 3000);
        backend.on("event", (message: { event: string; data: { result: { valid: boolean } } }) => {
          if (message.event === "spectrometer.tracking") { clearTimeout(timer); resolve(message); }
        });
      });
      await backend.request("spectrometer.start_tracking");
      const tracked = await trackingEvent;
      await backend.request("spectrometer.stop_tracking");
      await backend.request("spectrometer.disconnect");

      expect(devices.devices[0].id).toBe("SIMULATED");
      expect(transmission.values).toHaveLength(1201);
      expect(tracked.data.result.valid).toBe(true);
    } finally {
      await backend.stop();
      if (previousPython === undefined) delete process.env.LMRCHIP_PYTHON;
      else process.env.LMRCHIP_PYTHON = previousPython;
      if (previousSimulation === undefined) delete process.env.LMRCHIP_SIMULATE_SPECTROMETER;
      else process.env.LMRCHIP_SIMULATE_SPECTROMETER = previousSimulation;
    }
  });

  it("calibrates and selects a tube with simulated GRBL through Electron", async () => {
    const previousPython = process.env.LMRCHIP_PYTHON;
    const previousSimulation = process.env.LMRCHIP_SIMULATE_MICROFLUIDICS;
    process.env.LMRCHIP_PYTHON = python;
    process.env.LMRCHIP_SIMULATE_MICROFLUIDICS = "1";
    const backend = new BackendProcess(projectRoot);
    const completed = (operation: string) => new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`${operation} timed out.`)), 3000);
      const listener = (message: { event: string; data: { operation?: string } }) => {
        if (message.event === "microfluidics.operation_completed" && message.data.operation === operation) {
          clearTimeout(timer); backend.removeListener("event", listener); resolve();
        }
      };
      backend.on("event", listener);
    });
    try {
      await backend.start();
      const ports = await backend.request("microfluidics.list_ports") as { ports: string[] };
      await backend.request("microfluidics.connect", { port: "SIMULATED" });
      const calibration = completed("calibrating");
      await backend.request("microfluidics.calibrate"); await calibration;
      const movement = completed("moving_carousel");
      await backend.request("microfluidics.select_tube", { tube_number: 4 }); await movement;
      const state = await backend.request("microfluidics.status") as { current_tube: number; needle_state: string };
      await backend.request("microfluidics.disconnect");
      expect(ports.ports).toEqual(["SIMULATED"]);
      expect(state.current_tube).toBe(4);
      expect(state.needle_state).toBe("lowered");
    } finally {
      await backend.stop();
      if (previousPython === undefined) delete process.env.LMRCHIP_PYTHON; else process.env.LMRCHIP_PYTHON = previousPython;
      if (previousSimulation === undefined) delete process.env.LMRCHIP_SIMULATE_MICROFLUIDICS; else process.env.LMRCHIP_SIMULATE_MICROFLUIDICS = previousSimulation;
    }
  });
});
