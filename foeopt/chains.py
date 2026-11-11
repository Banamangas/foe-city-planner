"""Linked chains as rigid composite blocks.

The game activates a chain member only when it sits exactly at a catalog
linkPosition of the member it links to (see foeopt.legality.chain_links).
Buildings cannot rotate, so a chain linked in the input is a rigid shape. The
search places it as ONE composite building:

- `members`: (building, dx, dy) offsets from the composite's top-left.
- footprint: the members' bounding box.
- `contact`: the composite-relative cells where a road counts as touching it.
  That is the road-needing member's own edge, not the whole bounding box, so a
  road touching only a link piece does not count.

Composition is deliberately narrow. A linked group is composed only if
(a) its members tile their bounding box exactly (no holes, so the box blocks
no usable cell) and (b) at most one member needs a road (one contact edge
suffices). Any other group stays as separate buildings, and the legality
gate reports a broken chain instead of passing it.

`expand` turns composites back into their members at the composite's position.
It runs before routing, so the router, filler packer and validators only
ever see real buildings.
"""
from __future__ import annotations

from dataclasses import replace

from foeopt.legality import chain_links
from foeopt.model import Building, Footprint, Layout


def linked_groups(layout: Layout) -> list[list[Building]]:
    """Connected components (size >= 2) of the input's active chain links."""
    by_id = {b.entity_id: b for b in layout.buildings}
    adj: dict[int, set[int]] = {}
    for a, b in chain_links(layout):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen, groups = set(), []
    for start in sorted(adj):
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            e = stack.pop()
            comp.append(by_id[e])
            for n in adj[e]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        groups.append(sorted(comp, key=lambda b: b.entity_id))
    return groups


def make_composite(group: list[Building]) -> Building | None:
    """One rigid block for a linked group, or None if it is not composable."""
    if any(b.is_townhall for b in group):
        return None
    x0 = min(b.footprint.x for b in group)
    y0 = min(b.footprint.y for b in group)
    x1 = max(b.footprint.x + b.footprint.width for b in group)
    y1 = max(b.footprint.y + b.footprint.length for b in group)
    w, l = x1 - x0, y1 - y0
    if sum(b.footprint.width * b.footprint.length for b in group) != w * l:
        return None  # holes: the bounding box would block usable cells
    roaders = [b for b in group if b.needs_road]
    if len(roaders) > 1:
        return None  # each would need its own contact; not modelled
    cells = Footprint(x0, y0, w, l).cells()
    contact = None
    if roaders:
        r = roaders[0]
        contact = frozenset((cx - x0, cy - y0) for cx, cy in r.footprint.border_cells()
                            if (cx, cy) not in cells)
    head = roaders[0] if roaders else group[0]
    members = tuple((b, b.footprint.x - x0, b.footprint.y - y0) for b in group)
    return Building(
        entity_id=-head.entity_id, cityentity_id=f"chain:{head.chain_id}",
        type="chain", footprint=Footprint(x0, y0, w, l),
        needs_road=bool(roaders), road_level=max((b.road_level for b in roaders), default=1),
        is_townhall=False, set_id=None, chain_id=head.chain_id,
        name=f"{head.name} + {len(group) - 1} linked", members=members, contact=contact)


def compose(layout: Layout) -> Layout:
    """`layout` with every composable linked chain replaced by one composite.
    Returns the same object when there is nothing to compose."""
    composites, absorbed = [], set()
    for group in linked_groups(layout):
        c = make_composite(group)
        if c is not None:
            composites.append(c)
            absorbed |= {b.entity_id for b in group}
    if not composites:
        return layout
    keep = [b for b in layout.buildings if b.entity_id not in absorbed]
    out = Layout(layout.region, keep + composites, layout.townhall, dict(layout.roads))
    out.catalog_known = getattr(layout, "catalog_known", True)
    return out


def expand_buildings(buildings: list[Building]) -> list[Building]:
    out = []
    for b in buildings:
        if not b.members:
            out.append(b)
            continue
        x, y = b.footprint.x, b.footprint.y
        for m, dx, dy in b.members:
            out.append(replace(m, footprint=Footprint(x + dx, y + dy, m.footprint.width,
                                                      m.footprint.length)))
    return out


def has_composites(layout: Layout) -> bool:
    return any(b.members for b in layout.buildings)


def expand(layout: Layout) -> Layout:
    """Composites replaced by their members in place (same roads)."""
    if not has_composites(layout):
        return layout
    th = layout.townhall
    return Layout(layout.region, expand_buildings(layout.buildings), th, layout.roads)
