"""Select the stations a profile's study area is served by. Build step 03c.

`resolve_metro_stations.py` places every station in the two TNFRS regional
directories and flags which fall inside the METRO study area. A profile build
needs the same question answered against ITS OWN boundary, because the full
settlement reaches 650 km2 further than the metro does and a station outside one
is not outside the other.

This was previously done by hand, once, and then not redone -- so the metro
profile kept a station table produced before ADR-001a and before the map-listing
lookups were wired in, and carried a station on a 2,000 m town centroid that had
a 50 m position sitting in a file next to it.

A station just OUTSIDE the boundary still covers into it, so the test is the
study area buffered by `--keep-buffer-m`, matching the resolver's own rule.

  python scripts/project_stations_to_profile.py --area data/interim/metro_area.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--stations", default="data/interim/stations_metro.csv")
ap.add_argument("--area", required=True, help="the profile's study-area parquet")
ap.add_argument("--out", default="data/interim/stations_resolved.csv")
ap.add_argument("--keep-buffer-m", type=float, default=3000.0,
                help="a station this far outside the boundary still covers into it")
args = ap.parse_args()

cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]

src = Path(args.stations)
if not src.exists():
    raise SystemExit(f"{src} absent. Run: python scripts/resolve_metro_stations.py")

st = pd.read_csv(src)
area = gpd.read_parquet(args.area).to_crs(METRIC).union_all()
keep = area.buffer(args.keep_buffer_m)

pts = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat),
                       crs="EPSG:4326").to_crs(METRIC)
inside = pts.geometry.within(keep)
sel = st[inside.to_numpy()].copy()

# The columns the rest of the pipeline reads. `position_source` is the resolver's
# vocabulary; downstream expects `match_source`/`geocode_confidence`, and
# `survey_required` is TRUE for everything here -- none of these are surveyed.
out = pd.DataFrame({
    "station_name": sel["station_name"],
    "division": sel["division"],
    "service": sel["service"],
    "lat": sel["lat"],
    "lon": sel["lon"],
    "geocode_confidence": sel["geocode_confidence"],
    "match_source": sel["position_source"],
    "match_detail": sel["match_detail"],
    "uncertainty_m": sel["uncertainty_m"].fillna(50.0),
    "survey_required": True,
    "osm_class": None, "osm_type": None,
    "plausibility": "ok",
    "identity_confirmed_by": sel["identity_confirmed_by"],
})
out = out.sort_values("station_name").reset_index(drop=True)
Path(args.out).parent.mkdir(parents=True, exist_ok=True)
out.to_csv(args.out, index=False)

by_source = out["match_source"].value_counts().to_dict()
print(f"{len(out)} stations serve {args.area} "
      f"(study area + {args.keep_buffer_m:,.0f} m)")
for k, v in sorted(by_source.items()):
    unc = out.loc[out["match_source"] == k, "uncertainty_m"].max()
    print(f"  {k:18s} {v:3d}  (worst uncertainty {unc:,.0f} m)")
print(f"wrote {args.out}")
