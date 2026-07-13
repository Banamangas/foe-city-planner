import { describe, it, expect } from "vitest";
import { regionBounds, fitTransform, screenToGrid, buildingAt } from "./geometry";
import type { MapView, BuildingView } from "./types";

const view: MapView = {
  cell: 12,
  origin: [3, 5],
  width: 72,
  height: 72,
  region: [[0, 0], [12, 0], [0, 12], [60, 60]],
  buildings: [
    { x: 0, y: 0, w: 24, h: 24, name: "TH", size: "2x2", needs_road: false, townhall: true },
    { x: 36, y: 24, w: 12, h: 12, name: "Hut", size: "1x1", needs_road: true, townhall: false },
  ],
  current_roads: [],
  optimized_roads: null,
  palette: {} as never,
};

describe("geometry", () => {
  it("regionBounds returns grid-cell bounds from pixel region", () => {
    expect(regionBounds(view)).toEqual({ minGX: 0, minGY: 0, maxGX: 5, maxGY: 5 });
  });

  it("fitTransform centers and scales to fit", () => {
    const t = fitTransform(view, 600, 600);
    expect(t.scale).toBeGreaterThan(0);
    expect(Number.isFinite(t.offsetX)).toBe(true);
    expect(Number.isFinite(t.offsetY)).toBe(true);
  });

  it("screenToGrid inverts the transform to absolute grid cells", () => {
    const t = { offsetX: 0, offsetY: 0, scale: 1 };
    // pixel (0,0) at cell 12 → grid-relative (0,0) → absolute (origin) (3,5)
    const g = screenToGrid(0, 0, t, view.cell, view.origin);
    expect(g).toEqual({ gx: 3, gy: 5 });
    // pixel (13,25) → relative cell (1,2) → absolute (4,7)
    expect(screenToGrid(13, 25, t, view.cell, view.origin)).toEqual({ gx: 4, gy: 7 });
  });

  it("buildingAt hit-tests in relative grid units", () => {
    const bs: BuildingView[] = view.buildings;
    // absolute grid (3,5) → relative (0,0) → inside TH (0..2, 0..2)
    expect(buildingAt(3, 5, bs, view.origin, view.cell)?.name).toBe("TH");
    // absolute grid (6,7) → relative (3,2) → inside Hut at rel (3,2) size 1x1
    expect(buildingAt(6, 7, bs, view.origin, view.cell)?.name).toBe("Hut");
    // empty cell
    expect(buildingAt(8, 9, bs, view.origin, view.cell)).toBeNull();
  });
});
