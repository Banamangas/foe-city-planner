import { create } from "zustand";
import { useCityStore } from "../stores/cityStore";
import { detectLang, translate } from "./i18n";
import type { LayoutEntry, RunState } from "./types";

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
  selectedId: number | "player" | null;
  select: (id: number | "player" | null) => void;
  reset: () => void;
};

export const useWizardStore = create<WizardState>((set) => ({
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
  // Plain append for now; Task 6 swaps in mergeLayouts.
  addLayouts: (entries) => set((s) => ({ layouts: [...s.layouts, ...entries] })),
  selectedId: null,
  select: (id) => set({ selectedId: id }),
  reset: () => {
    set({
      step: 1,
      keepUnconnected: null,
      run: null,
      layouts: [],
      selectedId: null,
    });
    useCityStore.getState().reset();
  },
}));

export function useT(): (key: string, vars?: Record<string, string | number>) => string {
  const lang = useWizardStore((s) => s.lang);
  return (key, vars) => translate(lang, key, vars);
}
