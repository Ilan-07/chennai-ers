"""Stage 4: refit the trip overhead and junction scale on a SOUND statistic.

Two problems with the stage-3 fit, both found after the fact:

1. THE BAND GATE WAS TESTING A STATISTIC IT COULD NOT ESTIMATE. `bias_pct` is a
   ratio of sums, so within a band it is dominated by the longest trips, and at
   n~50 its bootstrap 95% CI runs 5.5 to 25.2 points wide. A <=5% threshold on a
   quantity with a +/-12 point CI is not a test, and no configuration on the grid
   could ever clear it. Worse, both E-10 verdicts used it as a criterion.

2. IT HID A REAL EFFECT. Because within-band sums are dominated by long trips,
   the sum-ratio statistic washed out a systematic short-trip bias that the
   median ratio shows plainly: +15.1% at 0-2 km falling to +3.2% at 10-20 km,
   three of four CIs excluding zero. That is the signature of a flat per-trip
   overhead being too blunt -- 45 s is 21% of a median 0-2 km trip and 3% of a
   10-20 km one.

So this stage scores on the MEDIAN RATIO per band, reports bootstrap CIs, and is
cross-validated on held-out pairs. A two-part overhead (a + b*km) was tested and
REJECTED: it does not beat a single smaller constant out of sample, so the
simpler model stands.

  python scripts/calibrate4.py [--splits N]
"""
import argparse, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.attrs import attribute_edges
from ers.publish import publication_basis
from ers.geo.graph import read_graph_tables
from ers.pipeline import station_signature
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.scenario import head_delay_seconds

ap = argparse.ArgumentParser()
ap.add_argument("--splits", type=int, default=40)
ap.add_argument("--seed", type=int, default=20260904)
ap.add_argument("--out", default="data/interim/calibration_stage4.json")
args = ap.parse_args()

JS_GRID = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
OH_GRID = list(np.arange(0, 61, 2.5))
BAND_TARGET = 0.05

t0 = time.time()
speeds = yaml.safe_load(open("config/speeds/base.yml"))
car = yaml.safe_load(open("config/services/car.yml"))
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]

samp = pd.read_csv("data/interim/routing_validation_pairs.csv")
samp = samp[np.isfinite(samp["oracle_s"])].reset_index(drop=True)
oracle = samp["oracle_s"].to_numpy(); band = samp["band"].to_numpy()
rv = json.load(open("data/interim/routing_validation.json"))
st = pd.read_csv("data/interim/stations_resolved.csv")
if rv.get("stations_signature_at_computation") != station_signature(st):
    raise SystemExit("cached OSRM pairs do not match current station positions; "
                     "re-run scripts/validate_routing.py")

nodes, edges = read_graph_tables("data/interim/graph")
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)


def model_times(js):
    hd = head_delay_seconds(nodes, edges, speeds, junction_scale=js)
    r = attribute_edges(edges, hd, speeds=speeds, service=car)
    e2 = edges[["u", "v", "key"]].copy(); e2["tau"] = r.tau_ds
    g = build_graph(nodes, e2, "tau")
    c_idx, _ = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
    s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
    d = travel_times(g, s_idx, c_idx, cutoff_ds=None)
    return np.array([to_seconds(d[int(x.s), int(x.c)]) for x in samp.itertuples()])


print("computing model times per junction scale ...", flush=True)
TAU = {js: model_times(js) for js in JS_GRID}
print(f"  done ({time.time()-t0:.0f}s)", flush=True)


def stats(m, o, b):
    """Median ratio per band -- stable under resampling, unlike a ratio of sums."""
    r = m / o
    per = {x: float(np.median(r[b == x]) - 1.0) for x in np.unique(b)}
    return max(abs(v) for v in per.values()), float(np.median(np.abs(m - o) / o)), per


def best_on(idx):
    out = None
    for js in JS_GRID:
        for oh in OH_GRID:
            w, me, _ = stats(TAU[js][idx] + oh, oracle[idx], band[idx])
            sc = w + me
            if out is None or sc < out[0]:
                out = (sc, js, oh)
    return out[1], out[2]


