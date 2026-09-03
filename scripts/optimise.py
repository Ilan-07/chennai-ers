"""Coverage matrix + siting optimisation. Build steps 09b/11.

PROVISIONAL: 29 of 33 station positions are geocoder output, not surveyed.
"""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.model.problem import SitingProblem
from ers.optimise import greedy, exact

SVC = sys.argv[1] if len(sys.argv) > 1 else "ems"
t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]
scfg = yaml.safe_load(open(f"config/services/{SVC}.yml"))
std = yaml.safe_load(open("config/standards/sfac.yml"))
budget_s = std["presets"][scfg["default_standard"]]["t_target_s"] - scfg["t_alarm_s"] - scfg["t_turnout_s"]

nodes, edges = read_graph_tables("data/interim/graph")
arcs = pd.read_parquet("data/interim/arc_times.parquet")
edges = edges.merge(arcs[["u","v","key","tau_ds_ems","tau_ds_fire"]], on=["u","v","key"], how="left")
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cand = gpd.read_parquet("data/interim/candidates.parquet").to_crs(METRIC)
st = pd.read_csv("data/interim/stations_resolved.csv")

g = build_graph(nodes, edges, f"tau_ds_{SVC}")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
c_idx, c_dist = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
access_s = c_dist / 1.2
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)
s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
j_idx, _ = snap(g, cand.geometry.x.to_numpy(), cand.geometry.y.to_numpy())

cutoff = budget_s * 10 * 3
print(f"[{SVC}] budget {budget_s}s | {len(cells):,} cells | {len(cand):,} candidates | "
      f"{len(st)} stations", flush=True)

t1 = time.time()
d_st = travel_times(g, s_idx, c_idx, cutoff_ds=cutoff)
pre_s = to_seconds(d_st.min(axis=0)) + access_s
precovered = np.isfinite(pre_s) & (pre_s <= budget_s)
print(f"  existing-station sweep: {time.time()-t1:.1f}s -> precovered {precovered.sum():,} cells",
      flush=True)

t1 = time.time()
d_c = travel_times(g, j_idx, c_idx, cutoff_ds=cutoff)          # |J| x |I|
cand_s = to_seconds(d_c) + access_s[None, :]
M = sparse.csr_matrix((cand_s <= budget_s).T)                  # |I| x |J|
print(f"  candidate sweep: {time.time()-t1:.1f}s -> matrix {M.shape} nnz {M.nnz:,} "
      f"({100*M.nnz/(M.shape[0]*M.shape[1]):.2f}% dense)", flush=True)
sparse.save_npz(f"data/interim/coverage_{SVC}.npz", M)

demand = cells["population"].to_numpy().astype("float64")
ward = cells["ward_id"].to_numpy()
feas = cand["land_feasible"].to_numpy().astype(bool)
tot = demand.sum()
base_share = demand[precovered].sum() / tot
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
            "greedy_s": gs.wall_s, "exact_s": ex.wall_s,
            "sites": list(ex.selected),
        })
        r = rows[-1]
        print(f"  {label:14s} k={k:2d}  exact {r['exact_share']:6.1%}  "
              f"greedy {r['greedy_share']:6.1%}  greedy-gap {r['greedy_gap_vs_exact']:7.3%}  "
              f"proven-gap {str(r['proven_gap']):>8}  {r['exact_s']:6.2f}s", flush=True)

out = {"PROVISIONAL": True, "service": SVC, "travel_budget_s": budget_s,
       "baseline_share": round(float(base_share), 4),
       "cells": len(cells), "candidates": len(cand),
       "candidates_land_feasible": int(feas.sum()),
       "matrix_nnz": int(M.nnz), "runs": rows, "seconds": round(time.time()-t0, 1)}
json.dump(out, open(f"data/interim/optimise_{SVC}.json", "w"), indent=2, sort_keys=True)
print(f"\ntotal {out['seconds']}s")
