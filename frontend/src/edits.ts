/** Plan E: pure helpers for the per-city edit set (remove / add buildings).
 *  The chain logic (reattach, store, end-of-chain slots) lives on the server
 *  (foeopt/editing.py); the UI only builds the edit set and shows the report. */
import type {
  AddSpec, AddedBuilding, BuildingSummary, BuildingView, CatalogEntry, EditReport, Edits,
} from "./types";

export const emptyEdits = (): Edits => ({ remove: [], add: [], relink: {} });

export function normalizeEdits(e: Edits | null | undefined): Edits {
  return {
    remove: [...(e?.remove ?? [])],
    add: [...(e?.add ?? [])],
    relink: { ...(e?.relink ?? {}) },
  };
}

export const isEmptyEdits = (e: Edits): boolean => e.remove.length === 0 && e.add.length === 0;

const isTownhall = (buildings: BuildingSummary[], id: number) =>
  buildings.some((b) => Number(b.entity_id) === id && b.is_townhall);

/** Toggle one building's removal; the Town Hall is never removable. */
export function toggleRemove(edits: Edits, id: number, buildings: BuildingSummary[]): Edits {
  if (isTownhall(buildings, id)) return edits;
  const on = edits.remove.includes(id);
  return setRemoved(edits, [id], !on, buildings);
}

export function setRemoved(
  edits: Edits, ids: number[], on: boolean, buildings: BuildingSummary[],
): Edits {
  const want = ids.filter((id) => !isTownhall(buildings, id));
  const cur = new Set(edits.remove);
  for (const id of want) (on ? cur.add(id) : cur.delete(id));
  const relink = { ...(edits.relink ?? {}) };
  for (const k of Object.keys(relink)) if (!cur.has(Number(k))) delete relink[k];
  return { ...edits, remove: [...cur].sort((a, b) => a - b), relink };
}

/** Every building of the same type as `b` (same catalog id, else same name and size). */
export function sameTypeIds(buildings: BuildingSummary[], b: BuildingSummary): number[] {
  return buildings
    .filter((o) => !o.is_townhall && (b.cityentity_id
      ? o.cityentity_id === b.cityentity_id
      : o.name === b.name && o.width === b.width && o.length === b.length))
    .map((o) => Number(o.entity_id));
}

/** Main buildings of a chain still on the map (candidates for `link_to`). */
export function chainMains(
  buildings: BuildingSummary[], chainId: string, edits: Edits,
): BuildingSummary[] {
  return buildings.filter((b) => b.chain_id === chainId && b.is_chain_head
    && !edits.remove.includes(Number(b.entity_id)));
}

export const isPatch = (e: CatalogEntry): boolean => !!e.chain_id && !e.is_chain_head;

export function catalogAdd(entry: CatalogEntry, count: number, linkTo?: number): AddSpec {
  const spec: AddSpec = {
    cityentity_id: entry.id, count: Math.max(1, Math.min(50, Math.round(count) || 1)),
    label: entry.name, size: `${entry.width}x${entry.length}`,
  };
  if (linkTo !== undefined) spec.link_to = linkTo;
  return spec;
}

export function customAdd(
  width: number, length: number, needsRoad: boolean, name: string, count: number,
): AddSpec {
  const w = Math.round(width), l = Math.round(length);
  return {
    width: w, length: l, needs_road: needsRoad, name: name.trim() || undefined,
    count: Math.max(1, Math.min(50, Math.round(count) || 1)),
    label: name.trim() || `Custom ${w}x${l}`, size: `${w}x${l}`,
  };
}

export const addAt = (edits: Edits, spec: AddSpec): Edits => ({ ...edits, add: [...edits.add, spec] });
export const dropAddAt = (edits: Edits, i: number): Edits =>
  ({ ...edits, add: edits.add.filter((_, j) => j !== i) });

export function setRelink(edits: Edits, mainId: number, target: number | null): Edits {
  const relink = { ...(edits.relink ?? {}) };
  if (target === null) delete relink[String(mainId)];
  else relink[String(mainId)] = target;
  return { ...edits, relink };
}

/** The edit set as the API takes it (UI labels stripped). */
export function forServer(edits: Edits): Edits {
  const add = edits.add.map(({ label: _l, size: _s, ...rest }) => rest);
  const out: Edits = { remove: [...edits.remove], add };
  if (edits.relink && Object.keys(edits.relink).length) out.relink = { ...edits.relink };
  return out;
}