# ---- cross-validation: does the refit survive on pairs it never saw?
rng = np.random.default_rng(args.seed)
cv = []
for _ in range(args.splits):
    p = rng.permutation(len(oracle)); tr, te = p[:len(p)//2], p[len(p)//2:]
    js, oh = best_on(tr)
    w_new, me_new, _ = stats(TAU[js][te] + oh, oracle[te], band[te])
    w_old, me_old, _ = stats(TAU[0.10][te] + 45.0, oracle[te], band[te])
    cv.append((js, oh, w_new, me_new, w_old, me_old))
cv = np.array(cv)
print(f"\n{args.splits}x half-sample CV, evaluated on held-out pairs:")
print(f"  refit picks js median {np.median(cv[:,0]):.3f}, overhead median {np.median(cv[:,1]):.1f}s")
print(f"  worst |median ratio-1|   refit {np.median(cv[:,2]):.2%}  vs shipped {np.median(cv[:,4]):.2%}")
print(f"  MedAPE                   refit {np.median(cv[:,3]):.2%}  vs shipped {np.median(cv[:,5]):.2%}")
print(f"  refit wins worst-band in {(cv[:,2]<cv[:,4]).mean():.0%} of splits, "
      f"MedAPE in {(cv[:,3]<cv[:,5]).mean():.0%}")

# ---- full-sample fit, with bootstrap CIs on the band statistic
js, oh = best_on(np.arange(len(oracle)))
w, me, per = stats(TAU[js] + oh, oracle, band)
w0, me0, per0 = stats(TAU[0.10] + 45.0, oracle, band)
boot = {}
for x in np.unique(band):
    sel = np.flatnonzero(band == x)
    r = (TAU[js][sel] + oh) / oracle[sel]
    bs = [np.median(r[rng.integers(0, len(sel), len(sel))]) - 1 for _ in range(4000)]
    boot[x] = [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]

print(f"\nselected: junction x{js:.3f} + {oh:.1f}s overhead   "
      f"(shipped: x0.10 + 45s)")
print(f"  worst band |median ratio-1|  {w:.2%}   (shipped {w0:.2%})")
print(f"  MedAPE                       {me:.2%}   (shipped {me0:.2%})")
print("\n  per band, median ratio - 1, with bootstrap 95% CI:")
for x in sorted(per):
    lo, hi = boot[x]
    flag = "" if abs(per[x]) <= BAND_TARGET else "   OVER TARGET"
    print(f"    {x:9s} refit {per[x]:+7.2%} [{lo:+.1%},{hi:+.1%}]   shipped {per0[x]:+7.2%}{flag}")

gate = {"medape_le_15pct": me <= 0.15,
        "band_median_ratio_le_5pct": bool(w <= BAND_TARGET),
        "band_target": BAND_TARGET}
print(f"\n  GATE  MedAPE<=15%: {gate['medape_le_15pct']}   "
      f"worst band<=5% (median ratio): {gate['band_median_ratio_le_5pct']}")

json.dump({"stage": 4, "statistic": "median ratio per band (sum-ratio bias retired)",
           "selected_junction_scale": js, "selected_trip_overhead_s": oh,
           "shipped_junction_scale": 0.10, "shipped_trip_overhead_s": 45.0,
           "worst_band": round(w, 4), "worst_band_shipped": round(w0, 4),
           "medape": round(me, 4), "medape_shipped": round(me0, 4),
           "per_band": {k: round(v, 4) for k, v in per.items()},
           "per_band_bootstrap_ci": boot, "gate": gate,
           "cv_splits": args.splits,
           "cv_refit_worst_band_median": round(float(np.median(cv[:, 2])), 4),
           "cv_shipped_worst_band_median": round(float(np.median(cv[:, 4])), 4),
           "cv_refit_wins_worst_band_share": round(float((cv[:, 2] < cv[:, 4]).mean()), 3),
           "two_part_overhead_tested_and_rejected": True,
           "stations_signature": station_signature(st),
           **publication_basis(), "seconds": round(time.time()-t0, 1)},
          open(args.out, "w"), indent=2, sort_keys=True)
print(f"\nwrote {args.out}  ({time.time()-t0:.0f}s)")
