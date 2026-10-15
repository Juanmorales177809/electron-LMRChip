import { useEffect, useState } from "react";

import { TemperaturePanel } from "./TemperaturePanel";
import { SpectrometerPanel } from "./SpectrometerPanel";
import { MicrofluidicsPanel } from "./MicrofluidicsPanel";
import { ExperimentPanel } from "./ExperimentPanel";


const initialState: BackendSnapshot = { state: "stopped", pid: null, lastError: null };

export function App() {
  const [backend, setBackend] = useState<BackendSnapshot>(initialState);
  const [status, setStatus] = useState<BackendStatus["service"]>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [diagnostics, setDiagnostics] = useState<ResourceDiagnostics | null>(null);

  useEffect(() => {
    const removeState = window.lmrchip.backend.onStateChange(setBackend);
    const removeLog = window.lmrchip.backend.onLog((message) => {
      setLogs((current) => [...current.slice(-99), message]);
    });
    void refreshStatus();
    void window.lmrchip.backend.diagnostics().then(setDiagnostics).catch(() => setDiagnostics(null));
    return () => {
      removeState();
      removeLog();
    };
  }, []);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await refreshStatus();
    } catch (error) {
      setLogs((current) => [...current, error instanceof Error ? error.message : String(error)]);
    } finally {
      setBusy(false);
    }
  }

  async function refreshStatus() {
    try {
      const result = await window.lmrchip.backend.status();
      setBackend(result.process);
      setStatus(result.service);
    } catch (error) {
      setLogs((current) => [...current, error instanceof Error ? error.message : String(error)]);
    }
  }

  const isRunning = backend.state === "running";

  return (
    <main className="shell">
      <header>
        <div>
          <p className="eyebrow">Experimental system</p>
          <h1>LMRChip Desktop</h1>
          <p className="subtitle">Electron–Python communication diagnostics</p>
        </div>
        <span className={`state state-${backend.state}`}>{backend.state}</span>
      </header>

      <section className="grid">
        <article className="card">
          <h2>Python backend</h2>
          <dl>
            <div><dt>State</dt><dd>{backend.state}</dd></div>
            <div><dt>PID</dt><dd>{backend.pid ?? "—"}</dd></div>
            <div><dt>Python</dt><dd>{status?.python_version ?? "—"}</dd></div>
            <div><dt>Service</dt><dd>{status?.service_version ?? "—"}</dd></div>
            <div><dt>Protocol</dt><dd>{status?.protocol_version ?? "—"}</dd></div>
            <div><dt>Resources</dt><dd>{diagnostics?.valid ? "ready" : "incomplete"}</dd></div>
          </dl>
          {backend.lastError && <p className="error">{backend.lastError}</p>}
          <div className="actions">
            <button disabled={busy || isRunning} onClick={() => void run(() => window.lmrchip.backend.start())}>Start</button>
            <button disabled={busy || !isRunning} onClick={() => void run(() => window.lmrchip.backend.request("system.ping"))}>Ping</button>
            <button disabled={busy} onClick={() => void run(refreshStatus)}>Refresh</button>
            <button className="secondary" disabled={busy || !isRunning} onClick={() => void run(() => window.lmrchip.backend.stop())}>Stop</button>
          </div>
        </article>

        <article className="card logs-card">
          <div className="card-heading">
            <h2>Log</h2>
            <button className="text-button" onClick={() => setLogs([])}>Clear</button>
          </div>
          <pre>{logs.length ? logs.join("\n") : "No messages."}</pre>
        </article>
      </section>
      <TemperaturePanel backendRunning={isRunning} />
      <SpectrometerPanel backendRunning={isRunning} />
      <MicrofluidicsPanel backendRunning={isRunning} />
      <ExperimentPanel backendRunning={isRunning} />
    </main>
  );
}
