"""Prioritise the station survey by leverage. Follows E-11.

E-11 showed station position uncertainty (900 m on 29 of 33) puts a +/-6.7 point
noise floor under every coverage figure and makes the recommended site list
irreproducible. The survey is therefore the binding constraint on the project.

But 29 site visits are not equally worth making. This ranks them, and prices the
answer to the question a project manager actually asks: "if I can only send
someone to ten of these, which ten, and what does it buy me?"

  LEVERAGE   perturb ONE station inside its own uncertainty, hold the other 32 at
             their point estimates, and measure the coverage spread it alone
             causes. A station in a dense, poorly-covered area moves the answer;
             one deep inside another station's catchment does not.

  RESIDUAL   perturb only the stations NOT in the top N, i.e. simulate having
             surveyed the top N, and measure the noise floor that remains. This
             is the decision curve.
             Caveat, stated rather than buried: this estimates the residual
             SPREAD. Surveying also moves the centre, by however wrong each
             geocode turns out to be, and that part cannot be known in advance.

  python scripts/prioritise_survey.py [--draws N] [--seed S]
"""
import argparse, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd
from ers import coverage as cov
from ers.pipeline import load_service
from ers.routing.csr import snap

ap = argparse.ArgumentParser()
ap.add_argument("--draws", type=int, default=60, help="draws per station for leverage")
ap.add_argument("--residual-draws", type=int, default=200)
ap.add_argument("--seed", type=int, default=20260904)
ap.add_argument("--max-snap-m", type=float, default=300.0)
ap.add_argument("--top-n", default="0,5,10,15,20,29")
ap.add_argument("--worklist", default="data/interim/station_survey_worklist.csv")
ap.add_argument("--out", default="data/interim/survey_priority.json")
args = ap.parse_args()

t0 = time.time()
CTX = {svc: load_service(svc) for svc in ("ems", "fire")}
st = CTX["ems"].stations
unc = st["uncertainty_m"].to_numpy(dtype="float64")
names = st["station_name"].to_numpy()
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]),
                   crs="EPSG:4326").to_crs(CTX["ems"].metric_crs)
XY0 = np.column_stack([sp.x.to_numpy(), sp.y.to_numpy()])
rng = np.random.default_rng(args.seed)
GRAPH = CTX["ems"].graph          # same node set for both services


def perturb(mask: np.ndarray) -> np.ndarray:
    """Positions with the stations in `mask` drawn inside their uncertainty discs.

    Per-station rejection, as in E-11: the uncertainties are independent, so
    resampling everything whenever one lands badly would let the plausibility
    filter rather than the uncertainty decide the answer.
    """
    xy = XY0.copy()
    todo = mask & (unc > 0)
    for _ in range(40):
        if not todo.any():
            break
        m = int(todo.sum())
        r = unc[todo] * np.sqrt(rng.random(m))
        th = rng.random(m) * 2 * np.pi
        trial = XY0[todo] + np.column_stack([r * np.cos(th), r * np.sin(th)])
        _, dist = snap(GRAPH, trial[:, 0], trial[:, 1])
        ok = dist <= args.max_snap_m
        sel = np.flatnonzero(todo)[ok]
        xy[sel] = trial[ok]
        todo[sel] = False
    return xy


def shares(xy: np.ndarray, svc: str) -> float:
    ctx = CTX[svc]
    s_idx, _ = snap(ctx.graph, xy[:, 0], xy[:, 1])
    best = cov.response_seconds(ctx.graph, s_idx, ctx.cell_idx, ctx.cell_snap_m,
                                overhead_s=ctx.overhead_s,
                                cutoff_ds=ctx.budget_s * 10 * 3)
    pre = np.isfinite(best) & (best <= ctx.budget_s)
    return float(ctx.demand[pre].sum() / ctx.total_demand)


# ---------------------------------------------------------------- LEVERAGE
movable = np.flatnonzero(unc > 60)          # the 29 locality geocodes
print(f"leverage: {len(movable)} stations x {args.draws} draws x 2 services", flush=True)
lev = []
for n, i in enumerate(movable):
    mask = np.zeros(len(unc), dtype=bool)
    mask[i] = True
    per = {}
    for svc in ("ems", "fire"):
        vals = np.array([shares(perturb(mask), svc) for _ in range(args.draws)])
        # sd, not P5-P95: at this many draws per station a standard deviation is
        # the stabler estimator, and only the RANKING is needed here.
        per[svc] = float(vals.std())
    lev.append({"station": str(names[i]), "index": int(i),
                "leverage_ems_points": round(100 * per["ems"], 3),
                "leverage_fire_points": round(100 * per["fire"], 3),
                "leverage_points": round(100 * (per["ems"] + per["fire"]) / 2, 3)})
    if (n + 1) % 5 == 0:
        print(f"  {n+1}/{len(movable)}  ({time.time()-t0:.0f}s)", flush=True)

