"""Peak-hour ambulance staging. Build step 15b.

THE QUESTION. Peak hour is the binding scenario: it takes ambulance coverage from
71.8% to 39.6%, worse than the 100-year flood (step 13, step 15). Every answer
this project has offered to it so far is a BUILDING -- a new station on a
land-feasible parcel. An ambulance is not a building. During the hours the roads
are full, a crew can wait at a roadside post and leave from there, and a post
needs a kerb, not a parcel.

So this is the same maximal covering problem as step 11, solved on the PEAK
network with the land-feasibility filter switched off: every candidate on the
road lattice may hold a post. The building is not the constraint being relaxed
by accident; it is the constraint that does not apply.

WHAT A POST IS, HERE. An ADDITIONAL ambulance stationed at the post for the peak
window. It is not a crew moved out of an existing station: that would uncover the
station's own ground, and pricing it needs the per-station fleet, which no
registered dataset carries (see ASSUMPTIONS.md A-15 and ADR-012). The additive
reading is therefore an upper bound on what repositioning the existing fleet
would buy.

Two curves are written, both on the peak network and both solved exactly:

  posts      any road-lattice candidate      what a staging plan buys
  stations   land-feasible candidates only   what step 11's answer buys at peak

Their difference at the same k is what dropping the parcel requirement is worth.
By construction posts >= stations at every k (a superset of sites); the run
refuses to publish if that ever fails, because it would mean the solver, not the
city, produced the number.

  python scripts/stage.py [service] [--scenario peak] [--max-k 10]

PROVISIONAL: 34 of 39 station positions are geocoder output, not surveyed.
"""
import argparse, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd
from scipy import sparse
from ers.model.problem import SitingProblem
from ers.optimise import exact, greedy
from ers.pipeline import build_scenario_coverage, demand_column
from ers.provenance import config_bundle, stamp
from ers.publish import publication_basis

ap = argparse.ArgumentParser()
ap.add_argument("service", nargs="?", default="ems")
ap.add_argument("--scenario", default="peak")
ap.add_argument("--max-k", type=int, default=10)
ap.add_argument("--time-limit", type=float, default=120.0)
args = ap.parse_args()
SVC, SCEN = args.service, args.scenario

t0 = time.time()
print(f"[{SVC}] staging on the {SCEN} network", flush=True)
(sc,), meta = build_scenario_coverage(SVC, [SCEN])
dry_sc, _ = build_scenario_coverage(SVC, ["dry"], progress=False)

cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cand = gpd.read_parquet("data/interim/candidates.parquet")
demand = np.asarray(demand_column(cells, SVC), dtype="float64")
ward = cells["ward_id"].to_numpy()
feas = cand["land_feasible"].to_numpy().astype(bool)
tot = float(demand.sum())
M, pre = sc.coverage, sc.precovered
peak_share = float(demand[pre].sum() / tot)
dry_share = float(demand[dry_sc[0].precovered].sum() / tot)
lost = dry_share - peak_share
print(f"  {len(cand):,} candidates ({feas.sum():,} land-feasible) | "
      f"{SCEN} {peak_share:.2%} vs dry {dry_share:.2%}\n", flush=True)


def solve(k, land):
    p = SitingProblem(coverage=M, precovered=pre, demand=demand, k=k,
                      ward_of=ward, land_feasible=land)
    gs = greedy.solve(p)
    ex = exact.solve(p, time_limit_s=args.time_limit)
    share = (ex.baseline_covered + ex.objective) / tot
    return {
        "k": k,
        "share": round(share, 4),
        "gain_points": round(100 * (share - peak_share), 2),
        # How much of what peak hour takes away this plan gives back. The
        # headline number for a planner: "three posts recover a quarter of it".
        "recovers_share_of_peak_loss": round((share - peak_share) / lost, 4) if lost > 0 else None,
        "greedy_share": round((gs.baseline_covered + gs.objective) / tot, 4),
        "proven_optimal": bool(ex.proven_optimal),
        "proven_gap": ex.gap,
        "optimality": ex.optimality_note,
        "sites": [int(j) for j in ex.selected],
        "seconds": ex.wall_s,
    }


