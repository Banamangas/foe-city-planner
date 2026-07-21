from foeopt.model import Footprint
from foeopt.roads_first import Pattern
from foeopt.placement_proxies import (
    road_contacts,
    proxy_touched_cells,
    proxy_subtree,
    proxy_double_loaded,
    proxy_same_size_clusters,
)

# Fixture: TH 2x1 at origin, a vertical road lane x=2 (y=0..3).
TH = Footprint(0, 0, 2, 1)
ROADS = frozenset({(2, 0), (2, 1), (2, 2), (2, 3)})
PAT = Pattern(th=TH, roads=ROADS, params={})

# Placement A: eid1 & eid2 flank road (2,2); eid3 touches (2,3).
POS_A = {1: (1, 2, 1, 1), 2: (3, 2, 1, 1), 3: (3, 3, 1, 1)}


def test_road_contacts_maps_cells_to_consumers():
    c = road_contacts(PAT, POS_A)
    assert c == {(2, 2): {1, 2}, (2, 3): {3}}


def test_touched_cells_counts_distinct_road_cells():
    assert proxy_touched_cells(PAT, POS_A) == 2


def test_touched_cells_detects_sharing():
    # both consumers flank the same cell (2,2) -> one touched cell
    assert proxy_touched_cells(PAT, {1: (1, 2, 1, 1), 2: (3, 2, 1, 1)}) == 1


def test_subtree_adds_connectors_to_townhall():
    # touched cells are (2,2) and (2,3); the only TH-root is (2,0) (adj to (1,0)),
    # so the subtree must include connectors (2,1)+(2,0): {(2,0),(2,1),(2,2),(2,3)} = 4.
    assert proxy_subtree(PAT, POS_A) == 4


def test_double_loaded_rewards_shared_cells_and_runs():
    # Only (2,2) serves >=2 consumers; no adjacent load>=2 cell -> 1 + 0 = 1.
    assert proxy_double_loaded(PAT, POS_A) == 1


def test_double_loaded_counts_a_run():
    # Two vertically-adjacent double-loaded cells (2,1)&(2,2): 2 cells + 1 run = 3.
    pos = {1: (1, 1, 1, 1), 2: (3, 1, 1, 1),   # flank (2,1)
           3: (1, 2, 1, 1), 4: (3, 2, 1, 1)}   # flank (2,2)
    assert proxy_double_loaded(PAT, pos) == 3


def test_same_size_clusters_rewards_aligned_same_size_pairs():
    # POS_A: three 1x1s. (1,2)&(3,2) share row y=2 -> +1; (3,2)&(3,3) share col x=3
    # -> +1; (1,2)&(3,3) neither -> 0. Total 2.
    assert proxy_same_size_clusters(PAT, POS_A) == 2


def test_same_size_clusters_ignores_different_sizes():
    # a 1x1 and a 2x1 sharing a row are NOT the same footprint -> 0.
    assert proxy_same_size_clusters(PAT, {1: (1, 2, 1, 1), 2: (3, 2, 2, 1)}) == 0