lev.sort(key=lambda r: -r["leverage_points"])
for rank, r in enumerate(lev, 1):
    r["survey_priority"] = rank

rho = pd.Series([r["leverage_ems_points"] for r in lev]).corr(
    pd.Series([r["leverage_fire_points"] for r in lev]), method="spearman")
print(f"\nEMS/fire leverage rank correlation (Spearman): {rho:.2f}")
print(f"\n{'rank':>4} {'station':18s} {'EMS':>8} {'fire':>8} {'mean':>8}")
for r in lev[:12]:
    print(f"{r['survey_priority']:>4} {r['station']:18s} {r['leverage_ems_points']:>8.3f} "
          f"{r['leverage_fire_points']:>8.3f} {r['leverage_points']:>8.3f}")
print(f"{'...':>4}")
for r in lev[-3:]:
    print(f"{r['survey_priority']:>4} {r['station']:18s} {r['leverage_ems_points']:>8.3f} "
          f"{r['leverage_fire_points']:>8.3f} {r['leverage_points']:>8.3f}")

# ---------------------------------------------------------------- RESIDUAL
order = [r["index"] for r in lev]
print(f"\nresidual noise floor after surveying the top N "
      f"({args.residual_draws} draws each):", flush=True)
residual = []
for N in [int(x) for x in args.top_n.split(",")]:
    surveyed = set(order[:N])
    mask = np.array([(i in set(movable)) and (i not in surveyed)
                     for i in range(len(unc))])
    row = {"surveyed": N, "still_uncertain": int(mask.sum())}
    for svc in ("ems", "fire"):
        vals = np.array([shares(perturb(mask), svc) for _ in range(args.residual_draws)])
        lo, hi = np.percentile(vals, [5, 95])
        row[f"{svc}_p5_p95_points"] = round(100 * (hi - lo), 2)
        row[f"{svc}_sd_points"] = round(100 * float(vals.std()), 2)
    residual.append(row)
    print(f"  survey {N:2d} -> {row['still_uncertain']:2d} still uncertain | "
          f"EMS spread {row['ems_p5_p95_points']:5.2f} pts | "
          f"fire {row['fire_p5_p95_points']:5.2f} pts", flush=True)

base = residual[0]
for row in residual[1:]:
    if row["surveyed"]:
        cut = 100 * (1 - row["ems_p5_p95_points"] / base["ems_p5_p95_points"])
        row["ems_noise_reduction_pct"] = round(cut, 1)

# ------------------------------------------------------- prioritised worklist
wl = pd.read_csv(args.worklist)
rank = {r["station"]: r for r in lev}
wl["survey_priority"] = wl["station_name"].map(
    lambda n: rank.get(n, {}).get("survey_priority"))
wl["leverage_points"] = wl["station_name"].map(
    lambda n: rank.get(n, {}).get("leverage_points"))
unmatched = wl["survey_priority"].isna().sum()
if unmatched:
    print(f"\nWARNING: {unmatched} worklist row(s) did not match a station name; "
          f"they are ranked last and flagged.", flush=True)
wl = wl.sort_values("survey_priority", na_position="last")
# Keep the empty verification columns at the end where field staff expect them.
cols = [c for c in wl.columns if c not in ("verified_lat", "verified_lon", "verified_by")]
wl = wl[cols + ["verified_lat", "verified_lon", "verified_by"]]
wl.to_csv(args.worklist, index=False)
print(f"\nrewrote {args.worklist} in priority order ({len(wl)} rows, "
      f"{unmatched} unmatched)")

json.dump({"experiment": "E-11b", "seed": args.seed, "draws_per_station": args.draws,
           "residual_draws": args.residual_draws,
           "ems_fire_rank_spearman": round(float(rho), 3),
           "leverage": lev, "residual_noise": residual,
           "PROVISIONAL": True, "seconds": round(time.time() - t0, 1)},
          open(args.out, "w"), indent=2, sort_keys=True)
print(f"wrote {args.out}  ({time.time()-t0:.0f}s)")
