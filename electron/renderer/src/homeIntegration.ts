export type HomeCommand = "experiment.pause" | "experiment.resume" | "experiment.cancel";

export function readProtocolList(value: unknown): Array<{ id: string; name: string }> {
  if (!value || typeof value !== "object") return [];
  const protocols = (value as { protocols?: unknown }).protocols;
  return Array.isArray(protocols) ? protocols.filter((item): item is { id: string; name: string } => Boolean(item && typeof item === "object" && typeof (item as { id?: unknown }).id === "string" && typeof (item as { name?: unknown }).name === "string")) : [];
}

export function homeProgress(snapshot: { progress_percent?: number }) {
  return Math.max(0, Math.min(100, snapshot.progress_percent ?? 0));
}

export function homeExperimentCommand(state: "running" | "paused", action: "pause-or-resume" | "stop"): HomeCommand {
  if (action === "stop") return "experiment.cancel";
  return state === "paused" ? "experiment.resume" : "experiment.pause";
}
