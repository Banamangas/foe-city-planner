import { describe, it, expect, beforeEach } from "vitest";
import { useCityStore } from "./cityStore";
import type { LoadResponse, Improvement, MapView } from "../types";

const mapView: MapView = {
  cell: 12, origin: [0, 0], width: 24, height: 24,
  region: [[0, 0]], buildings: [], current_roads: [], optimized_roads: null,
  palette: {} as never,
};

const resp: LoadResponse = {
  city_id: "c1",
  buildings: [
    { entity_id: "E1", name: "Armory", width: 2, length: 2, needs_road: true, is_townhall: false },
  ],
  region_cells: 1, road_estimate: 3, map_view: mapView,
};

describe("cityStore", () => {
  beforeEach(() => useCityStore.getState().reset());

  it("setCity stores the response and builds summaryById", () => {
    useCityStore.getState().setCity(resp);
    const s = useCityStore.getState();
    expect(s.city?.city_id).toBe("c1");
    expect(s.summaryById.get("E1")?.name).toBe("Armory");
    expect(s.viewMode).toBe("current");
  });

  it("applyImprovement converts and stores optimized layout", () => {
    useCityStore.getState().setCity(resp);
    const imp: Improvement = { k: 10, achieved: 7, roads: [[1, 1]], buildings: { E1: [2, 2, 2, 2] } };
    useCityStore.getState().applyImprovement(imp);
    const s = useCityStore.getState();
    expect(s.optimized?.achieved).toBe(7);
    expect(s.optimized?.roads[0]).toEqual({ x: 12, y: 12, level: 1 });
    expect(s.optimized?.buildings[0].name).toBe("Armory");
    expect(s.viewMode).toBe("optimized");
  });

  it("reset clears everything", () => {
    useCityStore.getState().setCity(resp);
    useCityStore.getState().reset();
    expect(useCityStore.getState().city).toBeNull();
  });

  it("drops improvements from a job that is not the current city's job", () => {
    useCityStore.getState().setCity(resp);
    const imp: Improvement = { k: 10, achieved: 7, roads: [[1, 1]], buildings: { E1: [2, 2, 2, 2] } };
    useCityStore.getState().setJob({ id: "j2", cityId: "c1", state: "running", elapsed: 0 });
    useCityStore.getState().applyImprovement(imp, "j1");          // stale job
    expect(useCityStore.getState().optimized).toBeNull();
    useCityStore.getState().setJob({ id: "j1", cityId: "other", state: "running", elapsed: 0 });
    useCityStore.getState().applyImprovement(imp, "j1");          // other city
    expect(useCityStore.getState().optimized).toBeNull();
    useCityStore.getState().setJob({ id: "j1", cityId: "c1", state: "running", elapsed: 0 });
    useCityStore.getState().applyImprovement(imp, "j1");
    expect(useCityStore.getState().optimized?.achieved).toBe(7);
  });
});
