import { create } from "zustand";
import type { LoadResponse, BuildingSummary, Improvement, RoadView, BuildingView } from "../types";
import { improvementToView } from "../api";

type Optimized = { roads: RoadView[]; buildings: BuildingView[]; k: number; achieved: number };
/** Terminal report from the server's `done` event (webapp/app.py). */
export type JobResult = {
  verdict?: string; best_achieved?: number | null;
  legality?: { status: string; violations: unknown[]; military?: string };
  [key: string]: unknown;
};
export type Job = {
  id: string; cityId: string;
  state: "submitting" | "running" | "done" | "error";
  elapsed: number; error?: string | null; result?: JobResult | null; stopped?: boolean;
};
type ViewMode = "current" | "optimized";

type CityState = {
  city: LoadResponse | null;
  summaryById: Map<string, BuildingSummary>;
  optimized: Optimized | null;
  optimizedRaw: Improvement | null;
  job: Job | null;
  viewMode: ViewMode;
  setCity: (resp: LoadResponse) => void;
  /** `jobId`: drop the improvement unless it belongs to the current job of the
   *  current city (a stream from a previous city/run must not leak in). */
  applyImprovement: (imp: Improvement, jobId?: string) => void;
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
  applyImprovement: (imp, jobId) => {
    const city = get().city;
    if (!city) return;
    if (jobId !== undefined) {
      const job = get().job;
      if (!job || job.id !== jobId || job.cityId !== city.city_id) return;
    }
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
