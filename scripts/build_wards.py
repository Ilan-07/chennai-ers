"""Ward and zone boundaries. Build step 04.

Written during the 2026-09 repair. `ers.geo.wards` had existed and been unit
tested since step 04, but NO script called it: `wards.parquet` and
`zones.parquet` were produced by hand, appeared in no registry entry, and
therefore carried no source, no licence and no checksum -- while every equity
result in the project is grouped by them.

That is the same defect class as F-13 (an artefact nothing produces) and F-02
(a number that cannot be replayed), on the geometry the ward floor is measured
against.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "src")

import yaml  # noqa: E402

from ers.geo.wards import assign_zones, load_wards, load_zones, validate  # noqa: E402
from ers.hashing import run_id  # noqa: E402
from ers.io.registry import DatasetRegistry  # noqa: E402

WARD_KML = "data/raw/Chennai_GCC_Ward_Map_2022.kml"
ZONE_KML = "data/raw/Chennai_GCC_Zones_Map_2022.kml"
# The GCC ArcGIS REST endpoint returned HTTP 500 at build time; the OpenCity
# CKAN mirror is the documented fallback, recorded here rather than in a comment.
SOURCE_URI = "https://data.opencity.in/dataset/chennai-ward-map"

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))

reg = DatasetRegistry()
ward_ds = reg.register(source="gcc_ward_map_2022", uri=SOURCE_URI, local_path=WARD_KML,
                       licence="Greater Chennai Corporation / OpenCity mirror",
                       notes={"note": "ward boundaries, 2022 delimitation"})
zone_ds = reg.register(source="gcc_zone_map_2022", uri=SOURCE_URI, local_path=ZONE_KML,
                       licence="Greater Chennai Corporation / OpenCity mirror",
                       notes={"note": "15 zone boundaries, 2022 delimitation"})

wards, wrep = load_wards(WARD_KML)
zones, zrep = load_zones(ZONE_KML)
wards, arep = assign_zones(wards, zones, cfg["crs"]["metric"])
checks = validate(wards, cfg)

print("wards: " + json.dumps(wrep))
print("zones: " + json.dumps(zrep))
print("zone assignment: " + json.dumps(arep))
print("gate: " + json.dumps(checks, indent=2))

if not checks["passes"]:
    # A boundary set that fails its own area or count check is not a detail to
    # be carried downstream: every ward-level equity figure would inherit it.
    raise SystemExit("STEP 04 GATE FAILED - boundaries not written")

wards.to_parquet("data/interim/wards.parquet")
zones.to_parquet("data/interim/zones.parquet")

report = {
    "run_id": run_id(inputs=[ward_ds.sha256, zone_ds.sha256], config=cfg,
                     seed=None, extra={"step": "04-wards"}),
    "inputs": {"gcc_ward_map_2022": ward_ds.id, "gcc_zone_map_2022": zone_ds.id},
    "wards": wrep,
    "zones": zrep,
    "zone_assignment": arep,
    "gate": checks,
    "seconds": round(time.time() - t0, 1),
}
json.dump(report, open("data/interim/wards_report.json", "w"), indent=2, sort_keys=True)
print(f"\nwrote wards.parquet, zones.parquet ({time.time() - t0:.1f}s)")
