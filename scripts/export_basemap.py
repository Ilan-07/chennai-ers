"""Vector basemap for the coverage console. Build step 18.

Artifacts cannot load map tiles (external images are CSP-blocked), so the map is
drawn from the project's OWN geometry. That is not a workaround dressed up as a
virtue: the roads on screen are literally the network the model routes over, the
ward outlines are the ones the equity analysis groups by, and the flood extents
are the polygons that removed the arcs. A tile basemap would show a different,
prettier city than the one being analysed.

Coordinates are rounded to 4 decimals (~11 m) and geometry simplified, because a
city-scale map cannot resolve better and the payload has to stay small.
"""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from shapely.geometry import LineString, MultiLineString, Polygon, MultiPolygon
from ers.flood import load_flood_zones
from ers.geo.graph import read_graph_tables

R = 4
t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))


def rings(geom, tol):
    """Polygon exteriors as coordinate rings, simplified and rounded."""
    if geom is None or geom.is_empty:
        return []
    g = geom.simplify(tol, preserve_topology=True)
    parts = g.geoms if isinstance(g, MultiPolygon) else [g]
    out = []
    for p in parts:
        if p.is_empty or p.area <= 0:
            continue
        out.append([[round(c[0], R), round(c[1], R)] for c in p.exterior.coords])
    return out


def lines(geom, tol):
    if geom is None or geom.is_empty:
        return []
    g = geom.simplify(tol, preserve_topology=False)
    parts = g.geoms if isinstance(g, MultiLineString) else [g]
    return [[[round(c[0], R), round(c[1], R)] for c in p.coords]
            for p in parts if not p.is_empty and len(p.coords) > 1]


wards = gpd.read_parquet("data/interim/wards.parquet").to_crs("EPSG:4326")
zones = gpd.read_parquet("data/interim/zones.parquet").to_crs("EPSG:4326")
bm = {"outline": [], "wards": [], "zones": [], "zone_labels": [],
      "arterial": [], "secondary": [], "water": [], "waterline": [], "flood": {}}

# GCC outline — the coastline comes free with it
bm["outline"] = rings(wards.union_all(), 0.0004)
# ward outlines are legible on the raster; the zone boundaries are what the
# equity analysis actually groups by, so only those are drawn.
pass
for r in zones.itertuples():
    bm["zones"] += rings(r.geometry, 0.0003)
    c = r.geometry.representative_point()
    bm["zone_labels"].append({"n": str(r.zone_name), "lat": round(c.y, R), "lon": round(c.x, R)})

# Roads, water and ward fills now come from the imported raster basemap
# (scripts/export_basemap_raster.py), which is real cartography rather than a
# hand-drawn approximation of it. Only ANALYSIS geometry stays vector: the GCC
# outline, the zone boundaries the equity work groups by, and the flood extents
# that actually removed arcs. Those must be ours, drawn on top, and exact.
_SKIP_ROADS = True

# water: rivers and canals as lines, lakes and tanks as polygons
try:
    raw = {"elements": []}      # water is in the raster now
    _unused = json.load(open("data/raw/osm_water_overpass.json"))
    for e in raw["elements"]:
        t = e.get("tags", {})
        geom = e.get("geometry") or []
        if len(geom) < 2:
            continue
        pts = [[round(p["lon"], R), round(p["lat"], R)] for p in geom]
        if t.get("natural") == "water":
            # Keep water bodies large enough to read at city scale. 1,207 tanks
            # cost 0.52 MB -- half the basemap -- for features a few pixels wide,
            # and the page blanks for 25 s while the browser parses them.
            if len(pts) > 3:
                xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                span = max(max(xs) - min(xs), max(ys) - min(ys))
                if span >= 0.0022 or t.get("name"):     # ~250 m, or named
                    bm["water"].append(pts)
        else:
            bm["waterline"].append(pts)
except FileNotFoundError:
    print("no water extract; run the Overpass fetch first")

# flood extents — the polygons that actually removed arcs
for sid, path in (("flood5", "data/raw/chennai_flows_5yr.kml"),
                  ("flood25", "data/raw/chennai_flows_25yr.kml"),
                  ("flood100", "data/raw/chennai_flows_100yr.kml")):
    z, st = load_flood_zones(path, "EPSG:4326")
    keep = z[z["CATEGORY"].isin(["HIGH", "MODERATE"])]
    merged = keep.union_all()
    bm["flood"][sid] = rings(merged, 0.0004)
    print(f"  {sid:9s} {st['features']:4d} zones -> {len(bm['flood'][sid]):4d} rings")

path = "data/interim/ui_basemap.json"
json.dump(bm, open(path, "w"), separators=(",", ":"))
import os
print(f"\noutline {len(bm['outline'])} | wards {len(bm['wards'])} | zones {len(bm['zones'])}")
print(f"arterial {len(bm['arterial'])} | secondary {len(bm['secondary'])}")
print(f"water polys {len(bm['water'])} | water lines {len(bm['waterline'])}")
print(f"wrote {path}  {os.path.getsize(path)/1e6:.2f} MB  ({time.time()-t0:.0f}s)")
