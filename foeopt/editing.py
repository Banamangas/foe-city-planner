"""City edits (plan E): remove buildings and add new ones before a run.

`apply_edits(layout, remove_ids, add)` returns the EDITED layout plus a report.
The edited layout keeps the upload's roads and every kept building's position,
so a legal upload minus some buildings is still legal and `seed_input` keeps
publishing it as the instant first result.

Chains (user decisions, 2026-11-17, tasks/todo.md plan E):
- Only patches link. A chain's MAIN building (`Catalog.is_chain_head`) is the
  piece patches attach to; mains never link to each other.
- Removing a patch REATTACHES the pieces behind it: the tail piece that sat in
  the removed piece's link slot moves into that freed slot and the whole tail
  shifts by the same offset. The player relinks it in game.
- Removing a main stores its patches ("to store"), unless `relink` names
  another main of the same chain: the patches then move to the free end slot of
  that main's chain.
- An added patch links to the chain's main building: automatically when the
  city has exactly one, else `link_to` must name one. It takes a free link slot
  at the END of that chain, so `chains.compose` makes the group one rigid block.

Added buildings that fit in the upload's free cells (no road change) are placed
there, so the seed survives an edit with additions; the others get a position
outside the region and the report says the seed cannot be used.
"""
from __future__ import annotations

from collections import deque
from dataclasses import replace

from foeopt.catalog import Catalog
from foeopt.chains import make_composite
from foeopt.legality import chain_links, check as legality_check, two_lane_connected
from foeopt.model import Building, Footprint, Layout
from foeopt.validate import connected_road_cells

MAX_ADD_COUNT = 50
# Types that never sit on the buildable grid (loader._OFF_GRID_TYPES) + streets.
UNPLACEABLE_TYPES = {"street", "off_grid", "outpost_ship", "friends_tavern", "hub_main",
                     "hub_part"}


class EditError(ValueError):
    """An edit set that cannot be applied; `detail` goes into the 400 body."""

    def __init__(self, message: str, **detail):
        super().__init__(message)
        self.detail = detail


def _info(b: Building, **extra) -> dict:
    return {"entity_id": b.entity_id, "cityentity_id": b.cityentity_id, "name": b.name,
            "width": b.footprint.width, "length": b.footprint.length, **extra}


