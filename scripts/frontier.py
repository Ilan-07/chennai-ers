"""Efficiency-equity Pareto frontier. Build step 14.

Finding F-04: the deck's motivation is equity ("the worst-covered wards are
peripheral and lower-income") but its objective is total covered population,
which is the most concentration-favouring objective in the covering family.

The fix is not to pick a different single optimum. It is to sweep the per-ward
coverage floor beta and report the FRONTIER, so a planner can read off what each
point of guaranteed ward-level coverage costs in city-wide coverage, and how far
it moves the recommended sites.
"""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers.model.problem import SitingProblem
from ers.publish import publication_basis
from ers.optimise import exact
from ers.pipeline import load_service, ward_shares as _ward_shares
from ers.provenance import config_bundle, stamp

SVC = sys.argv[1] if len(sys.argv) > 1 else "ems"
K = int(sys.argv[2]) if len(sys.argv) > 2 else 5
t0 = time.time()

M = sparse.load_npz(f"data/interim/coverage_{SVC}.npz")
cand = gpd.read_parquet("data/interim/candidates.parquet")
base = json.load(open(f"data/interim/optimise_{SVC}.json"))

# BUG FIX: this script previously computed `pre_s` without the calibrated 45 s
# `trip_overhead_s`, so every ward figure below described a model 45 s faster
# than the rest of the project. Routing now comes from ers.pipeline, which is
# the same code baseline/optimise/equity use, and the result is cross-checked
# against the share optimise.py actually recorded.
ctx = load_service(SVC)
ctx.check_baseline_share(base["baseline_share"])
budget_s, demand, ward, precovered = ctx.budget_s, ctx.demand, ctx.ward, ctx.precovered
cells, tot = ctx.cells, ctx.total_demand
feas = cand["land_feasible"].to_numpy().astype(bool)


def ward_shares(covered_mask):
    return _ward_shares(ward, demand, covered_mask)


def covered_from(sel):
    m = precovered.copy()
    if sel:
        m |= np.asarray(M[:, list(sel)].sum(axis=1)).ravel() > 0
    return m


print(f"[{SVC}] k={K}, budget {budget_s}s, baseline {base['baseline_share']:.1%}", flush=True)
base_ws = ward_shares(precovered)
print(f"baseline worst ward {base_ws.min():.1%} | median {base_ws.median():.1%}\n", flush=True)

# beta_max(k): the largest ward floor k stations can actually achieve. Without
# this the ladder is guesswork and every rung past the limit is an infeasible solve.
p_mm = SitingProblem(coverage=M, precovered=precovered, demand=demand, k=K,
                     ward_of=ward, land_feasible=feas)
MAXIMIN_LIMIT_S = 300
beta_max, mm = exact.solve_maximin(p_mm, time_limit_s=MAXIMIN_LIMIT_S)
print(f"maximin at k={K}: best achievable worst-ward floor = {beta_max:.2%} "
      f"({mm.wall_s:.1f}s, {mm.optimality_note})\n", flush=True)
if not mm.proven_optimal:
    # beta_max sets the whole ladder. An unproven floor makes every rung below
    # it a guess, so say so rather than printing it like a proven quantity.
    print("  WARNING: beta_max is an incumbent, not a proven maximum. The ladder "
          "below is derived from it and inherits that caveat.", flush=True)

# DEGENERATE CASE. When beta_max is 0 the ladder collapses: every rung is the
# same unconstrained solve, and printing seven identical rows dressed as a
# frontier implies a trade-off that does not exist at this k. 200 wards cannot
# all be reached from K sites, so the honest output is one row plus the reason.
degenerate = beta_max <= 1e-4
if degenerate:
    print(f"  DEGENERATE at k={K}: the best achievable worst-ward floor is 0%, so the "
          f"equity constraint\n  binds nothing and there is no frontier to trace. "
          f"200 wards cannot be reached from {K} sites.\n  The question at this k is "
          f"not what equity costs, but how many stations equity needs at all.",
          flush=True)

ladder = [0.0] if degenerate else \
    [0.0] + [round(beta_max * f, 4) for f in (0.25, 0.5, 0.7, 0.85, 0.95, 1.0)]
