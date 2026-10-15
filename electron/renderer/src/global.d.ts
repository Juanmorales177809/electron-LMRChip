export {};

declare global {
type BackendState = "stopped" | "starting" | "running" | "stopping" | "crashed";

interface BackendSnapshot {
  state: BackendState;
  pid: number | null;
  lastError: string | null;
}

interface BackendStatus {
  process: BackendSnapshot;
  service: {
    state: string;
    service_version: string;
    protocol_version: number;
    python_version: string;
    process_id: number;
    temperature: TemperatureSnapshot;
  } | null;
}
interface ResourceDiagnostics {
  packaged: boolean; pythonExecutable: string; pythonPackage: string;
  pythonFound: boolean; packageFound: boolean; valid: boolean;
}

interface TemperatureSample {
  block_temp: number | null;
  ambient_temp: number | null;
  active_temp: number | null;
  setpoint: number | null;
  output: number | null;
  raw_line: string;
}

interface TemperatureMonitoring {
  onboard_temp: number | null;
  input_voltage: number | null;
  main_current: number | null;
}

interface TemperatureSnapshot {
  connection_state: "disconnected" | "connected" | "unknown";
  control_state: "stopped" | "running" | "unknown";
  port: string | null;
  version: string | null;
  simulation: boolean;
  latest_sample: TemperatureSample | null;
  latest_monitoring: TemperatureMonitoring | null;
}

interface BackendEvent {
  version: number;
  type: "event";
  event: string;
  data: unknown;
}

interface SpectrometerDevice { id: string; model: string; serial: string; }
interface SpectrometerSettings {
  integration_time: number; scans_to_average: number; delay: number; boxcar_width: number;
  search_min_nm: number; search_max_nm: number; fit_half_window_nm: number;
  smoothing_window: number; tracking_half_window_nm: number; tracking_interval_ms: number;
}
interface SpectrometerSnapshot {
  connection_state: "disconnected" | "connected" | "unknown";
  device_id: string | null; simulation: boolean; tracking: boolean;
  has_background: boolean; has_reference: boolean; has_sample: boolean;
  settings: SpectrometerSettings;
}
interface SpectrumPayload {
  kind?: string; wavelengths: Array<number | null>; values: Array<number | null>;
  diagnostics?: Record<string, unknown>;
  result?: { valid: boolean; wavelength: number | null; transmission: number | null; r_squared: number | null; prominence: number | null; reason: string };
  timestamp?: number;
}
interface MicrofluidicsSnapshot {
  connection_state: "disconnected" | "connected" | "unknown";
  operation_state: string; busy: boolean; calibrated: boolean;
  current_tube: number | null; needle_state: "raised" | "lowered" | "unknown";
  last_grbl_status: string | null; simulation: boolean;
}
interface ExperimentConfig {
  tubes: number[]; setpoint: number; temperature_tolerance: number;
  stable_seconds: number; stabilization_timeout_seconds: number; tracking_seconds: number;
}
interface ExperimentSnapshot {
  state: "idle" | "running" | "paused" | "completed" | "cancelled" | "failed";
  phase: string; config: ExperimentConfig | null; result_directory: string | null;
  current_tube: number | null; completed_tubes: number[]; total_tubes: number;
  pause_requested: boolean; error: { code: string; message: string } | null;
  started_at: string | null; finished_at: string | null;
}

  interface Window {
    lmrchip: {
      selectResultsDirectory(): Promise<string | null>;
      backend: {
        start(): Promise<BackendSnapshot>;
        stop(): Promise<BackendSnapshot>;
        status(): Promise<BackendStatus>;
        diagnostics(): Promise<ResourceDiagnostics>;
        request(command: string, payload?: Record<string, unknown>): Promise<unknown>;
        onEvent(callback: (event: BackendEvent) => void): () => void;
        onStateChange(callback: (state: BackendSnapshot) => void): () => void;
        onLog(callback: (message: string) => void): () => void;
      };
    };
  }
}
