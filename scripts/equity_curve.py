"""Maximin ward coverage vs k. Build step 14.

The efficiency-equity frontier is degenerate at small k: with 5 new stations the
best achievable worst-ward coverage is 0%, because 200 wards cannot all be
reached from 5 sites. So the prior question is not "what does equity cost in
coverage" but "how many stations does equity cost at all".
"""
import json, pathlib, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers.model.problem import SitingProblem
from ers.publish import publication_basis
from ers.optimise import exact
from ers.pipeline import load_service
from ers.provenance import config_bundle, stamp

# Usage: equity_curve.py [service] [k,k,...] [maximin_time_limit_s]
#
# Running a SUBSET of k merges into the existing curve rather than replacing it,
# so a single unproven row can be re-solved at a longer limit without discarding
# the rows that were already proven. Each row records the limit it was solved
# under, because "not proven" is only meaningful next to how long we waited.
SVC = sys.argv[1] if len(sys.argv) > 1 else "ems"
KS = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else "5,10,20,30,45,60".split(","))]
MAXIMIN_LIMIT_S = float(sys.argv[3]) if len(sys.argv) > 3 else 600.0
EFF_LIMIT_S = 300.0

M = sparse.load_npz(f"data/interim/coverage_{SVC}.npz")
cand = gpd.read_parquet("data/interim/candidates.parquet")
base = json.load(open(f"data/interim/optimise_{SVC}.json"))

# BUG FIX: this script used to load `data/interim/precovered_{SVC}.npy`, a file
# NO SCRIPT IN THIS REPO PRODUCED. It held 906 cells / 36.3% of population for
# EMS -- a stale copy of the FIRE mask (911 cells / 36.75%) -- against the 55.7%
# that baseline.py and optimise.py both compute. That put the k=5 "efficiency"
# coverage at 47.5%, BELOW the 55.7% do-nothing baseline, which is arithmetically
# impossible for a maximisation that counts precovered demand. Every figure this
# script emitted was wrong.
#
# precovered is now DERIVED from the shared routing path and cross-checked
# against optimise.py's recorded share. An array on disk with no producer cannot
# be replayed, and the project rule is that unreplayable numbers do not ship.
ctx = load_service(SVC)
ctx.check_baseline_share(base["baseline_share"])
precov, demand, ward, tot = ctx.precovered, ctx.demand, ctx.ward, ctx.total_demand
feas = cand["land_feasible"].to_numpy().astype(bool)
print(f"[{SVC}] baseline {ctx.baseline_share:.2%} ({precov.sum():,} of {len(precov):,} cells) "
      f"| budget {ctx.budget_s}s | overhead {ctx.overhead_s}s", flush=True)

# STRUCTURAL BOUND, computed once. The worst-ward share is positive only if no
# ward is left at zero, so the fewest candidates that touch every zero-coverage
# ward is a hard lower bound on any k with a positive floor. Below it the maximin
# answer is 0 by construction and the MIP is not worth solving -- k=10 previously
# burned 600 s failing to prove exactly this, because proving z=0 means ruling
# out every way of covering 43 wards with 10 sites. The LSCP settles it in
# milliseconds and PROVES it.
_probe = SitingProblem(coverage=M, precovered=precov, demand=demand, k=1,
                       ward_of=ward, land_feasible=feas)
K_MIN_POSITIVE, LSCP = exact.min_sites_for_positive_floor(_probe)
print(f"  structural bound: {LSCP['wards_zero_coverage']} of {LSCP['wards_with_demand']} "
      f"wards have no coverage today; the fewest candidates that reach all of them "
      f"is {K_MIN_POSITIVE}.\n  Any k below that has a worst-ward floor of exactly 0, "
      f"provably.", flush=True)

def _covered_by(sites) -> np.ndarray:
    covered = precov.copy()
    for j in sites:
        covered |= (M[:, int(j)].toarray().ravel() > 0)
    return covered


def _worst_ward_of(sites) -> float:
    """The worst ward's coverage share under an explicit siting.

    The solver's `z` is NOT this number. HiGHS satisfies the maximin constraints
    to its primal feasibility tolerance, so the z it reports sits about 1e-6
    ABOVE what its own integer solution actually achieves -- measured at exactly
    1.000e-06 for fire k=20. Re-imposing z as a hard floor is then infeasible
    against the very siting that produced it, and an infeasible second stage used
    to be published as a coverage figure. Score the siting instead of trusting
    the objective.
    """
    covered = _covered_by(sites)
    return min(float(demand[(ward == w) & covered].sum() / demand[ward == w].sum())
               for w in np.unique(ward) if demand[ward == w].sum() > 0)


