"""Every legal layout a run finds, not just the improvements: the player can
browse the alternatives at (or near) the best road count."""
from __future__ import annotations

from foeopt.legality import check as check_legality
from foeopt.model import Layout
from foeopt.stats import city_stats


def layout_to_dict(layout: Layout) -> dict:
    """Serialize a validated Layout to the compact dict format for SSE/API."""
    return {
        # [x, y, level]: level 2 marks a two-lane tile cell (older readers
        # that destructure [x, y] keep working).
        "roads": [[x, y, lvl] for (x, y), lvl in sorted(layout.roads.items())],
        "buildings": {str(b.entity_id): [b.footprint.x, b.footprint.y,
                                         b.footprint.width, b.footprint.length]
                      for b in layout.buildings},
    }


class LayoutCollector:
    """Keeps the `cap` legal, distinct layouts with the fewest roads.

    `offer` is cheap for a layout that cannot be kept (seen before, or no
    better than the worst kept one with the store full); the legality check and
    the stats run only for a layout that would be admitted. `count` is the
    number of layouts admitted over the run, evicted ones included."""

    def __init__(self, reference: Layout, *, military: str,
                 off_road: frozenset[int], cap: int = 30,
                 extra: dict | None = None) -> None:
        self.reference = reference
        self.military = military
        self.off_road = off_road
        self.cap = cap
        self.extra = extra
        self.count = 0
        self._kept: list[dict] = []
        self._seen: set = set()

    @staticmethod
    def _key(layout: Layout):
        return (frozenset(layout.roads),
                frozenset((b.entity_id, b.footprint.x, b.footprint.y)
                          for b in layout.buildings))

    def offer(self, layout: Layout, k: int | None, achieved: int) -> dict | None:
        roads = len(layout.roads)
        if len(self._kept) >= self.cap and roads >= self._worst()[0]:
            return None
        key = self._key(layout)
        if key in self._seen:
            return None
        self._seen.add(key)
        leg = check_legality(layout, self.reference, military=self.military,
                             off_road=self.off_road).as_dict()
        if leg["status"] != "valid":
            return None
        leg["military"] = self.military
        entry = {"id": self.count, "k": k, "achieved": achieved,
                 "stats": city_stats(layout, reference=self.reference),
                 "legality": leg, **layout_to_dict(layout),
                 **(self.extra or {})}
        self.count += 1
        if len(self._kept) >= self.cap:
            self._kept.remove(self._worst()[1])
        self._kept.append(entry)
        return entry

    def _worst(self) -> tuple[int, dict]:
        """(roads, entry) of the kept layout evicted first: most roads, latest found."""
        e = max(self._kept, key=lambda e: (len(e["roads"]), e["id"]))
        return len(e["roads"]), e

    def entries(self) -> list[dict]:
        return sorted(self._kept, key=lambda e: (len(e["roads"]), e["id"]))