class _Editor:
    def __init__(self, layout: Layout, catalog: Catalog | None, relink: dict[int, int]):
        self.src = layout
        self.catalog = catalog
        self.relink = relink
        self.work: dict[int, Building] = {b.entity_id: b for b in layout.buildings}
        self.order: list[int] = [b.entity_id for b in layout.buildings]
        self.stored: list[dict] = []
        self.reattached: list[dict] = []
        self.cascades: list[dict] = []
        self.warnings: list[str] = []
        self.touched: set[int] = set()   # entity ids whose chain group an edit changed
        self.relinked: list[int] = []    # patches moved to another main's chain
        self.loose_relinked: list[dict] = []   # loose pieces attached to their main
        self.loose_failed: list[dict] = []     # loose pieces left where they were

    # -- chain helpers ------------------------------------------------------
    def is_head(self, b: Building) -> bool:
        if not b.chain_id:
            return False
        if self.catalog is not None and self.catalog.known and b.cityentity_id in self.catalog.ids():
            return self.catalog.is_chain_head(b.cityentity_id)
        return b.needs_road  # catalog-less fallback: only mains need a road

    def _layout(self) -> Layout:
        return Layout(self.src.region, list(self.work.values()), self.src.townhall,
                      dict(self.src.roads))

    def adjacency(self) -> dict[int, set[int]]:
        adj: dict[int, set[int]] = {}
        for a, b in chain_links(self._layout()):
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        return adj

    @staticmethod
    def component(adj: dict[int, set[int]], start: int, skip: frozenset = frozenset()) -> set[int]:
        seen, stack = {start}, [start]
        while stack:
            for n in adj.get(stack.pop(), ()):
                if n not in seen and n not in skip:
                    seen.add(n)
                    stack.append(n)
        return seen

    def heads_of(self, chain_id: str, exclude: set[int] = frozenset()) -> list[Building]:
        return [b for b in self.work.values()
                if b.chain_id == chain_id and self.is_head(b) and b.entity_id not in exclude]

    def free_slot(self, head_id: int, w: int, l: int) -> tuple[int, int] | None:
        """Top-left of a link slot of size w x l at the END of head's chain: a
        linkPosition of a member that no member of the group occupies, taken
        from the member farthest from the main building."""
        adj = self.adjacency()
        group = self.component(adj, head_id)
        depth = {head_id: 0}
        q = deque([head_id])
        while q:
            e = q.popleft()
            for n in adj.get(e, ()):
                if n not in depth:
                    depth[n] = depth[e] + 1
                    q.append(n)
        occupied = set()
        for e in group:
            occupied |= self.work[e].footprint.cells()
        for e in sorted(group, key=lambda e: (-depth.get(e, 0), e)):
            m = self.work[e]
            for (dx0, dy0, dx1, dy1) in m.link_positions:
                rw, rl = dx1 - dx0 + 1, dy1 - dy0 + 1
                if (rw, rl) != (w, l):
                    continue
                rx, ry = m.footprint.x + dx0, m.footprint.y + dy0
                if not (Footprint(rx, ry, rw, rl).cells() & occupied):
                    return rx, ry
        return None

    def shift(self, ids: set[int], dx: int, dy: int) -> None:
        for e in ids:
            b = self.work[e]
            fp = b.footprint
            self.work[e] = replace(b, footprint=Footprint(fp.x + dx, fp.y + dy, fp.width, fp.length))

    def linked_to_any(self, e: int, others: set[int]) -> bool:
        return bool(self.adjacency().get(e, set()) & others)

    def store(self, e: int, reason: str, **extra) -> None:
        b = self.work.pop(e)
        self.stored.append(_info(b, reason=reason, **extra))

    # -- removal ------------------------------------------------------------
    def remove(self, x_id: int) -> None:
        if x_id not in self.work:
            return  # already stored with its main
        x = self.work[x_id]
        adj = self.adjacency()
        comp = self.component(adj, x_id) if x.chain_id else {x_id}
        self.store(x_id, "removed")
        if len(comp) == 1:
            return
        neighbours = adj.get(x_id, set())
        rest = comp - {x_id}
        parts, seen = [], set()
        for e in sorted(rest):
            if e not in seen:
                p = self.component(adj, e, skip=frozenset({x_id}))
                seen |= p
                parts.append(p)
        rooted = [p for p in parts if any(self.is_head(self.work[e]) for e in p)]
        rooted_ids = set().union(*rooted) if rooted else set()
        tails = [p for p in parts if not (p & rooted_ids)]
        if self.is_head(x):
            for tail in tails:
                self._main_removed(x, tail, neighbours)
            return
        for tail in tails:
            if not rooted:
                self.warnings.append(f"{x.name}: its chain has no main building; "
                                     "the rest stays where it is")
                continue
            self._reattach(x, tail, neighbours, rooted_ids)

    def _reattach(self, x: Building, tail: set[int], neighbours: set[int],
                  rooted_ids: set[int]) -> None:
        """The tail piece in x's link slot moves into x's place; the tail shifts with it."""
        head = next((self.work[e] for e in rooted_ids if self.is_head(self.work[e])), None)
        entry = {"removed": x.entity_id, "moved": sorted(tail),
                 "to": head.entity_id if head else None,
                 "to_name": head.name if head else None}
        size = (x.footprint.width, x.footprint.length)
        for s in sorted(tail & neighbours):
            sb = self.work[s]
            if (sb.footprint.width, sb.footprint.length) != size:
                continue
            dx, dy = x.footprint.x - sb.footprint.x, x.footprint.y - sb.footprint.y
            self.shift(tail, dx, dy)
            if self.linked_to_any(s, rooted_ids):
                self.reattached.append({**entry, "ok": True, "offset": [dx, dy]})
                self.touched |= tail | rooted_ids
                return
            self.shift(tail, -dx, -dy)
        self.reattached.append({**entry, "ok": False})
        self.warnings.append(
            f"removing {x.name} cuts off {len(tail)} chain piece(s) that cannot take its "
            "slot (different size); they stay in place, unlinked")

    def _main_removed(self, x: Building, tail: set[int], neighbours: set[int]) -> None:
        target = self.relink.get(x.entity_id)
        others = self.heads_of(x.chain_id)
        if target is not None:
            s = next(iter(sorted(tail & neighbours)), None)
            if s is not None:
                sb = self.work[s]
                slot = self.free_slot(target, sb.footprint.width, sb.footprint.length)
                if slot is not None:
                    dx, dy = slot[0] - sb.footprint.x, slot[1] - sb.footprint.y
                    self.shift(tail, dx, dy)
                    tgroup = self.component(self.adjacency(), target)
                    if s in tgroup:
                        self.relinked += sorted(tail)
                        self.reattached.append({
                            "removed": x.entity_id, "moved": sorted(tail), "to": target,
                            "to_name": self.work[target].name, "ok": True,
                            "offset": [dx, dy], "relinked": True})
                        self.touched |= tgroup
                        return
                    self.shift(tail, -dx, -dy)
            self.warnings.append(f"the patches of {x.name} could not be attached to "
                                 f"{self.work[target].name} (no free slot); they go to store")
        for e in sorted(tail):
            self.store(e, "patch of a removed main building", main=x.entity_id)
        self.cascades.append({
            "main": x.entity_id, "main_name": x.name, "stored": sorted(tail),
            "relink_candidates": [{"entity_id": h.entity_id, "name": h.name}
                                  for h in others]})

    # -- additions ----------------------------------------------------------
    def add(self, specs: list[dict]) -> list[dict]:
        next_id = max(self.work.keys() | {b.entity_id for b in self.src.buildings},
                      default=0) + 1
        xs = [x for x, _ in self.src.region.cells] or [0]
        ys = [y for _, y in self.src.region.cells] or [0]
        vx, vy = max(xs) + 6, min(ys)          # parking lot outside the region
        total = sum(s["count"] for s in specs)
        added: list[dict] = []
        # Mains and plain buildings first, so patches can link to a new main.
        for spec in sorted(specs, key=lambda s: s.get("_patch", False)):
            for _ in range(spec["count"]):
                b = spec["_proto"]
                b = replace(b, entity_id=next_id)
                next_id += 1
                link_to = None
                w, l = b.footprint.width, b.footprint.length
                if spec.get("_patch"):
                    link_to = self._pick_main(b, spec.get("link_to"))
                    slot = self.free_slot(link_to, w, l)
                    if slot is None:
                        raise EditError(
                            f"{self.work[link_to].name} has no free {w}x{l} link slot at the "
                            f"end of its chain for {b.name}", entity=b.cityentity_id)
                    b = replace(b, footprint=Footprint(slot[0], slot[1], w, l))
                    self.work[b.entity_id] = b
                    group = self.component(self.adjacency(), link_to)
                    if b.entity_id not in group or make_composite(
                            [self.work[e] for e in group]) is None:
                        raise EditError(
                            f"adding {b.name} to {self.work[link_to].name}'s chain would not "
                            "give one rigid block; not supported", entity=b.cityentity_id)
                    self.touched |= group
                else:
                    b = replace(b, footprint=Footprint(vx, vy, w, l))
                    vy += l + 2 * total + 6
                    self.work[b.entity_id] = b
                self.order.append(b.entity_id)
                added.append({"entity_id": b.entity_id, "link_to": link_to})
        return added

    def relink_loose(self) -> list[int]:
        """Attach every loose chain piece (ascending id) at the free END slot of
        its chain's main, like an added patch; the entity id is kept. With
        several mains the lowest id that has a free slot wins. A piece that
        cannot be attached stays where it is and is reported in `loose_failed`."""
        moved = []
        for e in loose_chain_pieces(self._layout(), self.catalog):
            b = self.work[e]
            w, l = b.footprint.width, b.footprint.length
            info = {"entity_id": e, "name": b.name}
            heads = sorted(h.entity_id for h in self.heads_of(b.chain_id))
            if not heads:
                self.loose_failed.append({**info, "reason": "no_main"})
                continue
            main = next((h for h in heads if self.free_slot(h, w, l) is not None), None)
            if main is None:
                self.loose_failed.append({**info, "reason": "no_free_slot"})
                continue
            sx, sy = self.free_slot(main, w, l)
            self.work[e] = replace(b, footprint=Footprint(sx, sy, w, l))
            group = self.component(self.adjacency(), main)
            if e not in group or make_composite([self.work[g] for g in group]) is None:
                self.work[e] = b
                self.loose_failed.append({**info, "reason": "not_rigid"})
                continue
            self.touched |= group
            self.loose_relinked.append({**info, "main": main})
            moved.append(e)
        return moved

    def _pick_main(self, b: Building, link_to) -> int:
        heads = self.heads_of(b.chain_id)
        cands = [{"entity_id": h.entity_id, "name": h.name} for h in heads]
        if link_to is not None:
            if link_to not in {h.entity_id for h in heads}:
                raise EditError(f"link_to {link_to} is not a main building of chain "
                                f"{b.chain_id}", candidates=cands, entity=b.cityentity_id)
            return link_to
        if not heads:
            raise EditError(f"{b.name} is a chain patch but the city has no main building "
                            f"of chain {b.chain_id}; add the main building first",
                            candidates=[], entity=b.cityentity_id)
        if len(heads) > 1:
            raise EditError(f"{b.name}: the city has {len(heads)} main buildings of chain "
                            f"{b.chain_id}; choose one with link_to",
                            candidates=cands, entity=b.cityentity_id, link_to_required=True)
        return heads[0].entity_id

    # -- seed placement -----------------------------------------------------
    def place_for_seed(self, new_ids: list[int]) -> list[int]:
        """Greedy: put every new building (or the chain block it joined) into
        free cells of the upload, road-needing ones touching the upload's own
        connected roads. Returns the ids that could not be placed."""
        region = self.src.region.cells
        roads = self.src.roads
        lay = self._layout()
        conn = connected_road_cells(lay)
        lane = two_lane_connected(lay)
        new = set(new_ids)
        adj = self.adjacency()
        units, seen = [], set()
        for e in new_ids:
            if e in seen:
                continue
            u = self.component(adj, e) if self.work[e].chain_id else {e}
            seen |= u
            units.append(u)
        unit_ids = set().union(*units) if units else set()
        occ: set = set(roads)
        for e, b in self.work.items():
            if e not in unit_ids:
                occ |= b.footprint.cells()

        def fits(u: set[int], dx: int, dy: int) -> bool:
            for e in u:
                fp = self.work[e].footprint
                cells = Footprint(fp.x + dx, fp.y + dy, fp.width, fp.length).cells()
                if not cells <= region or cells & occ:
                    return False
            for e in u:
                b = self.work[e]
                if not b.needs_road or b.is_townhall:
                    continue
                fp = b.footprint
                border = Footprint(fp.x + dx, fp.y + dy, fp.width, fp.length).border_cells()
                ok = (border & lane) if b.road_level >= 2 else {
                    c for c in border & conn if roads[c] >= b.road_level}
                if not ok:
                    return False
            return True

        def take(u: set[int]) -> None:
            for e in u:
                occ.update(self.work[e].footprint.cells())

        unplaced: list[int] = []
        area = lambda u: sum(self.work[e].footprint.width * self.work[e].footprint.length for e in u)
        xs = sorted({x for x, _ in region})
        ys = sorted({y for _, y in region})
        for u in sorted(units, key=lambda u: -area(u)):
            if fits(u, 0, 0):           # an added patch whose slot is free in the upload
                take(u)
                continue
            x0 = min(self.work[e].footprint.x for e in u)
            y0 = min(self.work[e].footprint.y for e in u)
            spot = next(((x - x0, y - y0) for y in ys for x in xs if fits(u, x - x0, y - y0)),
                        None)
            if spot is None:
                unplaced += sorted(u & new)
                continue
            self.shift(u, *spot)
            take(u)
        return unplaced

    def result(self) -> Layout:
        th = self.src.townhall
        out = Layout(self.src.region, [self.work[e] for e in self.order if e in self.work],
                     th, dict(self.src.roads))
        out.catalog_known = getattr(self.src, "catalog_known", True)
        return out


