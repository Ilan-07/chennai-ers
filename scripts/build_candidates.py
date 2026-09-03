"""Generate candidate sites. Build step 10."""
import json, sys, time
sys.path.insert(0, "src")
import pandas as pd, yaml
from ers.geo.graph import read_graph_tables
from ers.geo.candidates import build_candidates, load_osm_parcels
from ers.io.registry import DatasetRegistry

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]

nodes, edges = read_graph_tables("data/interim/graph")
parcels, prep = load_osm_parcels("data/raw/osm_parcels_overpass.json", METRIC)
print("parcels: " + json.dumps(prep), flush=True)

cs = build_candidates(nodes, edges, parcels, METRIC)
print("candidates: " + json.dumps({k: v for k, v in cs.stats.items()
                                   if k != "land_class_counts"}, indent=2), flush=True)
print("\nland classes for feasible candidates:")
for k, v in sorted(cs.stats["land_class_counts"].items(), key=lambda kv: -kv[1]):
    print(f"  {v:5d}  {k}")

parcels.to_parquet("data/interim/parcels.parquet")
cs.frame.to_crs("EPSG:4326").to_parquet("data/interim/candidates.parquet")
json.dump({"parcels": prep, "candidates": cs.stats, "seconds": round(time.time()-t0, 1)},
          open("data/interim/candidates_report.json", "w"), indent=2, sort_keys=True)
DatasetRegistry().register(source="osm_parcels", uri="https://overpass-api.de/api/interpreter",
                           local_path="data/raw/osm_parcels_overpass.json", licence="ODbL")
print(f"\nwrote candidates.parquet ({time.time()-t0:.1f}s)")
