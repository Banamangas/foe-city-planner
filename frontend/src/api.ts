import type {
  LoadResponse, CityListItem, LayoutListItem, Improvement,
  BuildingSummary, BuildingView, RoadView, Palette, OptionsResponse,
  CatalogEntry, EditReport, Edits,
} from "./types";
import type { LayoutEntry } from "./wizard/types";

export function parseSSE(buffer: string): { event: string; data: any }[] {
  const out: { event: string; data: any }[] = [];
  const records = buffer.split("\n\n");
  for (const record of records) {
    if (!record.includes("data:")) continue;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of record.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    try {
      out.push({ event, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      // incomplete/invalid JSON (partial trailing record) — skip
    }
  }
  return out;
}

export function improvementToView(
  imp: Improvement,
  summaryById: Map<string, BuildingSummary>,
  origin: [number, number],
  cell: number,
  _palette: Palette,
): { optimized_roads: RoadView[]; buildings: BuildingView[] } {
  const [ox, oy] = origin;
  const optimized_roads: RoadView[] = imp.roads.map(([x, y, level]) => ({
    x: (x - ox) * cell, y: (y - oy) * cell, level: level ?? 1,
  }));
  const buildings: BuildingView[] = [];
  for (const id of Object.keys(imp.buildings)) {
    const [x, y, w, l] = imp.buildings[id];
    const meta = summaryById.get(id);
    buildings.push({
      id,
      x: (x - ox) * cell, y: (y - oy) * cell, w: w * cell, h: l * cell,
      name: meta?.name ?? id, size: `${w}x${l}`,
      needs_road: meta?.needs_road ?? false, townhall: meta?.is_townhall ?? false,
    });
  }
  return { optimized_roads, buildings };
}

async function jsonPost(path: string, body: unknown): Promise<any> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ?? `${path} failed (${r.status})`);
  return data;
}

async function jsonGet(path: string): Promise<any> {
  const r = await fetch(path);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ?? `${path} failed (${r.status})`);
  return data;
}

/** `fileName` names the Forge Hammer export (`<name>-optimized.json`). */
export const apiLoad = (slim: unknown, fileName?: string): Promise<LoadResponse> =>
  jsonPost(fileName ? `/api/load?name=${encodeURIComponent(fileName)}` : "/api/load", slim);
export type CustomBuildings = Record<string, { width: number; length: number; road: 0 | 1 | 2 }>;

