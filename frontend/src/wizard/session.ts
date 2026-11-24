// Desktop app: "continue where you left off". The wizard's state is saved on the server
// (one file, overwritten) and offered back on the next start. In the developer setup the
// session routes don't exist and all of this is skipped silently.
import { apiCities, apiCity, apiLoadResult, apiSessionDelete, apiSessionGet, apiSessionPut } from "../api";
import { normalizeEdits } from "../edits";
import { useCityStore } from "../stores/cityStore";
import type { Edits } from "../types";
import { startPinging } from "./desktop";
import { classifyLoadProblem } from "./loadCity";
import type { LayoutEntry } from "./types";
import { useWizardStore, type Step } from "./wizardStore";

export const SESSION_VERSION = 1;
export const SAVE_DEBOUNCE_MS = 1000;

export type Session = {
  version: 1;
  cityId: string;
  fileName: string;
  step: Step;
  edits: Edits;
  keepUnconnected: number[] | null;
  layouts: LayoutEntry[];
  selectedId: number | "player" | null;
  runKey: string | null;
};

/** The wizard's state worth keeping; null while no city is loaded. */
export function toSession(): Session | null {
  const { city, edits } = useCityStore.getState();
  if (!city) return null;
  const w = useWizardStore.getState();
  return {
    version: SESSION_VERSION,
    cityId: city.city_id,
    fileName: w.fileName ?? "",
    step: w.step,
    edits,
    keepUnconnected: w.keepUnconnected,
    layouts: w.layouts,
    selectedId: w.selectedId,
    runKey: w.run?.key ?? null,
  };
}

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isNumberArray = (v: unknown): v is number[] =>
  Array.isArray(v) && v.every((x) => typeof x === "number");

/** A saved session, or null when it is from another version, malformed, or its city is gone. */
export function parseSession(raw: unknown, storedCityIds: string[]): Session | null {
  if (!isObject(raw) || raw.version !== SESSION_VERSION) return null;
  const { cityId, fileName, step, edits, keepUnconnected, layouts, selectedId, runKey } = raw;
  const ok =
    typeof cityId === "string" && storedCityIds.includes(cityId)
    && typeof fileName === "string"
    && [1, 2, 3, 4, 5].includes(step as number)
    && isObject(edits) && Array.isArray(edits.remove) && Array.isArray(edits.add)
    && (keepUnconnected === null || isNumberArray(keepUnconnected))
    && Array.isArray(layouts) && layouts.every((l) => isObject(l) && typeof l.id === "number")
    && (selectedId === null || selectedId === "player" || typeof selectedId === "number")
    && (runKey === null || typeof runKey === "string");
  return ok ? (raw as Session) : null;
}

/** Reloads the saved city and puts the wizard back where it was; false if the city can't be reloaded. */
export async function restoreSession(s: Session, lang: string): Promise<boolean> {
  let stored: { payload?: unknown };
  try {
    stored = await apiCity(s.cityId);
  } catch {
    return false;
  }
  const r = await apiLoadResult(stored?.payload, { fileName: s.fileName || undefined, lang });
  if (!r.ok || classifyLoadProblem({ resp: r.resp }) || r.resp.city_id !== s.cityId) return false;

  useWizardStore.getState().invalidateRun();
  useCityStore.getState().setCity(r.resp);
  useCityStore.getState().setEdits(normalizeEdits(s.edits));
  const keepLayouts = s.layouts.length > 0 && s.runKey !== null;
  useWizardStore.setState({
    fileName: s.fileName,
    keepUnconnected: s.keepUnconnected,
    layouts: keepLayouts ? s.layouts : [],
    selectedId: keepLayouts ? s.selectedId : null,
    run: keepLayouts
      ? {
          jobId: "", key: s.runKey as string, state: "done", stopped: false, elapsed: 0, timeBoxS: 0,
          phase: null, maxPhaseIdx: 0, layoutsFound: s.layouts.length, error: null,
        }
      : null,
    resume: null,
  });
  useWizardStore.getState().go(!keepLayouts && s.step > 3 ? 3 : s.step);
  return true;
}

/** True once GET /api/session showed this is the desktop app (until the wizard stops). */
let desktopMode = false;
/** JSON of the last session saved, so identical saves are skipped. */
let lastSaved = "";

/** Throttled: saves toSession() at most once a second, reading the stores when the timer fires
 *  (a debounce would never fire during a search, whose heartbeat changes the store constantly). */
function startSaving(): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const schedule = () => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      const s = toSession();
      if (!s) return;
      const json = JSON.stringify(s);
      if (json === lastSaved) return;
      lastSaved = json;
      apiSessionPut(s).catch(() => {
        lastSaved = "";
      });
    }, SAVE_DEBOUNCE_MS);
  };
  const unsubWizard = useWizardStore.subscribe(schedule);
  const unsubCity = useCityStore.subscribe(schedule);
  return () => {
    unsubWizard();
    unsubCity();
    if (timer) clearTimeout(timer);
  };
}

/** On wizard start: in the desktop app, ping the server, keep the session saved, and offer
 *  the last session on step 1. Does nothing in the developer setup. Returns a stop function. */
export function startDesktopSession(): () => void {
  let stopped = false;
  const stops: (() => void)[] = [];
  void (async () => {
    const r = await apiSessionGet();
    if (stopped || !r.desktop) return;
    desktopMode = true;
    stops.push(startPinging(), startSaving());
    if (r.session === null) return;
    const ids = await apiCities().then((list) => list.map((c) => c.id)).catch(() => [] as string[]);
    if (stopped) return;
    const s = parseSession(r.session, ids);
    if (s && !useCityStore.getState().city) useWizardStore.getState().setResume(s);
  })();
  return () => {
    stopped = true;
    desktopMode = false;
    stops.forEach((stop) => stop());
  };
}

/** The player starts over: the next launch must not offer the city they just left. */
export function forgetSession(): void {
  if (!desktopMode) return;
  lastSaved = "";
  void apiSessionDelete().catch(() => undefined);
}