def _share_of(sites) -> float:
    """City coverage share for an explicit site set.

    Needed because a maximin solve reports the worst-ward floor as its objective,
    not city coverage, so when the lexicographic stage cannot be used its siting
    still has to be scored somehow.
    """
    return float(demand[_covered_by(sites)].sum() / tot)


rows = []
for k in KS:
    p = SitingProblem(coverage=M, precovered=precov, demand=demand, k=k,
                      ward_of=ward, land_feasible=feas)
    t0 = time.time()
    if K_MIN_POSITIVE is not None and k < K_MIN_POSITIVE:
        beta, mm = 0.0, None                      # proven by the bound, not searched
    else:
        beta, mm = exact.solve_maximin(p, time_limit_s=MAXIMIN_LIMIT_S)
    eff = exact.solve(p, time_limit_s=EFF_LIMIT_S)
    eff_share = (eff.baseline_covered + eff.objective) / tot

    # LEXICOGRAPHIC second stage. Maximin is degenerate whenever several sitings
    # achieve the same worst-ward share -- and totally degenerate when that share
    # is 0, since then every siting ties and the solver returns an arbitrary one.
    # Re-solve for maximum coverage SUBJECT TO the achieved floor, so the
    # "equity" column is the best equitable solution rather than a random one.
    # Floors below 1e-4 are solver noise, not policy. Treat them as zero.
    lex, lex_failed = None, None
    # Re-impose the floor the maximin siting ACHIEVES, not the one the solver
    # reports. See _worst_ward_of: the two differ by the solver's feasibility
    # tolerance, and the difference is the whole bug.
    beta_achieved = _worst_ward_of(mm.selected) if mm is not None else beta
    if beta_achieved > 1e-4:
        p_lex = SitingProblem(coverage=M, precovered=precov, demand=demand, k=k,
                              ward_of=ward, land_feasible=feas,
                              equity_floor=beta_achieved)
        lex = exact.solve(p_lex, time_limit_s=EFF_LIMIT_S)

        # An infeasible or empty solve returns objective 0.0 and no sites, and
        # `(baseline_covered + 0) / tot` is then EXACTLY the do-nothing baseline.
        # That is what k=20 fire published: a 22.92-point "equity cost" measured
        # against a solution the solver never found. A failed second stage is not
        # a result -- fall back to the maximin siting itself, which is feasible by
        # construction, and say that is what happened.
        if not lex.selected or lex.status not in ("Optimal",):
            lex_failed = lex.status
            mm_sites = tuple(mm.selected) if mm is not None else eff.selected
            mm_share = _share_of(mm_sites)
        else:
            mm_share = float((lex.baseline_covered + lex.objective) / tot)
            mm_sites = lex.selected
    else:
        # Floor is 0: the equity constraint binds nothing, so the equitable
        # solution IS the efficient one. Reporting anything else is meaningless.
        mm_share = float(eff_share)
        mm_sites = eff.selected

    # Every published figure carries whether its solve was PROVEN, because pulp
    # reports a HiGHS time-limit stop as "Optimal" and the previous run recorded
    # 600 s solves that way. An unproven floor is a lower bound, not a maximum.
    maximin_proven = mm.proven_optimal if mm is not None else True
    maximin_note = (mm.optimality_note if mm is not None else
                    f"proven optimal (structural: k={k} < {K_MIN_POSITIVE} candidates "
                    f"needed to give every ward any coverage, so the floor is 0)")
    all_proven = maximin_proven and eff.proven_optimal and (
        lex is None or lex.proven_optimal)
    rows.append({"k": k, "maximin_worst_ward": round(beta_achieved, 4),
                 "maximin_worst_ward_solver_z": round(beta, 6),
                 "solver_z_overstates_by": round(beta - beta_achieved, 9),
                 "maximin_degenerate": bool(beta_achieved <= 1e-4),
                 "sites": list(mm_sites),
                 "maximin_city_coverage": round(mm_share, 4),
                 "efficiency_city_coverage": round(float(eff_share), 4),
                 "equity_cost_points": round(100 * (eff_share - mm_share), 2),
                 "solve_s": round(time.time() - t0, 1),
                 "status": mm.status if mm is not None else "Optimal",
                 "maximin_time_limit_s": None if mm is None else MAXIMIN_LIMIT_S,
                 "maximin_settled_structurally": mm is None,
                 "proven_optimal": bool(all_proven),
                 "maximin_optimality": maximin_note,
                 "efficiency_optimality": eff.optimality_note,
                 "lexicographic_optimality": None if lex is None else lex.optimality_note,
                 "lexicographic_failed": lex_failed,
                 "equity_coverage_from": ("maximin siting (lexicographic stage "
                                          f"{lex_failed})" if lex_failed else
                                          "lexicographic re-solve" if lex is not None
                                          else "efficiency siting (floor is 0)")})
    r = rows[-1]
    print(f"  k={k:3d}  worst-ward floor {beta_achieved:6.2%}  |  city coverage: "
          f"efficiency {eff_share:6.2%}  equity {mm_share:6.2%}  "
          f"cost {r['equity_cost_points']:5.2f} pts  ({r['solve_s']:.0f}s)"
          f"{'  [floor 0 by structural bound]' if mm is None else ''}"
          f"{'' if all_proven else '   <- NOT PROVEN: ' + maximin_note}", flush=True)