/** Human notices for the chain consequences in a report. */
export function chainNotices(
  report: EditReport, nameOf: (id: number) => string,
): { kind: "reattach" | "store" | "warn"; text: string; ids?: number[]; main?: number;
     candidates?: { entity_id: number; name: string }[] }[] {
  const out: ReturnType<typeof chainNotices> = [];
  for (const r of report.reattached) {
    const pieces = r.moved.map(nameOf).join(", ");
    if (!r.ok) continue;   // the failure is in report.warnings
    out.push({
      kind: "reattach", ids: r.moved,
      text: r.relinked
        ? `${pieces} will be attached to ${r.to_name ?? r.to}`
        : `${nameOf(r.removed)} removed: ${pieces} will be reattached to ${r.to_name ?? r.to}`,
    });
  }
  for (const c of report.cascades) {
    out.push({
      kind: "store", ids: c.stored, main: c.main, candidates: c.relink_candidates,
      text: `Removing ${c.main_name} sends its ${c.stored.length} patch(es) to store`,
    });
  }
  for (const w of report.warnings) out.push({ kind: "warn", text: w });
  return out;
}

/** summaryById extended with the buildings a run added (named from the catalog). */
export function withAdded(
  summaryById: Map<string, BuildingSummary>, added: AddedBuilding[] | undefined,
): Map<string, BuildingSummary> {
  if (!added || added.length === 0) return summaryById;
  const m = new Map(summaryById);
  for (const a of added) {
    m.set(String(a.entity_id), {
      entity_id: a.entity_id, name: `${a.name} (new)`, width: a.width, length: a.length,
      needs_road: a.needs_road, is_townhall: false, cityentity_id: a.cityentity_id,
      chain_id: a.chain_id,
    });
  }
  return m;
}

/** The current map under an edit set. Removed buildings and the patches a
 *  removed main sends to store are `off` (drawn hatched). A removed patch's
 *  tail slides into its slot (`moved`), so the space that frees up is at the
 *  END of the chain, not where the user clicked: `freed` lists those cells
 *  (view coordinates, one per grid cell). The report is used only when it was
 *  made for exactly this removal set; otherwise just the removals show. */
export function editedView(
  buildings: BuildingView[], edits: Edits, report: EditReport | null, cell: number,
): { buildings: (BuildingView & { off?: boolean; moved?: boolean })[]; freed: [number, number][] } {
  const removed = new Set(edits.remove);
  const fresh = report !== null && report.removed.length === removed.size
    && report.removed.every((id) => removed.has(id));
  const off = new Set(removed);
  const shift = new Map<number, [number, number]>();
  if (fresh) {
    for (const c of report.cascades) for (const id of c.stored) off.add(id);
    for (const r of report.reattached) {
      if (!r.ok || !r.offset) continue;
      for (const id of r.moved) shift.set(id, r.offset);
    }
  }
  const out: (BuildingView & { off?: boolean; moved?: boolean })[] = [];
  const cellsOf = (b: BuildingView) => {
    const cs: string[] = [];
    for (let x = b.x; x < b.x + b.w; x += cell) for (let y = b.y; y < b.y + b.h; y += cell) cs.push(`${x},${y}`);
    return cs;
  };
  const before = new Set<string>(), after = new Set<string>();
  for (const b of buildings) {
    const id = Number(b.id);
    const d = shift.get(id);
    if (d) {
      const nb = { ...b, x: b.x + d[0] * cell, y: b.y + d[1] * cell, moved: true };
      cellsOf(b).forEach((c) => before.add(c));
      cellsOf(nb).forEach((c) => after.add(c));
      out.push(nb);
    } else if (shift.size && removed.has(id) && fresh
               && report!.reattached.some((r) => r.ok && r.offset && r.removed === id)) {
      cellsOf(b).forEach((c) => before.add(c));   // its slot is taken by the tail
    } else {
      out.push(off.has(id) ? { ...b, off: true } : b);
    }
  }
  const freed = [...before].filter((c) => !after.has(c))
    .map((c) => c.split(",").map(Number) as [number, number]);
  return { buildings: out, freed };
}
