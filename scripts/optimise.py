"""Coverage matrix + siting optimisation. Build steps 09b/11.

PROVISIONAL: 29 of 33 station positions are geocoder output, not surveyed.
"""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers.pipeline import load_service
from ers.provenance import config_bundle, stamp
from ers.routing.csr import snap, travel_times, to_seconds
from ers.model.problem import SitingProblem
from ers.optimise import greedy, exact

SVC = sys.argv[1] if len(sys.argv) > 1 else "ems"
t0 = time.time()

# One routing implementation, shared with baseline/frontier/equity (ers.pipeline).
ctx = load_service(SVC)
budget_s, g, cells = ctx.budget_s, ctx.graph, ctx.cells
c_idx, access_s = ctx.cell_idx, ctx.cell_snap_m / 1.2
precovered, demand, ward = ctx.precovered, ctx.demand, ctx.ward
tot = ctx.total_demand

cand = gpd.read_parquet("data/interim/candidates.parquet").to_crs(ctx.metric_crs)
j_idx, _ = snap(g, cand.geometry.x.to_numpy(), cand.geometry.y.to_numpy())
feas = cand["land_feasible"].to_numpy().astype(bool)

# A cell beyond 3x the budget cannot be covered within it, so truncating the
# candidate sweep there is exact for the coverage matrix -- unlike truncating a
# sweep whose purpose is to report how far away something is.
cutoff = budget_s * 10 * 3
print(f"[{SVC}] budget {budget_s}s | {len(cells):,} cells | {len(cand):,} candidates | "
      f"{len(ctx.stations)} stations", flush=True)
print(f"  existing-station sweep -> precovered {precovered.sum():,} cells", flush=True)

t1 = time.time()
d_c = travel_times(g, j_idx, c_idx, cutoff_ds=cutoff)          # |J| x |I|
cand_s = to_seconds(d_c) + access_s[None, :] + ctx.overhead_s
M = sparse.csr_matrix((cand_s <= budget_s).T)                  # |I| x |J|
print(f"  candidate sweep: {time.time()-t1:.1f}s -> matrix {M.shape} nnz {M.nnz:,} "
      f"({100*M.nnz/(M.shape[0]*M.shape[1]):.2f}% dense)", flush=True)
sparse.save_npz(f"data/interim/coverage_{SVC}.npz", M)

base_share = ctx.baseline_share
print(f"  baseline coverage {base_share:.1%}\n", flush=True)

rows = []
for label, land in (("land-feasible", feas), ("unconstrained", None)):
    for k in (1, 2, 3, 5, 8, 10):
        p = SitingProblem(coverage=M, precovered=precovered, demand=demand, k=k,
                          ward_of=ward, land_feasible=land)
        gs = greedy.solve(p)
        ex = exact.solve(p, time_limit_s=120)
        rows.append({
            "candidate_set": label, "k": k,
            "greedy_share": round((gs.baseline_covered + gs.objective)/tot, 4),
            "exact_share": round((ex.baseline_covered + ex.objective)/tot, 4),
            "greedy_gap_vs_exact": round((ex.objective-gs.objective)/max(ex.objective,1e-9), 5),
            "proven_gap": ex.gap, "status": ex.status,
            "solution_status": ex.solution_status, "proven_optimal": ex.proven_optimal,
            "optimality": ex.optimality_note,
            "greedy_s": gs.wall_s, "exact_s": ex.wall_s,
            "sites": list(ex.selected),
        })
        r = rows[-1]
        print(f"  {label:14s} k={k:2d}  exact {r['exact_share']:6.1%}  "
              f"greedy {r['greedy_share']:6.1%}  greedy-gap {r['greedy_gap_vs_exact']:7.3%}  "
              f"proven-gap {str(r['proven_gap']):>8}  {r['exact_s']:6.2f}s"
              f"  {'' if ex.proven_optimal else '  <- ' + ex.optimality_note}", flush=True)

out = {**stamp(config=config_bundle(SVC), stations=ctx.stations, service=SVC),
       "PROVISIONAL": True, "service": SVC, "travel_budget_s": budget_s,
       "baseline_share": round(float(base_share), 4),
       "trip_overhead_s": ctx.overhead_s,
       "precovered_cells": int(precovered.sum()),
       "all_runs_proven_optimal": all(r["proven_optimal"] for r in rows),
       "cells": len(cells), "candidates": len(cand),
       "candidates_land_feasible": int(feas.sum()),
       "matrix_nnz": int(M.nnz), "runs": rows, "seconds": round(time.time()-t0, 1)}
json.dump(out, open(f"data/interim/optimise_{SVC}.json", "w"), indent=2, sort_keys=True)
print(f"\ntotal {out['seconds']}s")