# MERGE with any rows this run did not recompute, keyed by k.
OUT = f"data/interim/equity_curve_{SVC}.json"
merged = {}
if pathlib.Path(OUT).exists():
    prev = json.load(open(OUT))
    stale = abs(prev.get("baseline_share", ctx.baseline_share) - ctx.baseline_share) > 5e-4
    kept = [r["k"] for r in prev.get("curve", []) if r["k"] not in {x["k"] for x in rows}]
    # The guard exists to stop stale rows MIXING with fresh ones. If this run
    # recomputed every k the old file held, there is nothing stale to carry
    # forward and the file is simply replaced.
    if stale and kept:
        raise SystemExit(f"{OUT} was built against a different baseline "
                         f"({prev['baseline_share']} vs {ctx.baseline_share:.4f}) and "
                         f"this run does not recompute k={kept}; re-run the whole curve")
    if stale:
        print(f"  replacing curve built against baseline {prev['baseline_share']} "
              f"(now {ctx.baseline_share:.4f}) — every k recomputed", flush=True)
    merged = {} if stale else {r["k"]: r for r in prev.get("curve", [])}
merged.update({r["k"]: r for r in rows})
rows = [merged[k] for k in sorted(merged)]

# INVARIANT. Adding stations cannot reduce coverage, so no point on this curve
# may fall below the do-nothing baseline. Violating it is what made the previous
# run's numbers visibly impossible; assert it rather than trust it.
bad = [r for r in rows if min(r["efficiency_city_coverage"],
                              r["maximin_city_coverage"]) < ctx.baseline_share - 1e-9]
if bad:
    raise SystemExit(f"IMPOSSIBLE: {len(bad)} curve point(s) fall below the "
                     f"{ctx.baseline_share:.2%} do-nothing baseline: "
                     f"{[(r['k'], r['efficiency_city_coverage']) for r in bad]}")

# A row that spends k stations and names none of them is not a solution, and the
# baseline test above cannot catch it: an empty siting scores EXACTLY the
# baseline, not below it. Fire k=20 shipped that way -- a 22.92-point equity cost
# measured against a siting the solver never found.
empty = [r for r in rows if r["k"] > 0 and not r["sites"]]
if empty:
    raise SystemExit(f"IMPOSSIBLE: {len(empty)} curve point(s) select no sites at "
                     f"k>0: {[r['k'] for r in empty]}. An empty siting scores the "
                     f"do-nothing baseline and reads as a huge equity cost.")

# A lexicographic stage that fell back is a real result, but not the one the
# column claims, so it is surfaced rather than left in the JSON.
fell_back = [r for r in rows if r.get("lexicographic_failed")]
if fell_back:
    print(f"\n  NOTE: {len(fell_back)} point(s) fell back to the maximin siting "
          f"because the lexicographic re-solve did not return one: "
          f"{[(r['k'], r['lexicographic_failed']) for r in fell_back]}", flush=True)

json.dump({**stamp(config=config_bundle(SVC), stations=ctx.stations, service=SVC),
           **publication_basis(), "service": SVC,
           "baseline_share": round(ctx.baseline_share, 4),
           "trip_overhead_s": ctx.overhead_s,
           "precovered_cells": int(precov.sum()),
           "all_points_proven_optimal": all(r.get("proven_optimal") for r in rows),
           "unproven_k": [r["k"] for r in rows if not r.get("proven_optimal")],
           "min_sites_for_positive_ward_floor": K_MIN_POSITIVE,
           "lscp_detail": LSCP,
           "curve": rows},
          open(OUT, "w"), indent=2, sort_keys=True)
print(f"\nwrote {OUT}  ({len(rows)} rows, "
      f"{sum(1 for r in rows if not r.get('proven_optimal'))} unproven)", flush=True)
