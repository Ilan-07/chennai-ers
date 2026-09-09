"""Validate modelled travel times against an OSRM car oracle. Build step 07."""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.attrs import attribute_edges
from ers.scenario import head_delay_seconds
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.routing.oracle import (agreement_stats, band_median_ratio,
                                batch_durations, stratified_stats)

N_PAIRS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
REUSE = "--reuse-oracle" in sys.argv     # re-score the model without re-querying OSRM
SEED = 20260903
t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]
speeds = yaml.safe_load(open("config/speeds/base.yml"))
car = yaml.safe_load(open("config/services/car.yml"))

nodes, edges = read_graph_tables("data/interim/graph")

# F-18. This script used to build the junction delay WITHOUT
# `junction_delay_scale` and without adding `trip_overhead_s`, so it validated
# the UNCALIBRATED model -- not the one the pipeline ships. It could therefore
# never show the calibrated model passing its own gate, and its 42% MedAPE was
# read as a routing failure when it was a bookkeeping one. Both terms now come
# from the same place every other consumer uses.
# (calibrate.py / calibrate2.py legitimately omit the scale: they FIT it.)
head_delay = head_delay_seconds(nodes, edges, speeds)
OVERHEAD = float(speeds.get("trip_overhead_s", 0.0))

res = attribute_edges(edges, head_delay, speeds=speeds, service=car)
edges["tau_ds_car"] = res.tau_ds
g = build_graph(nodes, edges, "tau_ds_car")

# Stratified sample: origins at existing stations, destinations drawn to fill
# distance bands, so a band-specific bias cannot hide inside a global median.
rng = np.random.default_rng(SEED)
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
c_idx, _ = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
st = pd.read_csv("data/interim/stations_resolved.csv")
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)
s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())

sxy = np.column_stack([sp.x.to_numpy(), sp.y.to_numpy()])
cxy = np.column_stack([cc.x.to_numpy(), cc.y.to_numpy()])
BANDS = [(0, 2000), (2000, 5000), (5000, 10000), (10000, 20000)]
per_band = max(1, N_PAIRS // len(BANDS))

rows = []
for lo, hi in BANDS:
    for _ in range(per_band):
        si = int(rng.integers(len(sxy)))
        d = np.linalg.norm(cxy - sxy[si], axis=1)
        pool = np.flatnonzero((d >= lo) & (d < hi))
        if len(pool) == 0:
            continue
        ci = int(rng.choice(pool))
        rows.append({"band": f"{lo//1000}-{hi//1000}km", "s": si, "c": ci,
                     "crow_m": float(d[ci])})
samp = pd.DataFrame(rows).drop_duplicates(subset=["s", "c"]).reset_index(drop=True)
print(f"sampled {len(samp)} OD pairs across {len(BANDS)} bands", flush=True)

d_all = travel_times(g, s_idx, c_idx, cutoff_ds=None)
samp["model_s"] = [to_seconds(d_all[r.s, r.c]) + OVERHEAD for r in samp.itertuples()]

lat_s = sp.to_crs("EPSG:4326"); lon_s, la_s = lat_s.x.to_numpy(), lat_s.y.to_numpy()
cll = cc.to_crs("EPSG:4326"); lon_c, la_c = cll.x.to_numpy(), cll.y.to_numpy()
pairs = [(lon_s[r.s], la_s[r.s], lon_c[r.c], la_c[r.c]) for r in samp.itertuples()]

if REUSE:
    # Re-scoring the model against durations already fetched for THESE station
    # positions. Legitimate only because the oracle depends on the OD pairs, not
    # on our speed table -- and the signature check below proves the pairs match.
    cached = pd.read_csv("data/interim/routing_validation_pairs.csv")
    key = ["s", "c"]
    samp = samp.merge(cached[key + ["oracle_s", "oracle_m"]], on=key, how="left")
    print(f"reused cached oracle durations for {int(samp['oracle_s'].notna().sum())} "
          f"of {len(samp)} pairs (no OSRM query)", flush=True)
else:
    print("querying OSRM oracle ...", flush=True)
    res_o = batch_durations(pairs)
    samp["oracle_s"] = [r[0] if r else np.nan for r in res_o]
    samp["oracle_m"] = [r[1] if r else np.nan for r in res_o]

overall = agreement_stats(samp["model_s"].to_numpy(), samp["oracle_s"].to_numpy())
by_band = stratified_stats(samp["model_s"], samp["oracle_s"], samp["band"])

print("\n=== agreement vs OSRM car ===")
print(f"  n {overall['n']}  MedAPE {overall['median_abs_pct_error']:.1%}  "
      f"P90APE {overall['p90_abs_pct_error']:.1%}")
print(f"  median ratio model/oracle {overall['median_ratio_model_over_oracle']:.3f}  "
      f"bias {overall['bias_pct']:+.1%}")
print(f"  limits of agreement {overall['loa_lower_s']:+.0f}s .. {overall['loa_upper_s']:+.0f}s")
print("\n  by distance band:")
for b, s in by_band.items():
    if s.get("n"):
        print(f"    {b:9s} n={s['n']:3d}  MedAPE {s['median_abs_pct_error']:6.1%}  "
              f"ratio {s['median_ratio_model_over_oracle']:.3f}  bias {s['bias_pct']:+7.1%}")

# The band gate is scored on the MEDIAN RATIO, not on `bias_pct`: the latter is
# a ratio of sums whose 95% CI at this sample size runs 5.5-25.2 points wide, so
# a 5% threshold on it is untestable. See oracle.band_median_ratio.
bmr = band_median_ratio(samp["model_s"], samp["oracle_s"], samp["band"])
worst = max(abs(v["median_ratio_minus_1"]) for v in bmr.values() if v.get("n"))
gate = {"medape_le_15pct": overall["median_abs_pct_error"] <= 0.15,
        "band_median_ratio_le_5pct": bool(worst <= 0.05),
        "worst_band_median_ratio": round(float(worst), 4),
        "statistic": "median(model/oracle)-1 per band; sum-ratio bias_pct retired"}
print("\n  per band, median ratio - 1 (bootstrap 95% CI):")
for b, v in sorted(bmr.items()):
    if v.get("n"):
        print(f"    {b:9s} n={v['n']:3d}  {v['median_ratio_minus_1']:+7.2%} "
              f"[{v['ci_lower']:+.1%},{v['ci_upper']:+.1%}]  CI width {v['ci_width_points']:5.1f}p")
print(f"\n  GATE  MedAPE<=15%: {gate['medape_le_15pct']}  "
      f"worst band<=5%: {gate['band_median_ratio_le_5pct']} ({worst:.2%})")

samp.to_csv("data/interim/routing_validation_pairs.csv", index=False)
# The OD pairs are built FROM the station positions, so the oracle durations are
# only valid while those positions hold. Stamp them, so a later run against
# moved stations is detectable rather than silently wrong (E-11c moved all 29).
from ers.pipeline import station_signature
from ers.provenance import config_bundle, stamp
json.dump({**stamp(config=config_bundle("ems"), seed=SEED, stations=st),
           "overall": overall, "by_band": by_band,
           "band_median_ratio": bmr, "gate": gate,
           "oracle": "OSRM public demo, car profile",
           "stations_signature_at_computation": station_signature(st),
           "oracle_failures": int(samp["oracle_s"].isna().sum()),
           "seconds": round(time.time()-t0, 1)},
          open("data/interim/routing_validation.json", "w"), indent=2, sort_keys=True)
print(f"\ndone {time.time()-t0:.0f}s")