/** Like apiLoad, but never throws: the wizard needs the status and body of a refusal. */
export async function apiLoadResult(
  slim: unknown,
  opts: { fileName?: string; lang: string; custom?: CustomBuildings },
): Promise<{ ok: true; resp: LoadResponse } | { ok: false; status: number; body: any }> {
  const q = new URLSearchParams({ lang: opts.lang });
  if (opts.fileName) q.set("name", opts.fileName);
  const body =
    opts.custom && Object.keys(opts.custom).length > 0
      ? { ...(slim as object), custom_buildings: opts.custom }
      : slim;
  try {
    const r = await fetch(`/api/load?${q}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    return r.ok ? { ok: true, resp: data } : { ok: false, status: r.status, body: data };
  } catch (err) {
    return { ok: false, status: 0, body: { error: String(err) } };
  }
}
export const apiOptions = (): Promise<OptionsResponse> => jsonGet("/api/options");
/** Run parameters ride along untyped: /api/options declares them, the server validates them. */
export const apiOptimize = (
  body: { city_id: string } & Record<string, unknown>,
): Promise<{ job_id: string; options: Record<string, unknown> }> => jsonPost("/api/optimize", body);
/** Like apiOptimize, but never throws: the wizard needs the status and body of a refusal. */
export async function apiOptimizeResult(
  body: Record<string, unknown>,
): Promise<{ ok: true; job_id: string } | { ok: false; status: number; body: any }> {
  try {
    const r = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    return r.ok ? { ok: true, job_id: data.job_id } : { ok: false, status: r.status, body: data };
  } catch (err) {
    return { ok: false, status: 0, body: { error: String(err) } };
  }
}
export const apiCatalog = (q: string, cityId?: string, lang?: string): Promise<{ results: CatalogEntry[] }> =>
  jsonGet(`/api/catalog?q=${encodeURIComponent(q)}${cityId ? `&city_id=${encodeURIComponent(cityId)}` : ""}${lang ? `&lang=${encodeURIComponent(lang)}` : ""}`);
export const apiPreviewEdits = (cityId: string, edits: Edits): Promise<{ report: EditReport }> =>
  jsonPost("/api/edits/preview", { city_id: cityId, edits });
export async function apiSaveEdits(cityId: string, edits: Edits): Promise<void> {
  await fetch(`/api/cities/${encodeURIComponent(cityId)}/edits`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits),
  });
}
export const apiStop = (jobId: string): Promise<any> => jsonPost(`/api/stop/${jobId}`, {});
export const apiCities = (): Promise<CityListItem[]> => jsonGet("/api/cities");
/** Desktop mode is told apart from the developer setup (where these routes are plain 404 pages)
 *  by the exact body of the "no session" answer. Never throws. */
export async function apiSessionGet(): Promise<{ desktop: false } | { desktop: true; session: unknown | null }> {
  try {
    const r = await fetch("/api/session");
    const data = await r.json().catch(() => undefined);
    if (r.ok && data !== undefined) return { desktop: true, session: data };
    if (r.status === 404 && data?.error === "no session") return { desktop: true, session: null };
  } catch {
    /* network error: not the desktop app */
  }
  return { desktop: false };
}
export async function apiSessionPut(session: unknown): Promise<void> {
  const r = await fetch("/api/session", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(session),
  });
  if (!r.ok) throw new Error(`session save failed (${r.status})`);
}
export async function apiSessionDelete(): Promise<void> {
  await fetch("/api/session", { method: "DELETE" });
}
export async function apiPing(): Promise<void> {
  await fetch("/api/ping", { method: "POST" });
}
export const apiCity = (id: string): Promise<any> => jsonGet(`/api/cities/${id}`);
export const apiLayouts = (cityId?: string): Promise<LayoutListItem[]> =>
  jsonGet(cityId ? `/api/layouts?city_id=${encodeURIComponent(cityId)}` : "/api/layouts");
export const apiLayout = (id: string): Promise<any> => jsonGet(`/api/layouts/${id}`);
export const apiSaveLayout = (body: unknown): Promise<{ id: string }> => jsonPost("/api/layouts", body);
export const apiDeleteLayout = (id: string): Promise<any> =>
  fetch(`/api/layouts/${id}`, { method: "DELETE" }).then((r) => r.json());

/** The file name in a Content-Disposition header, or `fallback`. */
export function attachmentName(header: string | null, fallback: string): string {
  const m = /filename="([^"]+)"/.exec(header ?? "");
  return m ? m[1] : fallback;
}

/** The result as a v3 city file for Forge Hammer (plan X): the original upload
 *  with mapBuildings = this layout and storedBuildings = the buildings to store. */
export async function apiExportV3(
  cityId: string, layout: unknown,
): Promise<{ blob: Blob; filename: string; warnings: string[] }> {
  const r = await fetch("/api/export/v3", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ city_id: cityId, layout }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data.error ?? `export failed (${r.status})`);
  }
  let warnings: string[] = [];
  try { warnings = JSON.parse(r.headers.get("X-Export-Warnings") ?? "[]"); } catch { /* none */ }
  return {
    blob: await r.blob(),
    filename: attachmentName(r.headers.get("Content-Disposition"), `${cityId}-optimized.json`),
    warnings,
  };
}

export function openStream(
  jobId: string,
  handlers: {
    onImprovement?: (data: Improvement) => void;
    onHeartbeat?: (data: any) => void;
    onLayout?: (entry: LayoutEntry) => void;
    /** The connection failed; check `es.readyState === 2` (CLOSED) for a stream that will not come back. */
    onError?: (es: EventSource) => void;
    onDone?: (data: any) => void;
  },
): EventSource {
  const es = new EventSource(`/api/stream/${jobId}`);
  es.addEventListener("improvement", (e) => handlers.onImprovement?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("layout", (e) => handlers.onLayout?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("heartbeat", (e) => handlers.onHeartbeat?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("done", (e) => {
    handlers.onDone?.(JSON.parse((e as MessageEvent).data));
    es.close();
  });
  es.onerror = () => handlers.onError?.(es);
  return es;
}
