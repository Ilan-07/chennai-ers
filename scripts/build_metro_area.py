"""Derive the built-up metro study area. Build step 04b.

Answers the question the GCC boundary cannot: which contiguous built-up Chennai
should a coverage model cover? See `ers.geo.urban` for why the boundary is
measured from GHS-POP rather than drawn or taken from an administrative file
that does not exist.

    python scripts/build_metro_area.py [--density 1500]

Writes `data/interim/metro_area.parquet` (one polygon) plus a report naming
every station, from both TNFRS regional directories, that falls inside it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from ers.geo.urban import study_area, urban_centre  # noqa: E402
from ers.io.registry import DatasetRegistry  # noqa: E402

RASTER = "data/raw/ghsl/GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C26.tif"

ap = argparse.ArgumentParser()
ap.add_argument("--density", type=float, default=None,
                help="A-16 density threshold, inhabitants/km2 "
                     "(1500 = urban centre, 300 = urban cluster). Defaults to "
                     "the city config's density_floor_per_km2, or 1500.")
ap.add_argument("--min-cluster-population", type=float, default=50_000.0,
                help="Degree of Urbanisation minimum: 50,000 for a centre, 5,000 for a cluster")
ap.add_argument("--out", default="data/interim/metro_area.parquet")
ap.add_argument("--authority", default=None,
                help="the administrative boundary to union with the urban centre "
                     "(default: gcc_wards.parquet, else wards.parquet)")
ap.add_argument("--search-bbox", nargs=4, type=float, default=[12.40, 79.80, 13.60, 80.60],
                metavar=("S", "W", "N", "E"))
args = ap.parse_args()

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]

# The density floor is what separates the metro profile from the full one, so it
# belongs to the city config rather than to a flag somebody has to remember. A
# flag still wins when given -- sweeping A-16 is the point of it being an
# assumption -- but the default comes from the profile being built.
if args.density is None:
    args.density = float(cfg.get("density_floor_per_km2", 1500.0))
    print(f"density floor {args.density:,.0f}/km2 from the city config", flush=True)

if not Path(RASTER).exists():
    raise SystemExit(f"{RASTER} is absent. Run: sh scripts/fetch_ghsl.sh")

# The AUTHORITY boundary, which the urban centre is unioned with. Prefer the
# snapshot: in a profile tree `wards.parquet` has been overwritten with the
# profile's own 287 units, and unioning the urban centre with those grows the
# study area on every rebuild (see build_metro_units.py).
_auth = Path(args.authority) if args.authority else (
    Path("data/interim/gcc_wards.parquet")
    if Path("data/interim/gcc_wards.parquet").exists()
    else Path("data/interim/wards.parquet"))
wards = gpd.read_parquet(_auth)
if "unit_kind" in wards.columns:
    raise SystemExit(
        f"{_auth} holds profile units, not the authority boundary. Unioning the "
        f"urban centre with them would grow the study area from its own output. "
        f"Pass --authority with the corporation wards.")
print(f"authority boundary: {_auth}", flush=True)

print(f"deriving the urban centre at >= {args.density:,.0f}/km2 ...", flush=True)
urban, urep = urban_centre(RASTER, tuple(args.search_bbox),
                           seed_lonlat=(80.27, 13.08),
                           density_per_km2=args.density,
                           min_cluster_population=args.min_cluster_population)
print("  " + json.dumps(urep), flush=True)

area, arep = study_area(urban, wards, METRIC)
print("  " + json.dumps(arep), flush=True)

area.to_parquet(args.out)

# ------------------------------------------------------------------ stations
#
# Which of the authoritative directories' stations actually fall inside. The
# directories publish no coordinates, so this can only be answered for stations
# already resolved; the rest are listed as needing a position. That list IS the
# work item, and naming it is more useful than a count.
resolved = pd.read_csv("data/interim/stations_resolved.csv")
rg = gpd.GeoDataFrame(resolved,
                      geometry=gpd.points_from_xy(resolved.lon, resolved.lat),
                      crs="EPSG:4326").to_crs(METRIC)
poly = area.to_crs(METRIC).geometry.iloc[0]
inside = rg.within(poly)

directories = {}
for name, path in (("northern", "data/raw/tnfrs_region_northern.json"),
                   ("north_western", "data/raw/tnfrs_region_north_western.json")):
    if Path(path).exists():
        directories[name] = json.loads(Path(path).read_text())

def norm(s: str) -> str:
    return (s.lower().replace("fs", "").replace("fire station", "")
            .replace("&nbsp;", " ").replace(".", " ").replace("-", " ").strip())

known = {norm(n) for n in resolved["station_name"]}
unplaced = {}
for region, rows in directories.items():
    unplaced[region] = sorted(r["station"].replace("&nbsp;", " ").strip()
                              for r in rows if norm(r["station"]) not in known)

report = {
    "urban_centre": urep,
    "study_area": arep,
    "stations_resolved_total": int(len(rg)),
    "stations_resolved_inside_metro": int(inside.sum()),
    "stations_resolved_outside_metro": sorted(
        rg.loc[~inside, "station_name"].tolist()),
    "directory_stations_without_a_position": unplaced,
    "directory_counts": {k: len(v) for k, v in directories.items()},
    "seconds": round(time.time() - t0, 1),
}
json.dump(report, open(args.out.replace(".parquet", "_report.json"), "w"),
          indent=2, sort_keys=True)

DatasetRegistry().register(source="metro_study_area", uri="derived://ers.geo.urban",
                           local_path=args.out,
                           licence="derived",
                           notes={"method": urep["method"],
                                  "density_threshold_per_km2": args.density,
                                  "km2": arep["study_area_km2"]})

print(f"\nstudy area {arep['study_area_km2']:,} km2 "
      f"(GCC {arep['authority_km2']:,}, urban centre {arep['urban_centre_km2']:,})")
print(f"resolved stations inside: {report['stations_resolved_inside_metro']} of {len(rg)}")
for region, names in unplaced.items():
    print(f"{region}: {len(names)} directory stations have no position yet")
print(f"\nwrote data/interim/metro_area.parquet ({time.time() - t0:.1f}s)")
