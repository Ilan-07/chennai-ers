"""Fetch the Census 2011 ward populations and the ward geography they are counted on.
Build step 08a.

`build_demand.py` reconciled the modelled surface to a CITY total distributed
across wards in proportion to the model itself -- which is not a reconciliation
at all. Every ward received the identical scale factor (1.0554 in the run this
replaces), so the census contributed the magnitude and nothing else: the
within-city distribution was GHS-POP's opinion alone, and the report said so in
the word PLACEHOLDER.

Fixing it needs ward totals from the census. The obstacle is that they do not
exist for the wards this project uses:

  * The 2022 GCC map (registry id 14) has **200 wards over 426 km2**.
  * Census 2011 was enumerated on the **155 wards over 174 km2** that the
    corporation had before the expansion that same year, when 42 local bodies
    were merged in. The expansion areas were counted as separate towns and
    villages in other districts.

So there is no ward-wise Census 2011 table for the 200 wards, and there cannot
be one. What exists is the 155-ward enumeration-block table, plus the 155-ward
geography those blocks were counted on -- and with both, the totals can be put
back on the map and re-cut to the 2022 wards. That is build step 08b; this
script ingests its two inputs.

    python scripts/fetch_census_wards.py [--force]

Cached, like every other fetch here: registered and byte-identical means no
re-download.

Provenance note. Neither file is from censusindia.gov.in directly. The ward-EB
table is OpenCity's transcription of the Chennai PCA; the 2008 ward geometry
comes from Transparent Chennai via DataMeet, digitised from a CMDA master-plan
sheet rather than surveyed. Both are recorded with that basis in the registry,
and ADR-007 states what the vintage mismatch costs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

from ers.io.registry import DatasetRegistry  # noqa: E402

UA = "chennai-ers/0.1 (academic emergency-response siting research)"

EB_URI = ("https://data.opencity.in/dataset/db288d43-56e3-48f4-9932-710d80872155/"
          "resource/14e58af6-7ed9-4445-bb47-acc931364c12/download/"
          "af83d302-a504-479a-8be9-b3208eb5b6e7.csv")
EB_OUT = Path("data/raw/census2011_chennai_ward_eb.csv")

WARDS_URI = ("https://raw.githubusercontent.com/datameet/Municipal_Spatial_Data/"
             "master/Chennai/Wards-2008.geojson")
WARDS_OUT = Path("data/raw/chennai_wards_2008.geojson")

EXPECTED_WARDS = 155


def fetch(uri: str, out: Path) -> None:
    resp = requests.get(uri, headers={"User-Agent": UA}, timeout=300)
    resp.raise_for_status()      # a 404 page must not be registered as data
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(resp.content)


ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="re-download even if registered")
args = ap.parse_args()

reg = DatasetRegistry()


def cached(source: str, out: Path) -> bool:
    if args.force or not out.exists():
        return False
    try:
        reg.get(source)
    except KeyError:
        return False
    return True


# ------------------------------------------------- the enumeration-block table
if cached("census2011_chennai_ward_eb", EB_OUT):
    print(f"{EB_OUT} already registered; use --force to re-download")
else:
    print(f"fetching {EB_URI} ...", flush=True)
    fetch(EB_URI, EB_OUT)

eb = pd.read_csv(EB_OUT)
missing = {"Ward Number", "Total Population"} - set(eb.columns)
if missing:
    raise SystemExit(f"{EB_OUT}: expected columns are absent: {sorted(missing)}")

by_ward = eb.groupby("Ward Number")["Total Population"].sum()
if len(by_ward) != EXPECTED_WARDS:
    raise SystemExit(f"{EB_OUT}: {len(by_ward)} wards, expected {EXPECTED_WARDS} -- "
                     f"this is not the pre-expansion Chennai (M Corp.) table")

eb_total = int(by_ward.sum())
print(f"  {len(eb):,} enumeration blocks | {len(by_ward)} wards | "
      f"{eb_total:,} residents")

reg.register(
    source="census2011_chennai_ward_eb",
    uri=EB_URI,
    local_path=EB_OUT,
    licence="Public Domain (OpenCity; transcribed from Census of India 2011 PCA)",
    notes={"geography": "Chennai (M Corp.) 155 pre-expansion wards, 174 km2",
           "location_code": "803339",
           "enumeration_blocks": int(len(eb)),
           "wards": int(len(by_ward)),
           "population": eb_total,
           "purpose": "A-04 ward-total reconciliation (build step 08b)",
           "caveat": "third-party transcription, not a censusindia.gov.in download; "
                     "the sum is 0.6% below the published town total of 4,646,732"})

# ------------------------------------------------------- the 2008 ward polygons
if cached("chennai_wards_2008", WARDS_OUT):
    print(f"{WARDS_OUT} already registered; use --force to re-download")
else:
    print(f"fetching {WARDS_URI} ...", flush=True)
    fetch(WARDS_URI, WARDS_OUT)

w08 = gpd.read_file(WARDS_OUT)
if len(w08) != EXPECTED_WARDS:
    raise SystemExit(f"{WARDS_OUT}: {len(w08)} polygons, expected {EXPECTED_WARDS}")
if "ward" not in w08.columns:
    raise SystemExit(f"{WARDS_OUT}: no 'ward' column; columns are {list(w08.columns)}")

area_km2 = round(float(w08.to_crs("EPSG:32644").area.sum()) / 1e6, 1)
print(f"  {len(w08)} ward polygons | {area_km2} km2 | "
      f"wards {int(w08['ward'].min())}-{int(w08['ward'].max())}")

covered = set(int(x) for x in w08["ward"])
counted = set(int(x) for x in by_ward.index)
if covered != counted:
    raise SystemExit(f"ward numbering disagrees: {sorted(counted - covered)[:5]} counted "
                     f"but not mapped, {sorted(covered - counted)[:5]} mapped but not counted")
print("  ward numbering matches the enumeration-block table")

reg.register(
    source="chennai_wards_2008",
    uri=WARDS_URI,
    local_path=WARDS_OUT,
    licence="CC BY-SA 2.5 IN (Transparent Chennai via DataMeet)",
    notes={"geography": "Chennai Corporation electoral wards, 2008 delimitation",
           "wards": int(len(w08)),
           "area_km2": area_km2,
           "purpose": "carrier geography for the Census 2011 ward totals (build step 08b)",
           "caveat": "digitised from a CMDA master-plan sheet, not a survey product; "
                     "boundary error is absorbed by the dasymetric weighting"})

print("\nboth inputs registered; build step 08b can run")
