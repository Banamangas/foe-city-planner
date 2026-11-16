"""Topology metrics of scripts/analyze_network_topology.py on a hand-made network."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "analyze_network_topology",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "analyze_network_topology.py",
)
ant = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ant)

TH = (10, 10, 3, 4)          # x 10-12, y 10-13


def _network():
    cells = [(x, 9) for x in range(8, 17)]                 # flush trunk on top, 9 cells
    cells += [(15, y) for y in (8, 7, 6, 5)]               # branch up from (15, 9)
    cells += [(16, 6), (17, 6)]                            # sub-branch: depth 3
    cells += [(13, 11), (14, 11), (15, 11), (15, 12), (15, 13)]  # bent spoke, right side
    return {c: 1 for c in cells}


CONSUMERS = [(16, 7, 2, 2), (13, 7, 2, 2)]   # either side of the branch


def test_turn_levels_counts_turns():
    L = {(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)}
    lv = ant.turn_levels(L, [((0, 0), ant.H)])
    assert lv == {(0, 0): 1, (1, 0): 1, (2, 0): 1, (2, 1): 2, (2, 2): 2}


def test_metrics_on_hand_made_network():
    m = ant.analyze(_network(), TH, CONSUMERS)
    assert m["roads"] == 20
    assert m["roots"] == 4 and m["sides_used"] == {"top": 3, "right": 1}
    assert m["components"] == 2 and m["detached"] == 0
    assert m["cyclomatic"] == 0 and m["th_loops"] == 0
    assert m["depth_max"] == 3
    assert m["bends"] == 1
    assert m["junctions"] == {3: 2}
    assert m["dead_end_stubs_1_2"] == 3
    assert (m["trunk_len"], m["trunk_offset"], m["trunk_rel"]) == (9, 0, "parallel")
    assert m["load_hist"] == {0: 13, 1: 5, 2: 2}
    assert m["both_sides_share"] == 0.1


def test_grammar_coverage_and_extensions():
    m = ant.analyze(_network(), TH, CONSUMERS)
    o = m["oog"]
    assert o["base"] == 7              # sub-branch (2) + spoke (5) out of grammar
    assert o["two_trunks"] == 2        # the spoke becomes a second trunk
    assert o["depth3"] == 5            # the sub-branch becomes depth 3
    assert o["two_trunks+depth3"] == 0
    assert o["th_depth2"] == 2 and o["th_depth3"] == 0
    assert "2nd trunk" in m["violations"] and "depth3/bent" in m["violations"]
    assert "spoke trunk" not in m["violations"]


def test_offset_trunk_is_level_two_from_its_line():
    # connector up from the TH top, then a parallel trunk 3 rows above it
    net = {(11, y): 1 for y in (9, 8, 7, 6)}
    net.update({(x, 6): 1 for x in range(5, 18)})
    m = ant.analyze(net, TH, [])
    assert m["oog"]["base"] > 0
    assert m["oog"]["offset"] == 0 and m["best_offset"] == ["top", 3]
    assert (m["trunk_offset"], m["trunk_rel"]) == (3, "parallel")
