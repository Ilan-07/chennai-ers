"""Validate modelled travel times against an OSRM car oracle. Build step 07."""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.attrs import attribute_edges, junction_delay
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.routing.oracle import agreement_stats, batch_durations, stratified_stats

N_PAIRS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
SEED = 20260903
t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]
speeds = yaml.safe_load(open("config/speeds/base.yml"))
car = yaml.safe_load(open("config/services/car.yml"))

nodes, edges = read_graph_tables("data/interim/graph")
nidx = nodes.set_index("osmid")
deg = nidx["street_count"].fillna(0).to_numpy()
sig = nidx["highway"].fillna("").astype(str).str.contains("traffic_signals").to_numpy()
delay_by_node = pd.Series(junction_delay(deg, sig, speeds), index=nidx.index)
head_delay = edges["v"].map(delay_by_node).fillna(0.0).to_numpy()

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
samp["model_s"] = [to_seconds(d_all[r.s, r.c]) for r in samp.itertuples()]

lat_s = sp.to_crs("EPSG:4326"); lon_s, la_s = lat_s.x.to_numpy(), lat_s.y.to_numpy()
cll = cc.to_crs("EPSG:4326"); lon_c, la_c = cll.x.to_numpy(), cll.y.to_numpy()
pairs = [(lon_s[r.s], la_s[r.s], lon_c[r.c], la_c[r.c]) for r in samp.itertuples()]

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

gate = {"medape_le_15pct": overall["median_abs_pct_error"] <= 0.15,
        "no_band_bias_over_5pct": all(abs(s.get("bias_pct", 0)) <= 0.05
                                      for s in by_band.values() if s.get("n"))}
print(f"\n  GATE  MedAPE<=15%: {gate['medape_le_15pct']}  "
      f"no band bias>5%: {gate['no_band_bias_over_5pct']}")

samp.to_csv("data/interim/routing_validation_pairs.csv", index=False)
json.dump({"seed": SEED, "overall": overall, "by_band": by_band, "gate": gate,
           "oracle": "OSRM public demo, car profile",
           "seconds": round(time.time()-t0, 1)},
          open("data/interim/routing_validation.json", "w"), indent=2, sort_keys=True)
print(f"\ndone {time.time()-t0:.0f}s")