def loose_chain_pieces(layout: Layout, catalog: Catalog | None) -> list[int]:
    """Entity ids of non-head chain pieces that take part in no active chain
    link, in a city that holds a head of the same chain (so a slot exists for
    them). Empty without a catalog, which is needed to tell heads from patches."""
    if catalog is None:
        return []
    heads = {b.chain_id for b in layout.buildings
             if b.chain_id and catalog.is_chain_head(b.cityentity_id)}
    linked = {e for link in chain_links(layout) for e in link}
    return sorted(b.entity_id for b in layout.buildings
                  if b.chain_id in heads and b.entity_id not in linked
                  and not catalog.is_chain_head(b.cityentity_id))


def _int_ids(values, what: str) -> list[int]:
    try:
        return [int(v) for v in values]
    except (TypeError, ValueError):
        raise EditError(f"{what} must be a list of building ids")


def _parse_add(spec, catalog: Catalog | None) -> dict:
    if not isinstance(spec, dict):
        raise EditError("each addition must be an object")
    try:
        count = int(spec.get("count", 1))
    except (TypeError, ValueError):
        raise EditError(f"count must be a whole number, got {spec.get('count')!r}")
    if not 1 <= count <= MAX_ADD_COUNT:
        raise EditError(f"count must be 1..{MAX_ADD_COUNT}, got {count}")
    cid = spec.get("cityentity_id")
    if cid:
        if catalog is None or cid not in catalog.ids():
            raise EditError(f"unknown building type {cid!r}", unknown_entity=cid)
        size = catalog.size(cid)
        etype = catalog.entity_type(cid)
        if size is None or etype in UNPLACEABLE_TYPES or etype == "main_building":
            raise EditError(f"{cid!r} cannot be placed on the city grid", unknown_entity=cid)
        req = catalog.street_requirement(cid)
        chain = catalog.chain_id(cid)
        proto = Building(
            entity_id=0, cityentity_id=cid, type=etype, footprint=Footprint(0, 0, *size),
            needs_road=req > 0, road_level=catalog.required_level(cid), is_townhall=False,
            set_id=catalog.set_id(cid), chain_id=chain, name=catalog.name(cid),
            link_positions=catalog.link_positions(cid))
        link_to = spec.get("link_to")
        if link_to is not None:
            try:
                link_to = int(link_to)
            except (TypeError, ValueError):
                raise EditError(f"link_to must be a building id, got {link_to!r}")
        return {"count": count, "_proto": proto, "link_to": link_to,
                "_patch": bool(chain) and not catalog.is_chain_head(cid)}
    if "width" not in spec or "length" not in spec:
        raise EditError("an addition needs a cityentity_id, or a width and length")
    try:
        w, l = int(spec["width"]), int(spec["length"])
    except (TypeError, ValueError):
        raise EditError(f"width and length must be whole numbers, got "
                        f"{spec.get('width')!r} x {spec.get('length')!r}")
    if w < 1 or l < 1 or w > 20 or l > 20:
        raise EditError(f"building size must be 1x1 .. 20x20, got {w}x{l}")
    needs = bool(spec.get("needs_road", False))
    try:
        level = int(spec.get("road_level", 1) or 1) if needs else 1
    except (TypeError, ValueError):
        raise EditError("road_level must be 1 or 2")
    if level not in (1, 2):
        raise EditError("road_level must be 1 or 2")
    name = spec.get("name") or f"Custom {w}x{l}"
    proto = Building(entity_id=0, cityentity_id="custom", type="custom",
                     footprint=Footprint(0, 0, w, l), needs_road=needs, road_level=level,
                     is_townhall=False, set_id=None, chain_id=None, name=str(name)[:80])
    return {"count": count, "_proto": proto, "link_to": None, "_patch": False}


