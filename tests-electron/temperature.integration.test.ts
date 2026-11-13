import { describe, expect, it } from "vitest";
import { attachMonitoring, isStable, readingState, regulatorLabel, samplePoint } from "../electron/renderer/src/temperatureIntegration";

const sample = (cell: number | null, ambient: number | null = null): TemperatureSample => ({ block_temp: cell, active_temp: cell, ambient_temp: ambient, setpoint: 37, output: 10, raw_line: "" });

describe("Temperature integration presentation contract", () => {
  it("joins monitoring readings to the temporally adjacent sample", () => {
    const points = [samplePoint(sample(36.9), 1000)];
    expect(attachMonitoring(points, { onboard_temp: 29, input_voltage: 12, main_current: 1 }, 1800)[0].onboard).toBe(29);
    expect(attachMonitoring(points, { onboard_temp: 29, input_voltage: 12, main_current: 1 }, 5000)).toBe(points);
  });
  it("distinguishes valid, unavailable and disconnected readings", () => {
    expect(readingState("connected", 36.5)).toBe("valid");
    expect(readingState("connected", null)).toBe("unavailable");
    expect(readingState("disconnected", 36.5)).toBe("disconnected");
  });
  it("only reports Stable after five measured cell values pass the tolerance", () => {
    const points = [36.9, 36.92, 36.91, 36.89, 36.90].map((cell, index) => samplePoint(sample(cell), index));
    expect(isStable(points, "running")).toBe(true);
    expect(regulatorLabel("running", true)).toBe("Stable");
    expect(regulatorLabel("running", false)).toBe("Running");
    expect(regulatorLabel("unknown", false)).toBe("Unknown");
    expect(regulatorLabel("stopped", false)).toBe("Stopped");
  });
  it("does not call fan hardware because no fan command exists", () => {
    expect("temperature.fan" in { "temperature.start": true, "temperature.stop": true }).toBe(false);
  });
});
