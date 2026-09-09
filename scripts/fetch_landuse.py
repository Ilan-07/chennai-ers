"""Fetch the land-use surface that A-07 needs. Build step 05b.

A-07 assigns fire risk multipliers by land use -- residential 1.0, commercial
1.8, industrial 3.0, hazardous 5.0 -- and `ers.geo.demand.service_weights()` has
existed and been unit tested since step 05 to apply them. It was called by
nothing, and it could not have worked if it had been: the registered parcels
layer (`osm_parcels_overpass.json`, registry id 6) was fetched to find CANDIDATE
SITES, so it queries schools, parks, industrial estates and government offices.
It contains no residential class, no commercial class and no hazardous class --
three of A-07's four categories.

So the reason `demand_surface: landuse_weighted` in `config/services/fire.yml`
was ignored is not only that nothing read the key. The data to honour it was
never fetched. This script fetches it.

    python scripts/fetch_landuse.py [--force]

Cached: it will not re-query Overpass if the file is already registered, because
a public API should not be hit to re-derive a byte-identical answer.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import requests  # noqa: E402
import yaml  # noqa: E402

from ers.io.registry import DatasetRegistry  # noqa: E402

OVERPASS = "https://overpass-api.de/api/interpreter"
OUT = Path("data/raw/osm_landuse_overpass.json")
UA = "chennai-ers/0.1 (academic emergency-response siting research)"

# A-07's four categories, in OSM terms. `hazardous` is deliberately narrow:
# fuel stations, storage tanks and chemical works are the land uses that turn a
# fire into a different KIND of incident, and a 5.0 multiplier on a mis-tagged
# polygon would be the single most influential error in the demand surface.
QUERY = """
[out:json][timeout:180];
(
  way["landuse"~"^(residential|commercial|retail|industrial)$"]({bbox});
  relation["landuse"~"^(residential|commercial|retail|industrial)$"]({bbox});
  way["man_made"="storage_tank"]({bbox});
  way["amenity"="fuel"]({bbox});
  way["landuse"="depot"]({bbox});
  way["industrial"="chemical"]({bbox});
);
out geom;
"""

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="re-query even if registered")
args = ap.parse_args()

cfg = yaml.safe_load(open("config/city/chennai.yml"))
s, w, n, e = cfg["bbox"]
bbox = f"{s},{w},{n},{e}"

reg = DatasetRegistry()
try:
    existing = reg.get("osm_landuse")
    if OUT.exists() and not args.force:
        print(f"already registered as id {existing.id}; use --force to re-query")
        raise SystemExit(0)
except KeyError:
    pass

t0 = time.time()
print(f"querying Overpass over {bbox} ...", flush=True)
resp = requests.post(OVERPASS, data={"data": QUERY.format(bbox=bbox)},
                     headers={"User-Agent": UA}, timeout=300)
resp.raise_for_status()          # a transport error must not look like "no data"
payload = resp.json()

elements = payload.get("elements", [])
if not elements:
    raise SystemExit("Overpass returned zero elements - refusing to register an "
                     "empty land-use layer as if it were a measurement")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, indent=1, sort_keys=True))

from collections import Counter  # noqa: E402
classes = Counter()
for el in elements:
    tags = el.get("tags", {})
    for k in ("landuse", "man_made", "amenity", "industrial"):
        if k in tags:
            classes[f"{k}={tags[k]}"] += 1
            break

print(f"\n{len(elements)} features in {time.time() - t0:.0f}s")
for k, v in classes.most_common():
    print(f"  {v:6d}  {k}")

ds = reg.register(source="osm_landuse", uri=OVERPASS, local_path=OUT,
                  licence="ODbL (OpenStreetMap contributors)",
                  notes={"query": "landuse residential|commercial|retail|industrial "
                                  "+ storage_tank + fuel + depot + chemical",
                         "purpose": "A-07 fire land-use risk multipliers",
                         "features": len(elements),
                         "class_counts": dict(classes)})
print(f"\nregistered as id {ds.id}: {OUT}")
