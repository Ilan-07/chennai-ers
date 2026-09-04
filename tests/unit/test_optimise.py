"""Optimiser tests. Build step 11."""
import itertools

import numpy as np
import pytest
from scipy import sparse

from ers.model.problem import SitingProblem, SitingSolution
from ers.optimise import exact, greedy

ONE_MINUS_1_E = 1 - 1 / np.e


def make(M, demand=None, pre=None, k=2, **kw):
    M = np.asarray(M, dtype=bool)
    n_i, n_j = M.shape
    return SitingProblem(
        coverage=sparse.csr_matrix(M),
        precovered=np.zeros(n_i, bool) if pre is None else np.asarray(pre, bool),
        demand=np.ones(n_i) if demand is None else np.asarray(demand, float),
        k=k, **kw)


def brute(problem):
    M = problem.coverage.toarray()
    best, arg = -1.0, None
    allowed = np.flatnonzero(problem.allowed())
    for combo in itertools.combinations(allowed, min(problem.k, len(allowed))):
        cov = problem.precovered | M[:, list(combo)].any(axis=1)
        v = problem.demand[cov].sum() - problem.demand[problem.precovered].sum()
        if v > best:
            best, arg = v, combo
    return best, arg


def test_problem_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        SitingProblem(coverage=sparse.csr_matrix(np.zeros((3, 2), bool)),
                      precovered=np.zeros(2, bool), demand=np.ones(3), k=1)


def test_problem_rejects_negative_k():
    with pytest.raises(ValueError):
        make([[True]], k=-1)


def test_greedy_picks_the_obvious_site():
    p = make([[1, 0], [1, 0], [0, 1]], k=1)
    s = greedy.solve(p)
    assert s.selected == (0,)
    assert s.objective == 2.0


def test_greedy_tie_break_is_deterministic_and_index_ordered():
    """Two identical columns must always yield the lower index, whatever the
    memory layout -- otherwise the recommendation is not reproducible."""
    p = make([[1, 1], [1, 1]], k=1)
    picks = {greedy.solve(p).selected for _ in range(20)}
    assert picks == {(0,)}


def test_greedy_respects_the_submodular_bound_on_random_instances():
    rng = np.random.default_rng(11)
    for _ in range(15):
        M = rng.random((25, 8)) < 0.3
        p = make(M, demand=rng.integers(1, 50, 25), k=3)
        g = greedy.solve(p)
        opt, _ = brute(p)
        assert g.objective >= ONE_MINUS_1_E * opt - 1e-9


def test_exact_matches_brute_force_on_random_instances():
    rng = np.random.default_rng(23)
    for _ in range(10):
        M = rng.random((30, 9)) < 0.3
        p = make(M, demand=rng.integers(1, 60, 30), k=3)
        opt, _ = brute(p)
        e = exact.solve(p)
        assert e.status == "Optimal"
        assert e.objective == pytest.approx(opt, abs=1e-6)
        assert e.gap == pytest.approx(0.0, abs=1e-6)


def test_exact_is_never_worse_than_greedy():
    rng = np.random.default_rng(5)
    for _ in range(8):
        M = rng.random((40, 12)) < 0.25
        p = make(M, demand=rng.integers(1, 90, 40), k=4)
        assert exact.solve(p).objective >= greedy.solve(p).objective - 1e-6


def test_precovered_cells_are_excluded_from_gain():
    """A cell an existing station already reaches contributes nothing to the
    marginal value of a new site."""
    p = make([[1, 0], [1, 0], [0, 1]], pre=[True, True, False], k=1)
    s = greedy.solve(p)
    assert s.selected == (1,)
    assert s.objective == 1.0
    assert s.baseline_covered == 2.0


def test_land_infeasible_candidates_are_never_selected():
    p = make([[1, 0], [1, 0], [0, 1]], k=1,
             land_feasible=np.array([False, True]))
    assert greedy.solve(p).selected == (1,)
    assert exact.solve(p).selected == (1,)


def test_forbidden_candidates_are_never_selected():
    p = make([[1, 0], [1, 0], [0, 1]], k=1, forbidden=np.array([True, False]))
    assert greedy.solve(p).selected == (1,)


def test_cell_no_candidate_reaches_is_reported_not_dropped():
    M = [[1, 0], [0, 0], [0, 1]]          # cell 1 is unreachable
    e = exact.solve(make(M, k=2))
    assert e.extra["cells_no_candidate_reaches"] == 1


def test_k_zero_selects_nothing():
    p = make([[1, 1], [1, 1]], k=0)
    assert greedy.solve(p).selected == ()
    assert exact.solve(p).selected == ()


def test_greedy_stops_when_no_positive_gain_remains():
    p = make([[1, 0], [1, 0]], k=5)       # only candidate 0 covers anything
    s = greedy.solve(p)
    assert s.selected == (0,)             # not padded out to k


def test_marginal_gains_are_non_increasing():
    """Submodularity: each additional station can only be worth less."""
    rng = np.random.default_rng(3)
    M = rng.random((60, 15)) < 0.2
    s = greedy.solve(make(M, demand=rng.integers(1, 100, 60), k=6))
    g = list(s.marginal_gains)
    assert all(g[i] >= g[i + 1] - 1e-9 for i in range(len(g) - 1))


