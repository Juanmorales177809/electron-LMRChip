import { describe, expect, it } from "vitest";
import { acquisitionCommands, filterSpectrum, markerX, peakStatus, trackingTimestamp, validateSpectrometerSettings, validateViewRange } from "../electron/renderer/src/opticsIntegration";

describe("Optics integration presentation contract", () => {
  it("validates and applies independent View limits", () => {
    expect(validateViewRange(700, 650)).toContain("lower");
    expect(filterSpectrum([640, 700, 760], [1, 2, 3], { min: 650, max: 750 })).toEqual([[700, 2]]);
  });
  it("positions the marker against the active graph axis", () => {
    expect(markerX(700, { min: 650, max: 750 })).toBe(517.5);
    expect(markerX(700, { min: 680, max: 720 })).toBe(517.5);
  });
  it("uses backend tracking timestamps and preserves fallback behavior", () => {
    expect(trackingTimestamp(1700000000, 123)).toBe(1700000000000);
    expect(trackingTimestamp(undefined, 123)).toBe(123);
  });
  it("distinguishes peak states without inventing results", () => {
    expect(peakStatus(undefined)).toBe("No measurement");
    expect(peakStatus({ valid: false, wavelength: null, transmission: null, r_squared: null, prominence: null, reason: "No peak" })).toBe("Invalid result");
    expect(peakStatus({ valid: true, wavelength: 702, transmission: 0.8, r_squared: 0.99, prominence: 1, reason: "" })).toBe("Available");
  });
  it("uses the existing backend acquisition pipeline", () => {
    expect(acquisitionCommands()).toEqual(["spectrometer.capture_sample", "spectrometer.detect_resonance"]);
  });
  it("validates parameters before sending them to the backend", () => {
    const valid = { integration_time: 100, scans_to_average: 1, delay: 0, boxcar_width: 0, search_min_nm: 650, search_max_nm: 750, fit_half_window_nm: 1, smoothing_window: 3, tracking_half_window_nm: 10, tracking_interval_ms: 250 };
    expect(validateSpectrometerSettings(valid)).toBeNull();
    expect(validateSpectrometerSettings({ ...valid, scans_to_average: 0 })).toContain("Scans");
  });
});
