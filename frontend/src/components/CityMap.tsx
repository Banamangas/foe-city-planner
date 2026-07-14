import { useEffect, useRef, useState, useCallback } from "react";
import { useCityStore } from "../stores/cityStore";
import { fitTransform, screenToGrid, buildingAt, type Transform } from "../geometry";
import type { BuildingView } from "../types";

export function CityMap() {
  const city = useCityStore((s) => s.city);
  const optimized = useCityStore((s) => s.optimized);
  const viewMode = useCityStore((s) => s.viewMode);
  const setViewMode = useCityStore((s) => s.setViewMode);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 900, h: 640 });
  const [t, setT] = useState<Transform>({ offsetX: 0, offsetY: 0, scale: 1 });
  const [tip, setTip] = useState<{ x: number; y: number; b: BuildingView } | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);

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

    if (showOpt && optimized) {
      ctx.fillStyle = p.optimized_road;
      for (const r of optimized.roads) ctx.fillRect(r.x, r.y, cell, cell);
    } else {
      ctx.fillStyle = p.current_road;
      for (const r of view.current_roads) ctx.fillRect(r.x, r.y, cell, cell);
    }

    const buildings = showOpt && optimized ? optimized.buildings : view.buildings;
    ctx.lineWidth = 1;
    ctx.strokeStyle = p.border;
    for (const b of buildings) {
      ctx.fillStyle = b.townhall ? p.townhall : b.needs_road ? p.road_building : p.plain_building;
      ctx.fillRect(b.x, b.y, b.w, b.h);
      ctx.strokeRect(b.x, b.y, b.w, b.h);
    }
  }, [view, t, size, optimized, showOpt]);

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
              onClick={() => setViewMode("current")}>Current</button>
            <button className={viewMode === "optimized" ? "on" : ""}
              onClick={() => setViewMode("optimized")}>Optimized</button>
          </div>
        )}
        <button onClick={fit}>Fit</button>
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
            {tip.b.name} ({tip.b.size}) {tip.b.townhall ? "· townhall" : tip.b.needs_road ? "· needs road" : ""}
          </div>
        )}
      </div>
    </div>
  );
}