posts, stations = [], []
for k in range(1, args.max_k + 1):
    posts.append(solve(k, None))
    stations.append(solve(k, feas))
    a, b = posts[-1], stations[-1]
    print(f"  k={k:2d}  posts {a['share']:6.1%} (+{a['gain_points']:4.1f})  "
          f"stations {b['share']:6.1%} (+{b['gain_points']:4.1f})  "
          f"recovers {a['recovers_share_of_peak_loss']:5.1%} of the peak loss"
          f"{'' if a['proven_optimal'] and b['proven_optimal'] else '  <- not proven'}",
          flush=True)

# GATE: a superset of sites cannot do worse. Compared on proven runs only -- a
# timed-out incumbent is allowed to be beaten by luck.
for a, b in zip(posts, stations):
    if a["proven_optimal"] and b["proven_optimal"] and a["share"] + 1e-9 < b["share"]:
        raise SystemExit(f"k={a['k']}: posts {a['share']} < stations {b['share']} "
                         f"on a superset of candidates -- solver defect, not a finding")

# The comparison that says what staging is FOR. The dry-day station plan of the
# same size -- step 11's question, solved here on the dry network at every k so
# the curve has no interpolated points -- scored on THIS network. If it already
# did most of what the posts do, a separate peak plan would be redundant.
dry_M, dry_pre = dry_sc[0].coverage, dry_sc[0].precovered
cov_c = M.tocsc()
dry_plan = []
for k in range(1, args.max_k + 1):
    ex = exact.solve(SitingProblem(coverage=dry_M, precovered=dry_pre, demand=demand,
                                   k=k, ward_of=ward, land_feasible=feas),
                     time_limit_s=args.time_limit)
    hit = pre.copy()
    for j in ex.selected:
        hit[cov_c.indices[cov_c.indptr[j]:cov_c.indptr[j + 1]]] = True
    share = float(demand[hit].sum() / tot)
    match = posts[k - 1]
    dry_plan.append({
        "k": k, "sites": [int(j) for j in ex.selected],
        "proven_optimal_on_dry": bool(ex.proven_optimal),
        "share_at_peak": round(share, 4),
        "gain_points_at_peak": round(100 * (share - peak_share), 2),
        "sites_shared_with_posts": len(set(ex.selected) & set(match["sites"])),
    })
    print(f"  dry-day plan k={k:2d} at {SCEN}: {share:6.1%}  vs posts "
          f"{match['share']:6.1%}  ({dry_plan[-1]['sites_shared_with_posts']} sites shared)",
          flush=True)

pos = cand.to_crs("EPSG:4326").geometry
positions = [{"lat": round(float(p.y), 5), "lon": round(float(p.x), 5),
              "land_feasible": bool(f)} for p, f in zip(pos, feas)]

sparse.save_npz(f"data/interim/staging_{SVC}_{SCEN}.npz", M.tocsr())
out = {**stamp(config=config_bundle(SVC),
         stations=pd.read_csv("data/interim/stations_resolved.csv"), service=SVC),
       **publication_basis(),
       "service": SVC, "scenario": SCEN,
       "travel_budget_s": meta["budget_s"],
       "post_meaning": "additional ambulance posted for the peak window "
                       "(upper bound on repositioning the existing fleet; A-15)",
       "baseline_share": round(peak_share, 4),
       "dry_share": round(dry_share, 4),
       "peak_loss_points": round(100 * lost, 2),
       "candidates": len(cand), "candidates_land_feasible": int(feas.sum()),
       "candidate_positions": positions,
       "matrix_nnz": int(M.nnz),
       "all_runs_proven_optimal": all(r["proven_optimal"] for r in posts + stations),
       "posts": posts, "stations": stations, "dry_plan_at_peak": dry_plan,
       "seconds": round(time.time() - t0, 1)}
json.dump(out, open(f"data/interim/staging_{SVC}.json", "w"), indent=2, sort_keys=True)
print(f"\nwrote data/interim/staging_{SVC}.json  ({out['seconds']}s)")
