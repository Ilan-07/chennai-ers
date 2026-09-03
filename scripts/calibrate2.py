"""Second calibration stage: fit the SHAPE of the speed table, not a scalar.

Stage 1 found a best fit at speed x1.8, junction x0.5 (MedAPE 8.2%). That is a
fitting artifact, not a model: x1.8 implies 144 km/h motorways and 36 km/h
residential streets. A single multiplier cannot be right because the error is
not uniform across classes -- the original table is far too slow on local roads
and roughly right at the top end.

So stage 2 replaces the table with class speeds shaped like OSRM's car profile
(which is what the oracle actually uses) and fits ONLY the junction delay. The
result has to be defensible as a speed table on its own terms, not merely fit.
"""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.attrs import attribute_edges, junction_delay
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.routing.oracle import agreement_stats, stratified_stats

# Free-flow km/h shaped like the OSRM car profile, which the oracle uses.
# Physically defensible line by line, unlike a scalar multiplier.
OSRM_LIKE = {
    "motorway": 90, "motorway_link": 45,
    "trunk": 85, "trunk_link": 40,
    "primary": 65, "primary_link": 30,
    "secondary": 55, "secondary_link": 25,
    "tertiary": 40, "tertiary_link": 20,
    "unclassified": 25, "residential": 25,
    "living_street": 10, "service": 15,
}

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]
speeds = yaml.safe_load(open("config/speeds/base.yml"))
car = yaml.safe_load(open("config/services/car.yml"))
samp = pd.read_csv("data/interim/routing_validation_pairs.csv")
samp = samp[np.isfinite(samp["oracle_s"])].reset_index(drop=True)
oracle = samp["oracle_s"].to_numpy()

nodes, edges = read_graph_tables("data/interim/graph")
nidx = nodes.set_index("osmid")
deg = nidx["street_count"].fillna(0).to_numpy()
sig = nidx["highway"].fillna("").astype(str).str.contains("traffic_signals").to_numpy()
delay_by_node = pd.Series(junction_delay(deg, sig, speeds), index=nidx.index)
head_delay = edges["v"].map(delay_by_node).fillna(0.0).to_numpy()
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
st = pd.read_csv("data/interim/stations_resolved.csv")
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)


def evaluate(table, junction_scale, scale=1.0):
    sc = dict(speeds)
    sc["free_flow_kmh"] = {k: v * scale for k, v in table.items()}
    r = attribute_edges(edges, head_delay * junction_scale, speeds=sc, service=car)
    e2 = edges.copy(); e2["tau"] = r.tau_ds
    g = build_graph(nodes, e2, "tau")
    c_idx, _ = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
    s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
    d = travel_times(g, s_idx, c_idx, cutoff_ds=None)
    model = np.array([to_seconds(d[int(x.s), int(x.c)]) for x in samp.itertuples()])
    return agreement_stats(model, oracle), model


print("OSRM-shaped table, fitting junction delay only:", flush=True)
rows, best = [], None
for js in (1.0, 0.75, 0.5, 0.4, 0.3, 0.25, 0.2, 0.1, 0.0):
    s, model = evaluate(OSRM_LIKE, js)
    rows.append({"junction_scale": js, "medape": s["median_abs_pct_error"],
                 "bias_pct": s["bias_pct"], "ratio": s["median_ratio_model_over_oracle"]})
    r = rows[-1]
    print(f"  junction x{js:.2f}  MedAPE {r['medape']:6.1%}  bias {r['bias_pct']:+7.1%}  "
          f"ratio {r['ratio']:.3f}", flush=True)
    score = abs(r["bias_pct"]) + r["medape"]
    if best is None or score < best["_score"]:
        best = {**r, "_score": score}

