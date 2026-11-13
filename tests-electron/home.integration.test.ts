import { describe, expect, it } from "vitest";
import { homeExperimentCommand, homeProgress, readProtocolList } from "../electron/renderer/src/homeIntegration";

describe("Home integration contract", () => {
  it("reads the real protocol.list envelope and preserves selection data", () => {
    expect(readProtocolList({ protocols: [{ id: "p1", name: "Saved protocol" }] })).toEqual([{ id: "p1", name: "Saved protocol" }]);
    expect(readProtocolList([{ id: "wrong", name: "shape" }])).toEqual([]);
  });
  it("uses backend progress without recalculating it", () => {
    expect(homeProgress({ progress_percent: 37 })).toBe(37);
    expect(homeProgress({ progress_percent: 140 })).toBe(100);
  });
  it("maps Home controls to the existing backend commands", () => {
    expect(homeExperimentCommand("running", "pause-or-resume")).toBe("experiment.pause");
    expect(homeExperimentCommand("paused", "pause-or-resume")).toBe("experiment.resume");
    expect(homeExperimentCommand("running", "stop")).toBe("experiment.cancel");
  });
  it("keeps backend errors visible to the caller", () => {
    const error = new Error("FLOW_CONTROL_UNAVAILABLE: Flow control is not available.");
    expect(error.message).toContain("FLOW_CONTROL_UNAVAILABLE");
  });
});
