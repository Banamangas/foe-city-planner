import type { CustomBuildings } from "../api";
import type { LoadResponse } from "../types";

export type { CustomBuildings };

export type LoadProblem =
  | { kind: "unknown_buildings"; items: { cityentity_id: string; count: number }[] }
  | { kind: "not_forge_hammer" }
  | { kind: "app_not_running" }
  | { kind: "unreadable"; details: string };

export function classifyLoadProblem(
  r: { status: number; body: any } | { resp: LoadResponse },
): LoadProblem | null {
  if ("resp" in r) return r.resp.exportable === false ? { kind: "not_forge_hammer" } : null;
  if (r.status === 0) return { kind: "app_not_running" };
  const items = r.body?.unknown_buildings;
  if (r.status === 422 && Array.isArray(items) && items.length > 0) {
    return { kind: "unknown_buildings", items };
  }
  return { kind: "unreadable", details: String(r.body?.error ?? `status ${r.status}`) };
}

/** Ids whose size is not a whole number 1-20 or whose road need is not 0/1/2. */
export function validateCustom(c: CustomBuildings): string[] {
  const okSize = (n: unknown) => Number.isInteger(n) && (n as number) >= 1 && (n as number) <= 20;
  return Object.keys(c).filter((id) => {
    const b = c[id];
    return !okSize(b.width) || !okSize(b.length) || ![0, 1, 2].includes(b.road);
  });
}
