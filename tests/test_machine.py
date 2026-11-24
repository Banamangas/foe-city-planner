from foeopt.machine import pick_parallelism

def test_strong_cpu_keeps_today_setting():
    p = pick_parallelism(16)
    assert (p["workers"], p["probe_workers"], p["reduced"], p["warn"]) == (6, 2, False, False)

def test_eight_threads_leaves_headroom():
    assert (pick_parallelism(8)["workers"], pick_parallelism(8)["probe_workers"]) == (3, 2)

def test_four_threads():
    p = pick_parallelism(4)
    assert (p["workers"], p["probe_workers"], p["reduced"], p["warn"]) == (1, 2, True, False)

def test_tiny_or_unknown_machine_still_runs_and_warns():
    for n in (None, 1, 2):
        p = pick_parallelism(n)
        assert p["workers"] >= 1 and p["probe_workers"] >= 1 and p["warn"]

def test_low_memory_warns():
    assert pick_parallelism(16, mem_gb=3.0)["warn"]

def test_never_above_twelve_threads():
    assert pick_parallelism(64)["threads"] == 12
