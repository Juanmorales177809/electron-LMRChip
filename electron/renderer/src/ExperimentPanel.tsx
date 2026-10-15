import { useEffect, useState } from "react";


const initial: ExperimentSnapshot = {
  state: "idle", phase: "idle", config: null, result_directory: null,
  current_tube: null, completed_tubes: [], total_tubes: 0, pause_requested: false,
  error: null, started_at: null, finished_at: null,
};

export function ExperimentPanel({ backendRunning }: { backendRunning: boolean }) {
  const [snapshot, setSnapshot] = useState<ExperimentSnapshot>(initial);
  const [folder, setFolder] = useState("");
  const [tubes, setTubes] = useState("1,2,3,4,5,6,7,8,9,10,11,12");
  const [setpoint, setSetpoint] = useState(37);
  const [tolerance, setTolerance] = useState(0.2);
  const [stableSeconds, setStableSeconds] = useState(60);
  const [timeoutMinutes, setTimeoutMinutes] = useState(30);
  const [trackingSeconds, setTrackingSeconds] = useState(60);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const remove = window.lmrchip.backend.onEvent((event) => {
      if (["experiment.state", "experiment.progress", "experiment.completed", "experiment.cancelled", "experiment.failed"].includes(event.event)) {
        setSnapshot(event.data as ExperimentSnapshot);
      }
    });
    if (backendRunning) void refresh();
    else setSnapshot(initial);
    return remove;
  }, [backendRunning]);

  async function refresh() {
    try { setSnapshot(await window.lmrchip.backend.request("experiment.status") as ExperimentSnapshot); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
  }

  function payload() {
    return {
      results_root: folder,
      tubes: tubes.split(",").map((value) => Number(value.trim())).filter((value) => Number.isFinite(value)),
      setpoint, temperature_tolerance: tolerance, stable_seconds: stableSeconds,
      stabilization_timeout_seconds: timeoutMinutes * 60, tracking_seconds: trackingSeconds,
    };
  }

  async function run(command: string, body: Record<string, unknown> = {}) {
    setBusy(true); setMessage("");
    try { setSnapshot(await window.lmrchip.backend.request(command, body) as ExperimentSnapshot); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function chooseFolder() {
    const selected = await window.lmrchip.selectResultsDirectory();
    if (selected) setFolder(selected);
  }

  async function start() {
    if (!window.confirm("The experiment will move the carousel and needle. Confirm that the area is clear and the physical stop is accessible.")) return;
    await run("experiment.start", payload());
  }

  async function cancel() {
    if (window.confirm("Cancel the experiment? Acquisition will stop and the needle will be raised if possible.")) {
      await run("experiment.cancel");
    }
  }

  const active = snapshot.state === "running" || snapshot.state === "paused";
  const progress = snapshot.total_tubes ? snapshot.completed_tubes.length / snapshot.total_tubes * 100 : 0;

  return <section className="temperature-section experiment-section">
    <div className="section-heading">
      <div><p className="eyebrow">Orchestration</p><h2>Experiment</h2></div>
      <span className={`state state-${snapshot.state}`}>{snapshot.state}</span>
    </div>
    <div className="experiment-grid">
      <article className="card controls-card">
        <label>Results folder</label>
        <div className="inline-control"><input value={folder} readOnly placeholder="Select a folder"/><button disabled={active} onClick={() => void chooseFolder()}>Choose</button></div>
        <label>Tubes, in order</label><input value={tubes} disabled={active} onChange={(e) => setTubes(e.target.value)}/>
        <div className="settings-grid">
          <div><label>Setpoint (°C)</label><input type="number" step="0.1" value={setpoint} disabled={active} onChange={(e) => setSetpoint(Number(e.target.value))}/></div>
          <div><label>Tolerancia (±°C)</label><input type="number" step="0.1" value={tolerance} disabled={active} onChange={(e) => setTolerance(Number(e.target.value))}/></div>
          <div><label>Stability (s)</label><input type="number" value={stableSeconds} disabled={active} onChange={(e) => setStableSeconds(Number(e.target.value))}/></div>
          <div><label>Timeout (min)</label><input type="number" value={timeoutMinutes} disabled={active} onChange={(e) => setTimeoutMinutes(Number(e.target.value))}/></div>
          <div><label>Measurement per tube (s)</label><input type="number" value={trackingSeconds} disabled={active} onChange={(e) => setTrackingSeconds(Number(e.target.value))}/></div>
        </div>
        <div className="actions">
          <button disabled={!backendRunning || active || busy || !folder} onClick={() => void start()}>Start experiment</button>
          <button className="secondary" disabled={snapshot.state !== "running" || busy || snapshot.pause_requested} onClick={() => void run("experiment.pause")}>Pause</button>
          <button disabled={snapshot.state !== "paused" || busy} onClick={() => void run("experiment.resume")}>Resume</button>
          <button className="secondary" disabled={!active || busy} onClick={() => void cancel()}>Cancel</button>
        </div>
      </article>
      <article className="card">
        <h2>Progress</h2>
        <div className="progress-track"><div style={{ width: `${progress}%` }}/></div>
        <dl className="machine-state">
          <div><dt>Phase</dt><dd>{snapshot.phase}</dd></div>
          <div><dt>Current tube</dt><dd>{snapshot.current_tube ?? "—"}</dd></div>
          <div><dt>Completed</dt><dd>{snapshot.completed_tubes.length} / {snapshot.total_tubes}</dd></div>
          <div><dt>Pause requested</dt><dd>{snapshot.pause_requested ? "yes" : "no"}</dd></div>
        </dl>
        {snapshot.result_directory && <p className="result-path">Results: {snapshot.result_directory}</p>}
        {snapshot.error && <p className="error">{snapshot.error.code}: {snapshot.error.message}</p>}
        {message && <p className="error">{message}</p>}
        <p className="safety-warning">Temperature remains active when paused, cancelled, or failed. Always use the physical stop in an unsafe condition.</p>
      </article>
    </div>
  </section>;
}
