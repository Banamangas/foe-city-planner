from __future__ import annotations

import json

from foeopt.model import Layout

_CELL = 12  # pixels per grid cell

# Map palette. Non-road buildings MUST contrast clearly with the region
# background — an earlier #555-on-#3a3a3a pairing made them read as "missing".
COLOR_BACKGROUND = "#141414"
COLOR_REGION = "#262626"          # buildable cells (empty)
COLOR_CURRENT_ROAD = "rgba(150,150,150,0.95)"
COLOR_OPTIMIZED_ROAD = "rgba(80,200,120,0.95)"
COLOR_TOWNHALL = "#c0392b"        # red
COLOR_ROAD_BUILDING = "#2980b9"   # blue — needs a road
COLOR_PLAIN_BUILDING = "#d89b3c"  # amber — no road needed
COLOR_BUILDING_BORDER = "#0a0a0a"


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
        "palette": {
            "background": COLOR_BACKGROUND,
            "region": COLOR_REGION,
            "current_road": COLOR_CURRENT_ROAD,
            "optimized_road": COLOR_OPTIMIZED_ROAD,
            "townhall": COLOR_TOWNHALL,
            "road_building": COLOR_ROAD_BUILDING,
            "plain_building": COLOR_PLAIN_BUILDING,
            "border": COLOR_BUILDING_BORDER,
        },
    }

    payload = json.dumps(data).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", payload)


def render_comparison(current: Layout, optimized: Layout) -> str:
    # shared bounds over both layouts so the two views align
    cx0, cy0, cx1, cy1 = _bounds(current)
    ox0, oy0, ox1, oy1 = _bounds(optimized)
    min_x, min_y = min(cx0, ox0), min(cy0, oy0)
    max_x, max_y = max(cx1, ox1), max(cy1, oy1)
    width = (max_x - min_x + 1) * _CELL
    height = (max_y - min_y + 1) * _CELL

    def view(layout: Layout) -> dict:
        def px(x, y):
            return (x - min_x) * _CELL, (y - min_y) * _CELL
        buildings = []
        for b in layout.buildings:
            bx, by = px(b.footprint.x, b.footprint.y)
            buildings.append({
                "x": bx, "y": by,
                "w": b.footprint.width * _CELL, "h": b.footprint.length * _CELL,
                "name": b.name, "size": f"{b.footprint.width}x{b.footprint.length}",
                "needs_road": b.needs_road, "townhall": b.is_townhall,
            })
        roads = [{"x": (x - min_x) * _CELL, "y": (y - min_y) * _CELL, "level": lvl}
                 for (x, y), lvl in layout.roads.items()]
        region = [((x - min_x) * _CELL, (y - min_y) * _CELL)
                  for (x, y) in sorted(layout.region.cells)]
        return {"buildings": buildings, "roads": roads, "region": region}

    data = {
        "cell": _CELL, "width": width, "height": height,
        "palette": {
            "background": COLOR_BACKGROUND, "region": COLOR_REGION,
            "current_road": COLOR_CURRENT_ROAD, "optimized_road": COLOR_OPTIMIZED_ROAD,
            "townhall": COLOR_TOWNHALL, "road_building": COLOR_ROAD_BUILDING,
            "plain_building": COLOR_PLAIN_BUILDING, "border": COLOR_BUILDING_BORDER,
        },
        "views": {"current": view(current), "optimized": view(optimized)},
    }
    payload = json.dumps(data).replace("</", "<\\/")
    return _COMPARE_TEMPLATE.replace("__DATA__", payload)


_COMPARE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>FoE City — before/after</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #141414; color: #eee; }
  #toolbar { padding: 8px; }
  canvas { display: block; }
  #tip { position: fixed; pointer-events: none; background: #000; color: #fff;
         padding: 4px 8px; border-radius: 4px; font-size: 12px; display: none; }
</style></head><body>
<div id="toolbar">
  <label><input type="radio" name="view" value="current" checked> current</label>
  <label><input type="radio" name="view" value="optimized"> optimized</label>
</div>
<div><canvas id="cv"></canvas><div id="tip"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const PAL = DATA.palette, cell = DATA.cell;
const cv = document.getElementById('cv'); cv.width = DATA.width; cv.height = DATA.height;
const ctx = cv.getContext('2d'); const tip = document.getElementById('tip');
let activeRoadColor = PAL.current_road;
function current(){ return document.querySelector('input[name=view]:checked').value; }
function draw() {
  const v = DATA.views[current()];
  activeRoadColor = current() === 'optimized' ? PAL.optimized_road : PAL.current_road;
  ctx.fillStyle = PAL.background; ctx.fillRect(0,0,cv.width,cv.height);
  ctx.fillStyle = PAL.region; for (const [x,y] of v.region) ctx.fillRect(x,y,cell,cell);
  ctx.fillStyle = activeRoadColor; for (const r of v.roads) ctx.fillRect(r.x,r.y,cell,cell);
  for (const b of v.buildings) {
    ctx.fillStyle = b.townhall ? PAL.townhall : (b.needs_road ? PAL.road_building : PAL.plain_building);
    ctx.fillRect(b.x,b.y,b.w,b.h); ctx.strokeStyle = PAL.border; ctx.strokeRect(b.x,b.y,b.w,b.h);
  }
}
function buildingAt(mx,my){ for (const b of DATA.views[current()].buildings)
  if (mx>=b.x&&mx<b.x+b.w&&my>=b.y&&my<b.y+b.h) return b; return null; }
cv.addEventListener('mousemove', e => {
  const r = cv.getBoundingClientRect(); const b = buildingAt(e.clientX-r.left, e.clientY-r.top);
  if (b) { tip.style.display='block'; tip.style.left=(e.clientX+12)+'px'; tip.style.top=(e.clientY+12)+'px';
    tip.setAttribute('data-name', b.name); tip.setAttribute('data-size', b.size);
    tip.textContent = b.name + ' (' + b.size + ')'; } else { tip.style.display='none'; }
});
for (const el of document.querySelectorAll('input[name=view]')) el.addEventListener('change', draw);
draw();
</script>
</body></html>
"""


_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>FoE City Map</title>
<style>
  body { font-family: sans-serif; margin: 0; background: #1e1e1e; color: #eee; }
  #toolbar { padding: 8px; }
  #wrap { position: relative; }
  canvas { display: block; }
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
const PAL = DATA.palette;

function draw() {
  ctx.fillStyle = PAL.background;
  ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = PAL.region;
  for (const [x, y] of DATA.region) ctx.fillRect(x, y, cell, cell);
  if (document.getElementById('showCurrent').checked) {
    ctx.fillStyle = PAL.current_road;
    for (const r of DATA.current_roads) ctx.fillRect(r.x, r.y, cell, cell);
  }
  if (DATA.optimized_roads && document.getElementById('showOptimized').checked) {
    ctx.fillStyle = PAL.optimized_road;
    for (const r of DATA.optimized_roads) ctx.fillRect(r.x, r.y, cell, cell);
  }
  for (const b of DATA.buildings) {
    ctx.fillStyle = b.townhall ? PAL.townhall : (b.needs_road ? PAL.road_building : PAL.plain_building);
    ctx.fillRect(b.x, b.y, b.w, b.h);
    ctx.strokeStyle = PAL.border; ctx.strokeRect(b.x, b.y, b.w, b.h);
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
