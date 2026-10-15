import { useEffect, useMemo, useState } from "react";


interface HistoryPoint {
  time: number;
  block: number;
  setpoint: number;
}

const disconnected: TemperatureSnapshot = {
  connection_state: "disconnected",
  control_state: "stopped",
  port: null,
  version: null,
  simulation: false,
  latest_sample: null,
  latest_monitoring: null,
};

export function TemperaturePanel({ backendRunning }: { backendRunning: boolean }) {
  const [state, setState] = useState<TemperatureSnapshot>(disconnected);
  const [ports, setPorts] = useState<string[]>([]);
  const [selectedPort, setSelectedPort] = useState("");
  const [setpoint, setSetpoint] = useState(37);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => window.lmrchip.backend.onEvent((message) => {
    if (message.event === "temperature.state") {
      setState(message.data as TemperatureSnapshot);
    } else if (message.event === "temperature.sample") {
      const sample = message.data as TemperatureSample;
      setState((current) => ({ ...current, latest_sample: sample }));
      if (typeof sample.block_temp === "number" && typeof sample.setpoint === "number") {
        const now = Date.now();
        setHistory((current) => [
          ...current.filter((point) => now - point.time <= 600_000),
          { time: now, block: sample.block_temp!, setpoint: sample.setpoint! },
        ].slice(-3000));
      }
    } else if (message.event === "temperature.monitoring") {
      setState((current) => ({ ...current, latest_monitoring: message.data as TemperatureMonitoring }));
    } else if (message.event === "temperature.error") {
      const event = message.data as { code: string; message: string };
      setError(`${event.code}: ${event.message}`);
    }
  }), []);

  useEffect(() => {
    if (backendRunning) {
      void refreshStatus();
      void refreshPorts();
    } else {
      setState(disconnected);
      setPorts([]);
    }
  }, [backendRunning]);

  async function execute(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (result && typeof result === "object" && "connection_state" in result) {
        setState(result as TemperatureSnapshot);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function refreshPorts() {
    try {
      const result = await window.lmrchip.backend.request("temperature.list_ports") as { ports: string[] };
      setPorts(result.ports);
      setSelectedPort((current) => current || result.ports[0] || "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function refreshStatus() {
    try {
      const result = await window.lmrchip.backend.request("temperature.status") as TemperatureSnapshot;
      setState(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  const connected = state.connection_state === "connected";
  const running = state.control_state === "running";
  const sample = state.latest_sample;
  const monitoring = state.latest_monitoring;

  return (
    <section className="temperature-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Module 1</p>
          <h2>Temperature control</h2>
        </div>
        <span className={`state state-${state.connection_state}`}>{state.connection_state}</span>
      </div>

      <div className="temperature-grid">
        <article className="card controls-card">
          <label>Puerto</label>
          <div className="inline-control">
            <select value={selectedPort} disabled={!backendRunning || connected || busy} onChange={(event) => setSelectedPort(event.target.value)}>
              {ports.length === 0 && <option value="">No ports</option>}
              {ports.map((port) => <option key={port}>{port}</option>)}
            </select>
            <button disabled={!backendRunning || connected || busy} onClick={() => void refreshPorts()}>Refresh</button>
          </div>
          <div className="actions">
            <button disabled={!backendRunning || connected || busy || !selectedPort} onClick={() => void execute(() => window.lmrchip.backend.request("temperature.connect", { port: selectedPort }))}>Connect</button>
            <button className="secondary" disabled={!connected || busy} onClick={() => void execute(() => window.lmrchip.backend.request("temperature.disconnect"))}>Disconnect</button>
          </div>

          <label htmlFor="setpoint">Setpoint (°C)</label>
          <input id="setpoint" type="number" min="10" max="80" step="0.1" value={setpoint} disabled={!connected || running || busy} onChange={(event) => setSetpoint(Number(event.target.value))} />
          <div className="actions">
            <button disabled={!connected || running || busy || setpoint < 10 || setpoint > 80} onClick={() => void execute(() => window.lmrchip.backend.request("temperature.start", { setpoint }))}>Start control</button>
            <button className="secondary" disabled={!connected || !running || busy} onClick={() => void execute(() => window.lmrchip.backend.request("temperature.stop"))}>Stop</button>
          </div>
          {state.simulation && <p className="simulation">Simulation mode active</p>}
          {error && <p className="error">{error}</p>}
        </article>

        <article className="card readings-card">
          <h2>Readings</h2>
          <div className="readings">
            <Reading label="Block" value={sample?.block_temp} unit="°C" />
            <Reading label="Active" value={sample?.active_temp} unit="°C" />
            <Reading label="Ambient" value={sample?.ambient_temp} unit="°C" />
            <Reading label="Onboard" value={monitoring?.onboard_temp} unit="°C" />
            <Reading label="Setpoint" value={sample?.setpoint} unit="°C" />
            <Reading label="Output" value={sample?.output} unit="%" />
            <Reading label="Voltage" value={monitoring?.input_voltage} unit="V" />
            <Reading label="Current" value={monitoring?.main_current} unit="A" />
          </div>
          <p className="raw-line">{sample?.raw_line ?? "No A3 data."}</p>
        </article>

        <article className="card chart-card">
          <div className="card-heading"><h2>Last 10 minutes</h2><button className="text-button" onClick={() => setHistory([])}>Clear</button></div>
          <TemperatureChart points={history} />
        </article>
      </div>
    </section>
  );
}

function Reading({ label, value, unit }: { label: string; value: number | null | undefined; unit: string }) {
  return <div><span>{label}</span><strong>{typeof value === "number" ? `${value.toFixed(2)} ${unit}` : "—"}</strong></div>;
}

function TemperatureChart({ points }: { points: HistoryPoint[] }) {
  const geometry = useMemo(() => {
    if (points.length < 2) return null;
    const values = points.flatMap((point) => [point.block, point.setpoint]);
    const min = Math.min(...values) - 0.5;
    const max = Math.max(...values) + 0.5;
    const start = points[0].time;
    const duration = Math.max(points[points.length - 1].time - start, 1);
    const line = (key: "block" | "setpoint") => points.map((point) => {
      const x = ((point.time - start) / duration) * 1000;
      const y = 240 - ((point[key] - min) / (max - min)) * 220;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return { block: line("block"), setpoint: line("setpoint"), min, max };
  }, [points]);

  if (!geometry) return <div className="empty-chart">Waiting for samples...</div>;
  return (
    <div>
      <svg viewBox="0 0 1000 260" role="img" aria-label="Temperature history">
        <line x1="0" y1="20" x2="1000" y2="20" className="grid-line" />
        <line x1="0" y1="240" x2="1000" y2="240" className="grid-line" />
        <polyline points={geometry.setpoint} className="setpoint-line" />
        <polyline points={geometry.block} className="temperature-line" />
      </svg>
      <div className="chart-legend"><span className="block-key">Block</span><span className="setpoint-key">Setpoint</span><span>{geometry.min.toFixed(1)}–{geometry.max.toFixed(1)} °C</span></div>
    </div>
  );
}
