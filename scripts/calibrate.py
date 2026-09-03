"""Calibrate the travel-time model against the OSRM oracle. Build step 07.

Validation found the model uniformly ~1.77x slower than OSRM across every
distance band. A constant multiplicative bias points at the parameterisation,
not the topology, and there are only two parameters that can produce it:

  speed_scale     multiplies every class speed in the table
  junction_scale  multiplies the per-node junction delay

Junction delay is the prime suspect: 86,439 of 88,143 nodes have street_count>=3,
so the 5 s "unsignalised junction" penalty is charged at essentially every node
on every route. A 40-junction crossing therefore carries 200 s of pure delay.
"""
import itertools, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.attrs import attribute_edges, junction_delay
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.routing.oracle import agreement_stats

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
base_delay = junction_delay(deg, sig, speeds)
delay_by_node = pd.Series(base_delay, index=nidx.index)
head_delay = edges["v"].map(delay_by_node).fillna(0.0).to_numpy()

cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
st = pd.read_csv("data/interim/stations_resolved.csv")
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)


def evaluate(speed_scale: float, junction_scale: float) -> tuple[dict, np.ndarray]:
    sc = {k: {c: v * speed_scale for c, v in speeds[k].items()}
          if k == "free_flow_kmh" else speeds[k] for k in speeds}
    r = attribute_edges(edges, head_delay * junction_scale, speeds=sc, service=car)
    e2 = edges.copy(); e2["tau"] = r.tau_ds
    g = build_graph(nodes, e2, "tau")
    c_idx, _ = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
    s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
    d = travel_times(g, s_idx, c_idx, cutoff_ds=None)
    model = np.array([to_seconds(d[int(r_.s), int(r_.c)]) for r_ in samp.itertuples()])
    return agreement_stats(model, oracle), model


print("grid search over (speed_scale, junction_scale):", flush=True)
best, rows = None, []
for ss, js in itertools.product([1.0, 1.2, 1.4, 1.6, 1.8], [1.0, 0.5, 0.25, 0.0]):
    stats, _ = evaluate(ss, js)
    rows.append({"speed_scale": ss, "junction_scale": js,
                 "medape": stats["median_abs_pct_error"],
                 "bias_pct": stats["bias_pct"],
                 "ratio": stats["median_ratio_model_over_oracle"]})
    r = rows[-1]
    print(f"  speed x{ss:.1f}  junction x{js:.2f}  MedAPE {r['medape']:6.1%}  "
          f"bias {r['bias_pct']:+7.1%}  ratio {r['ratio']:.3f}", flush=True)
    if best is None or r["medape"] < best["medape"]:
        best = r

print(f"\nbest: speed x{best['speed_scale']}  junction x{best['junction_scale']}  "
      f"MedAPE {best['medape']:.1%}  bias {best['bias_pct']:+.1%}")
json.dump({"grid": rows, "best": best, "seconds": round(time.time()-t0, 1)},
          open("data/interim/calibration_grid.json", "w"), indent=2, sort_keys=True)
