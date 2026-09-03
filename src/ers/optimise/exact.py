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

from ers.model.problem import SitingProblem, SitingSolution
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
        extra={"binaries": len(x), "cells_in_model": len(y),
               "cells_no_candidate_reaches": unreachable},
    )


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
    """Dual bound from the solver, falling back to the incumbent when proven."""
    for attr in ("bestBound", "best_bound"):
        v = getattr(prob, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return objective if pulp.LpStatus[prob.status] == "Optimal" else None


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
        extra={"worst_ward_share": zval},
    )
    return zval, sol
