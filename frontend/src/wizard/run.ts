import type { Edits } from "../types";
import type { LayoutEntry } from "./types";

export const RUN_PRESETS_MIN = [2, 5, 15];
export const DEFAULT_MINUTES = 5;
export const CUSTOM_MIN = 1;
export const CUSTOM_MAX = 120;

/** The checklist shown during a run; each step covers some server phases (null = before any phase). */
export const PHASE_STEPS: { key: string; phases: (string | null)[] }[] = [
  { key: "phase.reading", phases: [null, "seed"] },
  { key: "phase.sketching", phases: ["walk"] },
  { key: "phase.fitting", phases: ["objective_polish", "union_polish", "rebased_polish"] },
  { key: "phase.trying", phases: ["mutation_polish", "seed_polish"] },
  { key: "phase.finishing", phases: ["exact"] },
];

/** The checklist step of `phase`; never goes backwards, unknown phases keep `previousMax`. */
export function phaseIndex(phase: string | null, previousMax: number): number {
  const i = PHASE_STEPS.findIndex((s) => s.phases.includes(phase));
  return Math.max(previousMax, i);
}

export function progressPct(elapsed: number, timeBoxS: number, finished: boolean): number {
  if (finished) return 100;
  if (timeBoxS <= 0) return 0;
  return Math.max(0, Math.min(99, Math.floor((100 * elapsed) / timeBoxS)));
}

export function timeLeft(elapsed: number, timeBoxS: number): string {
  const s = Math.max(0, Math.ceil(timeBoxS - elapsed));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** No `workers` / `probe_workers`: the server sizes them to the machine. */
export function buildOptimizeBody(a: {
  cityId: string;
  best: Record<string, unknown>;
  minutes: number;
  edits: Edits;
  keepUnconnected: number[];
}): Record<string, unknown> {
  return {
    ...a.best,
    city_id: a.cityId,
    time_box: a.minutes * 60,
    edits: a.edits,
    keep_unconnected: a.keepUnconnected,
    relink_chains: true,
  };
}

/** JSON with object keys sorted, so equal values always serialize the same way. */
function stableStringify(v: unknown): string {
  return JSON.stringify(v, (_k, x) =>
    x && typeof x === "object" && !Array.isArray(x)
      ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]]))
      : x,
  );
}

/** Identifies a run's inputs (city, the edits the server receives, kept unconnected buildings):
 *  results stay valid only while the current inputs give the same key. */
export function runKey(cityId: string, edits: Edits, keepUnconnected: number[]): string {
  return stableStringify({
    city_id: cityId,
    edits,
    keep_unconnected: [...keepUnconnected].sort((a, b) => a - b),
  });
}

/** Unique by id (incoming wins), sorted by roads then id, so the order is stable while layouts stream in. */
export function mergeLayouts(existing: LayoutEntry[], incoming: LayoutEntry[]): LayoutEntry[] {
  const byId = new Map<number, LayoutEntry>();
  for (const e of existing) byId.set(e.id, e);
  for (const e of incoming) byId.set(e.id, e);
  return [...byId.values()].sort((a, b) => a.stats.roads - b.stats.roads || a.id - b.id);
}

export function startDecision(
  r: { ok: true } | { ok: false; status: number; body: any },
  alreadyRetried: boolean,
): "started" | { stopThenRetry: string } | "failed" {
  if (r.ok) return "started";
  const id = r.body?.active_job_id;
  if (r.status === 409 && typeof id === "string" && id && !alreadyRetried) return { stopThenRetry: id };
  return "failed";
}

export function afterRun(layouts: LayoutEntry[], state: "done" | "error"): "choose" | "none_found" | "failed" {
  if (layouts.length > 0) return "choose";
  return state === "error" ? "failed" : "none_found";
}
