"""Build the station inventory. Build steps 02-03, plus the E-11c adoption.

Written during the 2026-09 repair. `stations_resolved.csv` -- the single most
load-bearing input in the project, read by `ers.pipeline` and eight scripts --
was produced by no script at all. `ers.io.stations.resolve()` was registered as
its provenance and called only from the test suite; the Google Maps positions
were merged in by hand. The file had drifted from its own registry checksum
(6866 bytes registered, 6423 on disk), which is precisely the condition
ASSUMPTIONS.md forbids:

    No number appears in any output unless it was produced by a run ID that can
    be replayed.  (Finding F-02)

Deterministic and network-free by construction. The 4 OSM-corroborated stations
come from the registered Overpass response; the other 29 come from the E-11c
lookup, which already encodes every tie-break that has been settled. Nominatim
is NOT called: its positions were falsified by E-11c (16 of 29 outside their own
stated uncertainty, max error 25.5 km) and nothing downstream uses them any more.

    python scripts/resolve_stations.py [--check]

`--check` resolves and diffs against the file on disk without writing, which is
the acceptance test for this script and is what `make verify` runs.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict

sys.path.insert(0, "src")

import yaml  # noqa: E402

from ers.hashing import run_id  # noqa: E402
from ers.io.registry import DatasetRegistry  # noqa: E402
from ers.io.stations import (ResolvedStation, adopt_gmaps_lookup,  # noqa: E402
                             qa_report, resolve)
from ers.provenance import stamp  # noqa: E402

AUTH = "data/reference/tnfrs_stations_gcc.csv"
# ADR-001a: TNFRS operates the stations, the corporation publishes a page about
# them, and the page is missing six that exist. The operator's own regional
# directory is the authority on EXISTENCE; E-11 remains the authority on
# POSITION, so each of the six arrives with the evidence that placed it.
SUPP = "data/reference/tnfrs_gcc_supplementary.csv"
OSM = "data/raw/osm_stations_overpass.json"
LOOKUP = "data/interim/stations_gmaps_lookup.csv"
OUT = "data/interim/stations_resolved.csv"
QA = "data/interim/stations_qa.json"
REPORT = "data/interim/stations_report.json"

ap = argparse.ArgumentParser()
ap.add_argument("--check", action="store_true",
                help="resolve and diff against the file on disk; write nothing")
args = ap.parse_args()

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
bbox = tuple(cfg["bbox"])

reg = DatasetRegistry()
auth_ds = reg.get("gcc_fire_stations")
osm_ds = reg.get("osm_stations_overpass")

# use_nominatim=False: the 29 provisional geocodes it used to produce are all
# superseded by the lookup below, so querying for them would add a network
# dependency and a source of non-determinism for values nothing consumes.
rows = resolve(AUTH, OSM, bbox, use_nominatim=False)

with open(LOOKUP, newline="") as fh:
    lookup = list(csv.DictReader(fh))
rows, adoption = adopt_gmaps_lookup(rows, lookup)

supp_added = []
with open(SUPP, newline="") as fh:
    known = {r.station_name.lower() for r in rows}
    for row in csv.DictReader(fh):
        if row["station_name"].lower() in known:
            continue
        rows.append(ResolvedStation(
            station_name=row["station_name"], division=row["division"], service="fire",
            lat=float(row["lat"]), lon=float(row["lon"]),
            geocode_confidence=row["evidence"],
            match_source=row["source"], match_detail=row["note"],
            # 60 m for an OSM fire feature (the E-11e residual), 50 m for a single
            # unambiguous map listing (the E-11c adoption). Neither is a survey.
            uncertainty_m=60 if row["evidence"] == "osm_fire_feature" else 50,
            survey_required=True, osm_class=None, osm_type=None,
            plausibility="ok", identity_confirmed_by=None))
        supp_added.append(row["station_name"])

unresolved = [r.station_name for r in rows if r.lat is None]
if unresolved:
    raise SystemExit(f"UNRESOLVED after adoption: {unresolved}")

gate = qa_report(rows)
fields = list(asdict(rows[0]))

print(f"stations       : {len(rows)}  (GCC page {len(rows) - len(supp_added)} "
      f"+ TNFRS-only {len(supp_added)})")
if supp_added:
    print(f"TNFRS-only     : {', '.join(supp_added)}")
print(f"adopted (gmaps): {adoption['adopted']}")
print(f"kept (osm)     : {len(adoption['kept_osm_positions'])}")
print(f"identity conf. : {len(adoption['identity_confirmed'])} of 29 (A-15 records 14)")
print(f"plausibility   : {json.dumps(adoption['by_plausibility'])}")
print(f"confidence     : {json.dumps(gate['by_confidence'])}")

if adoption["moved_from_previous"]:
    print("\nmoved from the previous provisional positions:")
    for m in adoption["moved_from_previous"][:5]:
        print(f"  {m['station']:16s} {m['moved_m']:>7} m")

if args.check:
    with open(OUT, newline="") as fh:
        on_disk = list(csv.DictReader(fh))
    fresh = [{k: ("" if v is None else str(v)) for k, v in asdict(r).items()} for r in rows]
    diffs = []
    for a, b in zip(sorted(on_disk, key=lambda r: r["station_name"]),
                    sorted(fresh, key=lambda r: r["station_name"])):
        for k in b:
            if k in a and str(a[k]) != str(b[k]):
                diffs.append(f"{b['station_name']:16s} {k:22s} disk={a[k]!r} fresh={b[k]!r}")
    print(f"\n--check: {len(diffs)} field difference(s) against {OUT}")
    for d in diffs:
        print("  " + d)
    raise SystemExit(1 if diffs else 0)

with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(asdict(r))

resolved_ds = reg.register(
    source="stations_resolved", uri="derived://scripts/resolve_stations.py",
    local_path=OUT, licence="derived",
    notes={"stations": len(rows), "adopted_google_maps_poi": adoption["adopted"],
           "identity_confirmed": len(adoption["identity_confirmed"])})

# stations_qa is itself station-dependent -- it went stale in 2026-09 precisely
# because it recorded nothing about the inventory it described.
import pandas as pd  # noqa: E402
qa_out = {**gate, **stamp(config=cfg, inputs=[auth_ds.sha256, osm_ds.sha256],
                          stations=pd.read_csv(OUT))}
json.dump(qa_out, open(QA, "w"), indent=2, sort_keys=True)

report = {
    "run_id": run_id(inputs=[auth_ds.sha256, osm_ds.sha256], config=cfg, seed=None,
                     extra={"step": "02-03-stations", "lookup": LOOKUP}),
    "inputs": {"gcc_fire_stations": auth_ds.id, "osm_stations_overpass": osm_ds.id},
    "output_registry_id": resolved_ds.id,
    "adoption": adoption,
    "gate": gate,
    "seconds": round(time.time() - t0, 1),
}
json.dump(report, open(REPORT, "w"), indent=2, sort_keys=True)

state = "PASS" if gate["passes_publish_gate"] else "BLOCKED"
print(f"\nwrote {OUT} and {QA}  ({time.time() - t0:.1f}s)")
print(f"PUBLISH GATE: {state} - {len(gate['survey_required'])} station(s) still provisional")
