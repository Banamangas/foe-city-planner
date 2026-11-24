import { describe, expect, it } from "vitest";
import {
  afterRun, buildOptimizeBody, mergeLayouts, phaseIndex, progressPct, startDecision, timeLeft,
} from "./run";
import type { LayoutEntry } from "./types";

const entry = (id: number, roads: number) => ({ id, stats: { roads } }) as unknown as LayoutEntry;

describe("phaseIndex", () => {
  it("maps phases to steps, never backwards", () => {
    expect(phaseIndex(null, 0)).toBe(0);
    expect(phaseIndex("walk", 0)).toBe(1);
    expect(phaseIndex("rebased_polish", 1)).toBe(2);
    expect(phaseIndex("exact", 2)).toBe(4);
    expect(phaseIndex("seed_polish", 4)).toBe(4);
    expect(phaseIndex("mystery", 2)).toBe(2);
  });
});

describe("progressPct / timeLeft", () => {
  it("computes progress", () => {
    expect(progressPct(150, 300, false)).toBe(50);
    expect(progressPct(400, 300, false)).toBe(99);
    expect(progressPct(10, 300, true)).toBe(100);
  });
  it("formats time left", () => {
    expect(timeLeft(0, 300)).toBe("5:00");
    expect(timeLeft(299, 300)).toBe("0:01");
    expect(timeLeft(400, 300)).toBe("0:00");
  });
});

describe("buildOptimizeBody", () => {
  it("overlays the run choices on the preset, without worker counts", () => {
    const b = buildOptimizeBody({
      cityId: "c1", best: { patterns: 200 }, minutes: 5, edits: { remove: [], add: [] }, keepUnconnected: [7],
    });
    expect(b.time_box).toBe(300);
    expect(b.patterns).toBe(200);
    expect(b.keep_unconnected).toEqual([7]);
    expect(b.relink_chains).toBe(true);
    expect(b.city_id).toBe("c1");
    expect("workers" in b).toBe(false);
    expect("probe_workers" in b).toBe(false);
  });
});

describe("mergeLayouts", () => {
  it("sorts by roads then id", () => {
    const m = mergeLayouts([entry(2, 70)], [entry(1, 70), entry(3, 68)]);
    expect(m.map((e) => e.id)).toEqual([3, 1, 2]);
  });
  it("does not duplicate and lets the incoming copy win", () => {
    const m = mergeLayouts([entry(2, 70)], [entry(2, 69)]);
    expect(m).toHaveLength(1);
    expect(m[0].stats.roads).toBe(69);
  });
});

describe("startDecision", () => {
  it("retries once after a 409", () => {
    const r = { ok: false as const, status: 409, body: { active_job_id: "j1" } };
    expect(startDecision(r, false)).toEqual({ stopThenRetry: "j1" });
    expect(startDecision(r, true)).toBe("failed");
    expect(startDecision({ ok: true }, false)).toBe("started");
    expect(startDecision({ ok: false, status: 500, body: {} }, false)).toBe("failed");
  });
});

describe("afterRun", () => {
  it("decides what follows a run", () => {
    expect(afterRun([], "done")).toBe("none_found");
    expect(afterRun([entry(1, 5)], "done")).toBe("choose");
    expect(afterRun([], "error")).toBe("failed");
  });
});