js = best["junction_scale"]
stats, model = evaluate(OSRM_LIKE, js)
by_band = stratified_stats(model, oracle, samp["band"])
gate = {"medape_le_15pct": stats["median_abs_pct_error"] <= 0.15,
        "no_band_bias_over_5pct": all(abs(v.get("bias_pct", 0)) <= 0.05
                                      for v in by_band.values() if v.get("n"))}
print(f"\nselected junction x{js:.2f}: MedAPE {stats['median_abs_pct_error']:.1%}  "
      f"bias {stats['bias_pct']:+.1%}")
print("  by band:")
for b, v in sorted(by_band.items()):
    if v.get("n"):
        print(f"    {b:9s} n={v['n']:3d}  MedAPE {v['median_abs_pct_error']:6.1%}  "
              f"bias {v['bias_pct']:+7.1%}")
print(f"\n  GATE  MedAPE<=15%: {gate['medape_le_15pct']}  "
      f"no band bias>5%: {gate['no_band_bias_over_5pct']}")

json.dump({"table": OSRM_LIKE, "junction_scale_sweep": rows, "selected_junction_scale": js,
           "overall": stats, "by_band": by_band, "gate": gate,
           "seconds": round(time.time()-t0, 1)},
          open("data/interim/calibration_stage2.json", "w"), indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Stage 3: a fixed per-trip overhead.
# Residual pattern at junction x0.20 is short trips ~17% too FAST and long trips
# ~5% too slow. That is the signature of a missing constant: a vehicle
# accelerating from rest and making a final approach pays an overhead that does
# not scale with distance. Fitting one constant plus the junction scale.
print("\nstage 3: junction scale x fixed per-trip overhead", flush=True)
best3, rows3 = None, []
for js in (0.10, 0.15, 0.20, 0.25, 0.30):
    _, model_js = evaluate(OSRM_LIKE, js)
    for c in (0, 10, 20, 30, 45, 60):
        s = agreement_stats(model_js + c, oracle)
        bb = stratified_stats(model_js + c, oracle, samp["band"])
        worst_band = max(abs(v.get("bias_pct", 0)) for v in bb.values() if v.get("n"))
        rows3.append({"junction_scale": js, "overhead_s": c,
                      "medape": s["median_abs_pct_error"], "bias_pct": s["bias_pct"],
                      "worst_band_bias": round(worst_band, 4)})
        r = rows3[-1]
        score = r["medape"] + abs(r["bias_pct"]) + max(0.0, worst_band - 0.05)
        if best3 is None or score < best3["_score"]:
            best3 = {**r, "_score": score}
    print(f"  js x{js:.2f} done", flush=True)

b = best3
print(f"\nbest: junction x{b['junction_scale']:.2f} + {b['overhead_s']}s overhead")
print(f"  MedAPE {b['medape']:.1%}  bias {b['bias_pct']:+.1%}  "
      f"worst band bias {b['worst_band_bias']:+.1%}")
_, m = evaluate(OSRM_LIKE, b["junction_scale"])
final = agreement_stats(m + b["overhead_s"], oracle)
fb = stratified_stats(m + b["overhead_s"], oracle, samp["band"])
print("  by band:")
for k, v in sorted(fb.items()):
    if v.get("n"):
        print(f"    {k:9s} n={v['n']:3d}  MedAPE {v['median_abs_pct_error']:6.1%}  "
              f"bias {v['bias_pct']:+7.1%}")
gate3 = {"medape_le_15pct": final["median_abs_pct_error"] <= 0.15,
         "no_band_bias_over_5pct": all(abs(v.get("bias_pct", 0)) <= 0.05
                                       for v in fb.values() if v.get("n"))}
print(f"\n  GATE  MedAPE<=15%: {gate3['medape_le_15pct']}  "
      f"no band bias>5%: {gate3['no_band_bias_over_5pct']}")
json.dump({"table": OSRM_LIKE, "grid": rows3, "best": b, "overall": final,
           "by_band": fb, "gate": gate3},
          open("data/interim/calibration_stage3.json", "w"), indent=2, sort_keys=True)
