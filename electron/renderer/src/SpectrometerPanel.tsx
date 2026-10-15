import { useEffect, useMemo, useState } from "react";

const defaults: SpectrometerSettings = {
  integration_time: 100, scans_to_average: 10, delay: 0.05, boxcar_width: 2,
  search_min_nm: 650, search_max_nm: 750, fit_half_window_nm: 1.5,
  smoothing_window: 9, tracking_half_window_nm: 15, tracking_interval_ms: 250,
};
const disconnected: SpectrometerSnapshot = {
  connection_state: "disconnected", device_id: null, simulation: false, tracking: false,
  has_background: false, has_reference: false, has_sample: false, settings: defaults,
};

export function SpectrometerPanel({ backendRunning }: { backendRunning: boolean }) {
  const [state, setState] = useState(disconnected);
  const [devices, setDevices] = useState<SpectrometerDevice[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [settings, setSettings] = useState(defaults);
  const [spectrum, setSpectrum] = useState<SpectrumPayload | null>(null);
  const [history, setHistory] = useState<Array<{ time: number; wavelength: number | null }>>([]);
  const [saturation, setSaturation] = useState<string>("No diagnostics");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => window.lmrchip.backend.onEvent((message) => {
    if (message.event === "spectrometer.state") setState(message.data as SpectrometerSnapshot);
    if (message.event === "spectrometer.spectrum" || message.event === "spectrometer.transmission") setSpectrum(message.data as SpectrumPayload);
    if (message.event === "spectrometer.tracking") {
      const data = message.data as SpectrumPayload;
      setSpectrum(data);
      const now = Date.now();
      setHistory((current) => [...current.filter((point) => now - point.time <= 600_000), { time: now, wavelength: data.result?.wavelength ?? null }].slice(-2400));
    }
    if (message.event === "spectrometer.saturation") {
      const data = message.data as { max_counts: number; is_saturated: boolean; is_near_saturation: boolean };
      setSaturation(`${data.max_counts.toFixed(0)} counts · ${data.is_saturated ? "Saturated" : data.is_near_saturation ? "Near saturation" : "OK"}`);
    }
    if (message.event === "spectrometer.error") {
      const data = message.data as { code: string; message: string };
      setError(`${data.code}: ${data.message}`);
    }
  }), []);

  useEffect(() => {
    if (backendRunning) { void refreshDevices(); void refreshStatus(); }
    else { setState(disconnected); setDevices([]); }
  }, [backendRunning]);

  async function execute(action: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try {
      const result = await action();
      if (result && typeof result === "object" && "connection_state" in result) setState(result as SpectrometerSnapshot);
      if (result && typeof result === "object" && "wavelengths" in result) setSpectrum(result as SpectrumPayload);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }
  async function refreshDevices() {
    try {
      const result = await window.lmrchip.backend.request("spectrometer.list_devices") as { devices: SpectrometerDevice[] };
      setDevices(result.devices); setDeviceId((current) => current || result.devices[0]?.id || "");
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
  }
  async function refreshStatus() {
    try { const result = await window.lmrchip.backend.request("spectrometer.status") as SpectrometerSnapshot; setState(result); setSettings(result.settings); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
  }
  const connected = state.connection_state === "connected";
  const locked = busy || state.tracking;
  const update = (key: keyof SpectrometerSettings, value: number) => setSettings((current) => ({ ...current, [key]: value }));

  return <section className="temperature-section">
    <div className="section-heading"><div><p className="eyebrow">Module 2</p><h2>Spectrometer and LMR tracking</h2></div><span className={`state state-${state.connection_state}`}>{state.connection_state}</span></div>
    <div className="spectrometer-grid">
      <article className="card controls-card">
        <label>Device</label><div className="inline-control"><select value={deviceId} disabled={!backendRunning || connected || busy} onChange={(e) => setDeviceId(e.target.value)}>{devices.length === 0 && <option value="">No devices</option>}{devices.map((d) => <option key={d.id} value={d.id}>{d.model} · {d.serial}</option>)}</select><button disabled={!backendRunning || connected || busy} onClick={() => void refreshDevices()}>Refresh</button></div>
        <div className="actions"><button disabled={!deviceId || connected || busy} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.connect", { device_id: deviceId }))}>Connect</button><button className="secondary" disabled={!connected || busy} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.disconnect"))}>Disconnect</button></div>
        <div className="settings-grid">
          <NumberField label="Integration (ms)" value={settings.integration_time} set={(v) => update("integration_time", v)} />
          <NumberField label="Averages" value={settings.scans_to_average} set={(v) => update("scans_to_average", v)} />
          <NumberField label="Delay (s)" value={settings.delay} step={0.01} set={(v) => update("delay", v)} />
          <NumberField label="Boxcar" value={settings.boxcar_width} set={(v) => update("boxcar_width", v)} />
          <NumberField label="Search minimum" value={settings.search_min_nm} set={(v) => update("search_min_nm", v)} />
          <NumberField label="Search maximum" value={settings.search_max_nm} set={(v) => update("search_max_nm", v)} />
        </div>
        <button disabled={!connected || locked} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.configure", { ...settings }))}>Apply configuration</button>
        {state.simulation && <p className="simulation">Simulation mode active</p>}{error && <p className="error">{error}</p>}
      </article>
      <article className="card">
        <h2>Calibration and acquisition</h2>
        <div className="calibration-status"><span className={state.has_background ? "done" : ""}>Background</span><span className={state.has_reference ? "done" : ""}>Reference</span><span className={state.has_sample ? "done" : ""}>Sample</span></div>
        <div className="actions vertical-actions"><button disabled={!connected || locked} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.capture_background"))}>Capture background</button><button disabled={!connected || locked} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.capture_reference"))}>Capture reference</button><button disabled={!connected || locked} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.capture_sample"))}>Capture sample</button><button disabled={!state.has_sample || locked} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.calculate_transmission"))}>Calculate transmission</button></div>
        <p className="diagnostic">{saturation}</p>
        <div className="actions"><button disabled={!state.has_background || !state.has_reference || state.tracking || busy} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.start_tracking"))}>Start tracking</button><button className="secondary" disabled={!state.tracking || busy} onClick={() => void execute(() => window.lmrchip.backend.request("spectrometer.stop_tracking"))}>Stop tracking</button></div>
      </article>
      <article className="card chart-card"><h2>{spectrum?.result ? "Transmission and resonance" : "Spectrum"}</h2><SpectrumChart data={spectrum} /></article>
      <article className="card chart-card"><div className="card-heading"><h2>LMR position · last 10 minutes</h2><button className="text-button" onClick={() => setHistory([])}>Clear</button></div><ResonanceChart points={history} /></article>
    </div>
  </section>;
}

