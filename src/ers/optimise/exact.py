"""Exact MCLP via HiGHS. Build step 11.

Finding F-11: the source deck led with greedy's (1-1/e) worst-case guarantee.
That inverts the story. A GCC-scale MCLP has a few hundred to a few thousand
binaries over a covering structure with a tight LP relaxation, and solves to
PROVEN optimality in seconds. The exact solve is the answer; greedy is the warm
start and the interactive fallback. HiGHS replaces CBC, which benchmarks show is
not competitive on MIP.

The y variables are relaxed to [0, 1]: their objective coefficients are positive
and the coverage constraint is the only thing binding them, so an optimal
solution drives each y_i to its upper bound anyway. Relaxing them shrinks the
branch-and-bound tree substantially at no cost to correctness.
"""
from __future__ import annotations

import time

import numpy as np
import pulp

from ers.model.problem import (RobustSitingProblem, SitingProblem,
                               SitingSolution)
from ers.optimise import greedy


def solve(problem: SitingProblem, *, time_limit_s: float = 300.0,
          warm_start: bool = True, msg: bool = False) -> SitingSolution:
    t0 = time.perf_counter()
    cov = problem.coverage.tocsr()
    demand = problem.demand.astype("float64")
    allowed = problem.allowed()
    allowed_idx = np.flatnonzero(allowed)

    # Cells already covered by an existing station contribute a constant; drop
    # them from the program entirely rather than carrying dead variables.
    open_cells = np.flatnonzero(~problem.precovered)
    baseline = float(demand[problem.precovered].sum())

    prob = pulp.LpProblem("mclp", pulp.LpMaximize)
    x = {j: pulp.LpVariable(f"x_{j}", cat="Binary") for j in allowed_idx}
    y = {i: pulp.LpVariable(f"y_{i}", lowBound=0, upBound=1, cat="Continuous")
         for i in open_cells}

    prob += pulp.lpSum(demand[i] * y[i] for i in open_cells)

    indptr, indices = cov.indptr, cov.indices
    allowed_set = set(int(j) for j in allowed_idx)
    unreachable = 0
    for i in open_cells:
        js = [int(j) for j in indices[indptr[i]:indptr[i + 1]] if int(j) in allowed_set]
        if js:
            prob += y[i] <= pulp.lpSum(x[j] for j in js), f"cov_{i}"
        else:
            prob += y[i] == 0, f"cov_{i}"       # no candidate can reach this cell
            unreachable += 1

    prob += pulp.lpSum(x.values()) <= problem.k, "budget"

    if problem.equity_floor is not None and problem.ward_of is not None:
        _add_equity(prob, problem, x, y, demand, open_cells)

    if warm_start:
        warm = greedy.solve(problem)
        for j in allowed_idx:
            x[j].setInitialValue(1 if j in warm.selected else 0)

    solver = pulp.HiGHS(msg=msg, timeLimit=time_limit_s, warmStart=warm_start)
    prob.solve(solver)

    status = pulp.LpStatus[prob.status]
    selected = tuple(sorted(int(j) for j in allowed_idx
                            if x[j].value() is not None and x[j].value() > 0.5))
    objective = float(pulp.value(prob.objective) or 0.0)

    bound = _best_bound(prob, objective)
    gap = None if bound in (None, 0) else max(0.0, (bound - objective) / abs(bound))

    return SitingSolution(
        selected=selected,
        objective=objective,
        bound=bound,
        gap=None if gap is None else round(gap, 6),
        marginal_gains=(),
        solver="highs",
        wall_s=round(time.perf_counter() - t0, 3),
        status=status,
        baseline_covered=baseline,
        solution_status=_solution_status(prob),
        proven_optimal=_proven_optimal(prob),
        extra={"binaries": len(x), "cells_in_model": len(y),
               "cells_no_candidate_reaches": unreachable,
               "time_limit_s": time_limit_s},
    )


