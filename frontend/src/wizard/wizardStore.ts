import { create } from "zustand";
import { useCityStore } from "../stores/cityStore";
import { mergeLayouts, runKey } from "./run";
import { detectLang, translate } from "./i18n";
import type { Edits } from "../types";
import type { LayoutEntry, RunState } from "./types";
import type { Session } from "./session";

const LANG_KEY = "foeopt.lang";

function readSavedLang(): string | null {
  try {
    return localStorage.getItem(LANG_KEY);
  } catch {
    return null;
  }
}

function initialLang(): string {
  const langs = typeof navigator !== "undefined" ? navigator.languages : [];
  return detectLang(langs ?? [], readSavedLang());
}

export type Step = 1 | 2 | 3 | 4 | 5;

type WizardState = {
  step: Step;
  go: (step: Step) => void;
  lang: string;
  setLang: (lang: string) => void;
  keepUnconnected: number[] | null;
  setKeepUnconnected: (ids: number[] | null) => void;
  run: RunState | null;
  setRun: (patch: Partial<RunState> | null) => void;
  layouts: LayoutEntry[];
  addLayouts: (entries: LayoutEntry[]) => void;
  clearLayouts: () => void;
  /** Drops the run and its layouts (and the layout drawn on the map). */
  invalidateRun: () => void;
  /** True when the stored run was made from the current city, edits and keep choice. */
  resultsAreCurrent: () => boolean;
  selectedId: number | "player" | null;
  select: (id: number | "player" | null) => void;
  /** Name of the loaded city file (kept for "continue where you left off"). */
  fileName: string | null;
  setFileName: (name: string | null) => void;
  /** Desktop app: the last session, offered on step 1 until the player decides. */
  resume: Session | null;
  setResume: (s: Session | null) => void;
  reset: () => void;
};

export const useWizardStore = create<WizardState>((set, get) => ({
  step: 1,
  go: (step) => set({ step }),
  lang: initialLang(),
  setLang: (lang) => {
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch {
      /* storage unavailable: the choice just isn't remembered */
    }
    set({ lang });
  },
  keepUnconnected: null,
  setKeepUnconnected: (ids) => set({ keepUnconnected: ids }),
  run: null,
  setRun: (patch) =>
    set((s) => ({
      run: patch === null ? null : s.run ? { ...s.run, ...patch } : (patch as RunState),
    })),
  layouts: [],
  addLayouts: (entries) => set((s) => ({ layouts: mergeLayouts(s.layouts, entries, s.selectedId) })),
  clearLayouts: () => set({ layouts: [], selectedId: null }),
  invalidateRun: () => {
    set({ run: null, layouts: [], selectedId: null });
    useCityStore.getState().clearOptimized();
  },
  resultsAreCurrent: () => {
    const run = get().run;
    const { city, edits } = useCityStore.getState();
    return !!run && !!city && run.key === currentRunKey(city.city_id, edits, get().keepUnconnected);
  },
  selectedId: null,
  select: (id) => set({ selectedId: id }),
  fileName: null,
  setFileName: (name) => set({ fileName: name }),
  resume: null,
  setResume: (s) => set({ resume: s }),
  reset: () => {
    set({
      step: 1,
      keepUnconnected: null,
      run: null,
      layouts: [],
      selectedId: null,
      fileName: null,
      resume: null,
    });
    useCityStore.getState().reset();
  },
}));

function currentRunKey(cityId: string, edits: Edits, keepUnconnected: number[] | null): string {
  return runKey(cityId, edits, keepUnconnected ?? []);
}

/** resultsAreCurrent() as a hook: re-renders when the run or any of its inputs changes. */
export function useResultsAreCurrent(): boolean {
  const runKeyStored = useWizardStore((s) => s.run?.key ?? null);
  const keepUnconnected = useWizardStore((s) => s.keepUnconnected);
  const cityId = useCityStore((s) => s.city?.city_id ?? null);
  const edits = useCityStore((s) => s.edits);
  return runKeyStored !== null && cityId !== null
    && runKeyStored === currentRunKey(cityId, edits, keepUnconnected);
}

export function useT(): (key: string, vars?: Record<string, string | number>) => string {
  const lang = useWizardStore((s) => s.lang);
  return (key, vars) => translate(lang, key, vars);
}
