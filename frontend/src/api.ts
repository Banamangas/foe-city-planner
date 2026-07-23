import type {
  LoadResponse, CityListItem, LayoutListItem, Improvement,
  BuildingSummary, BuildingView, RoadView, Palette,
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
  const optimized_roads: RoadView[] = imp.roads.map(([x, y]) => ({
    x: (x - ox) * cell, y: (y - oy) * cell, level: 1,
  }));
  const buildings: BuildingView[] = [];
  for (const id of Object.keys(imp.buildings)) {
    const [x, y, w, l] = imp.buildings[id];
    const meta = summaryById.get(id);
    buildings.push({
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

export const apiLoad = (slim: unknown): Promise<LoadResponse> => jsonPost("/api/load", slim);
export const apiOptimize = (
  body: { city_id: string; time_box: number; seed_polish?: number },
): Promise<{ job_id: string }> => jsonPost("/api/optimize", body);
export const apiStop = (jobId: string): Promise<any> => jsonPost(`/api/stop/${jobId}`, {});
export const apiCities = (): Promise<CityListItem[]> => jsonGet("/api/cities");
export const apiCity = (id: string): Promise<any> => jsonGet(`/api/cities/${id}`);
export const apiLayouts = (cityId?: string): Promise<LayoutListItem[]> =>
  jsonGet(cityId ? `/api/layouts?city_id=${encodeURIComponent(cityId)}` : "/api/layouts");
export const apiLayout = (id: string): Promise<any> => jsonGet(`/api/layouts/${id}`);
export const apiSaveLayout = (body: unknown): Promise<{ id: string }> => jsonPost("/api/layouts", body);
export const apiDeleteLayout = (id: string): Promise<any> =>
  fetch(`/api/layouts/${id}`, { method: "DELETE" }).then((r) => r.json());

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
