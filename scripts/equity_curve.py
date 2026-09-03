"""Maximin ward coverage vs k. Build step 14.

The efficiency-equity frontier is degenerate at small k: with 5 new stations the
best achievable worst-ward coverage is 0%, because 200 wards cannot all be
reached from 5 sites. So the prior question is not "what does equity cost in
coverage" but "how many stations does equity cost at all".
"""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers.model.problem import SitingProblem
from ers.optimise import exact

SVC = sys.argv[1] if len(sys.argv) > 1 else "ems"
KS = [int(x) for x in (sys.argv[2].split(",") if len(sys.argv) > 2 else "5,10,20,30,45,60".split(","))]

M = sparse.load_npz(f"data/interim/coverage_{SVC}.npz")
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cand = gpd.read_parquet("data/interim/candidates.parquet")
demand = cells["population"].to_numpy().astype("float64")
ward = cells["ward_id"].to_numpy()
feas = cand["land_feasible"].to_numpy().astype(bool)
tot = demand.sum()
precov = np.load(f"data/interim/precovered_{SVC}.npy")

rows = []
for k in KS:
    p = SitingProblem(coverage=M, precovered=precov, demand=demand, k=k,
                      ward_of=ward, land_feasible=feas)
    t0 = time.time()
    beta, mm = exact.solve_maximin(p, time_limit_s=600)
    eff = exact.solve(p, time_limit_s=300)
    eff_share = (eff.baseline_covered + eff.objective) / tot

    # LEXICOGRAPHIC second stage. Maximin is degenerate whenever several sitings
    # achieve the same worst-ward share -- and totally degenerate when that share
    # is 0, since then every siting ties and the solver returns an arbitrary one.
    # Re-solve for maximum coverage SUBJECT TO the achieved floor, so the
    # "equity" column is the best equitable solution rather than a random one.
    # Floors below 1e-4 are solver noise, not policy. Treat them as zero.
    if beta > 1e-4:
        p_lex = SitingProblem(coverage=M, precovered=precov, demand=demand, k=k,
                              ward_of=ward, land_feasible=feas, equity_floor=beta)
        lex = exact.solve(p_lex, time_limit_s=300)
        mm_share = float((lex.baseline_covered + lex.objective) / tot)
        mm_sites = lex.selected
    else:
        # Floor is 0: the equity constraint binds nothing, so the equitable
        # solution IS the efficient one. Reporting anything else is meaningless.
        mm_share = float(eff_share)
        mm_sites = eff.selected

    rows.append({"k": k, "maximin_worst_ward": round(beta, 4),
                 "maximin_degenerate": bool(beta <= 1e-4),
                 "sites": list(mm_sites),
                 "maximin_city_coverage": round(mm_share, 4),
                 "efficiency_city_coverage": round(float(eff_share), 4),
                 "equity_cost_points": round(100 * (eff_share - mm_share), 2),
                 "solve_s": round(time.time() - t0, 1), "status": mm.status})
    r = rows[-1]
    print(f"  k={k:3d}  worst-ward floor {beta:6.2%}  |  city coverage: "
          f"efficiency {eff_share:6.2%}  equity {mm_share:6.2%}  "
          f"cost {r['equity_cost_points']:5.2f} pts  ({r['solve_s']:.0f}s)", flush=True)

json.dump({"PROVISIONAL": True, "service": SVC, "curve": rows},
          open(f"data/interim/equity_curve_{SVC}.json", "w"), indent=2, sort_keys=True)
