"""Build the Chennai drive network. Build step 05.

Checkpoints the consolidated graph to a pickle BEFORE any table conversion:
consolidation costs ~25 minutes and must never be lost to a serialisation bug
downstream of it.
"""
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
import networkx as nx
import osmnx as ox
import yaml

from ers.geo.graph import write_graph_tables

CKPT = Path("data/interim/graph_consolidated.pkl")
cfg = yaml.safe_load(open("config/city/chennai.yml"))
south, west, north, east = cfg["bbox"]

ox.settings.use_cache = True
ox.settings.cache_folder = "data/raw/osm_cache"
ox.settings.requests_timeout = 900
ox.settings.useful_tags_way = [
    "highway", "oneway", "maxspeed", "bridge", "tunnel", "access", "service",
    "lanes", "width", "maxheight", "name", "ref", "junction", "area", "motor_vehicle",
]
ox.settings.useful_tags_node = ["highway", "crossing", "traffic_signals"]

t0 = time.time()
report: dict = {"bbox": cfg["bbox"], "crs_metric": cfg["crs"]["metric"]}

if CKPT.exists():
    print(f"resuming from checkpoint {CKPT}", flush=True)
    Gc = pickle.loads(CKPT.read_bytes())
    report.update(json.loads(Path("data/interim/graph_stage1.json").read_text()))
else:
    print(f"downloading (cached) bbox W{west} S{south} E{east} N{north} ...", flush=True)
    G = ox.graph.graph_from_bbox((west, south, east, north), network_type="drive",
                                 simplify=True, truncate_by_edge=True)
    print(f"raw: {G.number_of_nodes():,} nodes {G.number_of_edges():,} edges "
          f"({time.time()-t0:.0f}s)", flush=True)
    Gp = ox.projection.project_graph(G, to_crs=cfg["crs"]["metric"])
    print("consolidating intersections (tolerance 12 m) ...", flush=True)
    Gc = ox.simplification.consolidate_intersections(
        Gp, tolerance=12, rebuild_graph=True, dead_ends=False, reconnect_edges=True)
    print(f"consolidated: {Gc.number_of_nodes():,} nodes {Gc.number_of_edges():,} edges "
          f"({time.time()-t0:.0f}s)", flush=True)
    stage1 = {"raw_nodes": G.number_of_nodes(), "raw_edges": G.number_of_edges(),
              "consolidated_nodes": Gc.number_of_nodes(),
              "consolidated_edges": Gc.number_of_edges()}
    Path("data/interim/graph_stage1.json").write_text(json.dumps(stage1))
    CKPT.write_bytes(pickle.dumps(Gc))          # CHECKPOINT before anything can fail
    print(f"checkpointed -> {CKPT}", flush=True)
    report.update(stage1)

# Largest weakly connected component. Everything outside it is REPORTED, not dropped silently.
wccs = sorted(nx.weakly_connected_components(Gc), key=len, reverse=True)
Gl = Gc.subgraph(wccs[0]).copy()
nodes, edges = ox.convert.graph_to_gdfs(Gl)

report.update({
    "components": len(wccs),
    "largest_wcc_nodes": len(wccs[0]),
    "stranded_nodes": Gc.number_of_nodes() - len(wccs[0]),
    "largest_wcc_node_share": round(len(wccs[0]) / Gc.number_of_nodes(), 5),
    "final_nodes": int(Gl.number_of_nodes()), "final_edges": int(Gl.number_of_edges()),
    "network_length_km": round(float(edges["length"].sum()) / 1000.0, 1),
    "build_seconds": round(time.time() - t0, 1),
})
meta = write_graph_tables(nodes, edges, "data/interim/graph")
report["encoded_list_columns"] = meta
print(json.dumps(report, indent=2), flush=True)
json.dump(report, open("data/interim/graph_report.json", "w"), indent=2, sort_keys=True)
print("wrote graph_nodes/edges.parquet + graph_schema.json", flush=True)
