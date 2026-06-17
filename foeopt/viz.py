from __future__ import annotations

import json

from foeopt.model import Layout

_CELL = 12  # pixels per grid cell


def _bounds(layout: Layout) -> tuple[int, int, int, int]:
    xs, ys = [], []
    for c in layout.region.cells:
        xs.append(c[0]); ys.append(c[1])
    for b in layout.buildings:
        for (cx, cy) in b.footprint.cells():
            xs.append(cx); ys.append(cy)
    return min(xs), min(ys), max(xs), max(ys)


def render_html(
    layout: Layout,
    optimized_roads: dict[tuple[int, int], int] | None = None,
) -> str:
    min_x, min_y, max_x, max_y = _bounds(layout)
    width = (max_x - min_x + 1) * _CELL
    height = (max_y - min_y + 1) * _CELL

    def px(x: int, y: int) -> tuple[int, int]:
        return (x - min_x) * _CELL, (y - min_y) * _CELL

    region_cells = [px(x, y) for (x, y) in sorted(layout.region.cells)]

    buildings = []
    for b in layout.buildings:
        bx, by = px(b.footprint.x, b.footprint.y)
        buildings.append({
            "x": bx, "y": by,
            "w": b.footprint.width * _CELL,
            "h": b.footprint.length * _CELL,
            "name": b.name,
            "size": f"{b.footprint.width}x{b.footprint.length}",
            "needs_road": b.needs_road,
            "townhall": b.is_townhall,
        })

    def road_list(roads):
        out = []
        for (x, y), lvl in roads.items():
            rx, ry = px(x, y)
            out.append({"x": rx, "y": ry, "level": lvl})
        return out

    data = {
        "cell": _CELL,
        "width": width,
        "height": height,
        "region": region_cells,
        "buildings": buildings,
        "current_roads": road_list(layout.roads),
        "optimized_roads": road_list(optimized_roads) if optimized_roads else None,
    }

    payload = json.dumps(data).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", payload)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>FoE City Map</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #1e1e1e; color: #eee; }
  #toolbar { padding: 8px; }
  #wrap { position: relative; }
  canvas { background: #2a2a2a; display: block; }
  #tip { position: fixed; pointer-events: none; background: #000; color: #fff;
         padding: 4px 8px; border-radius: 4px; font-size: 12px; display: none; }
  label { margin-right: 12px; }
</style></head><body>
<div id="toolbar">
  <label><input type="checkbox" id="showCurrent" checked> current roads</label>
  <label><input type="checkbox" id="showOptimized" checked> optimized roads</label>
</div>
<div id="wrap"><canvas id="cv"></canvas><div id="tip"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const cv = document.getElementById('cv');
cv.width = DATA.width; cv.height = DATA.height;
const ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
const cell = DATA.cell;

function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = '#3a3a3a';
  for (const [x, y] of DATA.region) ctx.fillRect(x, y, cell, cell);
  if (document.getElementById('showCurrent').checked) {
    ctx.fillStyle = 'rgba(120,120,120,0.9)';
    for (const r of DATA.current_roads) ctx.fillRect(r.x, r.y, cell, cell);
  }
  if (DATA.optimized_roads && document.getElementById('showOptimized').checked) {
    ctx.fillStyle = 'rgba(80,200,120,0.9)';
    for (const r of DATA.optimized_roads) ctx.fillRect(r.x, r.y, cell, cell);
  }
  for (const b of DATA.buildings) {
    ctx.fillStyle = b.townhall ? '#c0392b' : (b.needs_road ? '#2980b9' : '#555');
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.strokeStyle = '#111'; ctx.strokeRect(b.x, b.y, b.w, b.h);
  }
}
function buildingAt(mx, my) {
  for (const b of DATA.buildings)
    if (mx >= b.x && mx < b.x + b.w && my >= b.y && my < b.y + b.h) return b;
  return null;
}
cv.addEventListener('mousemove', e => {
  const rect = cv.getBoundingClientRect();
  const b = buildingAt(e.clientX - rect.left, e.clientY - rect.top);
  if (b) {
    tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px';
    tip.style.top = (e.clientY + 12) + 'px';
    tip.setAttribute('data-name', b.name);
    tip.setAttribute('data-size', b.size);
    tip.textContent = b.name + ' (' + b.size + ')';
  } else { tip.style.display = 'none'; }
});
document.getElementById('showCurrent').addEventListener('change', draw);
document.getElementById('showOptimized').addEventListener('change', draw);
draw();
</script>
</body></html>
"""