def _solution_status(prob) -> str:
    """PuLP's SOLUTION status, which is the one that tells the truth.

    `LpStatus[prob.status]` reports "Optimal" for a solve that merely ran out of
    time: pulp maps HiGHS `kTimeLimit` to `LpStatusOptimal`. The distinction
    survives only in `sol_status`, where a timed-out solve is
    `LpSolutionIntegerFeasible` -- a feasible incumbent whose optimality was
    never proven. Reporting the former as "Optimal" overstates every result.
    """
    code = getattr(prob, "sol_status", None)
    if code is None:
        return "Unknown"
    return pulp.LpSolution.get(code, f"code={code}")


def _proven_optimal(prob) -> bool:
    return getattr(prob, "sol_status", None) == pulp.constants.LpSolutionOptimal


def _add_equity(prob, problem: SitingProblem, x, y, demand, open_cells) -> None:
    """Per-ward coverage floor (constraint C4).

    The floor is expressed on TOTAL ward demand, and cells already covered by an
    existing station count toward it — otherwise the constraint would demand
    that new stations alone cover beta of every ward, which is a different and
    much harder problem than the one being posed.
    """
    beta = float(problem.equity_floor)
    wards = problem.ward_of
    open_set = set(int(i) for i in open_cells)
    for w in np.unique(wards):
        idx = np.flatnonzero(wards == w)
        total = float(demand[idx].sum())
        if total <= 0:
            continue
        already = float(demand[[i for i in idx if i not in open_set]].sum())
        terms = [demand[i] * y[i] for i in idx if i in open_set]
        if terms:
            prob += pulp.lpSum(terms) + already >= beta * total, f"equity_w{int(w)}"


