"""Scenario-robust siting. Build step 15."""
import numpy as np
import pytest
from scipy import sparse

from ers.model.problem import RobustSitingProblem, ScenarioCoverage
from ers.optimise import exact


def _cov(rows):
    return sparse.csr_matrix(np.array(rows, dtype=bool))


# A hand-built instance where the two objectives provably disagree.
#   candidate 0: excellent in A (3 of 4 cells), useless in B
#   candidate 1: poor in A (1 cell), decent in B (2 cells)
#   candidate 2: poor in A, useless in B  -- dominated, never chosen
# With weights A=0.9 / B=0.1 and k=1:
#   expected  cand0 0.675 > cand1 0.275 > cand2 0.225
#   maximin   cand1 0.25  > cand0 0.0   = cand2 0.0
A = _cov([[1, 0, 0], [1, 0, 0], [1, 0, 0], [0, 1, 1]])
B = _cov([[0, 1, 0], [0, 0, 0], [0, 0, 0], [0, 1, 0]])
NONE = np.zeros(4, dtype=bool)


def _problem(k=1, extra=()):
    return RobustSitingProblem(
        scenarios=(ScenarioCoverage("A", 0.9, A, NONE),
                   ScenarioCoverage("B", 0.1, B, NONE)) + tuple(extra),
        demand=np.ones(4), k=k)


# ------------------------------------------------------------ structure

def test_scenarios_must_describe_the_same_cells_and_candidates():
    """A coverage matrix with a different shape is a different problem. Letting
    it through would silently misalign candidate indices between scenarios."""
    with pytest.raises(ValueError, match="SAME"):
        RobustSitingProblem(
            scenarios=(ScenarioCoverage("A", 1.0, A, NONE),
                       ScenarioCoverage("B", 1.0, _cov([[1, 0], [0, 1],
                                                        [0, 0], [0, 0]]), NONE)),
            demand=np.ones(4), k=1)


def test_duplicate_scenario_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        RobustSitingProblem(
            scenarios=(ScenarioCoverage("A", 0.5, A, NONE),
                       ScenarioCoverage("A", 0.5, B, NONE)),
            demand=np.ones(4), k=1)


def test_report_only_scenarios_are_excluded_from_the_design_basis():
    """Finding F-09: an extreme historical event is a stress test, not a design
    basis. The exclusion is structural, not something a caller must remember."""
    p = _problem(extra=(ScenarioCoverage("hist", 0.0, B, NONE, report_only=True),))
    assert [s.scenario for s in p.design_basis] == ["A", "B"]
    assert "hist" not in p.normalised_weights()


def test_zero_weight_scenarios_are_excluded_even_without_the_flag():
    p = _problem(extra=(ScenarioCoverage("unweighted", 0.0, B, NONE),))
    assert "unweighted" not in p.normalised_weights()


def test_weights_are_renormalised_over_the_scenarios_actually_run():
    """Running a subset must still give a weighted MEAN, not a number scaled
    down by the weight of whatever was left out."""
    p = _problem()
    w = p.normalised_weights()
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["A"] == pytest.approx(0.9)


def test_evaluate_scores_a_site_set_under_every_scenario_including_reported():
    p = _problem(extra=(ScenarioCoverage("hist", 0.0, B, NONE, report_only=True),))
    got = p.evaluate([0])
    assert got == {"A": 0.75, "B": 0.0, "hist": 0.0}


def test_evaluate_counts_precovered_demand():
    pre = np.array([True, False, False, False])
    p = RobustSitingProblem(scenarios=(ScenarioCoverage("A", 1.0, A, pre),),
                            demand=np.ones(4), k=1)
    assert p.evaluate([1])["A"] == 0.5      # cell 0 precovered + cell 3 by cand 1


def test_single_extracts_an_ordinary_one_scenario_problem():
    p = _problem()
    s = p.single("B")
    assert s.coverage.shape == B.shape and s.k == p.k


# ------------------------------------------------------------- objectives

def test_expected_objective_follows_the_weights():
    sol = exact.solve_robust(_problem(), objective="expected", time_limit_s=60)
    assert sol.proven_optimal
    assert sol.selected == (0,), "0.9 weight on A must dominate the choice"
    assert sol.objective == pytest.approx(0.675, abs=1e-6)


def test_maximin_objective_protects_the_worst_scenario():
    """The same instance, the opposite answer. Candidate 0 is the best expected
    choice and the worst robust one, because it contributes nothing in B."""
    sol = exact.solve_robust(_problem(), objective="maximin", time_limit_s=60)
    assert sol.proven_optimal
    assert sol.selected == (1,)
    assert sol.objective == pytest.approx(0.25, abs=1e-6)


def test_maximin_never_scores_worse_than_expected_on_the_worst_scenario():
    """The defining property. If this fails the formulation is wrong."""
    p = _problem()
    w = p.normalised_weights()
    exp = exact.solve_robust(p, objective="expected", time_limit_s=60)
    mm = exact.solve_robust(p, objective="maximin", time_limit_s=60)
    worst = lambda sel: min(p.evaluate(sel)[s] for s in w)
    assert worst(mm.selected) >= worst(exp.selected)


def test_expected_never_scores_worse_than_maximin_on_the_weighted_mean():
    p = _problem()
    w = p.normalised_weights()
    exp = exact.solve_robust(p, objective="expected", time_limit_s=60)
    mm = exact.solve_robust(p, objective="maximin", time_limit_s=60)
    mean = lambda sel: sum(w[s] * v for s, v in p.evaluate(sel).items() if s in w)
    assert mean(exp.selected) >= mean(mm.selected) - 1e-9


def test_a_single_scenario_reduces_to_the_ordinary_mclp():
    """Robustness over one network must be the plain problem, or the two code
    paths have diverged."""
    p = RobustSitingProblem(scenarios=(ScenarioCoverage("A", 1.0, A, NONE),),
                            demand=np.ones(4), k=1)
    for kind in ("expected", "maximin"):
        rob = exact.solve_robust(p, objective=kind, time_limit_s=60)
        plain = exact.solve(p.single("A"), time_limit_s=60)
        assert rob.selected == plain.selected
        assert rob.objective == pytest.approx(plain.total_covered / 4.0, abs=1e-6)


def test_solving_with_no_design_basis_is_an_error_not_an_empty_answer():
    p = RobustSitingProblem(
        scenarios=(ScenarioCoverage("hist", 0.0, A, NONE, report_only=True),),
        demand=np.ones(4), k=1)
    with pytest.raises(ValueError, match="report-only"):
        exact.solve_robust(p, objective="expected")


def test_unknown_objective_is_rejected():
    with pytest.raises(ValueError, match="objective"):
        exact.solve_robust(_problem(), objective="minimax-regret")


def test_budget_is_respected():
    for k in (0, 1, 2):
        sol = exact.solve_robust(_problem(k=k), objective="expected", time_limit_s=60)
        assert len(sol.selected) <= k