function NumberField({ label, value, set, step = 1 }: { label: string; value: number; set: (value: number) => void; step?: number }) { return <label>{label}<input type="number" value={value} step={step} onChange={(e) => set(Number(e.target.value))} /></label>; }

function SpectrumChart({ data }: { data: SpectrumPayload | null }) {
  const points = useMemo(() => chartPoints(data?.wavelengths ?? [], data?.values ?? []), [data]);
  if (!points) return <div className="empty-chart">No spectrum.</div>;
  return <div><svg viewBox="0 0 1000 260"><polyline points={points} className="temperature-line" /></svg>{data?.result && <p className="diagnostic">LMR: {data.result.valid && data.result.wavelength !== null ? `${data.result.wavelength.toFixed(3)} nm · R² ${data.result.r_squared?.toFixed(4)}` : data.result.reason}</p>}</div>;
}
function ResonanceChart({ points }: { points: Array<{ time: number; wavelength: number | null }> }) {
  const finite = points.filter((p): p is { time: number; wavelength: number } => p.wavelength !== null);
  const geometry = useMemo(() => chartPoints(finite.map((p) => p.time), finite.map((p) => p.wavelength)), [points]);
  return geometry ? <svg viewBox="0 0 1000 260"><polyline points={geometry} className="temperature-line" /></svg> : <div className="empty-chart">Waiting for a valid resonance...</div>;
}
function chartPoints(xs: Array<number | null>, ys: Array<number | null>) {
  const pairs = xs.map((x, i) => [x, ys[i]] as const).filter((p): p is readonly [number, number] => p[0] !== null && p[1] !== null);
  if (pairs.length < 2) return null;
  const minX = Math.min(...pairs.map((p) => p[0])), maxX = Math.max(...pairs.map((p) => p[0]));
  const minY = Math.min(...pairs.map((p) => p[1])), maxY = Math.max(...pairs.map((p) => p[1]));
  return pairs.map(([x, y]) => `${(((x - minX) / Math.max(maxX - minX, 1)) * 1000).toFixed(1)},${(240 - ((y - minY) / Math.max(maxY - minY, 1)) * 220).toFixed(1)}`).join(" ");
}
