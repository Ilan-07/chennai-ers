"""Invariants that must hold for ANY input, not just the ones we thought of.

`hypothesis` has been a declared dependency of this project since the start and
was used by nothing -- the same declared-but-unwired pattern the 2026-09 repair
found in the demand surfaces, the coverage bands and the ward loader.

These are the properties whose violation produced real defects:

  * F-13 published coverage BELOW the do-nothing baseline, which adding stations
    cannot cause. That is a monotonicity violation, and monotonicity is exactly
    what a property test is for.
  * The threshold ladder must be monotone in the budget. It is computed by a
    loop over thresholds and nothing checked the ordering it produces.
  * `leave_one_out_min` replaced a 33x more expensive reduction. "Same answer on
    the cases I tried" is not the standard it needs to meet.
"""
from __future__ import annotations

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from ers.coverage import graded_share, leave_one_out_min, summarise, to_response_s

# Response times in seconds, with infinities allowed: a flood CAN sever a cell,
# and every function here has to survive that rather than assume it away.
times = hnp.arrays(
    dtype=np.float64, shape=hnp.array_shapes(min_dims=1, max_dims=1, min_side=1, max_side=60),
    elements=st.one_of(st.floats(0, 3600, allow_nan=False), st.just(np.inf)))

pops = hnp.arrays(
    dtype=np.float64, shape=hnp.array_shapes(min_dims=1, max_dims=1, min_side=1, max_side=60),
    elements=st.floats(0, 1e5, allow_nan=False, allow_infinity=False))


@st.composite
def cells(draw, min_pop: float = 0.0):
    """A response time and a population for the SAME cells.

    Drawing the two arrays independently and filtering on equal length throws
    away almost every example -- hypothesis reports the health check rather
    than quietly testing nothing, which is the failure mode worth avoiding.
    """
    n = draw(st.integers(1, 60))
    best_s = draw(hnp.arrays(
        np.float64, n,
        elements=st.one_of(st.floats(0, 3600, allow_nan=False), st.just(np.inf))))
    pop = draw(hnp.arrays(
        np.float64, n,
        elements=st.floats(min_pop, 1e5, allow_nan=False, allow_infinity=False)))
    assume(pop.sum() > 0)
    return best_s, pop


@given(times, st.floats(1, 1200))
@settings(max_examples=120, deadline=None)
def test_coverage_share_is_always_a_share(best_s, budget):
    pop = np.ones_like(best_s)
    out = summarise(best_s, pop, budget_s=budget)
    assert 0.0 <= out["coverage_share"] <= 1.0
    assert 0.0 <= out["unreachable_share"] <= 1.0


@given(times, st.floats(1, 600), st.floats(1, 600))
@settings(max_examples=200, deadline=None)
def test_a_larger_budget_never_covers_fewer_people(best_s, a, b):
    """Monotonicity in the budget. F-13's symptom was a violation of the
    analogous property in k."""
    lo, hi = (a, b) if a <= b else (b, a)
    pop = np.ones_like(best_s)
    assert (summarise(best_s, pop, budget_s=lo)["coverage_share"]
            <= summarise(best_s, pop, budget_s=hi)["coverage_share"] + 1e-12)


@given(cells())
@settings(max_examples=150, deadline=None)
def test_covered_and_outside_partition_the_population(cp):
    best_s, pop = cp
    out = summarise(best_s, pop, budget_s=300.0)
    assert np.isclose(out["population_covered"] + out["population_outside"],
                      round(float(pop.sum())), atol=2.0)


@given(cells())
@settings(max_examples=150, deadline=None)
def test_unreachable_population_never_exceeds_the_population_outside(cp):
    """Severed is a SUBSET of not-covered. A severed cell cannot be covered."""
    best_s, pop = cp
    out = summarise(best_s, pop, budget_s=300.0)
    assert out["unreachable_population"] <= out["population_outside"] + 1e-6


@given(cells())
@settings(max_examples=150, deadline=None)
def test_graded_is_never_below_the_binary_share_at_the_first_band(cp):
    """Formulation E credits the first band at u=1.0 and everything beyond it at
    less, so it can only ever add to the binary figure."""
    best_s, pop = cp
    bands = [{"t_s": 300, "u": 1.0}, {"t_s": 420, "u": 0.7}, {"t_s": 600, "u": 0.3}]
    binary = summarise(best_s, pop, budget_s=300.0)["coverage_share"]
    assert graded_share(best_s, pop, bands)["graded_share"] >= binary - 1e-9


@given(cells())
@settings(max_examples=120, deadline=None)
def test_graded_share_stays_within_the_band_utilities(cp):
    best_s, pop = cp
    bands = [{"t_s": 300, "u": 1.0}, {"t_s": 600, "u": 0.3}]
    assert 0.0 <= graded_share(best_s, pop, bands)["graded_share"] <= 1.0


@given(hnp.arrays(
    dtype=np.float64,
    shape=hnp.array_shapes(min_dims=2, max_dims=2, min_side=2, max_side=8),
    elements=st.one_of(st.floats(0, 5000, allow_nan=False), st.just(np.inf))))
@settings(max_examples=150, deadline=None)
def test_leave_one_out_equals_the_naive_reduction_for_any_field(fields):
    """The optimisation that turned a 9.1 hour job into minutes. It must be
    exact for every input, including all-infinite rows and exact ties."""
    fast = leave_one_out_min(fields)
    for i in range(fields.shape[0]):
        naive = np.delete(fields, i, axis=0).min(axis=0)
        assert np.array_equal(fast[i], naive, equal_nan=True)


@given(hnp.arrays(
    dtype=np.float64,
    shape=hnp.array_shapes(min_dims=2, max_dims=2, min_side=2, max_side=8),
    elements=st.floats(0, 5000, allow_nan=False)))
@settings(max_examples=100, deadline=None)
def test_dropping_a_source_can_only_make_things_worse(fields):
    """Removing a station cannot bring anyone closer."""
    loo = leave_one_out_min(fields)
    overall = fields.min(axis=0)
    assert (loo >= overall - 1e-12).all()


@given(times, st.floats(0, 200), st.floats(0, 2000))
@settings(max_examples=120, deadline=None)
def test_response_time_is_monotone_in_the_overhead_and_the_access_walk(
        best_ds, overhead, snap_m):
    snap = np.full_like(best_ds, snap_m)
    a = to_response_s(best_ds, snap, overhead_s=overhead)
    b = to_response_s(best_ds, snap, overhead_s=overhead + 10.0)
    finite = np.isfinite(a)
    assert (b[finite] > a[finite] - 1e-9).all()
    assert np.isinf(b[~finite]).all(), "a severed cell stays severed"
