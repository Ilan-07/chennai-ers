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
    return to_response_s(d.min(axis=0), target_snap_m, overhead_s=overhead_s)


def to_response_s(best_ds: np.ndarray, target_snap_m: np.ndarray, *,
                  overhead_s: float) -> np.ndarray:
    """Deciseconds of driving -> a response time in seconds.

    Split out of `response_seconds` so a caller that has already computed the
    best-time field by another route -- the leave-one-out cache below, say --
    converts it with the SAME arithmetic rather than a second copy of it. Four
    scripts each re-implementing station-to-cell routing is what F-16 was.
    """
    return to_seconds(best_ds) + target_snap_m / ACCESS_SPEED_MS + overhead_s


def leave_one_out_min(fields: np.ndarray) -> np.ndarray:
    """For each source, the elementwise best time over all the OTHER sources.

    `fields` is (n_sources, n_targets) as returned by `travel_times`; the result
    has the same shape, and row i is `fields[[j != i]].min(axis=0)`.

    This is what makes a one-station-at-a-time sensitivity analysis affordable.
    `scipy.csgraph.dijkstra` runs one sweep PER SOURCE, so re-routing all 33
    stations to move one of them costs 33 times what it needs to: the other 32
    have not moved. E-11b did exactly that and took 9.1 hours. With the
    unmoved field cached, a draw costs one Dijkstra and a `np.minimum`.

    Computed from the two smallest values per target rather than by 33 separate
    reductions, so the whole table is O(n_sources * n_targets).
    """
    if fields.ndim != 2:
        raise ValueError(f"expected (n_sources, n_targets), got {fields.shape}")
    n = fields.shape[0]
    if n < 2:
        raise ValueError("leave-one-out is undefined for fewer than two sources")

    order = np.argsort(fields, axis=0, kind="stable")
    best_idx, second_idx = order[0], order[1]
    cols = np.arange(fields.shape[1])
    best, second = fields[best_idx, cols], fields[second_idx, cols]

    # Row i takes the overall best, unless station i IS the best -- then the
    # runner-up, which is what "without station i" means.
    out = np.repeat(best[None, :], n, axis=0)
    rows = np.arange(n)[:, None] == best_idx[None, :]
    out[rows] = np.broadcast_to(second, (n, len(cols)))[rows]
    return out


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


def graded_share(best_s: np.ndarray, pop: np.ndarray,
                 bands: list[dict]) -> dict:
    """Coverage credited on a utility ladder instead of a single threshold.

    Formulation E. Both service configs have declared `bands` since step 05 --
    EMS `[{t_s:300,u:1.0},{t_s:420,u:0.7},{t_s:600,u:0.3}]` -- and until the
    2026-09 repair NOTHING READ THE KEY. Every published figure was binary: a
    cell 301 seconds away counted exactly as much as one 30 minutes away, which
    is zero.

    Reported ALONGSIDE the binary share, never in place of it. Switching the
    headline definition would move every number in the repository, the console
    and the deck simultaneously, and the resulting difference could not be
    attributed to anything -- the mistake E-10 made once already by changing a
    parameter and a fitted constant together.
    """
    ladder = sorted(bands, key=lambda b: float(b["t_s"]))
    tot = float(pop.sum())
    reach = np.isfinite(best_s)

    utility = np.zeros_like(best_s, dtype="float64")
    assigned = np.zeros_like(best_s, dtype=bool)
    per_band = []
    for b in ladder:
        t, u = float(b["t_s"]), float(b["u"])
        sel = reach & ~assigned & (best_s <= t)
        utility[sel] = u
        assigned |= sel
        per_band.append({"t_s": t, "u": u,
                         "population": round(float(pop[sel].sum())),
                         "population_share": round(float(pop[sel].sum() / tot), 4)})

    return {
        "graded_share": round(float((pop * utility).sum() / tot), 4),
        "bands": per_band,
        "population_beyond_last_band": round(float(pop[~assigned].sum())),
        "definition": "sum(pop * u(band)) / sum(pop); a cell is credited at the "
                      "utility of the first band it falls inside",
    }


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
