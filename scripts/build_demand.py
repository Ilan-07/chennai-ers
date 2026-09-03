"""Build the demand surface. Build step 08."""
import json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, pandas as pd, yaml
from ers.geo.demand import (assign_wards, cells_for_area, population_to_cells,
                            reconcile_to_wards)
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

cells = cells[["cell_id", "h3_index", "ward_id", "ward_no", "zone_no",
               "population_raw", "population", "geometry"]]
cells.to_parquet("data/interim/demand_cells.parquet")

report = {
    "resolution": res, "cells": len(cells),
    "join": jrep, "aggregation": prep, "reconciliation": rrep,
    "reconciliation_status": "PLACEHOLDER city-total scaling; needs Census 2011 ward totals",
    "population_total": round(float(cells["population"].sum()), 1),
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
