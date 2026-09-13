"""Area units for the metro study area. Build step 04c.

Equity is reported per ward, and outside the GCC there are no wards. Tambaram
Corporation has its own, Avadi has its own, Navalur has none at all, and none of
them are published as GIS. Reporting metro equity per GCC ward is impossible;
reporting it per "everything outside GCC" is useless, because that single unit
would hold 3.2 M people and hide exactly the variation the analysis is for.

So outside the corporation the unit is an **H3 r7 cell** (~5.16 km², about 2.4
times a GCC ward) labelled by the settlement nearest its centre. That is a
neutral, reproducible tessellation with no administrative meaning claimed for
it: it is a reporting grid, and ADR-009 says so. Inside the corporation the unit
is the ward, unchanged, so every GCC figure stays comparable with the GCC build.

    python scripts/build_metro_units.py

Writes wards.parquet (GCC wards + outer cells) and zones.parquet in the same
schema the rest of the pipeline already consumes, so nothing downstream needs to
know the difference.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import geopandas as gpd  # noqa: E402
import h3  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

UA = "chennai-ers/0.1 (academic emergency-response siting research)"
OVERPASS = "https://overpass-api.de/api/interpreter"
PLACES = Path("data/raw/osm_places_metro.json")

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]
RES = int(cfg.get("outer_unit_resolution", 7))

# The study area comes from the city config, not a fixed filename. The full
# profile used to store its boundary AS "metro_area.parquet" because that was
# the name this line insisted on, which made the filename a lie and the two
# profiles indistinguishable on disk.
STUDY_AREA = cfg.get("study_area", "data/interim/metro_area.parquet")
area = gpd.read_parquet(STUDY_AREA).to_crs("EPSG:4326")
# This script OVERWRITES wards.parquet with 200 GCC wards + 87 outer cells, so
# the corporation boundary has to be preserved before that happens or it is gone.
# It was preserved by hand, once. On the next run `build_metro_area.py` read the
# overwritten file as its "authority", unioned the urban centre with all 287
# units, and returned a study area 73 km2 larger than the run before -- a
# feedback loop in which the profile grows from its own output every time it is
# rebuilt. Snapshot it, and the pipeline converges instead.
GCC_SNAPSHOT = Path("data/interim/gcc_wards.parquet")
if GCC_SNAPSHOT.exists():
    gcc = gpd.read_parquet(GCC_SNAPSHOT)
else:
    gcc = gpd.read_parquet("data/interim/wards.parquet")
    if "unit_kind" in gcc.columns:
        raise SystemExit(
            "data/interim/wards.parquet already holds metro units and no "
            "gcc_wards.parquet snapshot exists, so the corporation boundary "
            "cannot be recovered. Re-seed the tree from the GCC build.")
    gcc.to_parquet(GCC_SNAPSHOT)
    print(f"snapshotted the authority boundary to {GCC_SNAPSHOT}", flush=True)
gcc = gcc.to_crs("EPSG:4326")

# ------------------------------------------------------------------ outer grid
shape = area.geometry.iloc[0]
polys = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
idx: set[str] = set()
for poly in polys:
    idx.update(h3.h3shape_to_cells(h3.geo_to_h3shape(poly.__geo_interface__), RES))
cells = sorted(idx)
outer = gpd.GeoDataFrame(
    {"h3_index": cells},
    geometry=[Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells],
    crs="EPSG:4326")

# Keep only what lies outside the corporation: inside it, the ward is the unit.
gcc_union = gcc.to_crs(METRIC).union_all() if hasattr(gcc.to_crs(METRIC), "union_all") \
    else gcc.to_crs(METRIC).unary_union
om = outer.to_crs(METRIC)
om["outside_frac"] = 1.0 - (om.geometry.intersection(gcc_union).area / om.geometry.area)
outer = outer[om["outside_frac"].to_numpy() > 0.5].reset_index(drop=True)
print(f"outer grid: {len(outer)} H3 r{RES} cells beyond the GCC", flush=True)

# ------------------------------------------------------------------- names
if PLACES.exists():
    places = json.loads(PLACES.read_text())
else:
    s, w, n, e = cfg["bbox"]
    q = f"""[out:json][timeout:180];
