import { useEffect, useState } from "react";

const disconnected: MicrofluidicsSnapshot = { connection_state: "disconnected", operation_state: "idle", busy: false, calibrated: false, current_tube: null, needle_state: "unknown", last_grbl_status: null, simulation: false };

export function MicrofluidicsPanel({ backendRunning }: { backendRunning: boolean }) {
  const [state, setState] = useState(disconnected);
  const [ports, setPorts] = useState<string[]>([]);
  const [port, setPort] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => window.lmrchip.backend.onEvent((message) => {
    if (message.event === "microfluidics.state") setState(message.data as MicrofluidicsSnapshot);
    if (message.event === "microfluidics.operation_started") setState(message.data as MicrofluidicsSnapshot);
    if (message.event === "microfluidics.operation_completed") setState((message.data as { state: MicrofluidicsSnapshot }).state);
    if (message.event === "microfluidics.error") { const data = message.data as { code: string; message: string }; setError(`${data.code}: ${data.message}`); }
  }), []);
  useEffect(() => { if (backendRunning) { void refreshPorts(); void refreshStatus(); } else { setState(disconnected); setPorts([]); } }, [backendRunning]);

  async function execute(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { const result = await action(); if (result && typeof result === "object" && "connection_state" in result) setState(result as MicrofluidicsSnapshot); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }
  async function refreshPorts() { try { const result = await window.lmrchip.backend.request("microfluidics.list_ports") as { ports: string[] }; setPorts(result.ports); setPort((current) => current || result.ports[0] || ""); } catch (caught) { setError(String(caught)); } }
  async function refreshStatus() { try { setState(await window.lmrchip.backend.request("microfluidics.status") as MicrofluidicsSnapshot); } catch (caught) { setError(String(caught)); } }
  const connected = state.connection_state === "connected";
  const disabled = busy || state.busy;
  const confirmRun = (message: string, action: () => Promise<unknown>) => { if (window.confirm(message)) void execute(action); };

  return <section className="temperature-section">
    <div className="section-heading"><div><p className="eyebrow">Module 3</p><h2>Microfluidic system</h2></div><span className={`state state-${state.connection_state}`}>{state.connection_state}</span></div>
    <div className="microfluidics-grid">
      <article className="card controls-card">
        <label>GRBL port</label><div className="inline-control"><select value={port} disabled={!backendRunning || connected || disabled} onChange={(e) => setPort(e.target.value)}>{ports.length === 0 && <option value="">No ports</option>}{ports.map((item) => <option key={item}>{item}</option>)}</select><button disabled={!backendRunning || connected || disabled} onClick={() => void refreshPorts()}>Refresh</button></div>
        <div className="actions"><button disabled={!port || connected || disabled} onClick={() => void execute(() => window.lmrchip.backend.request("microfluidics.connect", { port }))}>Connect</button><button className="secondary" disabled={!connected || disabled} onClick={() => confirmRun("Disconnect GRBL? Confirm that the machine is stopped.", () => window.lmrchip.backend.request("microfluidics.disconnect"))}>Disconnect</button></div>
        <button disabled={!connected || disabled} onClick={() => confirmRun("Calibration will home the machine and move the carousel. Is the area clear?", () => window.lmrchip.backend.request("microfluidics.calibrate"))}>Calibrate system</button>
        <dl className="machine-state"><div><dt>Operation</dt><dd>{state.operation_state}</dd></div><div><dt>Calibrated</dt><dd>{state.calibrated ? "Yes" : "No"}</dd></div><div><dt>Needle</dt><dd>{state.needle_state}</dd></div><div><dt>GRBL</dt><dd>{state.last_grbl_status ?? "—"}</dd></div></dl>
        {state.simulation && <p className="simulation">Simulation mode active</p>}{error && <p className="error">{error}</p>}
      </article>
      <article className="card">
        <h2>Tube carousel</h2><div className="tube-grid">{Array.from({ length: 12 }, (_, index) => index + 1).map((tube) => <button key={tube} className={state.current_tube === tube ? "tube active" : "tube"} disabled={!state.calibrated || disabled} onClick={() => confirmRun(`The carousel will move to tube ${tube} and lower the needle. Continue?`, () => window.lmrchip.backend.request("microfluidics.select_tube", { tube_number: tube }))}>{tube}</button>)}</div>
        <div className="actions"><button disabled={!state.calibrated || disabled || state.needle_state === "raised"} onClick={() => confirmRun("Raise the needle?", () => window.lmrchip.backend.request("microfluidics.raise_needle"))}>Raise needle</button><button disabled={!state.calibrated || disabled || state.needle_state === "lowered"} onClick={() => confirmRun("Lower the needle? Confirm that the path is clear.", () => window.lmrchip.backend.request("microfluidics.lower_needle"))}>Lower needle</button></div>
        <p className="safety-warning">In an emergency, use the machine's physical stop. The application is not an emergency stop.</p>
      </article>
    </div>
  </section>;
}
