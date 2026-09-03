"""Greedy MCLP. Build step 11.

Monotone submodular maximisation under a cardinality constraint, so greedy is
within (1 - 1/e) ~ 0.632 of optimal (Nemhauser, Wolsey & Fisher 1978). That
bound still holds for the residual problem with existing stations fixed, because
the marginal coverage function stays monotone and submodular.

The bound is a WORST CASE and is not the selling point — a GCC-scale instance
solves to proven optimality in seconds (see optimise/exact.py). Greedy exists
here to drive the interactive slider and to warm-start the exact solver.
"""
from __future__ import annotations

import time

import numpy as np

from ers.model.problem import SitingProblem, SitingSolution

ONE_MINUS_1_OVER_E = 1.0 - 1.0 / np.e


def solve(problem: SitingProblem) -> SitingSolution:
    t0 = time.perf_counter()
    cov = problem.coverage.tocsc()          # column slicing per candidate
    demand = problem.demand.astype("float64")
    covered = problem.precovered.copy()
    allowed = problem.allowed()

    baseline = float(demand[covered].sum())
    selected: list[int] = []
    gains: list[float] = []

    for _ in range(problem.k):
        # Marginal gain of every candidate: demand it covers that is not yet covered.
        uncovered = (~covered).astype("float64") * demand
        gain = np.asarray(uncovered @ cov).ravel()
        gain[~allowed] = -np.inf
        if selected:
            gain[selected] = -np.inf

        if not np.isfinite(gain).any() or gain.max() <= 0:
            break

        # DETERMINISTIC TIE-BREAK: highest gain, then lowest candidate index.
        # argmax alone resolves ties by memory order, which would make the
        # recommendation depend on array layout.
        best = int(np.lexsort((np.arange(len(gain)), -gain))[0])
        selected.append(best)
        gains.append(float(gain[best]))
        covered |= np.asarray(cov[:, best].todense()).ravel().astype(bool)

    objective = float(sum(gains))
    return SitingSolution(
        selected=tuple(selected),
        objective=objective,
        bound=objective / ONE_MINUS_1_OVER_E if objective > 0 else None,
        gap=None,
        marginal_gains=tuple(gains),
        solver="greedy",
        wall_s=round(time.perf_counter() - t0, 4),
        status="optimal_within_bound",
        baseline_covered=baseline,
        extra={"guarantee": ">= (1-1/e) * OPT", "bound_kind": "worst_case_upper_on_OPT"},
    )
