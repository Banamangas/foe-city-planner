import random

from foeopt.reach import placement_is_safe


def _rect(x, y, w, l):
    return frozenset((x + dx, y + dy) for dx in range(w) for dy in range(l))


def _grid(w, h):
    return {(x, y) for x in range(w) for y in range(h)}


def test_open_space_is_safe():
    free = _grid(8, 8)
    assert placement_is_safe(free, _rect(3, 3, 2, 2), sources={(0, 0)})


def test_one_wide_corridor_severed_is_unsafe():
    # corridor y=0, x=0..7; a 1x1 at (3,0) splits it; right half loses the source
    free = {(x, 0) for x in range(8)}
    assert not placement_is_safe(free, _rect(3, 0, 1, 1), sources={(-1, 0)})


def test_two_wide_corridor_severed_by_2x2_is_unsafe():
    # THE articulation counter-example: no single cell of the 2x2 is an
    # articulation point, yet the pair severs the 2-wide corridor.
    free = {(x, y) for x in range(8) for y in range(2)}
    assert not placement_is_safe(free, _rect(3, 0, 2, 2), sources={(-1, 0)})


def test_pocket_reachable_around_corner_is_safe():
    # L-shaped free space; footprint in the corridor leaves an around-the-corner
    # path to the pocket
    free = {(x, 0) for x in range(6)} | {(5, y) for y in range(4)} \
         | {(x, 3) for x in range(3, 6)}
    assert placement_is_safe(free, _rect(2, 0, 1, 1), sources={(-1, 0)}) is False
    # severing the only path is unsafe; consuming the dead-end tip (3,3) is
    # safe — (4,3),(5,3) stay connected around the corner via (5,2)
    assert placement_is_safe(free, _rect(3, 3, 1, 1), sources={(-1, 0)})


def test_consuming_a_whole_pocket_exactly_is_safe():
    # 2x2 pocket connected to the corridor only via (2,1)->(2,0); filling the
    # pocket exactly leaves no stranded component
    free = {(x, 0) for x in range(6)} | {(1, 1), (2, 1), (1, 2), (2, 2)}
    assert placement_is_safe(free, frozenset({(1, 1), (2, 1), (1, 2), (2, 2)}),
                             sources={(-1, 0)})


def test_guarded_border_must_keep_a_free_cell():
    # consumer's border has one free cell left at (4,0); occupying it is unsafe
    free = {(x, y) for x in range(8) for y in range(2)}
    guard = frozenset({(4, 0)})
    assert not placement_is_safe(free, _rect(4, 0, 1, 1),
                                 sources={(-1, 0)}, guarded=(guard,))
    assert placement_is_safe(free, _rect(6, 0, 1, 1),
                             sources={(-1, 0)}, guarded=(guard,))
