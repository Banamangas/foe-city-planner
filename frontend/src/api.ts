import type {
  LoadResponse, CityListItem, LayoutListItem, Improvement,
  BuildingSummary, BuildingView, RoadView, Palette, OptionsResponse,
  CatalogEntry, EditReport, Edits,
} from "./types";

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
export const apiOptions = (): Promise<OptionsResponse> => jsonGet("/api/options");
/** Run parameters ride along untyped: /api/options declares them, the server validates them. */
export const apiOptimize = (
  body: { city_id: string } & Record<string, unknown>,
): Promise<{ job_id: string; options: Record<string, unknown> }> => jsonPost("/api/optimize", body);
export const apiCatalog = (q: string, cityId?: string): Promise<{ results: CatalogEntry[] }> =>
  jsonGet(`/api/catalog?q=${encodeURIComponent(q)}${cityId ? `&city_id=${encodeURIComponent(cityId)}` : ""}`);
export const apiPreviewEdits = (cityId: string, edits: Edits): Promise<{ report: EditReport }> =>
  jsonPost("/api/edits/preview", { city_id: cityId, edits });
export async function apiSaveEdits(cityId: string, edits: Edits): Promise<void> {
  await fetch(`/api/cities/${encodeURIComponent(cityId)}/edits`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits),
  });
}
export const apiStop = (jobId: string): Promise<any> => jsonPost(`/api/stop/${jobId}`, {});
export const apiCities = (): Promise<CityListItem[]> => jsonGet("/api/cities");
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
    onDone?: (data: any) => void;
  },
): EventSource {
  const es = new EventSource(`/api/stream/${jobId}`);
  es.addEventListener("improvement", (e) => handlers.onImprovement?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("heartbeat", (e) => handlers.onHeartbeat?.(JSON.parse((e as MessageEvent).data)));
  es.addEventListener("done", (e) => {
    handlers.onDone?.(JSON.parse((e as MessageEvent).data));
    es.close();
  });
  return es;
}
