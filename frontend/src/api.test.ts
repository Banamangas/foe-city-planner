import { describe, it, expect } from "vitest";
import { parseSSE, improvementToView } from "./api";
import type { BuildingSummary, Improvement, Palette } from "./types";

describe("parseSSE", () => {
  it("parses complete event records and ignores an incomplete trailer", () => {
    const buf =
      "event: improvement\ndata: {\"k\":92,\"achieved\":79}\n\n" +
      "event: done\ndata: {\"verdict\":\"DONE\"}\n\n" +
      "event: heartbeat\ndata: {\"stat";
    const events = parseSSE(buf);
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ event: "improvement", data: { k: 92, achieved: 79 } });
    expect(events[1]).toEqual({ event: "done", data: { verdict: "DONE" } });
  });
});

describe("improvementToView", () => {
  it("joins metadata by id and converts absolute grid to relative pixels", () => {
    const cell = 12;
    const origin: [number, number] = [3, 5];
    const summary: BuildingSummary[] = [
      { entity_id: "E1", name: "Armory", width: 2, length: 2, needs_road: true, is_townhall: false },
    ];
    const byId = new Map(summary.map((s) => [String(s.entity_id), s]));
    const imp: Improvement = {
      k: 10, achieved: 7,
      roads: [[4, 6]],
      buildings: { E1: [5, 7, 2, 2] },
    };
    const palette = {} as Palette;
    const out = improvementToView(imp, byId, origin, cell, palette);
    // road at abs (4,6) → relative pixel ((4-3)*12,(6-5)*12) = (12,12)
    expect(out.optimized_roads[0]).toEqual({ x: 12, y: 12, level: 1 });
    // building E1 at abs (5,7) size 2x2 → rel px ((5-3)*12,(7-5)*12)=(24,24), w/h 24
    expect(out.buildings[0]).toMatchObject({
      x: 24, y: 24, w: 24, h: 24, name: "Armory", needs_road: true, townhall: false,
    });
  });
});
