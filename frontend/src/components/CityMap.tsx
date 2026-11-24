import { useEffect, useRef, useState, useCallback } from "react";
import { useCityStore } from "../stores/cityStore";
import { fitTransform, screenToGrid, buildingAt, type Transform } from "../geometry";
import type { BuildingView } from "../types";
import { editedView, toggleRemove } from "../edits";

export type CityMapLabels = {
  current: string; optimized: string; fit: string; townhall: string;
  needsRoad: string; removedClickToKeep: string;
};

const DEFAULT_LABELS: CityMapLabels = {
  current: "Current", optimized: "Optimized", fit: "Fit", townhall: "townhall",
  needsRoad: "needs road", removedClickToKeep: "removed (click to keep)",
};

export function mapLabels(partial?: Partial<CityMapLabels>): CityMapLabels {
  return { ...DEFAULT_LABELS, ...partial };
}

/** A click on a building toggles its removal only in the editable current view. */
export const clickTogglesRemoval = (editable: boolean, showOpt: boolean): boolean =>
  editable && !showOpt;

export function CityMap({ labels, editable = true }: { labels?: Partial<CityMapLabels>; editable?: boolean } = {}) {
  const L = mapLabels(labels);
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const viewMode = useCityStore((s) => s.viewMode);
  const setViewMode = useCityStore((s) => s.setViewMode);
  const edits = useCityStore((s) => s.edits);
  const setEdits = useCityStore((s) => s.setEdits);
  const editReport = useCityStore((s) => s.editReport);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 900, h: 640 });
  const [t, setT] = useState<Transform>({ offsetX: 0, offsetY: 0, scale: 1 });
  const [tip, setTip] = useState<{ x: number; y: number; b: BuildingView } | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const down = useRef<{ x: number; y: number } | null>(null);

  const view = city?.map_view ?? null;
  const showOpt = viewMode === "optimized" && optimized !== null;

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: wrap.clientWidth, h: wrap.clientHeight });
    });
    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  const fit = useCallback(() => {
    if (!view) return;
    setT(fitTransform(view, size.w, size.h));
  }, [view, size]);

  useEffect(() => { fit(); }, [fit]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !view) return;
    const ctx = cv.getContext("2d")!;
    const p = view.palette;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = p.background;
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.setTransform(t.scale, 0, 0, t.scale, t.offsetX, t.offsetY);
    const cell = view.cell;

    ctx.fillStyle = p.region;
    for (const [x, y] of view.region) ctx.fillRect(x, y, cell, cell);

    const shownRoads = showOpt && optimized ? optimized.roads : view.current_roads;
    ctx.fillStyle = showOpt && optimized ? p.optimized_road : p.current_road;
    for (const r of shownRoads) ctx.fillRect(r.x, r.y, cell, cell);
    // two-lane tile cells (level 2) get an inner outline so they read as such
    ctx.strokeStyle = p.border;
    ctx.lineWidth = Math.max(1, cell / 6);
    for (const r of shownRoads) {
      if (r.level >= 2) ctx.strokeRect(r.x + cell / 4, r.y + cell / 4, cell / 2, cell / 2);
    }

    // Plan E: in the current view, removed buildings (and patches a removed
    // main sends to store) stay visible, faded and hatched; a removed patch's
    // tail is drawn where it slides to, and the cells that free up are hatched.
    const shown = showOpt && optimized
      ? { buildings: optimized.buildings as (BuildingView & { off?: boolean; moved?: boolean })[], freed: [] }
      : editedView(view.buildings, edits, editReport, cell);
    const hatch = (x: number, y: number, w: number, h: number) => {
      ctx.save();
      ctx.beginPath();
      ctx.rect(x, y, w, h);
      ctx.clip();
      ctx.strokeStyle = "#e07a5f";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let d = -h; d < w; d += cell / 2) {
        ctx.moveTo(x + d, y + h);
        ctx.lineTo(x + d + h, y);
      }
      ctx.stroke();
      ctx.restore();
    };
    for (const [x, y] of shown.freed) hatch(x, y, cell, cell);
    ctx.lineWidth = 1;
    ctx.strokeStyle = p.border;
    for (const b of shown.buildings) {
      ctx.globalAlpha = b.off ? 0.25 : 1;
      ctx.fillStyle = b.townhall ? p.townhall : b.needs_road ? p.road_building : p.plain_building;
      ctx.fillRect(b.x, b.y, b.w, b.h);
      ctx.globalAlpha = 1;
      if (b.moved) {
        ctx.save();
        ctx.strokeStyle = "#e07a5f";
        ctx.lineWidth = Math.max(1, cell / 5);
        ctx.strokeRect(b.x, b.y, b.w, b.h);
        ctx.restore();
      } else {
        ctx.strokeRect(b.x, b.y, b.w, b.h);
      }
      if (b.off) hatch(b.x, b.y, b.w, b.h);
    }
  }, [view, t, size, optimized, showOpt, edits, editReport]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const factor = Math.pow(1.1, -e.deltaY / 100);
      setT((prev) => {
        const scale = Math.max(0.1, Math.min(8, prev.scale * factor));
        const rect = cv.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const k = scale / prev.scale;
        return { scale, offsetX: mx - (mx - prev.offsetX) * k, offsetY: my - (my - prev.offsetY) * k };
      });
    };
    cv.addEventListener("wheel", handler, { passive: false });
    return () => cv.removeEventListener("wheel", handler);
  }, []);

  const onMouseDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, y: e.clientY };
    down.current = { x: e.clientX, y: e.clientY };
  };
  // A click (no drag) on a building in the current view toggles its removal.
  const onMouseUp = (e: React.MouseEvent) => {
    drag.current = null;
    const d = down.current;
    down.current = null;
    if (!d || !view || !city || !clickTogglesRemoval(editable, showOpt)) return;
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 4) return;
    const rect = canvasRef.current!.getBoundingClientRect();
    const { gx, gy } = screenToGrid(e.clientX - rect.left, e.clientY - rect.top, t, view.cell, view.origin);
    const b = buildingAt(gx, gy, view.buildings, view.origin, view.cell);
    if (b && b.id !== undefined && !b.townhall) {
      setEdits(toggleRemove(edits, Number(b.id), city.buildings));
    }
  };

  const onMouseMove = (e: React.MouseEvent) => {
    if (drag.current) {
      const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
      drag.current = { x: e.clientX, y: e.clientY };
      setT((prev) => ({ ...prev, offsetX: prev.offsetX + dx, offsetY: prev.offsetY + dy }));
      setTip(null);
      return;
    }
    if (!view) return;
    const rect = canvasRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const { gx, gy } = screenToGrid(sx, sy, t, view.cell, view.origin);
    const buildings = showOpt && optimized ? optimized.buildings : view.buildings;
    const b = buildingAt(gx, gy, buildings, view.origin, view.cell);
    setTip(b ? { x: sx, y: sy, b } : null);
  };

  return (
    <div className="citymap">
      <div className="citymap-toolbar">
        {optimized && (
          <div className="switch">
            <button className={viewMode === "current" ? "on" : ""}
              onClick={() => setViewMode("current")}>{L.current}</button>
            <button className={viewMode === "optimized" ? "on" : ""}
              onClick={() => setViewMode("optimized")}>{L.optimized}</button>
          </div>
        )}
        <button onClick={fit}>{L.fit}</button>
      </div>
      <div className="citymap-canvas-wrap" ref={wrapRef}>
        <canvas
          ref={canvasRef}
          width={size.w}
          height={size.h}
          onMouseDown={onMouseDown}
          onMouseUp={onMouseUp}
          onMouseLeave={() => { drag.current = null; setTip(null); }}
          onMouseMove={onMouseMove}
        />
        {tip && (
          <div className="citymap-tip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
            {tip.b.name} ({tip.b.size}) {tip.b.townhall ? `· ${L.townhall}` : tip.b.needs_road ? `· ${L.needsRoad}` : ""}
            {!showOpt && tip.b.id !== undefined && edits.remove.includes(Number(tip.b.id)) ? ` · ${L.removedClickToKeep}` : ""}
          </div>
        )}
      </div>
    </div>
  );
}
