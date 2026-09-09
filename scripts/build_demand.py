"""Build the demand surface. Build step 08."""
import json, pathlib, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, pandas as pd, yaml
from ers.geo.demand import (assign_wards, cells_for_area, landuse_risk_weights,
                            load_landuse, population_to_cells, reconcile_to_wards)

# A-07 starting values, overridable per service config.
A07_DEFAULT = {"residential": 1.0, "commercial": 1.8,
               "industrial": 3.0, "hazardous": 5.0}
from ers.io.registry import DatasetRegistry

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
res = int(cfg["demand"]["resolution"])
wards = gpd.read_parquet("data/interim/wards.parquet")

print(f"tessellating GCC at H3 r{res} ...", flush=True)
cells = cells_for_area(wards, res)
cells, jrep = assign_wards(cells, wards, cfg["crs"]["metric"])
print(f"  {len(cells):,} cells | {jrep}", flush=True)

raster = "data/raw/ghspop_chennai_2020_100m.tif"
pop, prep = population_to_cells(raster, cells, res)
cells["population_raw"] = pop
print("  " + json.dumps(prep), flush=True)

# Census 2011 ward totals are not yet loaded; reconcile to the city total by
# distributing it across wards in proportion to the modelled population. This is
# a PLACEHOLDER reconciliation -- swapped for true ward totals in build step 08b.
target_total = float(cfg["census_2011_population"]) * float(cfg["growth_factor"])
ward_model = cells.groupby("ward_id")["population_raw"].sum()
share = ward_model / ward_model.sum()
ward_targets = (share * target_total).to_dict()

cells["population"] = cells["population_raw"]
recon, rrep = reconcile_to_wards(cells, ward_targets, pop_col="population")
cells["population"] = recon
print("  " + json.dumps(rrep), flush=True)

# ---------------------------------------------------------- service surfaces
#
# Both service configs declare a `demand_surface`, and until the 2026-09 repair
# NOTHING READ THE KEY: every coverage figure, EMS and fire, was weighted by raw
# headcount. A-06 and A-07 existed as numbers in ASSUMPTIONS.md and as an
# untested-in-anger function in ers.geo.demand.
#
# An unimplementable value now RAISES rather than being ignored, so a config
# that promises a weighting the pipeline cannot deliver fails loudly.
surfaces, surface_reports = {}, {}
for svc in ("ems", "fire"):
    scfg = yaml.safe_load(open(f"config/services/{svc}.yml"))
    kind = scfg.get("demand_surface", "population")

    if kind == "population":
        surfaces[svc] = cells["population"]
        surface_reports[svc] = {"surface": "population", "status": "raw headcount"}

    elif kind == "landuse_weighted":
        # A-07. Needs the land-use layer that scripts/fetch_landuse.py fetches;
        # the candidate-site parcels layer does not carry the classes A-07 names.
        lpath = "data/raw/osm_landuse_overpass.json"
        if not pathlib.Path(lpath).exists():
            raise SystemExit(
                f"config/services/{svc}.yml asks for '{kind}' but {lpath} is absent. "
                f"Run: python scripts/fetch_landuse.py")
        parcels, lrep = load_landuse(lpath, cfg["crs"]["metric"])
        mult = scfg.get("landuse_risk_multipliers") or A07_DEFAULT
        w, wrep = landuse_risk_weights(cells, parcels, mult, cfg["crs"]["metric"])
        surfaces[svc] = w
        surface_reports[svc] = {"surface": kind, "parcels": lrep, "weighting": wrep,
                                "assumption": "A-07", "tested_by": "E-06"}
        print(f"  {svc}: {kind} | " + json.dumps(wrep), flush=True)

    elif kind == "age_weighted":
        # A-06. DATA-GATED: no registered dataset carries a ward-level 60+ share.
        # wards.parquet holds geometry and zone only, and Census 2011 age tables
        # are not machine-accessible to this project. Falling back to headcount
        # is the honest behaviour -- inventing an age surface would be worse --
        # but it is RECORDED as a gap rather than passed off as A-06 applied.
        surfaces[svc] = cells["population"]
        surface_reports[svc] = {
            "surface": "population",
            "requested": kind,
            "status": "DATA-GATED - falling back to raw headcount",
            "assumption": "A-06",
            "blocker": "no registered dataset carries ward-level 60+ population share",
            "resolves_when": "Census 2011 ward age tables (C-13/C-14) are ingested",
        }
        print(f"  {svc}: {kind} REQUESTED but data-gated; using raw headcount",
              flush=True)
    else:
        raise SystemExit(f"config/services/{svc}.yml: unknown demand_surface {kind!r}")

    cells[f"demand_{svc}"] = surfaces[svc]

cells = cells[["cell_id", "h3_index", "ward_id", "ward_no", "zone_no",
               "population_raw", "population", "demand_ems", "demand_fire",
               "geometry"]]
cells.to_parquet("data/interim/demand_cells.parquet")

report = {
    "resolution": res, "cells": len(cells),
    "join": jrep, "aggregation": prep, "reconciliation": rrep,
    "reconciliation_status": "PLACEHOLDER city-total scaling; needs Census 2011 ward totals",
    "population_total": round(float(cells["population"].sum()), 1),
    "service_surfaces": surface_reports,
    "cells_with_zero_population": int((cells["population"] <= 0).sum()),
    "seconds": round(time.time() - t0, 1),
}
json.dump(report, open("data/interim/demand_report.json", "w"), indent=2, sort_keys=True)
DatasetRegistry().register(source="ghspop_chennai_clip",
                           uri="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/",
                           local_path=raster, licence="CC-BY 4.0 (EC JRC GHSL)",
                           notes={"product": "GHS_POP_E2020_R2023A_54009_100 tile R8_C26"})
DatasetRegistry().register(source="demand_cells", uri="derived://ers.geo.demand",
                           local_path="data/interim/demand_cells.parquet", licence="derived")
print(json.dumps(report, indent=2), flush=True)
