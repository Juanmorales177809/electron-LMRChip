export type ViewRange = { min: number; max: number };

export function validateViewRange(min: number, max: number): string | null {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) return "Minimum wavelength must be lower than maximum wavelength.";
  return null;
}

export function filterSpectrum(wavelengths: Array<number | null>, values: Array<number | null>, range: ViewRange) {
  return wavelengths.map((wavelength, index) => [wavelength, values[index]] as const).filter((pair): pair is [number, number] => typeof pair[0] === "number" && pair[0] >= range.min && pair[0] <= range.max && typeof pair[1] === "number" && Number.isFinite(pair[1]));
}

export function markerX(wavelength: number, range: ViewRange, left = 55, width = 925) {
  return left + ((wavelength - range.min) / Math.max(range.max - range.min, 1)) * width;
}

export function peakStatus(result: SpectrumPayload["result"]): "No measurement" | "Invalid result" | "Available" {
  if (!result) return "No measurement";
  return result.valid && result.wavelength !== null && result.transmission !== null ? "Available" : "Invalid result";
}

export function trackingTimestamp(timestamp: number | undefined, fallback: number) { return typeof timestamp === "number" && Number.isFinite(timestamp) ? timestamp * 1000 : fallback; }
export function acquisitionCommands() { return ["spectrometer.capture_sample", "spectrometer.detect_resonance"] as const; }
export function validateSpectrometerSettings(settings: SpectrometerSettings): string | null {
  if (!Number.isFinite(settings.integration_time) || settings.integration_time <= 0) return "Integration time must be greater than zero.";
  if (!Number.isInteger(settings.scans_to_average) || settings.scans_to_average < 1) return "Scans to average must be a positive integer.";
  if (!Number.isFinite(settings.delay) || settings.delay < 0) return "Delay must be zero or greater.";
  if (!Number.isInteger(settings.boxcar_width) || settings.boxcar_width < 0) return "Boxcar width must be a non-negative integer.";
  if (settings.search_min_nm >= settings.search_max_nm) return "LMR search minimum must be lower than maximum.";
  if (!Number.isInteger(settings.smoothing_window) || settings.smoothing_window < 1 || settings.tracking_half_window_nm <= 0 || settings.tracking_interval_ms < 0) return "Tracking filter parameters are invalid.";
  return null;
}
