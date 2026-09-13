"""Fetch the candidate-site parcel layer. Build step 10a.

`osm_parcels_overpass.json` (registry id 6) was fetched ad hoc for the GCC bbox
and has been consumed by `build_candidates.py` ever since with no script behind
it -- the same defect class as F-20, where the station inventory was read by
eight scripts and produced by none. Extending the study area exposed it: a
metro build needs the same layer over a bigger box, and there was nothing to
re-run.

The query mirrors what the shipped layer contains, verified against it by tag
frequency: public and institutional land a station could plausibly be built on,
ranked downstream by `ers.geo.candidates._PREF_RANK`.

    python scripts/fetch_parcels.py [--out PATH] [--force]

The bbox comes from the active city profile, so the GCC and metro profiles fetch
their own extents without either overwriting the other.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")

import requests  # noqa: E402
import yaml  # noqa: E402

from ers.io.registry import DatasetRegistry  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "chennai-ers/0.1 (academic emergency-response siting research)"

QUERY = """
[out:json][timeout:300];
(
  way["amenity"~"^(school|college|university|hospital|community_centre|townhall)$"]({bbox});
  relation["amenity"~"^(school|college|university|hospital|community_centre|townhall)$"]({bbox});
  way["leisure"~"^(park|sports_centre|pitch|recreation_ground)$"]({bbox});
  relation["leisure"~"^(park|sports_centre|pitch|recreation_ground)$"]({bbox});
  way["landuse"~"^(industrial|commercial|brownfield|greenfield|recreation_ground|military)$"]({bbox});
  relation["landuse"~"^(industrial|commercial|brownfield|greenfield|recreation_ground|military)$"]({bbox});
  way["office"="government"]({bbox});
  relation["office"="government"]({bbox});
);
out geom;
"""

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="data/raw/osm_parcels_overpass.json")
ap.add_argument("--force", action="store_true")
args = ap.parse_args()

out = Path(args.out)
cfg = yaml.safe_load(open("config/city/chennai.yml"))
s, w, n, e = cfg["bbox"]
bbox = f"{s},{w},{n},{e}"

if out.exists() and not args.force:
    print(f"{out} exists; use --force to re-query")
    raise SystemExit(0)

t0 = time.time()
print(f"querying Overpass for candidate parcels over {bbox} ...", flush=True)
resp = requests.post(OVERPASS, data={"data": QUERY.format(bbox=bbox)},
                     headers={"User-Agent": UA}, timeout=600)
resp.raise_for_status()
payload = resp.json()
elements = payload.get("elements", [])
if not elements:
    raise SystemExit("Overpass returned zero parcels - refusing to register an empty "
                     "candidate layer as if it were a measurement")

classes = Counter()
for el in elements:
    tags = el.get("tags", {})
    for k in ("office", "amenity", "leisure", "landuse"):
        if k in tags:
            classes[f"{k}={tags[k]}"] += 1
            break

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=1, sort_keys=True))
print(f"\n{len(elements):,} parcels in {time.time() - t0:.0f}s")
for k, v in classes.most_common(10):
    print(f"  {v:6d}  {k}")

DatasetRegistry().register(source="osm_parcels", uri=OVERPASS, local_path=out,
                           licence="ODbL (OpenStreetMap contributors)",
                           notes={"bbox": bbox, "parcels": len(elements),
                                  "purpose": "candidate sites (build step 10)",
                                  "class_counts": dict(classes.most_common(20))})
print(f"\nregistered: {out}")
