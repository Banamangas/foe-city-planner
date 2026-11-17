import { describe, it, expect } from "vitest";
import {
  addAt, catalogAdd, chainMains, chainNotices, customAdd, dropAddAt, emptyEdits, forServer,
  isEmptyEdits, normalizeEdits, sameTypeIds, setRelink, setRemoved, toggleRemove, withAdded,
} from "./edits";
import type { BuildingSummary, CatalogEntry, EditReport } from "./types";

const B = (id: number, extra: Partial<BuildingSummary> = {}): BuildingSummary => ({
  entity_id: id, name: `b${id}`, width: 2, length: 2, needs_road: false, is_townhall: false,
  cityentity_id: `C${id}`, ...extra,
});
const buildings = [
  B(1, { is_townhall: true, name: "Town Hall" }),
  B(2, { cityentity_id: "HOUSE", name: "House" }), B(3, { cityentity_id: "HOUSE", name: "House" }),
  B(10, { chain_id: "farm", is_chain_head: true, name: "Farm" }),
  B(11, { chain_id: "farm", is_chain_head: false, name: "Field" }),
  B(20, { chain_id: "farm", is_chain_head: true, name: "Farm 2" }),
];

describe("removal edits", () => {
  it("toggles a building and never the Town Hall", () => {
    let e = toggleRemove(emptyEdits(), 2, buildings);
    expect(e.remove).toEqual([2]);
    e = toggleRemove(e, 1, buildings);
    expect(e.remove).toEqual([2]);
    e = toggleRemove(e, 2, buildings);
    expect(isEmptyEdits(e)).toBe(true);
  });

  it("removes all of a type", () => {
    const ids = sameTypeIds(buildings, buildings[1]);
    expect(ids).toEqual([2, 3]);
    expect(setRemoved(emptyEdits(), ids, true, buildings).remove).toEqual([2, 3]);
    expect(sameTypeIds(buildings, buildings[0])).toEqual([]);   // townhall excluded
  });

  it("drops a relink when its main is kept again", () => {
    let e = setRemoved(emptyEdits(), [10], true, buildings);
    e = setRelink(e, 10, 20);
    expect(e.relink).toEqual({ "10": 20 });
    e = setRemoved(e, [10], false, buildings);
    expect(e.relink).toEqual({});
  });
});

describe("additions", () => {
  const field: CatalogEntry = {
    id: "FIELD", name: "Field", type: "decoration", width: 1, length: 2, needs_road: false,
    road_level: 0, chain_id: "farm", is_chain_head: false,
  };

  it("builds catalog and custom specs and strips UI labels for the server", () => {
    let e = addAt(emptyEdits(), catalogAdd(field, 3, 20));
    e = addAt(e, customAdd(3, 4, true, " Wonder ", 1));
    expect(forServer(e)).toEqual({
      remove: [],
      add: [{ cityentity_id: "FIELD", count: 3, link_to: 20 },
            { width: 3, length: 4, needs_road: true, name: "Wonder", count: 1 }],
    });
    expect(dropAddAt(e, 0).add).toHaveLength(1);
    expect(catalogAdd(field, 999).count).toBe(50);
  });

  it("lists the chain's main buildings still on the map", () => {
    expect(chainMains(buildings, "farm", emptyEdits()).map((b) => b.entity_id)).toEqual([10, 20]);
    const e = setRemoved(emptyEdits(), [20], true, buildings);
    expect(chainMains(buildings, "farm", e).map((b) => b.entity_id)).toEqual([10]);
  });

  it("normalizes a saved edit set", () => {
    expect(normalizeEdits(null)).toEqual({ remove: [], add: [], relink: {} });
    expect(normalizeEdits({ remove: [4], add: [] }).relink).toEqual({});
  });
});

describe("report notices and result names", () => {
  const report = {
    reattached: [{ removed: 11, moved: [12, 13], to: 10, to_name: "Farm", ok: true }],
    cascades: [{ main: 20, main_name: "Farm 2", stored: [21], relink_candidates: [{ entity_id: 10, name: "Farm" }] }],
    warnings: ["careful"],
  } as unknown as EditReport;

  it("says which pieces are reattached and which go to store", () => {
    const n = chainNotices(report, (id) => `P${id}`);
    expect(n[0]).toMatchObject({ kind: "reattach", ids: [12, 13] });
    expect(n[0].text).toBe("P11 removed: P12, P13 will be reattached to Farm");
    expect(n[1]).toMatchObject({ kind: "store", main: 20 });
    expect(n[1].candidates).toEqual([{ entity_id: 10, name: "Farm" }]);
    expect(n[2]).toEqual({ kind: "warn", text: "careful" });
  });

  it("names added buildings from the catalog", () => {
    const m = withAdded(new Map(), [{
      entity_id: 99, cityentity_id: "HOUSE", name: "House", width: 2, length: 2,
      needs_road: true, road_level: 1, chain_id: null, link_to: null, placed: true, x: 0, y: 0,
    }]);
    expect(m.get("99")?.name).toBe("House (new)");
    expect(m.get("99")?.needs_road).toBe(true);
  });
});