rows, prev_sites = [], None
for beta in ladder:
    p = SitingProblem(coverage=M, precovered=precovered, demand=demand, k=K,
                      ward_of=ward, land_feasible=feas,
                      equity_floor=None if beta == 0 else beta)
    s = exact.solve(p, time_limit_s=180)
    # `status` alone cannot distinguish these: pulp reports a HiGHS time-limit
    # stop as "Optimal" too. A rung is only usable if a solution was actually
    # found, so test the SOLUTION status.
    if s.status != "Optimal" or s.solution_status == "No Solution Found":
        print(f"  beta {beta:.2f}  NO SOLUTION ({s.status} / {s.solution_status}) "
              f"-- beta_max lies below this", flush=True)
        rows.append({"beta": beta, "status": s.status,
                     "solution_status": s.solution_status, "feasible": False})
        break
    cov = covered_from(s.selected)
    ws = ward_shares(cov)
    share = float(demand[cov].sum()/tot)
    jac = (len(set(s.selected) & set(prev_sites))/len(set(s.selected) | set(prev_sites))
           if prev_sites else 1.0)
    rows.append({"beta": beta, "feasible": True, "coverage_share": round(share, 4),
                 "worst_ward": round(float(ws.min()), 4),
                 "median_ward": round(float(ws.median()), 4),
                 "ward_share_std": round(float(ws.std()), 4),
                 "sites": list(s.selected), "jaccard_vs_prev": round(jac, 3),
                 "proven_optimal": s.proven_optimal, "optimality": s.optimality_note,
                 "solve_s": s.wall_s})
    r = rows[-1]
    print(f"  beta {beta:.2f}  coverage {share:6.2%}  worst ward {ws.min():6.2%}  "
          f"ward sd {ws.std():.3f}  site-overlap {jac:5.1%}  {s.wall_s:5.2f}s", flush=True)
    prev_sites = s.selected

feasible = [r for r in rows if r.get("feasible")]
# CROSS-CHECK: the beta=0 rung is by definition the unconstrained MCLP at this k,
# so it must equal what optimise.py recorded. A mismatch means the two scripts
# have drifted apart again -- which is exactly the failure being fixed here.
if feasible:
    rec = [r for r in base["runs"]
           if r["candidate_set"] == "land-feasible" and r["k"] == K]
    if rec and abs(feasible[0]["coverage_share"] - rec[0]["exact_share"]) > 5e-4:
        raise SystemExit(f"beta=0 rung {feasible[0]['coverage_share']:.4f} disagrees with "
                         f"optimise.py k={K} {rec[0]['exact_share']:.4f}")
    if rec:
        print(f"\ncross-check: beta=0 rung {feasible[0]['coverage_share']:.2%} "
              f"== optimise.py k={K} {rec[0]['exact_share']:.2%}  OK")

if len(feasible) > 1:
    a, b = feasible[0], feasible[-1]
    print(f"\ncost of equity: worst ward {a['worst_ward']:.1%} -> {b['worst_ward']:.1%} "
          f"costs {100*(a['coverage_share']-b['coverage_share']):.2f} points of city coverage")
    print(f"site displacement: {len(set(a['sites'])^set(b['sites']))} of {2*K} site-slots differ")

json.dump({**stamp(config=config_bundle(SVC), stations=ctx.stations, service=SVC),
           **publication_basis(), "service": SVC, "k": K,
           "degenerate": bool(degenerate),
           "degenerate_reason": (f"maximin floor is 0% at k={K}: the equity constraint "
                                 f"binds nothing and the ladder collapses to the "
                                 f"unconstrained solve") if degenerate else None,
           "baseline_share": round(ctx.baseline_share, 4),
           "trip_overhead_s": ctx.overhead_s,
           "baseline_worst_ward": round(float(base_ws.min()), 4),
           "beta_max": round(float(beta_max), 4),
           "beta_max_proven": mm.proven_optimal,
           "beta_max_optimality": mm.optimality_note,
           "all_rungs_proven_optimal": all(r.get("proven_optimal", False)
                                           for r in rows if r.get("feasible")),
           "frontier": rows, "seconds": round(time.time()-t0, 1)},
          open(f"data/interim/frontier_{SVC}.json", "w"), indent=2, sort_keys=True)
print(f"\nwrote data/interim/frontier_{SVC}.json ({time.time()-t0:.0f}s)")
