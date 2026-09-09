"""`ers.coverage` -- the module every published coverage figure goes through.

It had no direct test before the 2026-09 repair: it was exercised only
incidentally through the pipeline, which is how `leave_one_out_min`'s job (the
one-station-at-a-time sensitivity that E-11b spends its time on) could have been
got wrong without anything noticing.
"""
from __future__ import annotations

import numpy as np
import pytest

from ers.coverage import (ACCESS_SPEED_MS, by_group, leave_one_out_min,
                          summarise, to_response_s)


# ------------------------------------------------------------ leave_one_out_min

def test_leave_one_out_matches_the_naive_reduction():
    """The whole point: identical numbers, far less work."""
    rng = np.random.default_rng(11)
    fields = rng.random((33, 500)) * 1000

    fast = leave_one_out_min(fields)
    for i in range(fields.shape[0]):
        naive = np.delete(fields, i, axis=0).min(axis=0)
        assert np.array_equal(fast[i], naive), f"row {i} differs from the naive min"


def test_leave_one_out_handles_ties():
    """Two sources equally close is the case an argmin-based shortcut gets wrong."""
    fields = np.array([[5.0, 5.0], [5.0, 9.0], [7.0, 9.0]])
    out = leave_one_out_min(fields)
    # Dropping one of a tied pair leaves the other, so the best time is unchanged.
    assert out[0].tolist() == [5.0, 9.0]
    assert out[1].tolist() == [5.0, 5.0]
    assert out[2].tolist() == [5.0, 5.0]


def test_leave_one_out_propagates_unreachable():
    """A cutoff leaves inf. Removing the only source that reached a target must
    give inf back, not a finite number borrowed from somewhere else."""
    fields = np.array([[10.0, np.inf], [np.inf, 20.0]])
    out = leave_one_out_min(fields)
    assert out[0][0] == np.inf and out[0][1] == 20.0
    assert out[1][0] == 10.0 and out[1][1] == np.inf


def test_leave_one_out_rejects_a_single_source():
    with pytest.raises(ValueError):
        leave_one_out_min(np.zeros((1, 4)))


# ------------------------------------------------------------- to_response_s

def test_response_adds_access_walk_and_overhead():
    best_ds = np.array([1200.0])          # 120 s of driving
    snap_m = np.array([60.0])             # 50 s at 1.2 m/s
    got = to_response_s(best_ds, snap_m, overhead_s=17.5)
    assert got[0] == pytest.approx(120 + 60 / ACCESS_SPEED_MS + 17.5)


def test_unreachable_stays_unreachable_through_the_conversion():
    got = to_response_s(np.array([np.inf]), np.array([10.0]), overhead_s=17.5)
    assert np.isinf(got[0]), "a severed cell must not acquire a finite response time"


# ---------------------------------------------------------------- summarise

def test_coverage_share_is_population_weighted_not_cell_counted():
    """Two cells inside the budget, one holding 100x the people of the other."""
    best_s = np.array([100.0, 100.0, 900.0])
    pop = np.array([10.0, 1000.0, 10.0])
    out = summarise(best_s, pop, budget_s=300.0)
    assert out["coverage_share"] == pytest.approx(1010 / 1020, abs=1e-4)


def test_severed_cells_are_reported_separately_from_merely_distant_ones():
    best_s = np.array([100.0, 5000.0, np.inf])
    pop = np.array([100.0, 100.0, 100.0])
    out = summarise(best_s, pop, budget_s=300.0)
    assert out["unreachable_cells"] == 1
    assert out["unreachable_population"] == 100
    assert out["population_outside"] == 200, "distant and severed are both outside"


def test_percentiles_are_defined_on_an_all_severed_scenario():
    """A flood CAN cut every cell from every station. That is a result."""
    out = summarise(np.array([np.inf, np.inf]), np.array([1.0, 1.0]), budget_s=300.0)
    assert out["coverage_share"] == 0.0
    assert out["p90_travel_s"] is None


def test_threshold_ladder_is_monotone_in_the_budget():
    rng = np.random.default_rng(3)
    best_s = rng.random(500) * 900
    pop = np.ones(500)
    out = summarise(best_s, pop, budget_s=300.0,
                    ladder={"a": 180.0, "b": 300.0, "c": 420.0})
    shares = [out["threshold_ladder"][k]["coverage_share"] for k in ("a", "b", "c")]
    assert shares == sorted(shares), "a larger budget cannot cover fewer people"


# ----------------------------------------------------------------- by_group

def test_groups_with_no_population_are_skipped_not_reported_as_zero():
    best_s = np.array([100.0, 100.0, 100.0])
    pop = np.array([50.0, 0.0, 50.0])
    out = by_group(best_s, pop, np.array([1, 2, 3]), budget_s=300.0)
    assert set(out) == {"1", "3"}, "an empty ward has no coverage share to report"


# ------------------------------------------------------------- graded_share

BANDS = [{"t_s": 300, "u": 1.0}, {"t_s": 420, "u": 0.7}, {"t_s": 600, "u": 0.3}]


def test_graded_credits_each_cell_at_its_first_band():
    from ers.coverage import graded_share
    best_s = np.array([100.0, 350.0, 500.0, 900.0])
    pop = np.array([100.0, 100.0, 100.0, 100.0])
    out = graded_share(best_s, pop, BANDS)
    assert out["graded_share"] == pytest.approx((1.0 + 0.7 + 0.3 + 0.0) / 4)
    assert out["population_beyond_last_band"] == 100


def test_graded_is_never_below_the_binary_share_at_the_same_threshold():
    """The first band is the binary definition; the rest is extra credit."""
    from ers.coverage import graded_share, summarise
    rng = np.random.default_rng(7)
    best_s = rng.random(400) * 900
    pop = rng.random(400) * 1000
    binary = summarise(best_s, pop, budget_s=300.0)["coverage_share"]
    graded = graded_share(best_s, pop, BANDS)["graded_share"]
    assert graded >= binary - 1e-9


def test_graded_ignores_severed_cells():
    from ers.coverage import graded_share
    out = graded_share(np.array([100.0, np.inf]), np.array([100.0, 100.0]), BANDS)
    assert out["graded_share"] == pytest.approx(0.5)
    assert out["population_beyond_last_band"] == 100


def test_graded_is_order_independent_in_the_band_list():
    from ers.coverage import graded_share
    best_s = np.array([100.0, 350.0, 500.0])
    pop = np.ones(3) * 10
    a = graded_share(best_s, pop, BANDS)["graded_share"]
    b = graded_share(best_s, pop, list(reversed(BANDS)))["graded_share"]
    assert a == b
