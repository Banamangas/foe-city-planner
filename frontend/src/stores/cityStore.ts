import { create } from "zustand";
import type { LoadResponse, BuildingSummary, Improvement, RoadView, BuildingView } from "../types";
import { improvementToView } from "../api";

type Optimized = { roads: RoadView[]; buildings: BuildingView[]; k: number; achieved: number };
type Job = { id: string; state: "running" | "done" | "idle"; elapsed: number };

type CityState = {
  city: LoadResponse | null;
  summaryById: Map<string, BuildingSummary>;
  optimized: Optimized | null;
  optimizedRaw: Improvement | null;
  job: Job | null;
  showCurrent: boolean;
  showOptimized: boolean;
  setCity: (resp: LoadResponse) => void;
  applyImprovement: (imp: Improvement) => void;
  clearOptimized: () => void;
  setJob: (job: Job | null) => void;
  toggleCurrent: () => void;
  toggleOptimized: () => void;
  reset: () => void;
};

export const useCityStore = create<CityState>((set, get) => ({
  city: null,
  summaryById: new Map(),
  optimized: null,
  optimizedRaw: null,
  job: null,
  showCurrent: true,
  showOptimized: true,
  setCity: (resp) =>
    set({
      city: resp,
      summaryById: new Map(resp.buildings.map((b) => [String(b.entity_id), b])),
      optimized: null,
      optimizedRaw: null,
      job: null,
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
      showOptimized: true,
    });
  },
  clearOptimized: () => set({ optimized: null, optimizedRaw: null }),
  setJob: (job) => set({ job }),
  toggleCurrent: () => set((s) => ({ showCurrent: !s.showCurrent })),
  toggleOptimized: () => set((s) => ({ showOptimized: !s.showOptimized })),
  reset: () =>
    set({
      city: null, summaryById: new Map(), optimized: null, optimizedRaw: null,
      job: null, showCurrent: true, showOptimized: true,
    }),
}));
