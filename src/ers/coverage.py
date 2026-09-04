"""Population coverage from a routed network. Build step 09, shared from step 13.

Extracted from `scripts/baseline.py` so the flood degradation curve and the E-10
ablation measure coverage with EXACTLY the same code as the published baseline.
A degradation curve whose dry point is computed differently from the baseline is
not a curve, it is two unrelated numbers.
"""
from __future__ import annotations

import numpy as np

from ers.routing.csr import travel_times, to_seconds

# ASSM A-14: centroid-to-network access at walking pace, m/s.
ACCESS_SPEED_MS = 1.2


def response_seconds(graph, source_idx: np.ndarray, target_idx: np.ndarray,
                     target_snap_m: np.ndarray, *, overhead_s: float,
                     cutoff_ds: float | None = None) -> np.ndarray:
    """Best travel time to each target from any source, in seconds.

    `cutoff_ds=None` runs the sweep to exhaustion. That matters for flood
    scenarios: with a cutoff, a cell that is merely FAR is indistinguishable
    from a cell that is CUT OFF, and telling those two apart is the entire
    reason for modelling flooding as a graph perturbation.
    """
    d = travel_times(graph, source_idx, target_idx, cutoff_ds=cutoff_ds)
    best_ds = d.min(axis=0)
    return to_seconds(best_ds) + target_snap_m / ACCESS_SPEED_MS + overhead_s


def summarise(best_s: np.ndarray, pop: np.ndarray, *, budget_s: float,
              ladder: dict[str, float] | None = None) -> dict:
    """Population-weighted coverage statistics for one routed scenario."""
    reach = np.isfinite(best_s)
    covered = reach & (best_s <= budget_s)
    tot = float(pop.sum())

    out = {
        "travel_budget_s": float(budget_s),
        "coverage_share": round(float(pop[covered].sum() / tot), 4),
        "population_covered": round(float(pop[covered].sum())),
        "population_outside": round(float(tot - pop[covered].sum())),
        "unreachable_cells": int((~reach).sum()),
        "unreachable_population": round(float(pop[~reach].sum())),
        "unreachable_share": round(float(pop[~reach].sum() / tot), 4),
    }

    finite, wts = best_s[reach], pop[reach]
    if len(finite) == 0 or wts.sum() == 0:
        # A scenario CAN sever every cell from every station. That is a result,
        # not an error, and percentiles are undefined on an empty population.
        out.update({"mean_travel_s": None, "p50_travel_s": None,
                    "p90_travel_s": None, "max_travel_s": None})
        return out

    order = np.argsort(finite)
    cw = np.cumsum(wts[order]) / wts.sum()
    out.update({
        "mean_travel_s": round(float(np.average(finite, weights=wts)), 1),
        "p50_travel_s": round(float(finite[order][np.searchsorted(cw, 0.50)]), 1),
        "p90_travel_s": round(float(finite[order][np.searchsorted(cw, 0.90)]), 1),
        "max_travel_s": round(float(finite.max()), 1),
    })
    if ladder:
        out["threshold_ladder"] = {
            label: {"travel_budget_s": b,
                    "coverage_share": round(float(pop[reach & (best_s <= b)].sum() / tot), 4)}
            for label, b in ladder.items()
        }
    return out


def by_group(best_s: np.ndarray, pop: np.ndarray, group: np.ndarray,
             *, budget_s: float) -> dict:
    """Coverage share per group (ward, zone). Groups with no population are skipped."""
    reach = np.isfinite(best_s)
    covered = reach & (best_s <= budget_s)
    out = {}
    for g in np.unique(group):
        sel = group == g
        p = float(pop[sel].sum())
        if p <= 0:
            continue
        out[str(g)] = {
            "population": round(p),
            "coverage_share": round(float(pop[sel & covered].sum() / p), 4),
            "unreachable_share": round(float(pop[sel & ~reach].sum() / p), 4),
        }
    return out
