"""Build the demand surface. Build step 08.

`--landuse-scale` exists so E-06 can sweep A-07's fire risk multipliers without
editing `config/services/fire.yml`. It scales each multiplier's DEVIATION from
1.0, so 0.0 is pure headcount, 1.0 is the shipped table and 2.0 doubles the
spread between a residential block and a fuel depot.
"""
import argparse, json, pathlib, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, pandas as pd, yaml
from ers.geo.census import census_ward_targets, ward_population_2011
from ers.geo.demand import (assign_wards, cells_for_area, landuse_risk_weights,
                            load_landuse, population_to_cells, reconcile_to_wards)

# A-07 starting values, overridable per service config.
A07_DEFAULT = {"residential": 1.0, "commercial": 1.8,
               "industrial": 3.0, "hazardous": 5.0}
from ers.io.registry import DatasetRegistry

_ap = argparse.ArgumentParser()
_ap.add_argument("--landuse-scale", type=float, default=1.0,
                 help="scale A-07 multiplier deviations from 1.0 (E-06 sweep)")
_ap.add_argument("--quiet", action="store_true")
_args = _ap.parse_args()

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

# Build step 08b: reconcile to Census 2011 ward totals, re-cut from the 155
# pre-expansion wards they were counted on onto the 200 wards this project maps.
# See ers.geo.census and ADR-007. Until 2026-09 this was a PLACEHOLDER that
# distributed the city total in proportion to the model, which gave every ward
# the same scale factor and reconciled nothing but the magnitude.
eb_csv = "data/raw/census2011_chennai_ward_eb.csv"
w08_path = "data/raw/chennai_wards_2008.geojson"
for p in (eb_csv, w08_path):
    if not pathlib.Path(p).exists():
        raise SystemExit(f"{p} is absent. Run: python scripts/fetch_census_wards.py")

growth = float(cfg["growth_factor"])
ward_pop_2008 = ward_population_2011(eb_csv)
wards_2008 = gpd.read_file(w08_path)

# A metro profile reaches past the corporation, and the census reconciliation
# cannot follow it: the 155-ward Census 2011 table covers the pre-expansion GCC,
# and no ward-level table exists for Tambaram, Avadi or Chengalpattu district.
# Reconciling the WHOLE metro to the GCC's 6.75 M would be worse than not
# reconciling at all -- it would delete the 3 M people who live outside the
# corporation. So the re-cut is applied to the cells inside the corporation and
# the rest keep GHS-POP as modelled, reported as unreconciled.
metro = "urban_centre_population_2020" in cfg
if metro:
    gcc_only = cells[cells["ward_id"] < 10_000].copy()
    targets_2011, crep = census_ward_targets(
        gcc_only, wards_2008, ward_pop_2008,
        city_total=float(cfg["census_2011_population"]),
        metric_crs=cfg["crs"]["metric"])
    outside = cells[cells["ward_id"] >= 10_000]
    crep["profile"] = "metro"
    crep["reconciled_units"] = int(gcc_only["ward_id"].nunique())
    crep["unreconciled_units"] = int(outside["ward_id"].nunique())
    crep["unreconciled_population_ghspop"] = round(float(outside["population_raw"].sum()), 1)
    crep["note"] = ("outside the GCC there is no ward-level census; those cells keep "
                    "GHS-POP unreconciled and are excluded from the re-cut")
else:
    targets_2011, crep = census_ward_targets(
        cells, wards_2008, ward_pop_2008,
        city_total=float(cfg["census_2011_population"]),
        metric_crs=cfg["crs"]["metric"])
print("  " + json.dumps(crep), flush=True)

# A-05 applies here and nowhere else: the growth factor scales the 2011 census
# basis to the modelling year. E-10's growth arm shows it moves every absolute
# count and no coverage share.
ward_targets = {w: p * growth for w, p in targets_2011.items()}

cells["population"] = cells["population_raw"]
if metro:
    # Reconcile the corporation's cells only; everything else keeps its modelled
    # population, so the metro total is GHS-POP's 10.8 M rather than the GCC's.
    inside = cells["ward_id"] < 10_000
    part = cells[inside].copy()
    recon, rrep = reconcile_to_wards(part, ward_targets, pop_col="population")
    cells.loc[inside, "population"] = recon.to_numpy()
    rrep["applies_to"] = "GCC wards only"
    rrep["population_left_unreconciled"] = round(
        float(cells.loc[~inside, "population"].sum()), 1)
else:
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
        if _args.landuse_scale != 1.0:
            mult = {k: 1.0 + _args.landuse_scale * (v - 1.0) for k, v in mult.items()}
        w, wrep = landuse_risk_weights(cells, parcels, mult, cfg["crs"]["metric"])
        surfaces[svc] = w
        surface_reports[svc] = {"surface": kind, "parcels": lrep, "weighting": wrep,
                                "assumption": "A-07", "tested_by": "E-06",
                                "landuse_scale": _args.landuse_scale}
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
    "reconciliation_status": (
        f"Census 2011 ward totals, re-cut from the 155 pre-expansion wards "
        f"({crep['census_population']:,.0f} residents) onto the 200 mapped wards; "
        f"the {crep['residual_share_of_city']:.0%} of the city inside the 2011 "
        f"expansion area has no ward-level census and takes the residual "
        f"model-proportionally (ADR-007)"),
    "census_recut": crep,
    "growth_factor": growth,
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
# Both census inputs are registered by scripts/fetch_census_wards.py, which is
# where they are fetched. Re-registering here is a no-op on a byte-identical
# file and keeps a build that ingested them from claiming inputs it never read.
DatasetRegistry().register(
    source="census2011_chennai_ward_eb", uri=eb_csv, local_path=eb_csv,
    licence="Public Domain (OpenCity; transcribed from Census of India 2011 PCA)")
DatasetRegistry().register(
    source="chennai_wards_2008", uri=w08_path, local_path=w08_path,
    licence="CC BY-SA 2.5 IN (Transparent Chennai via DataMeet)")
if not _args.quiet:
    print(json.dumps(report, indent=2), flush=True)
