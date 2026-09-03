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
from ers.optimise import exact

SVC = sys.argv[1] if len(sys.argv) > 1 else "ems"
K = int(sys.argv[2]) if len(sys.argv) > 2 else 5
t0 = time.time()

M = sparse.load_npz(f"data/interim/coverage_{SVC}.npz")
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cand = gpd.read_parquet("data/interim/candidates.parquet")
base = json.load(open(f"data/interim/optimise_{SVC}.json"))

demand = cells["population"].to_numpy().astype("float64")
ward = cells["ward_id"].to_numpy()
feas = cand["land_feasible"].to_numpy().astype(bool)
tot = demand.sum()

# Recover precovered from the recorded baseline share.
import geopandas as gpd2
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]
scfg = yaml.safe_load(open(f"config/services/{SVC}.yml"))
std = yaml.safe_load(open("config/standards/sfac.yml"))
budget_s = std["presets"][scfg["default_standard"]]["t_target_s"] - scfg["t_alarm_s"] - scfg["t_turnout_s"]
nodes, edges = read_graph_tables("data/interim/graph")
arcs = pd.read_parquet("data/interim/arc_times.parquet")
edges = edges.merge(arcs[["u","v","key","tau_ds_ems","tau_ds_fire"]], on=["u","v","key"], how="left")
g = build_graph(nodes, edges, f"tau_ds_{SVC}")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
c_idx, c_dist = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
st = pd.read_csv("data/interim/stations_resolved.csv")
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)
s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
pre_s = to_seconds(travel_times(g, s_idx, c_idx, cutoff_ds=budget_s*10*3).min(axis=0)) + c_dist/1.2
precovered = np.isfinite(pre_s) & (pre_s <= budget_s)


def ward_shares(covered_mask):
    df = pd.DataFrame({"w": ward, "d": demand, "c": covered_mask.astype(float)})
    gsum = df.groupby("w").apply(lambda x: (x["d"]*x["c"]).sum()/max(x["d"].sum(), 1e-9),
                                 include_groups=False)
    return gsum


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
beta_max, mm = exact.solve_maximin(p_mm, time_limit_s=300)
print(f"maximin at k={K}: best achievable worst-ward floor = {beta_max:.2%} "
      f"({mm.wall_s:.1f}s, {mm.status})\n", flush=True)

ladder = [0.0] + [round(beta_max * f, 4) for f in (0.25, 0.5, 0.7, 0.85, 0.95, 1.0)]
rows, prev_sites = [], None
for beta in ladder:
    p = SitingProblem(coverage=M, precovered=precovered, demand=demand, k=K,
                      ward_of=ward, land_feasible=feas,
                      equity_floor=None if beta == 0 else beta)
    s = exact.solve(p, time_limit_s=180)
    if s.status != "Optimal":
        print(f"  beta {beta:.2f}  INFEASIBLE ({s.status}) -- beta_max lies below this", flush=True)
        rows.append({"beta": beta, "status": s.status, "feasible": False})
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
                 "solve_s": s.wall_s})
    r = rows[-1]
    print(f"  beta {beta:.2f}  coverage {share:6.2%}  worst ward {ws.min():6.2%}  "
          f"ward sd {ws.std():.3f}  site-overlap {jac:5.1%}  {s.wall_s:5.2f}s", flush=True)
    prev_sites = s.selected

feasible = [r for r in rows if r.get("feasible")]
if len(feasible) > 1:
    a, b = feasible[0], feasible[-1]
    print(f"\ncost of equity: worst ward {a['worst_ward']:.1%} -> {b['worst_ward']:.1%} "
          f"costs {100*(a['coverage_share']-b['coverage_share']):.2f} points of city coverage")
    print(f"site displacement: {len(set(a['sites'])^set(b['sites']))} of {2*K} site-slots differ")

json.dump({"PROVISIONAL": True, "service": SVC, "k": K,
           "baseline_worst_ward": round(float(base_ws.min()), 4),
           "frontier": rows, "seconds": round(time.time()-t0, 1)},
          open(f"data/interim/frontier_{SVC}.json", "w"), indent=2, sort_keys=True)
