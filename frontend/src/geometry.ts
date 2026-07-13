import type { MapView, BuildingView } from "./types";

export type Transform = { offsetX: number; offsetY: number; scale: number };

export function regionBounds(view: MapView) {
  const c = view.cell;
  let minGX = Infinity, minGY = Infinity, maxGX = -Infinity, maxGY = -Infinity;
  for (const [px, py] of view.region) {
    const gx = px / c, gy = py / c;
    if (gx < minGX) minGX = gx;
    if (gy < minGY) minGY = gy;
    if (gx > maxGX) maxGX = gx;
    if (gy > maxGY) maxGY = gy;
  }
  return { minGX, minGY, maxGX, maxGY };
}

export function fitTransform(view: MapView, canvasW: number, canvasH: number): Transform {
  const b = regionBounds(view);
  const cols = b.maxGX - b.minGX + 1;
  const rows = b.maxGY - b.minGY + 1;
  const cell = view.cell;
  const pad = 20;
  const sx = (canvasW - pad * 2) / (cols * cell);
  const sy = (canvasH - pad * 2) / (rows * cell);
  const scale = Math.max(0.05, Math.min(sx, sy));
  const contentW = cols * cell * scale;
  const contentH = rows * cell * scale;
  const offsetX = (canvasW - contentW) / 2 - b.minGX * cell * scale;
  const offsetY = (canvasH - contentH) / 2 - b.minGY * cell * scale;
  return { offsetX, offsetY, scale };
}

export function screenToGrid(
  sx: number, sy: number, t: Transform, cell: number, origin: [number, number],
): { gx: number; gy: number } {
  const relPxX = (sx - t.offsetX) / t.scale;
  const relPxY = (sy - t.offsetY) / t.scale;
  const gx = Math.floor(relPxX / cell) + origin[0];
  const gy = Math.floor(relPxY / cell) + origin[1];
  return { gx, gy };
}

export function buildingAt(
  gx: number, gy: number, buildings: BuildingView[],
  origin: [number, number], cell: number,
): BuildingView | null {
  const relX = (gx - origin[0]) * cell;
  const relY = (gy - origin[1]) * cell;
  for (const b of buildings) {
    if (relX >= b.x && relX < b.x + b.w && relY >= b.y && relY < b.y + b.h) {
      return b;
    }
  }
  return null;
}
