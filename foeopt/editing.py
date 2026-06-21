from __future__ import annotations

from foeopt.model import Building, Footprint, Layout


def apply_edits(loaded: Layout, remove_ids: set[int], add_specs: list[dict]) -> Layout:
    """Return a new Layout with the requested buildings removed and added, ready
    for `repack`. The region and townhall are preserved; the Townhall is never
    removed. Added buildings get a fresh id and a position-irrelevant footprint
    (repack ignores positions)."""
    th_id = loaded.townhall.entity_id if loaded.townhall is not None else None
    kept = [b for b in loaded.buildings
            if b.entity_id not in remove_ids or b.entity_id == th_id]

    next_id = (max((b.entity_id for b in loaded.buildings), default=0)) + 1
    added: list[Building] = []
    for spec in add_specs:
        w, l = int(spec["width"]), int(spec["length"])
        if w < 1 or l < 1:
            raise ValueError(f"building size must be >= 1x1, got {w}x{l}")
        needs = bool(spec["needs_road"])
        name = spec.get("name") or f"Custom {w}x{l}"
        added.append(Building(
            entity_id=next_id, cityentity_id="custom", type="custom",
            footprint=Footprint(0, 0, w, l), needs_road=needs,
            road_level=1 if needs else 0, is_townhall=False,
            set_id=None, chain_id=None, name=name,
        ))
        next_id += 1

    return Layout(region=loaded.region, buildings=kept + added,
                  townhall=loaded.townhall, roads={})
