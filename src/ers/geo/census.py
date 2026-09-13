"""Census 2011 ward totals, re-cut to the 2022 wards. Build step 08b.

The reconciliation this replaces distributed the city total across wards in
proportion to the modelled population, which gives every ward the same scale
factor and leaves the within-city distribution entirely to GHS-POP. Real ward
totals are what make the reconciliation pycnophylactic in the sense
`ers.geo.demand.reconcile_to_wards` documents: the model keeps the WITHIN-ward
shape, the census fixes the ward MAGNITUDE.

The complication is that the census does not count on the wards this project
models. Census 2011 enumerated the 155 wards of the 174 km2 pre-expansion
corporation; the project maps the 200 wards of the 426 km2 corporation the same
expansion created. The two ward sets share neither numbering nor boundaries, and
no crosswalk between them is published.

The way across is areal, and it goes through the demand cells rather than
through a ward-to-ward table:

  1. Each 2008 ward's census total is spread over the H3 cells that intersect
     it, weighted by the GHS-POP mass in the intersection. This is dasymetric:
     the census says how many people the ward holds, the raster says where
     inside it they are, and the 2008 boundary only has to be right enough to
     decide which cells are in the ward at all.
  2. Cells outside the 2008 corporation -- the 42 merged local bodies, roughly
     252 km2 of the modern city -- get no census ward total, because none was
     published for them at ward level. They share the RESIDUAL: the GCC-limits
     census total minus what the 155 wards hold, distributed by raster mass.
  3. Cell values are summed back up to the 2022 wards, which is the target
     vector the reconciliation wants.

Step 2 is the honest limit of this approach and it is reported, not buried: for
the expansion area this is still model-proportional allocation, now against a
correct residual rather than against the whole city. ADR-007 records the trade.

Mass is conserved exactly: the targets sum to the city total that goes in.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd


def ward_population_2011(eb_csv: str) -> pd.Series:
    """Census 2011 population per pre-expansion ward, from the EB table.

    The published file is enumeration-block level (8,802 rows over 155 wards);
    the ward total is their sum. '-' appears in the SC/ST columns for suppressed
    counts and never in the total, so a non-numeric total is an error, not a
    zero, and is refused rather than coerced.
    """
    eb = pd.read_csv(eb_csv)
    for col in ("Ward Number", "Total Population"):
        if col not in eb.columns:
            raise ValueError(f"{eb_csv}: no {col!r} column")

    pop = pd.Series(pd.to_numeric(eb["Total Population"], errors="coerce"))
    if pop.isna().any():
        bad = int(pop.isna().sum())
        raise ValueError(f"{eb_csv}: {bad} enumeration blocks have a non-numeric "
                         f"population; refusing to treat them as zero")

    out = pop.groupby(eb["Ward Number"].astype(int)).sum().sort_index()
    out.index.name = "ward_2008"
    return out.astype("float64")


def census_ward_targets(
    cells: gpd.GeoDataFrame,
    wards_2008: gpd.GeoDataFrame,
    ward_pop_2008: pd.Series,
    city_total: float,
    metric_crs: str,
    pop_col: str = "population_raw",
    ward_col: str = "ward_id",
    ward_2008_col: str = "ward",
) -> tuple[dict[int, float], dict]:
    """Per-2022-ward census targets, on the 2011 population basis.

    Returns `{ward_id: population}` summing to `city_total`, plus a report that
    states how much of the city the census part actually covers -- because the
    difference between "reconciled to census ward totals" and "reconciled to
    census ward totals over 41% of the area" is the whole point.
    """
    if city_total <= 0:
        raise ValueError("city_total must be positive")

    cm = cells.to_crs(metric_crs)[[ "cell_id", ward_col, pop_col, "geometry"]].copy()
    wm = wards_2008.to_crs(metric_crs)[[ward_2008_col, "geometry"]].copy()
    wm[ward_2008_col] = wm[ward_2008_col].astype(int)

    counted = set(int(i) for i in ward_pop_2008.index)
    mapped = set(int(w) for w in wm[ward_2008_col])
    if mapped - counted:
        raise ValueError(f"wards with geometry but no census total: "
                         f"{sorted(mapped - counted)[:10]}")

    census_total = float(ward_pop_2008.loc[sorted(mapped)].sum())
    residual = float(city_total) - census_total
    if residual < 0:
        raise ValueError(
            f"the 155 counted wards hold {census_total:,.0f} people but the city "
            f"total is {city_total:,.0f}; the expansion area cannot hold a "
            f"negative population")

    cm["cell_area"] = cm.area
    pieces = gpd.overlay(cm, wm, how="intersection", keep_geom_type=True)

    if pieces.empty:
        raise ValueError("no demand cell intersects the 2008 ward geography; "
                         "check the CRS of both inputs")

    # Share of each cell that lies inside each old ward, and the raster mass in
    # that slice. Weighting by mass rather than by area is what keeps the
    # allocation dasymetric -- a slice of a ward that the raster says is empty
    # (water, airport, port) receives none of the ward's residents.
    pieces["frac"] = pieces.area / pieces["cell_area"]
    pieces["weight"] = pieces[pop_col] * pieces["frac"]

    per_ward = pieces.groupby(ward_2008_col)["weight"].sum()
    empty_wards = sorted(int(w) for w in per_ward.index[per_ward <= 0])

    # A 2008 ward the raster believes is empty still has residents. Fall back to
    # area within that ward; dropping it would delete real people.
    if empty_wards:
        m = pieces[ward_2008_col].isin(empty_wards)
        pieces.loc[m, "weight"] = pieces.loc[m, "frac"]
        per_ward = pieces.groupby(ward_2008_col)["weight"].sum()

    share = pieces["weight"] / pieces[ward_2008_col].map(per_ward).to_numpy()
    pieces["allocated"] = share * pieces[ward_2008_col].map(ward_pop_2008).to_numpy()

    census_part = pieces.groupby("cell_id")["allocated"].sum()

    # How much of each cell the 2008 corporation covers. Cells straddling the old
    # boundary are split: the covered part is censused, the rest joins the
    # residual pool, so no cell is forced to be wholly one or the other.
    inside = pieces.groupby("cell_id")["frac"].sum().clip(upper=1.0)

    out = cm[["cell_id", ward_col, pop_col]].copy()
    out["census_pop"] = out["cell_id"].map(census_part).fillna(0.0)
    out["inside_2008"] = out["cell_id"].map(inside).fillna(0.0)

    # The expansion area: model-proportional against the residual.
    outside_weight = out[pop_col] * (1.0 - out["inside_2008"])
    ow_total = float(outside_weight.sum())
    if residual > 0 and ow_total <= 0:
        raise ValueError("the expansion area holds no modelled population, so the "
                         f"residual of {residual:,.0f} cannot be placed")
    out["residual_pop"] = (residual * outside_weight / ow_total) if ow_total > 0 else 0.0

    out["target"] = out["census_pop"] + out["residual_pop"]
    targets = out.groupby(ward_col)["target"].sum()

    placed = float(targets.sum())
    if not np.isclose(placed, city_total, rtol=1e-9, atol=1.0):
        raise AssertionError(f"targets sum to {placed:,.1f}, expected {city_total:,.1f}")

    # What this actually changed: the placeholder gave every ward the same scale
    # factor, so the spread of census share against model share IS the effect.
    model_share = out.groupby(ward_col)[pop_col].sum()
    model_share = model_share / model_share.sum()
    census_share = targets / targets.sum()
    ratio = (census_share / model_share.replace(0.0, np.nan)).dropna()

    report = {
        "method": "dasymetric re-cut of Census 2011 ward totals onto 2022 wards",
        "wards_2008_counted": len(counted),
        "wards_2008_mapped": len(mapped),
        "wards_2008_without_modelled_population": empty_wards,
        "wards_2022_targeted": int(len(targets)),
        "census_population": round(census_total, 1),
        "residual_population": round(residual, 1),
        "residual_share_of_city": round(residual / float(city_total), 4),
        "cells_fully_inside_2008": int((out["inside_2008"] >= 0.999).sum()),
        "cells_partly_inside_2008": int(((out["inside_2008"] > 0.001) &
                                         (out["inside_2008"] < 0.999)).sum()),
        "cells_outside_2008": int((out["inside_2008"] <= 0.001).sum()),
        "ward_target_over_model_min": round(float(ratio.min()), 4),
        "ward_target_over_model_median": round(float(ratio.median()), 4),
        "ward_target_over_model_max": round(float(ratio.max()), 4),
        "wards_moved_over_10pct": int((ratio.sub(1.0).abs() > 0.10).sum()),
        "city_total": round(float(city_total), 1),
    }
    return {int(k): float(v) for k, v in targets.items()}, report
