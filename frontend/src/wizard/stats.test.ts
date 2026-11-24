import { describe, expect, it } from "vitest";
import { layoutForExport, statRows } from "./stats";
import type { CityStats, LayoutEntry } from "./types";

const base: CityStats = {
  area: 1000, roads: 90, road_efficiency_pct: null, buildings_pct: 62, roads_pct: 9,
  free_pct: 12, free_cells: 340, with_roads: 5, without_roads: 6, unconnected: [],
};

describe("statRows", () => {
  const rows = statRows(base, { ...base, road_efficiency_pct: 133.3 }, "en");
  it("formats efficiency, null as a dash", () => {
    expect(rows[1]).toEqual({ key: "stat.efficiency", before: "—", after: "133.3%" });
  });
  it("formats the free row", () => {
    expect(rows[4].before).toBe("12% (340)");
  });
  it("keeps the order", () => {
    expect(rows.map((r) => r.key)).toEqual([
      "stat.roads", "stat.efficiency", "stat.buildingsCoverage", "stat.roadsCoverage",
      "stat.free", "stat.withRoads", "stat.withoutRoads",
    ]);
  });
});

describe("layoutForExport", () => {
  const e: LayoutEntry = {
    id: 1, k: 3, achieved: 66, stats: base, legality: { status: "ok" }, roads: [[1, 2, 1]], buildings: {},
  };
  it("omits to_store/added when absent", () => {
    const o = layoutForExport(e);
    expect("to_store" in o).toBe(false);
    expect("added" in o).toBe(false);
  });
  it("keeps them when present", () => {
    const o = layoutForExport({ ...e, to_store: [], added: [] });
    expect(o.to_store).toEqual([]);
    expect(o.added).toEqual([]);
  });
});
