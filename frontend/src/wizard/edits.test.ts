import { describe, expect, it } from "vitest";
import { addOne, changesSummary, removeAdded } from "./edits";
import { clickTogglesRemoval, mapLabels } from "../components/CityMap";
import type { CatalogEntry, Edits } from "../types";

const entry = (id: string): CatalogEntry => ({
  id, name: `Name ${id}`, type: "t", width: 3, length: 2, needs_road: true,
  road_level: 1, chain_id: null, is_chain_head: false,
});
const empty = (): Edits => ({ remove: [], add: [] });

describe("step 2 edit helpers", () => {
  it("summarises removed and added counts", () => {
    expect(changesSummary({ remove: [1, 2], add: [{ cityentity_id: "A", count: 2 }] }))
      .toEqual({ removed: 2, added: 2 });
  });
  it("addOne increments the same entry and appends a different one", () => {
    const once = addOne(empty(), entry("A"));
    expect(once.add).toEqual([{ cityentity_id: "A", count: 1, label: "Name A", size: "3x2" }]);
    const twice = addOne(once, entry("A"));
    expect(twice.add).toHaveLength(1);
    expect(twice.add[0].count).toBe(2);
    expect(addOne(twice, entry("B")).add).toHaveLength(2);
  });
  it("removeAdded drops the row", () => {
    const e = addOne(addOne(empty(), entry("A")), entry("B"));
    expect(removeAdded(e, "A").add.map((a) => a.cityentity_id)).toEqual(["B"]);
  });
});

describe("CityMap options", () => {
  it("mapLabels defaults to today's English and merges overrides", () => {
    expect(mapLabels()).toEqual({
      current: "Current", optimized: "Optimized", fit: "Fit", townhall: "townhall",
      needsRoad: "needs road", removedClickToKeep: "removed (click to keep)",
    });
    expect(mapLabels({ fit: "Ajuster" }).fit).toBe("Ajuster");
    expect(mapLabels({ fit: "Ajuster" }).current).toBe("Current");
  });
  it("clicks toggle removal only when editable and in the current view", () => {
    expect(clickTogglesRemoval(true, false)).toBe(true);
    expect(clickTogglesRemoval(false, false)).toBe(false);
    expect(clickTogglesRemoval(true, true)).toBe(false);
  });
});
