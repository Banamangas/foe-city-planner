/** Pure helpers for step 2 (remove / add buildings). */
import type { CatalogEntry, Edits } from "../types";

export function changesSummary(edits: Edits): { removed: number; added: number } {
  return {
    removed: edits.remove.length,
    added: edits.add.reduce((n, a) => n + a.count, 0),
  };
}

export function addOne(edits: Edits, entry: CatalogEntry): Edits {
  if (edits.add.some((a) => a.cityentity_id === entry.id)) {
    return {
      ...edits,
      add: edits.add.map((a) => (a.cityentity_id === entry.id ? { ...a, count: a.count + 1 } : a)),
    };
  }
  return {
    ...edits,
    add: [...edits.add, {
      cityentity_id: entry.id, count: 1, label: entry.name, size: `${entry.width}x${entry.length}`,
    }],
  };
}

export function removeAdded(edits: Edits, cityentityId: string): Edits {
  return { ...edits, add: edits.add.filter((a) => a.cityentity_id !== cityentityId) };
}
