import { useEffect, useRef, useState, useCallback } from "react";
import { useCityStore } from "../stores/cityStore";
import { fitTransform, screenToGrid, buildingAt, type Transform } from "../geometry";
import type { BuildingView } from "../types";

export function CityMap() {
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const showCurrent = useCityStore((s) => s.showCurrent);
  const showOptimized = useCityStore((s) => s.showOptimized);
  const toggleCurrent = useCityStore((s) => s.toggleCurrent);
  const toggleOptimized = useCityStore((s) => s.toggleOptimized);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [t, setT] = useState<Transform>({ offsetX: 0, offsetY: 0, scale: 1 });
  const [tip, setTip] = useState<{ x: number; y: number; b: BuildingView } | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);

  const view = city?.map_view ?? null;

  const fit = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv || !view) return;
    setT(fitTransform(view, cv.width, cv.height));
  }, [view]);

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

    if (showCurrent) {
      ctx.fillStyle = p.current_road;
      for (const r of view.current_roads) ctx.fillRect(r.x, r.y, cell, cell);
    }
    if (showOptimized && optimized) {
      ctx.fillStyle = p.optimized_road;
      for (const r of optimized.roads) ctx.fillRect(r.x, r.y, cell, cell);
    }

    const buildings = showOptimized && optimized ? optimized.buildings : view.buildings;
    ctx.lineWidth = 1;
    ctx.strokeStyle = p.border;
    for (const b of buildings) {
      ctx.fillStyle = b.townhall ? p.townhall : b.needs_road ? p.road_building : p.plain_building;
      ctx.fillRect(b.x, b.y, b.w, b.h);
      ctx.strokeRect(b.x, b.y, b.w, b.h);
    }
  }, [view, t, optimized, showCurrent, showOptimized]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = Math.pow(1.1, -e.deltaY / 100);
    setT((prev) => {
      const scale = Math.max(0.1, Math.min(8, prev.scale * factor));
      const rect = canvasRef.current!.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const k = scale / prev.scale;
      return { scale, offsetX: mx - (mx - prev.offsetX) * k, offsetY: my - (my - prev.offsetY) * k };
    });
  };

  const onMouseDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY }; };
  const onMouseUp = () => { drag.current = null; };

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
    const buildings = showOptimized && optimized ? optimized.buildings : view.buildings;
    const b = buildingAt(gx, gy, buildings, view.origin, view.cell);
    setTip(b ? { x: sx, y: sy, b } : null);
  };

  return (
    <div className="citymap">
      <div className="citymap-toolbar">
        <label><input type="checkbox" checked={showCurrent} onChange={toggleCurrent} /> Current roads</label>
        <label><input type="checkbox" checked={showOptimized} onChange={toggleOptimized} /> Optimized roads</label>
        <button onClick={fit}>Fit</button>
      </div>
      <div className="citymap-canvas-wrap">
        <canvas
          ref={canvasRef}
          width={900}
          height={640}
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseUp={onMouseUp}
          onMouseLeave={() => { drag.current = null; setTip(null); }}
          onMouseMove={onMouseMove}
        />
        {tip && (
          <div className="citymap-tip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
            {tip.b.name} ({tip.b.size}) {tip.b.townhall ? "· townhall" : tip.b.needs_road ? "· needs road" : ""}
          </div>
        )}
      </div>
    </div>
  );
}
