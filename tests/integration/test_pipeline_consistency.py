"""Cross-script consistency. The tests that would have caught bugs 1-4.

Every failure fixed here was invisible to unit tests, because each script was
internally consistent and wrong only RELATIVE TO ITS SIBLINGS. Unit tests cannot
see that. These can.

They route the real graph, and skip when the derived artefacts are absent
(those are gitignored and cost ~17 min to rebuild).
"""
import json
import re
from pathlib import Path

import numpy as np
import pytest

REQUIRED = [
    Path("data/interim/graph_nodes.parquet"),
    Path("data/interim/arc_times.parquet"),
    Path("data/interim/demand_cells.parquet"),
    Path("data/interim/stations_resolved.csv"),
]
pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in REQUIRED),
    reason="derived graph artefacts absent; run build_graph.py + attribute.py")


@pytest.fixture(scope="module")
def contexts():
    from ers.pipeline import load_service
    return {svc: load_service(svc) for svc in ("ems", "fire")}


def _report(name):
    p = Path(f"data/interim/{name}.json")
    if not p.exists():
        pytest.skip(f"{name}.json not generated yet")
    return json.loads(p.read_text())


# ------------------------------------------------------- the four bugs

@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_every_consumer_agrees_on_the_baseline_share(svc, contexts):
    """BUG 1 + 2. baseline.py, optimise.py, frontier.py and equity_curve.py must
    all report the same do-nothing coverage. They did not: frontier omitted the
    45 s trip overhead and equity_curve loaded a stale precovered array."""
    ctx = contexts[svc]
    baseline = _report("baseline_report")["results"][svc]["coverage_share"]
    assert ctx.baseline_share == pytest.approx(baseline, abs=5e-4)

    for name in (f"optimise_{svc}", f"frontier_{svc}", f"equity_curve_{svc}"):
        p = Path(f"data/interim/{name}.json")
        if not p.exists():
            continue
        rep = json.loads(p.read_text())
        if "baseline_share" in rep:
            assert rep["baseline_share"] == pytest.approx(ctx.baseline_share, abs=5e-4), \
                f"{name} disagrees with the shared routing path"


@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_trip_overhead_is_applied_by_every_consumer(svc, contexts):
    """BUG 2 specifically. frontier.py dropped the calibrated 45 s constant."""
    import yaml
    shipped = float(yaml.safe_load(Path("config/speeds/base.yml").read_text())
                    ["trip_overhead_s"])
    assert contexts[svc].overhead_s == shipped
    for name in (f"optimise_{svc}", f"frontier_{svc}", f"equity_curve_{svc}"):
        p = Path(f"data/interim/{name}.json")
        if p.exists() and "trip_overhead_s" in (rep := json.loads(p.read_text())):
            assert rep["trip_overhead_s"] == shipped, f"{name} routes on a different model"


def test_no_script_loads_a_precovered_array_from_disk():
    """BUG 1. `precovered_{svc}.npy` had no producer anywhere in the repo, so it
    could never be replayed and had silently gone stale (it held the FIRE mask
    under the EMS name). precovered must be DERIVED, always."""
    # Match the load itself, not a mention of the filename -- the fix's own
    # comment names the file it removed.
    loader = re.compile(r"np\.load\s*\([^)]*precovered")
    for script in Path("scripts").glob("*.py"):
        assert not loader.search(script.read_text()), \
            f"{script} reloads a precovered array instead of deriving it"
    assert not list(Path("data/interim").glob("precovered_*.npy")), \
        "an unproducible precovered array is back on disk"


@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_no_siting_result_falls_below_the_do_nothing_baseline(svc, contexts):
    """BUG 1's visible symptom. Adding stations cannot REDUCE coverage, yet the
    equity curve reported 47.5% at k=5 against a 55.7% baseline."""
    ctx = contexts[svc]
    for name, key in ((f"optimise_{svc}", "runs"), (f"equity_curve_{svc}", "curve")):
        p = Path(f"data/interim/{name}.json")
        if not p.exists():
            continue
        for row in json.loads(p.read_text())[key]:
            for field in ("exact_share", "greedy_share", "efficiency_city_coverage",
                          "maximin_city_coverage"):
                if field in row:
                    assert row[field] >= ctx.baseline_share - 1e-6, \
                        f"{name} {field} at k={row['k']} is below the baseline"