def apply_edits(layout: Layout, remove_ids, add: list | None = None,
                catalog: Catalog | None = None,
                relink: dict | None = None,
                relink_loose: bool = False) -> tuple[Layout, dict]:
    """The edited layout (upload roads kept) and a report:
    `to_store` (every building that leaves the map, with the reason),
    `reattached`, `cascades` (mains whose patches go to store, with the other
    mains they could be attached to instead), `added`, `warnings`,
    `not_composable`, `seed` ({possible, reason}) and `space`.
    With `relink_loose`, loose chain pieces are attached to their main
    (`relinked`); those that cannot be are listed in `relink_failed` with a
    reason: no_main, no_free_slot or not_rigid.
    Raises EditError on an invalid edit set."""
    add = add if add is not None else []
    if not isinstance(add, list):
        raise EditError("add must be a list")
    remove = _int_ids(remove_ids or [], "remove")
    known = {b.entity_id: b for b in layout.buildings}
    unknown = sorted({e for e in remove if e not in known})
    if unknown:
        raise EditError(f"unknown building ids: {unknown[:10]}", unknown_ids=unknown)
    th_id = layout.townhall.entity_id if layout.townhall is not None else None
    if th_id in remove:
        raise EditError("the Town Hall cannot be removed")
    relink_map: dict[int, int] = {}
    for k, v in (relink or {}).items():
        try:
            main, target = int(k), int(v)
        except (TypeError, ValueError):
            raise EditError("relink maps a removed main building id to another main's id")
        if main not in remove or target not in known or target in remove:
            raise EditError(f"relink {main} -> {target}: the first must be removed, the "
                            "second kept")
        if known[main].chain_id is None or known[main].chain_id != known[target].chain_id:
            raise EditError(f"relink {main} -> {target}: not the same chain")
        relink_map[main] = target
    specs = [_parse_add(s, catalog) for s in add]

    ed = _Editor(layout, catalog, relink_map)
    # Mains first: their patches go to store (or move) before a patch removal
    # would try to reattach them.
    for e in sorted(set(remove), key=lambda e: (not ed.is_head(known[e]), e)):
        ed.remove(e)
    added = ed.add(specs)
    new_ids = [a["entity_id"] for a in added]
    loose_moved = ed.relink_loose() if relink_loose else []

    adj = ed.adjacency()
    not_composable, seen = [], set()
    for e in sorted(ed.touched & ed.work.keys()):
        if e in seen:
            continue
        group = ed.component(adj, e)
        seen |= group
        if len(group) > 1 and make_composite([ed.work[g] for g in group]) is None:
            names = sorted({ed.work[g].name for g in group})
            not_composable.append({"members": sorted(group), "names": names})
            ed.warnings.append(f"the chain {', '.join(names[:3])} is no longer one rigid "
                               "block after the edit; a run would break its links")

    # Relinked patches moved next to another main, usually onto other
    # buildings: they need a free spot as much as new buildings do.
    movers = new_ids + ed.relinked + loose_moved
    unplaced = ed.place_for_seed(movers) if movers else []
    out = ed.result()

    added_info = []
    for a in added:
        b = ed.work[a["entity_id"]]
        added_info.append(_info(b, needs_road=b.needs_road, road_level=b.road_level,
                                chain_id=b.chain_id, link_to=a["link_to"],
                                placed=a["entity_id"] not in unplaced,
                                x=b.footprint.x, y=b.footprint.y))

    if unplaced:
        seed = {"possible": False,
                "reason": f"{len(unplaced)} new or relinked building(s) do not fit in the "
                          "upload's free cells"}
    elif not layout.roads or layout.townhall is None:
        seed = {"possible": False, "reason": "no roads"}
    else:
        rep = legality_check(out, out)
        seed = ({"possible": True, "reason": None} if rep.status == "valid" else
                {"possible": False, "reason": f"edited upload is {rep.status}",
                 "violations": rep.violations[:3]})

    region = len(layout.region.cells)
    area = sum(b.footprint.width * b.footprint.length for b in out.buildings)
    removed_cells = sum(s["width"] * s["length"] for s in ed.stored)
    added_cells = sum(a["width"] * a["length"] for a in added_info)
    free = region - area
    space = {"region_cells": region, "building_cells": area, "free_cells": free,
             "removed_cells": removed_cells, "added_cells": added_cells,
             "upload_roads": len(layout.roads), "fits_without_roads": free >= 0,
             "fits_with_upload_roads": free - len(layout.roads) >= 0,
             "overflow": max(0, -free)}

    report = {"removed": sorted(set(remove)), "to_store": ed.stored,
              "reattached": ed.reattached, "cascades": ed.cascades, "added": added_info,
              "warnings": ed.warnings, "not_composable": not_composable, "seed": seed,
              "space": space, "relinked": ed.loose_relinked,
              "relink_failed": ed.loose_failed}
    return out, report
