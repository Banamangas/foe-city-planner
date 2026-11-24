import type { CityStats, LayoutEntry } from "./types";

export type StatRow = { key: string; before: string; after: string };

export function statRows(before: CityStats, after: CityStats, lang: string): StatRow[] {
  const num = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  const pct = (v: number) => `${num.format(v)}%`;
  const eff = (v: number | null) => (v === null ? "—" : pct(v));
  const free = (s: CityStats) => `${pct(s.free_pct)} (${num.format(s.free_cells)})`;
  return [
    { key: "stat.roads", before: num.format(before.roads), after: num.format(after.roads) },
    { key: "stat.efficiency", before: eff(before.road_efficiency_pct), after: eff(after.road_efficiency_pct) },
    { key: "stat.buildingsCoverage", before: pct(before.buildings_pct), after: pct(after.buildings_pct) },
    { key: "stat.roadsCoverage", before: pct(before.roads_pct), after: pct(after.roads_pct) },
    { key: "stat.free", before: free(before), after: free(after) },
    { key: "stat.withRoads", before: num.format(before.with_roads), after: num.format(after.with_roads) },
    { key: "stat.withoutRoads", before: num.format(before.without_roads), after: num.format(after.without_roads) },
  ];
}

export function layoutForExport(e: LayoutEntry): Record<string, unknown> {
  const out: Record<string, unknown> = {
    k: e.k, achieved: e.achieved, roads: e.roads, buildings: e.buildings,
  };
  if (e.to_store) out.to_store = e.to_store;
  if (e.added) out.added = e.added;
  return out;
}