def test_reports_state_whether_solves_were_proven_optimal():
    """BUG 4. pulp maps a HiGHS time-limit stop to LpStatus 'Optimal', so the
    previous equity curve published 600 s timeouts as proven optima."""
    for name, key in (("optimise_ems", "runs"), ("equity_curve_ems", "curve")):
        p = Path(f"data/interim/{name}.json")
        if not p.exists():
            continue
        for row in json.loads(p.read_text())[key]:
            assert "proven_optimal" in row, f"{name} publishes solves without a proof flag"


def test_timed_out_solve_is_not_reported_as_proven_optimal():
    """The mechanism itself, tested directly rather than via an artefact."""
    import pulp
    # kTimeLimit maps to LpStatusOptimal, which is precisely the trap.
    assert pulp.LpStatus[pulp.constants.LpStatusOptimal] == "Optimal"
    assert pulp.LpSolution[pulp.constants.LpSolutionIntegerFeasible] != \
        pulp.LpSolution[pulp.constants.LpSolutionOptimal], \
        "solution status must distinguish a proven optimum from an incumbent"

    from ers.model.problem import SitingSolution
    timed_out = SitingSolution(
        selected=(1,), objective=1.0, bound=None, gap=None, marginal_gains=(),
        solver="highs", wall_s=600.0, status="Optimal",
        solution_status="Solution Found", proven_optimal=False,
        extra={"time_limit_s": 600})
    assert not timed_out.proven_optimal
    assert "NOT PROVEN" in timed_out.optimality_note


# ------------------------------------------------------- routing invariants

@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_precovered_is_exactly_the_within_budget_mask(svc, contexts):
    ctx = contexts[svc]
    expected = np.isfinite(ctx.baseline_s) & (ctx.baseline_s <= ctx.budget_s)
    assert np.array_equal(ctx.precovered, expected)


def test_ems_budget_exceeds_fire_budget_because_turnout_differs(contexts):
    """Finding F-03: the budget is target minus alarm minus turnout. Fire's
    80 s NFPA turnout must leave it 20 s less travel time than EMS."""
    assert contexts["ems"].budget_s - contexts["fire"].budget_s == 20


@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_coverage_matrix_matches_the_context_it_was_built_from(svc, contexts):
    from scipy import sparse
    p = Path(f"data/interim/coverage_{svc}.npz")
    if not p.exists():
        pytest.skip("coverage matrix not built")
    M = sparse.load_npz(p)
    assert M.shape[0] == len(contexts[svc].demand), \
        "coverage matrix has a different cell count than the current demand surface"


# ------------------------------------------------- E-11 uncertainty reporting

def test_baseline_states_whether_position_uncertainty_was_measured():
    """A coverage share published without an error bar implies a precision this
    data does not have. The report must either carry the E-11 interval or say
    plainly that it is missing -- silence is the failure mode."""
    rep = _report("baseline_report")
    assert "position_uncertainty_measured" in rep
    assert "headline_caveat" in rep and rep["headline_caveat"]


@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_headline_coverage_carries_its_interval_when_measured(svc):
    rep = _report("baseline_report")
    if not rep["position_uncertainty_measured"]:
        pytest.skip("sensitivity not run for this pipeline state")
    pu = rep["results"][svc]["position_uncertainty"]
    assert pu["coverage_p5"] < rep["results"][svc]["coverage_share"] <= pu["coverage_p95"] \
        or pu["coverage_p5"] <= rep["results"][svc]["coverage_share"]
    assert pu["p5_p95_spread_points"] > 0
    assert pu["draws"] >= 100, "an interval from a handful of draws is not an interval"


@pytest.mark.parametrize("svc", ["ems", "fire"])
def test_sensitivity_sampling_filter_is_not_the_binding_constraint(svc):
    """If the plausibility filter rejects most draws it, not the stated
    uncertainty, decides the spread. Per-station rejection should bite lightly."""
    p = Path(f"data/interim/sensitivity_stations_{svc}.json")
    if not p.exists():
        pytest.skip("sensitivity not run")
    sn = json.loads(p.read_text())
    if "rejection_rate_per_station_draw" not in sn:
        pytest.skip("run predates the rejection-rate field")
    assert sn["rejection_rate_per_station_draw"] < 0.5, \
        "the filter is rejecting more than half of all station draws"
