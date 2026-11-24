import type { AddedBuilding, StoredBuilding } from "../types";

export type CityStats = {
  area: number;
  roads: number;
  road_efficiency_pct: number | null;
  buildings_pct: number;
  roads_pct: number;
  free_pct: number;
  free_cells: number;
  with_roads: number;
  without_roads: number;
  unconnected: number[];
};

export type LoadChecks = { unconnected: number[]; loose_chain_pieces: number[] };

export type MachineInfo = {
  workers: number;
  probe_workers: number;
  threads: number;
  logical_cpus: number | null;
  reduced: boolean;
  warn: boolean;
};

export type LayoutEntry = {
  id: number;
  k: number | null;
  achieved: number;
  stats: CityStats;
  legality: { status: string };
  roads: [number, number, number][];
  buildings: Record<string, [number, number, number, number]>;
  to_store?: StoredBuilding[];
  added?: AddedBuilding[];
};

export type RunState = {
  jobId: string;
  state: "running" | "done" | "error";
  stopped: boolean;
  elapsed: number;
  timeBoxS: number;
  phase: string | null;
  maxPhaseIdx: number;
  layoutsFound: number;
  error: string | null;
};
