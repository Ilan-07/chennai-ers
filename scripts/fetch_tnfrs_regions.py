"""Fetch the TNFRS regional station directories. Build step 02b.

ADR-001 made the GCC fire-station page the source of truth, and that was right
for a GCC-scoped study: it is the authority for the 33 stations inside the
corporation. It is the wrong authority for a metropolitan one, because the
corporation does not run the stations in Tambaram's outskirts, at Siruseri
SIPCOT or in Maraimalai Nagar -- TNFRS does, and GCC does not list them.

TNFRS publishes a station directory per REGION, each a table of station name,
TAB number, landline, CUG mobile and an email address. Two regions cover the
Chennai metropolitan area:

  * **Northern** (id 411) -- 43 stations. Already registered as
    `tnfrs_chennai_station_directory` (id 12) and used by E-11f to confirm
    station identities. Ten of its 43 are absent from the GCC list, including
    Tambaram STC, Medavakkam and Athipattu-II.
  * **North Western** (id 412) -- 58 stations across Tiruvallur, Kanchipuram,
    Chengalpattu, Vellore, Ranipet, Tiruvannamalai and Tirupattur. Only a
    handful fall inside the metro, but those few are exactly the ones the
    GCC-scoped model was missing in the south.

    python scripts/fetch_tnfrs_regions.py [--force]

Both are ingested whole and filtered downstream. Ingesting only the rows that
look relevant would bake a judgement about the study area into the raw data,
and the study area is a decision the boundary step makes, not this one.

Provenance note. These are HTML tables scraped from a government CMS, not an
API. The parser therefore refuses anything that does not look like the expected
six-column station table rather than silently registering a shorter list.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")

import requests  # noqa: E402

from ers.io.registry import DatasetRegistry  # noqa: E402

UA = "chennai-ers/0.1 (academic emergency-response siting research)"
BASE = ("https://www.tnfrs.tn.gov.in/subsubmenu_page_content.php"
        "?menu_id=NDM2&submenu_id=ODk5&thirdlvl_id={tid}&dept_id=443&lang=MQ==")

# thirdlvl_id values, base64 of the region id, as published in the site's menu.
REGIONS = {
    "northern": {"tid": "NDEx", "id": 411, "min_rows": 40,
                 "out": "data/raw/tnfrs_region_northern.json"},
    "north_western": {"tid": "NDEy", "id": 412, "min_rows": 50,
                      "out": "data/raw/tnfrs_region_north_western.json"},
}

CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def clean(html: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub("", html)).replace("\xa0", " ").strip()


def parse_stations(html: str) -> list[dict]:
    """Station rows from the directory table.

    The table repeats its header once per district block and restarts its
    numbering, so rows are identified by SHAPE -- six cells whose second is a
    station name -- rather than by position.
    """
    out: list[dict] = []
    for tr in ROW.findall(html):
        cells = [clean(c) for c in CELL.findall(tr)]
        if len(cells) < 6:
            continue
        name = cells[1]
        if not name or name.lower() in ("fire station", "fire station name"):
            continue          # a repeated header block
        if not re.search(r"\bFS\b|fire", name, re.I):
            continue
        out.append({
            "station": re.sub(r"\s+", " ", name).strip(),
            "tab": cells[2] if cells[2] != "-" else None,
            "landline": cells[3] if cells[3] != "-" else None,
            "cug": cells[4] if cells[4] != "-" else None,
            "email": cells[5] if cells[5] != "-" else None,
        })
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="re-fetch even if registered")
args = ap.parse_args()

reg = DatasetRegistry()
total = 0

for name, spec in REGIONS.items():
    out = Path(spec["out"])
    source = f"tnfrs_region_{name}"

    cached = out.exists() and not args.force
    if cached:
        try:
            reg.get(source)
        except KeyError:
            cached = False

    if cached:
        print(f"{out} already registered; use --force to re-fetch")
        stations = json.loads(out.read_text())
    else:
        url = BASE.format(tid=spec["tid"])
        print(f"fetching region {spec['id']} ({name}) ...", flush=True)
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=120)
        resp.raise_for_status()
        stations = parse_stations(resp.text)

        if len(stations) < spec["min_rows"]:
            raise SystemExit(
                f"region {spec['id']}: parsed {len(stations)} stations, expected at "
                f"least {spec['min_rows']}. The page layout has changed -- refusing to "
                f"register a truncated directory as if it were the whole region.")

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stations, indent=1, sort_keys=True))

    with_contact = sum(1 for s in stations if s["landline"] or s["cug"])
    print(f"  {len(stations)} stations | {with_contact} with a phone number")
    total += len(stations)

    reg.register(
        source=source,
        uri=BASE.format(tid=spec["tid"]),
        local_path=out,
        licence="Government of Tamil Nadu (public directory)",
        notes={"region_id": spec["id"], "region": name,
               "stations": len(stations),
               "fields": "station, tab number, landline, CUG mobile, email",
               "purpose": "authoritative station inventory beyond the GCC list",
               "caveat": "scraped from an HTML table; no coordinates are published, "
                         "so every position still needs resolution and survey"})

print(f"\n{total} stations across {len(REGIONS)} regions registered")
print("positions are NOT included -- resolve_stations.py places them, and the "
      "survey gate still applies")
