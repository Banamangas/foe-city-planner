import { create } from "zustand";
import type { LoadResponse, BuildingSummary, Improvement, RoadView, BuildingView } from "../types";
import { improvementToView } from "../api";

type Optimized = { roads: RoadView[]; buildings: BuildingView[]; k: number; achieved: number };
type Job = { id: string; state: "running" | "done" | "idle"; elapsed: number };
type ViewMode = "current" | "optimized";

type CityState = {
  city: LoadResponse | null;
  summaryById: Map<string, BuildingSummary>;
  optimized: Optimized | null;
  optimizedRaw: Improvement | null;
  job: Job | null;
  viewMode: ViewMode;
  setCity: (resp: LoadResponse) => void;
  applyImprovement: (imp: Improvement) => void;
  clearOptimized: () => void;
  setJob: (job: Job | null) => void;
  setViewMode: (mode: ViewMode) => void;
  reset: () => void;
};

export const useCityStore = create<CityState>((set, get) => ({
  city: null,
  summaryById: new Map(),
  optimized: null,
  optimizedRaw: null,
  job: null,
  viewMode: "current",
  setCity: (resp) =>
    set({
      city: resp,
      summaryById: new Map(resp.buildings.map((b) => [String(b.entity_id), b])),
      optimized: null,
      optimizedRaw: null,
      job: null,
      viewMode: "current",
    }),
  applyImprovement: (imp) => {
    const city = get().city;
    if (!city) return;
    const mv = city.map_view;
    const { optimized_roads, buildings } = improvementToView(
      imp, get().summaryById, mv.origin, mv.cell, mv.palette,
    );
    set({
      optimized: { roads: optimized_roads, buildings, k: imp.k, achieved: imp.achieved },
      optimizedRaw: imp,
      viewMode: "optimized",
    });
  },
  clearOptimized: () => set({ optimized: null, optimizedRaw: null, viewMode: "current" }),
  setJob: (job) => set({ job }),
  setViewMode: (mode) => set({ viewMode: mode }),
  reset: () =>
    set({
      city: null, summaryById: new Map(), optimized: null, optimizedRaw: null,
      job: null, viewMode: "current",
    }),
}));