def test_equity_floor_redirects_investment_to_the_worst_ward():
    """Ward 0 is large and ALREADY above the floor from existing stations;
    ward 1 is small and at zero. Efficiency buys the big ward's last cell;
    the floor forces the small ward instead, and that costs coverage."""
    #        candA candB
    M = [[1, 0],      # cell 0 - ward 0, uncovered
         [0, 0],      # cell 1 - ward 0, precovered
         [0, 0],      # cell 2 - ward 0, precovered
         [0, 1]]      # cell 3 - ward 1, uncovered
    ward = np.array([0, 0, 0, 1])
    demand = np.array([50.0, 50.0, 50.0, 5.0])
    pre = [False, True, True, False]                   # ward 0 starts at 66.7%

    free = exact.solve(make(M, demand=demand, pre=pre, k=1, ward_of=ward))
    assert free.selected == (0,)                       # efficiency takes the big ward
    assert free.objective == 50.0

    fair = exact.solve(make(M, demand=demand, pre=pre, k=1, ward_of=ward,
                            equity_floor=0.6))
    assert fair.status == "Optimal"
    assert fair.selected == (1,)                       # floor redirects to ward 1
    assert fair.objective == 5.0
    assert fair.objective < free.objective             # equity has a price


def test_equity_floor_is_infeasible_when_k_cannot_reach_every_ward():
    """Two disjoint wards, one station: no siting satisfies a positive floor.
    Infeasibility is a RESULT to surface, not an error to swallow."""
    M = [[0, 1], [1, 0]]
    ward = np.array([0, 1])
    s = exact.solve(make(M, k=1, ward_of=ward, equity_floor=0.9))
    assert s.status == "Infeasible"
    assert s.selected == ()


def test_maximin_finds_the_best_achievable_floor():
    M = [[0, 1], [1, 0], [1, 0]]
    ward = np.array([0, 1, 1])
    beta, sol = exact.solve_maximin(make(M, k=1, ward_of=ward))
    assert sol.status == "Optimal"
    assert beta == pytest.approx(0.0)      # k=1 cannot cover both wards
    beta2, _ = exact.solve_maximin(make(M, k=2, ward_of=ward))
    assert beta2 == pytest.approx(1.0)


def test_maximin_requires_wards():
    with pytest.raises(ValueError):
        exact.solve_maximin(make([[1]], k=1))


# --------------------------------------------------------------------------
# Structural bound on the maximin floor (added closing the k=10 unproven row).
# --------------------------------------------------------------------------

def _ward_problem(coverage_rows, ward, precovered, demand=None, k=1):
    """Small hand-built instance: rows are cells, columns candidates."""
    from scipy import sparse
    M = sparse.csr_matrix(np.array(coverage_rows, dtype=bool))
    n = M.shape[0]
    return SitingProblem(
        coverage=M, precovered=np.array(precovered, dtype=bool),
        demand=np.ones(n) if demand is None else np.asarray(demand, dtype="float64"),
        k=k, ward_of=np.asarray(ward))


def test_min_sites_is_zero_when_every_ward_already_has_coverage():
    p = _ward_problem([[1], [1]], ward=[1, 2], precovered=[True, True])
    n, d = exact.min_sites_for_positive_floor(p)
    assert n == 0
    assert d["wards_zero_coverage"] == 0


def test_min_sites_counts_wards_not_cells():
    """Three uncovered wards, one candidate reaching all three: the answer is 1.
    Counting cells instead of wards would say 3."""
    p = _ward_problem([[1], [1], [1]], ward=[1, 2, 3], precovered=[False] * 3)
    n, _ = exact.min_sites_for_positive_floor(p)
    assert n == 1


def test_min_sites_needs_one_candidate_per_disjoint_ward():
    # candidate 0 reaches ward 1 only, candidate 1 reaches ward 2 only.
    p = _ward_problem([[1, 0], [0, 1]], ward=[1, 2], precovered=[False, False])
    n, _ = exact.min_sites_for_positive_floor(p)
    assert n == 2


def test_min_sites_is_none_when_a_ward_is_unreachable_from_every_candidate():
    """No k whatsoever produces a positive floor, so there is no bound to give.
    Returning a number here would understate an impossibility."""
    p = _ward_problem([[1], [0]], ward=[1, 2], precovered=[False, False])
    n, d = exact.min_sites_for_positive_floor(p)
    assert n is None
    assert d["wards_no_candidate_reaches"] == [2]


def test_wards_with_no_demand_are_ignored():
    """A zero-population ward cannot pin the maximin objective -- solve_maximin
    skips it -- so the bound must skip it too or it overstates the requirement."""
    p = _ward_problem([[1, 0], [0, 1]], ward=[1, 2], precovered=[False, False],
                      demand=[1.0, 0.0])
    n, d = exact.min_sites_for_positive_floor(p)
    assert d["wards_with_demand"] == 1
    assert n == 1


def test_bound_is_consistent_with_the_maximin_solve():
    """The contract that makes the short-circuit valid: below the bound the
    maximin floor must actually be zero."""
    rows = [[1, 0], [0, 1], [0, 0]]
    ward = [1, 2, 3]
    p = _ward_problem(rows, ward=ward, precovered=[False] * 3, k=2)
    n, d = exact.min_sites_for_positive_floor(p)
    assert n is None                      # ward 3 is unreachable
    beta, _ = exact.solve_maximin(p, time_limit_s=30)
    assert beta == pytest.approx(0.0, abs=1e-6)
