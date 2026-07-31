"""Fast scoring of a road skeleton by the anchor-option count `probe()` already
computes and throws away.

`probe()` begins by enumerating, for every road-needing consumer, the anchor
positions where its footprint is entirely free and at least one border cell is a
road (`roads_first._anchor_candidates`). It records the total into `diag` as
`opts_total` and then discards it. Measured on the 1,400-probe run that produced
the 98-road darkzig record, that single number separates feasible skeletons from
infeasible ones at **ROC-AUC 0.990** (0.993 within the strongest parameter
bucket) -- for 0.1% of a 300 s CP-SAT probe.

Why this module exists rather than just calling `_anchor_candidates` in a loop:
the reference implementation costs ~0.37 s per skeleton, which is fine for the
63 consumers of one probe but not for ranking a *population* of ~160,000
skeletons per k-level. This computes the identical number with per-row integer
bitmasks (shift/AND/OR over Python big ints, grouped by distinct footprint
size), which is ~3 orders of magnitude faster and pure-stdlib.

**This is a heuristic ranker, not a certificate.** Unlike `prefilter()`, which
never rejects a feasible skeleton, a low `opts_total` does not prove
infeasibility. And it must not be used to pick the *best* skeleton: among known
SATs, `opts_total` correlates with the final `route()` road count at Spearman
+0.50 -- the wrong sign. Use it to discard the bulk of hopeless skeletons, then
sample uniformly among the survivors. See `tasks/rl-situation-report.md` §4.4
and `tasks/todo.md` Track F.
"""
from __future__ import annotations

from foeopt.model import Building, Footprint

Cell = tuple[int, int]


def mean_free_adjacency(region: set[Cell], th: Footprint,
                        roads: frozenset[Cell]) -> float:
    """Average number of free cells orthogonally adjacent to each road cell.

    The project's first measured *quality* predictor. Unlike `opts_total` (which
    predicts whether a skeleton is feasible, and is anti-correlated with road
    count), this predicts what `route()` will actually cost: Spearman **+0.76**
    against `achieved` on the 20 SATs of the 98-road baseline run and **+0.64**
    on held-out SATs of the widened-pitch screen -- two independent datasets,
    different pitch ranges, different sampling. Lower is better.

    Mechanism: a road cell with many free neighbours sits in open ground, so the
    placement around it is loose and `route()` rebuilds a large network; a cell
    hemmed in by buildings is double-loaded and serves consumers on both sides.
    It is a computable proxy for the sharing the expert city maximises.

    Cheap enough to filter a whole population with (4 lookups per road cell) and
    computable *before* probing, since it needs only the skeleton and the region.
    """
    free = region - roads - th.cells()
    if not roads:
        return 0.0
    total = 0
    for (x, y) in roads:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) in free:
                total += 1
    return total / len(roads)


class SkeletonScorer:
    """Scores skeletons for one fixed city (region + consumer footprint mix).

    Build once per city, then call `opts_total` per skeleton. The region masks
    and the footprint-size histogram are the expensive constant parts and are
    computed here, not per skeleton.
    """

    def __init__(self, region: set[Cell], consumers: list[Building]):
        xs = [c[0] for c in region]
        ys = [c[1] for c in region]
        self.x0, self.y0 = min(xs), min(ys)
        self.x1, self.y1 = max(xs), max(ys)
        self.w = self.x1 - self.x0 + 1
        self.h = self.y1 - self.y0 + 1
        self._region_rows = [0] * self.h
        for (x, y) in region:
            self._region_rows[y - self.y0] |= 1 << (x - self.x0)
        # Distinct footprint sizes with multiplicity: consumers sharing a size
        # have identical anchor sets, so the window arithmetic runs once per
        # size and is multiplied out.
        sizes: dict[tuple[int, int], int] = {}
        for b in consumers:
            key = (b.footprint.width, b.footprint.length)
            sizes[key] = sizes.get(key, 0) + 1
        self._sizes = sorted(sizes.items())

    def opts_total(self, th: Footprint, roads: frozenset[Cell]) -> int:
        """Total road-adjacent, fully-free anchor positions summed over every
        consumer. Equal to `sum(len(_anchor_candidates(b, region, roads | th, roads)))`.
        """
        h, w_grid = self.h, self.w
        x0, y0 = self.x0, self.y0
        free_rows = list(self._region_rows)
        road_rows = [0] * h
        for (x, y) in roads:
            iy = y - y0
            if 0 <= iy < h:
                bit = 1 << (x - x0)
                road_rows[iy] |= bit
                free_rows[iy] &= ~bit
        for (x, y) in th.cells():
            iy = y - y0
            if 0 <= iy < h:
                free_rows[iy] &= ~(1 << (x - x0))

        total = 0
        for (bw, bl), count in self._sizes:
            if bw > w_grid or bl > h:
                continue
            # x positions must keep the whole footprint inside the bbox
            xlimit = (1 << (w_grid - bw + 1)) - 1
            # row_run[r]: bit j set iff cells (x0+j .. x0+j+bw-1, y0+r) all free
            row_run = []
            for r in range(h):
                m = free_rows[r]
                for i in range(1, bw):
                    m &= free_rows[r] >> i
                row_run.append(m & xlimit)
            # road_run[r]: bit j set iff any road in that same w-window
            road_run = []
            for r in range(h):
                m = road_rows[r]
                for i in range(1, bw):
                    m |= road_rows[r] >> i
                road_run.append(m & xlimit)
            for r in range(h - bl + 1):
                box = row_run[r]
                for d in range(1, bl):
                    box &= row_run[r + d]
                    if not box:
                        break
                if not box:
                    continue
                # border cells are the orthogonal ring without corners
                # (model._footprint_border): the row above, the row below, and
                # the single column on each side spanning the footprint's rows.
                adj = 0
                if r - 1 >= 0:
                    adj |= road_run[r - 1]
                if r + bl < h:
                    adj |= road_run[r + bl]
                for d in range(bl):
                    rm = road_rows[r + d]
                    adj |= (rm << 1) | (rm >> bw)
                hit = box & adj & xlimit
                if hit:
                    total += hit.bit_count() * count
        return total