def _best_bound(prob, objective: float) -> float | None:
    """Dual bound from the solver, falling back to the incumbent when proven.

    The fallback must test PROVEN optimality, not `LpStatus`. A time-limited
    solve reports `LpStatus == "Optimal"`, so keying off it returned
    `bound = objective` for a solve that never closed -- and therefore a
    published `proven_gap` of exactly 0.0 on an unproven result.
    """
    for attr in ("bestBound", "best_bound"):
        v = getattr(prob, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return objective if _proven_optimal(prob) else None


def solve_maximin(problem: SitingProblem, *, time_limit_s: float = 300.0,
                  msg: bool = False) -> tuple[float, SitingSolution]:
    """Maximise the WORST ward's coverage share for a fixed k.

    This is the right-hand end of the efficiency-equity frontier, and it is what
    makes the frontier sweep well-posed: a fixed beta ladder is meaningless
    without knowing the largest beta that k stations can actually achieve.
    Sweeping past it just produces a run of infeasible solves.
    """
    t0 = time.perf_counter()
    cov = problem.coverage.tocsr()
    demand = problem.demand.astype("float64")
    wards = problem.ward_of
    if wards is None:
        raise ValueError("maximin requires ward_of")

    allowed_idx = np.flatnonzero(problem.allowed())
    open_cells = np.flatnonzero(~problem.precovered)
    open_set = set(int(i) for i in open_cells)

    prob = pulp.LpProblem("mclp_maximin", pulp.LpMaximize)
    x = {j: pulp.LpVariable(f"x_{j}", cat="Binary") for j in allowed_idx}
    y = {i: pulp.LpVariable(f"y_{i}", lowBound=0, upBound=1) for i in open_cells}
    z = pulp.LpVariable("z", lowBound=0, upBound=1)
    prob += z

    indptr, indices = cov.indptr, cov.indices
    allowed_set = set(int(j) for j in allowed_idx)
    for i in open_cells:
        js = [int(j) for j in indices[indptr[i]:indptr[i + 1]] if int(j) in allowed_set]
        prob += (y[i] <= pulp.lpSum(x[j] for j in js)) if js else (y[i] == 0), f"cov_{i}"

    prob += pulp.lpSum(x.values()) <= problem.k, "budget"

    for w in np.unique(wards):
        idx = np.flatnonzero(wards == w)
        total = float(demand[idx].sum())
        if total <= 0:
            continue
        already = float(demand[[i for i in idx if i not in open_set]].sum())
        terms = [demand[i] * y[i] for i in idx if i in open_set]
        prob += (pulp.lpSum(terms) + already) / total >= z, f"minshare_w{int(w)}"

    prob.solve(pulp.HiGHS(msg=msg, timeLimit=time_limit_s))
    zval = float(z.value() or 0.0)
    selected = tuple(sorted(int(j) for j in allowed_idx
                            if x[j].value() is not None and x[j].value() > 0.5))
    sol = SitingSolution(
        selected=selected, objective=zval, bound=None, gap=None, marginal_gains=(),
        solver="highs-maximin", wall_s=round(time.perf_counter() - t0, 3),
        status=pulp.LpStatus[prob.status],
        baseline_covered=float(demand[problem.precovered].sum()),
        solution_status=_solution_status(prob),
        proven_optimal=_proven_optimal(prob),
        extra={"worst_ward_share": zval, "time_limit_s": time_limit_s},
    )
    return zval, sol


def min_sites_for_positive_floor(problem: SitingProblem, *,
                                 time_limit_s: float = 300.0,
                                 msg: bool = False) -> tuple[int | None, dict]:
    """Fewest candidates that give EVERY demand-bearing ward some coverage.

    A location set covering problem, and a hard lower bound on the maximin
    program: the worst-ward share is positive only if no ward is left at zero,
    so a ward with neither existing coverage nor a selected candidate pins the
    maximin objective to exactly 0. If this minimum exceeds k, the maximin floor
    at k is provably 0 and the MIP need not be solved at all.

    That matters practically, not just theoretically. The k=10 EMS maximin ran
    600 s without proving its own answer, because proving z=0 means ruling out
    every way of covering 43 zero-coverage wards with 10 sites. This LSCP settles
    the same question in seconds, and returns 12 -- so k=5 and k=10 are decided
    immediately and k=12 is the first k at which a positive floor is even
    possible.

    Returns (minimum, detail). `minimum` is None when some ward is unreachable
    from every candidate, because then no k whatsoever yields a positive floor.
    """
    cov = problem.coverage.tocsc()
    demand = problem.demand.astype("float64")
    wards = problem.ward_of
    if wards is None:
        raise ValueError("min_sites_for_positive_floor requires ward_of")
    allowed_idx = np.flatnonzero(problem.allowed())

    with_demand = [w for w in np.unique(wards) if demand[wards == w].sum() > 0]
    # Wards that already have coverage need nothing selected for them.
    todo = [w for w in with_demand
            if demand[(wards == w) & problem.precovered].sum() <= 0]

    touches: dict[int, set] = {}
    for j in allowed_idx:
        cells = cov[:, j].indices
        if len(cells):
            touches[int(j)] = set(int(w) for w in np.unique(wards[cells]))

    reachable = set().union(*touches.values()) if touches else set()
    orphan = sorted(w for w in todo if w not in reachable)
    detail = {"wards_with_demand": len(with_demand),
              "wards_zero_coverage": len(todo),
              "wards_no_candidate_reaches": orphan}
    if orphan:
        # No number of stations fixes this; the candidate set is the constraint.
        detail["reason"] = ("some zero-coverage ward is unreachable from every "
                            "candidate, so no k gives a positive worst-ward floor")
        return None, detail
    if not todo:
        detail["reason"] = "every ward already has coverage from existing stations"
        return 0, detail

    prob = pulp.LpProblem("lscp_positive_floor", pulp.LpMinimize)
    x = {j: pulp.LpVariable(f"x_{j}", cat="Binary") for j in touches}
    prob += pulp.lpSum(x.values())
    for w in todo:
        prob += pulp.lpSum(x[j] for j, t in touches.items() if w in t) >= 1, f"ward_{int(w)}"
    prob.solve(pulp.HiGHS(msg=msg, timeLimit=time_limit_s))

    detail["status"] = pulp.LpStatus[prob.status]
    detail["solution_status"] = _solution_status(prob)
    detail["proven_optimal"] = _proven_optimal(prob)
    if not _proven_optimal(prob):
        # An unproven LSCP gives no valid bound in either direction. Say so
        # rather than shipping an incumbent as if it were a minimum.
        detail["reason"] = "LSCP did not prove optimality; no bound available"
        return None, detail
    return int(round(pulp.value(prob.objective))), detail


def solve_robust(problem: RobustSitingProblem, *, objective: str = "expected",
                 time_limit_s: float = 600.0, msg: bool = False) -> SitingSolution:
    """Site once against several networks at once. Build step 15.

    Two objectives, because they answer different questions and a plan needs both:

      expected  maximise the A-10 weighted mean coverage across the design-basis
                scenarios. This is the right objective if the weights really are
                the planner's belief about how often each network state holds.

      maximin   maximise the coverage share of the WORST design-basis scenario.
                This is the right objective if the weights are not credible --
                and A-10 is explicitly an engineering assumption, not a measured
                frequency, so this is not a hypothetical concern.

    The x variables are shared across scenarios; only the y variables and the
    coverage constraints are per scenario. That is the whole point: one site set
    must work in every network, so the scenarios are coupled through x alone.
    """
    if objective not in ("expected", "maximin"):
        raise ValueError(f"objective must be 'expected' or 'maximin', got {objective!r}")

    t0 = time.perf_counter()
    demand = problem.demand.astype("float64")
    total = float(demand.sum())
    allowed_idx = np.flatnonzero(problem.allowed())
    design = problem.design_basis
    if not design:
        raise ValueError("no design-basis scenario: every scenario is report-only "
                         "or carries zero weight, so there is nothing to optimise")
    weights = problem.normalised_weights()

    prob = pulp.LpProblem(f"mclp_robust_{objective}", pulp.LpMaximize)
    x = {j: pulp.LpVariable(f"x_{j}", cat="Binary") for j in allowed_idx}
    allowed_set = set(int(j) for j in allowed_idx)

    # Per-scenario coverage expression, in SHARE of total demand so the two
    # objectives are on the same scale and a maximin bound is interpretable.
    share_expr, baselines = {}, {}
    for sc in design:
        cov = sc.coverage.tocsr()
        open_cells = np.flatnonzero(~sc.precovered)
        base = float(demand[sc.precovered].sum())
        baselines[sc.scenario] = base
        y = {i: pulp.LpVariable(f"y_{sc.scenario}_{i}", lowBound=0, upBound=1)
             for i in open_cells}
        indptr, indices = cov.indptr, cov.indices
        for i in open_cells:
            js = [int(j) for j in indices[indptr[i]:indptr[i + 1]] if int(j) in allowed_set]
            prob += (y[i] <= pulp.lpSum(x[j] for j in js)) if js else (y[i] == 0), \
                f"cov_{sc.scenario}_{i}"
        share_expr[sc.scenario] = (
            pulp.lpSum(demand[i] * y[i] for i in open_cells) + base) / total

    if objective == "expected":
        prob += pulp.lpSum(weights[s] * e for s, e in share_expr.items())
    else:
        z = pulp.LpVariable("z", lowBound=0, upBound=1)
        prob += z
        for s, e in share_expr.items():
            prob += z <= e, f"worst_{s}"

    prob += pulp.lpSum(x.values()) <= problem.k, "budget"
    prob.solve(pulp.HiGHS(msg=msg, timeLimit=time_limit_s))

    selected = tuple(sorted(int(j) for j in allowed_idx
                            if x[j].value() is not None and x[j].value() > 0.5))
    obj = float(pulp.value(prob.objective) or 0.0)
    return SitingSolution(
        selected=selected,
        objective=obj,
        bound=_best_bound(prob, obj),
        gap=None,
        marginal_gains=(),
        solver=f"highs-robust-{objective}",
        wall_s=round(time.perf_counter() - t0, 3),
        status=pulp.LpStatus[prob.status],
        baseline_covered=0.0,           # baselines differ per scenario; see `extra`
        solution_status=_solution_status(prob),
        proven_optimal=_proven_optimal(prob),
        extra={"objective_kind": objective,
               "objective_is_share": True,
               "weights": weights,
               "design_basis": [sc.scenario for sc in design],
               "reported_only": [sc.scenario for sc in problem.scenarios
                                 if sc not in design],
               "baseline_share_by_scenario": {s: round(b / total, 4)
                                              for s, b in baselines.items()},
               "binaries": len(x), "time_limit_s": time_limit_s},
    )