(
  node["place"~"^(city|town|suburb|village|neighbourhood)$"]({s},{w},{n},{e});
);
out tags center;"""
    print("querying Overpass for settlement names ...", flush=True)
    r = requests.post(OVERPASS, data={"data": q}, headers={"User-Agent": UA}, timeout=300)
    r.raise_for_status()
    places = r.json().get("elements", [])
    PLACES.write_text(json.dumps({"elements": places}, indent=1, sort_keys=True))
places = places["elements"] if isinstance(places, dict) else places

RANK = {"city": 0, "town": 1, "suburb": 2, "neighbourhood": 3, "village": 4}
pts = [{"name": p["tags"].get("name"), "rank": RANK.get(p["tags"].get("place"), 9),
        "lat": p.get("lat"), "lon": p.get("lon")}
       for p in places if p.get("tags", {}).get("name") and p.get("lat")]
pg = gpd.GeoDataFrame(pts, geometry=gpd.points_from_xy([p["lon"] for p in pts],
                                                       [p["lat"] for p in pts]),
                      crs="EPSG:4326").to_crs(METRIC)
print(f"{len(pg)} named settlements for labelling", flush=True)

centres = outer.to_crs(METRIC).geometry.centroid
labels = []
for c in centres:
    d = pg.geometry.distance(c)
    # Prefer the more significant settlement when two are comparably close: a
    # cell between Navalur and a nameless hamlet should read "Navalur".
    score = d.to_numpy() + pg["rank"].to_numpy() * 400.0
    j = int(score.argmin())
    labels.append(f"{pg.iloc[j]['name']}")
outer["unit_name"] = labels

# ------------------------------------------------------- one table, two kinds
gcc = gcc.copy()
gcc["unit_kind"] = "gcc_ward"
gcc["unit_name"] = "Ward " + gcc["ward_no"].astype(str)

outer["ward_id"] = range(10_001, 10_001 + len(outer))
outer["ward_no"] = outer["ward_id"]
outer["zone_no"] = 900
outer["zone_name"] = "OUTSIDE GCC"
outer["region"] = "Metro"
outer["unit_kind"] = "h3_r7"

keep = ["ward_id", "ward_no", "zone_no", "zone_name", "region",
        "unit_kind", "unit_name", "geometry"]
units = pd.concat([gcc[keep], outer[keep]], ignore_index=True)
units = gpd.GeoDataFrame(units, geometry="geometry", crs="EPSG:4326")
units.to_parquet("data/interim/wards.parquet")

zones = units.dissolve("zone_no", as_index=False)[["zone_no", "zone_name", "region", "geometry"]]
zones.to_parquet("data/interim/zones.parquet")

report = {
    "gcc_wards": int((units["unit_kind"] == "gcc_ward").sum()),
    "outer_h3_cells": int((units["unit_kind"] == "h3_r7").sum()),
    "h3_resolution": RES,
    "outer_unit_mean_km2": round(float(outer.to_crs(METRIC).area.mean()) / 1e6, 2),
    "zones": int(len(zones)),
    "named_settlements_used": int(len(pg)),
    "outer_units_named": sorted(set(outer["unit_name"]))[:40],
    "note": ("H3 cells are a reporting grid, not an administrative geography. "
             "No local body is claimed to correspond to any outer unit."),
    "seconds": round(time.time() - t0, 1),
}
json.dump(report, open("data/interim/metro_units_report.json", "w"), indent=2, sort_keys=True)
print(json.dumps(report, indent=2))
print(f"\nwrote {len(units)} units ({time.time() - t0:.1f}s)")
