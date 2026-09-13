"""Which flood scenarios each study area may honestly be asked. Build step 12b.

The metro and full profiles offered only dry and peak, and the console explained
that with a sentence somebody typed: "the inundation layers stop at the
corporation boundary". That sentence was true, but nothing measured it and
nothing would have noticed if it stopped being true -- a new flood layer covering
Tambaram would have changed nothing, because the refusal was hard-coded.

This measures it instead. For every scenario and every profile it reports how
much of the study area the layer can speak for, and whether the scenario is
therefore applicable. The console reads the result rather than a sentence.

  python scripts/flood_extent_report.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import geopandas as gpd  # noqa: E402
import yaml  # noqa: E402

from ers.flood import scenario_extent_coverage  # noqa: E402
from ers.publish import publication_basis  # noqa: E402
from ers.scenario import load_scenarios  # noqa: E402

OUT = Path("data/interim/flood_extent.json")

# Each profile's extent, from the artefact that defines it.
#
# The corporation is the authority SNAPSHOT where one exists, not wards.parquet:
# inside a profile tree that file has been overwritten with the profile's own
# reporting units, and reading it here would report a "gcc" extent of whatever
# the profile covers (F-33).
_GCC = ("data/interim/gcc_wards.parquet"
        if Path("data/interim/gcc_wards.parquet").exists()
        else "data/interim/wards.parquet")


def _areas(cfg: dict) -> dict[str, str]:
    """Which profiles this working tree can honestly speak for.

    In the repo root all three area files are the profiles they are named after.
    Inside a PROFILE TREE they are not: the full profile's tree carries a
    `metro_area.parquet` that holds the old full boundary, because the manual
    build wrote every profile's area under the metro's filename (F-33). Reporting
    it as "metro" would publish a 1,581 km2 metro that has never existed.

    So a profile tree reports exactly two things: the corporation, from the
    authority snapshot, and the profile it is building, from its own config.
    """
    here = cfg.get("interim_subdir")
    if here:
        return {"gcc": _GCC, here: cfg.get("study_area",
                                           f"data/interim/{here}_area.parquet")}
    return {"gcc": _GCC,
            "metro": "data/interim/metro_area.parquet",
            "full": "data/interim/full_area.parquet"}

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]
scenarios = load_scenarios(sorted(Path("config/scenarios").glob("*.yml")))
AREAS = _areas(cfg)

profiles = {}
for name, path in AREAS.items():
    p = Path(path)
    if not p.exists():
        print(f"{name:6s} SKIP  {path} not built")
        continue
    area = gpd.read_parquet(p).to_crs(METRIC).union_all()
    rows = [scenario_extent_coverage(s, area, METRIC, profile=name)
            for s in scenarios]
    floods = [r for r in rows if r["network_state"] == "flood"]
    profiles[name] = {
        "study_area_km2": round(area.area / 1e6, 1),
        "scenarios": {r["scenario"]: r for r in rows},
        "applicable": sorted(r["scenario"] for r in rows if r["applicable"]),
        "refused": sorted(r["scenario"] for r in floods if not r["applicable"]),
    }
    print(f"\n{name} ({profiles[name]['study_area_km2']:,.0f} km²)")
    for r in floods:
        mark = "ok    " if r["applicable"] else "REFUSE"
        print(f"  {mark} {r['scenario']:9s} {r['test']:22s} domain "
              f"{r['modelling_domain_km2']:6,.0f} km² covers "
              f"{100 * r['domain_covers_study_area']:5.1f}% of the area")

report = {**publication_basis(),
          "profiles": profiles,
          "note": ("A flood scenario is applicable to a study area only if its "
                   "layer extends beyond that area. A layer wholly contained in "
                   "the area cannot distinguish 'dry' from 'not modelled', and "
                   "reporting the second as the first understates flood impact "
                   "exactly where the study area was widened."),
          "seconds": round(time.time() - t0, 1)}
OUT.write_text(json.dumps(report, indent=2, sort_keys=True))
print(f"\nwrote {OUT}  ({report['seconds']}s)")
