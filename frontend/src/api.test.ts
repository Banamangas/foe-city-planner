import { describe, it, expect, vi, afterEach } from "vitest";
import { parseSSE, improvementToView, attachmentName, apiExportV3, apiLoad } from "./api";
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

  it("keeps the road level when the server sends [x, y, level]", () => {
    const out = improvementToView(
      { k: 1, achieved: 1, roads: [[4, 6, 2]], buildings: {} } as never,
      new Map(), [0, 0], 3, {} as never);
    expect(out.optimized_roads[0].level).toBe(2);
  });
});

describe("Forge Hammer export (plan X)", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("reads the file name from Content-Disposition", () => {
    expect(attachmentName('attachment; filename="essay-optimized.json"', "x")).toBe("essay-optimized.json");
    expect(attachmentName(null, "fallback.json")).toBe("fallback.json");
  });

  it("posts city_id + layout and returns the file, its name and the warnings", async () => {
    const fetchMock = vi.fn(async () => new Response('{"version":3}', {
      status: 200,
      headers: { "Content-Disposition": 'attachment; filename="essay-optimized.json"',
                 "X-Export-Warnings": '["custom 2x2 not exported"]' },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await apiExportV3("abc", { roads: [], buildings: {} });
    expect(fetchMock).toHaveBeenCalledWith("/api/export/v3", expect.objectContaining({ method: "POST" }));
    const body = JSON.parse((fetchMock.mock.calls[0] as any)[1].body);
    expect(body).toEqual({ city_id: "abc", layout: { roads: [], buildings: {} } });
    expect(out.filename).toBe("essay-optimized.json");
    expect(out.warnings).toEqual(["custom 2x2 not exported"]);
    expect(await out.blob.text()).toBe('{"version":3}');
  });

  it("throws the server's error (e.g. re-upload a slim cache)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: "re-upload the city file" }), { status: 400 })));
    await expect(apiExportV3("abc", {})).rejects.toThrow("re-upload the city file");
  });

  it("sends the upload's file name with the city", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await apiLoad({ cityData: {} }, "my city.json");
    expect((fetchMock.mock.calls[0] as any)[0]).toBe("/api/load?name=my%20city.json");
  });
});
