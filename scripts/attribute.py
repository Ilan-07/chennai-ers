"""Attribute traversal times to the real network. Build step 06."""
import json, sys, time
sys.path.insert(0, "src")
import numpy as np, pandas as pd, yaml
from ers.geo.graph import read_graph_tables
from ers.geo.attrs import attribute_edges, junction_delay, primary_highway

t0 = time.time()
speeds = yaml.safe_load(open("config/speeds/base.yml"))
nodes, edges = read_graph_tables("data/interim/graph")
print(f"loaded {len(nodes):,} nodes  {len(edges):,} edges  ({time.time()-t0:.1f}s)", flush=True)

# Junction delay is credited at each arc's HEAD node.
nodes = nodes.set_index("osmid")
deg = nodes["street_count"].fillna(0).to_numpy()
sig = (nodes["highway"].fillna("").astype(str).str.contains("traffic_signals")).to_numpy()
node_delay = junction_delay(deg, sig, speeds)
delay_by_node = pd.Series(node_delay, index=nodes.index)
head_delay = edges["v"].map(delay_by_node).fillna(0.0).to_numpy()

print(f"signalised nodes: {int(sig.sum()):,} ({100*sig.mean():.1f}%) | "
      f"degree>=3: {int((deg>=3).sum()):,}", flush=True)

out = {}
for svc_name in ("ems", "fire"):
    svc = yaml.safe_load(open(f"config/services/{svc_name}.yml"))
    for scen, peak in (("dry", False), ("peak", True)):
        r = attribute_edges(edges, head_delay, speeds=speeds, service=svc, peak=peak)
        out[f"{svc_name}/{scen}"] = r.stats
        if scen == "dry":
            edges[f"tau_ds_{svc_name}"] = r.tau_ds
        print(f"  {svc_name:4s} {scen:4s}  mean {r.stats['mean_speed_kmh']:5.1f} km/h  "
              f"usable {r.stats['arcs_usable']:,}  excluded {r.stats['arcs_excluded_by_access_filter']:,}  "
              f"junction share {r.stats['junction_delay_share']:.1%}", flush=True)

hw = pd.Series([primary_highway(v) for v in edges["highway"]], name="class")
by_class = (pd.DataFrame({"class": hw, "km": edges["length"].to_numpy()/1000.0})
            .groupby("class")["km"].agg(["count", "sum"]).sort_values("sum", ascending=False))
print("\nnetwork composition:")
print(by_class.assign(pct=lambda d: 100*d["sum"]/d["sum"].sum()).round(1).to_string())

report = {
    "scenarios": out,
    "signalised_nodes": int(sig.sum()),
    "nodes_degree_ge_3": int((deg >= 3).sum()),
    "maxspeed_tagged_share": out["ems/dry"]["maxspeed_tagged_share"],
    "composition_km": {k: round(v, 1) for k, v in by_class["sum"].items()},
    "seconds": round(time.time()-t0, 1),
}
json.dump(report, open("data/interim/attribution_report.json", "w"), indent=2, sort_keys=True)
edges[["u", "v", "key", "tau_ds_ems", "tau_ds_fire", "length"]].to_parquet(
    "data/interim/arc_times.parquet")
print(f"\nwrote arc_times.parquet ({time.time()-t0:.1f}s)")
