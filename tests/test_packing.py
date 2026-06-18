from foeopt.packing import Grid, first_fit


def test_fits_respects_bounds_and_blocked():
    g = Grid(3, 3, blocked={(2, 2)})
    assert g.fits(0, 0, 2, 2)
    assert not g.fits(2, 2, 1, 1)   # blocked
    assert not g.fits(2, 0, 2, 1)   # out of bounds (x+w > width)


def test_occupy_then_fits_false():
    g = Grid(3, 1, blocked=set())
    g.occupy(0, 0, 2, 1)
    assert not g.fits(0, 0, 1, 1)
    assert g.fits(2, 0, 1, 1)


def test_reserve_blocks_placement():
    g = Grid(3, 1, blocked=set())
    g.reserve([(1, 0)])
    assert not g.is_available((1, 0))
    assert not g.fits(0, 0, 2, 1)   # spans the reserved cell


def test_first_fit_bottom_left():
    g = Grid(3, 2, blocked=set())
    g.occupy(0, 0, 1, 1)            # (0,0) taken
    # lowest y then lowest x: a 1x1 should land at (1,0)
    assert first_fit(g, 1, 1) == (1, 0)


def test_first_fit_none_when_full():
    g = Grid(2, 1, blocked={(0, 0), (1, 0)})
    assert first_fit(g, 1, 1) is None
