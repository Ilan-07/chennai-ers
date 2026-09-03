"""Demand surface construction. Build step 08.

Design note on aggregation. The blueprint called for area-weighted zonal
extraction (`exactextract`). WorldPop cells hold a population COUNT, not a
density, so splitting a cell across hexes by area would be an assumption about
the within-pixel distribution -- and one that does not conserve people. Centroid
assignment instead places each populated pixel wholly in one hex: it is
mass-conserving by construction, which matters more here because the result is
then reconciled to census ward totals anyway. The cost is edge error at hex
boundaries, which the r10 sensitivity run measures.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import geopandas as gpd
import h3
import rasterio
from shapely.geometry import Polygon


def cells_for_area(area: gpd.GeoDataFrame, resolution: int) -> gpd.GeoDataFrame:
    """Every H3 cell covering `area`, as polygons in EPSG:4326."""
    if area.crs is None or area.crs.to_epsg() != 4326:
        area = area.to_crs("EPSG:4326")
    idx: set[str] = set()
    for geom in area.geometry:
        for poly in ([geom] if geom.geom_type == "Polygon" else list(geom.geoms)):
            shape = h3.geo_to_h3shape(poly.__geo_interface__)
            idx.update(h3.h3shape_to_cells(shape, resolution))
    cells = sorted(idx)                      # sorted -> deterministic cell_id assignment
    polys = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells]
    g = gpd.GeoDataFrame({"h3_index": cells}, geometry=polys, crs="EPSG:4326")
    g["cell_id"] = range(1, len(g) + 1)
    return g


def assign_wards(cells: gpd.GeoDataFrame, wards: gpd.GeoDataFrame,
                 metric_crs: str) -> tuple[gpd.GeoDataFrame, dict]:
    """Attach a ward to each cell by largest overlap."""
    cm = cells.to_crs(metric_crs)[["cell_id", "geometry"]]
    wm = wards.to_crs(metric_crs)[["ward_id", "ward_no", "zone_no", "geometry"]]
    inter = gpd.overlay(cm, wm, how="intersection", keep_geom_type=True)
    inter["ov"] = inter.area
    best = inter.sort_values("ov", ascending=False).drop_duplicates("cell_id")
    out = cells.merge(best[["cell_id", "ward_id", "ward_no", "zone_no"]], on="cell_id", how="left")
    return out, {"cells_without_ward": int(out["ward_id"].isna().sum())}


def population_to_cells(raster_path: str, cells: gpd.GeoDataFrame,
                        resolution: int) -> tuple[pd.Series, dict]:
    """Sum WorldPop pixels into H3 cells by pixel centroid.

    Returns a population series indexed like `cells`, plus a mass-balance report:
    every person in the raster window is either placed in a cell or explicitly
    counted as falling outside the study area. Nothing disappears quietly.
    """
    with rasterio.open(raster_path) as src:
        arr = src.read(1)
        nodata = src.nodata
        transform = src.transform
        src_crs = src.crs

    valid = np.isfinite(arr) & (arr > 0)
    if nodata is not None:
        valid &= arr != nodata
    rows, cols = np.nonzero(valid)
    vals = arr[rows, cols].astype("float64")

    # Pixel centroids -> lon/lat (rasterio's xy takes row, col and returns x, y).
    xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
    xs = np.asarray(xs, dtype="float64")
    ys = np.asarray(ys, dtype="float64")

    # GHS-POP ships in Mollweide (ESRI:54009). Transform the CENTROIDS rather
    # than warping the raster: a population COUNT grid cannot be reprojected
    # without resampling, and resampling does not conserve people.
    if src_crs is not None and src_crs.to_string() not in ("EPSG:4326", "OGC:CRS84"):
        from pyproj import Transformer
        tf = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
        lons, lats = tf.transform(xs, ys)
        lons = np.asarray(lons, dtype="float64")
        lats = np.asarray(lats, dtype="float64")
    else:
        lons, lats = xs, ys

    idx = np.array(
        [h3.latlng_to_cell(float(la), float(lo), resolution) for la, lo in zip(lats, lons)],
        dtype=object,
    )
    summed = pd.Series(vals).groupby(pd.Series(idx)).sum()

    pop = cells["h3_index"].map(summed).fillna(0.0)
    placed = float(pop.sum())
    total = float(vals.sum())
    report = {
        "raster_population": round(total, 1),
        "population_placed_in_cells": round(placed, 1),
        "population_outside_study_area": round(total - placed, 1),
        "populated_pixels": int(valid.sum()),
        "cells_with_population": int((pop > 0).sum()),
        "raster_crs": None if src_crs is None else src_crs.to_string(),
        "mass_balance_ok": abs(total - placed) < max(1.0, 1e-6 * total) or placed <= total,
    }
    return pop, report


def reconcile_to_wards(cells: gpd.GeoDataFrame, ward_totals: dict[int, float],
                       pop_col: str = "population") -> tuple[pd.Series, dict]:
    """Pycnophylactic reconciliation: scale cells so each ward sums to its census total.

    WorldPop models the WITHIN-ward distribution well and the ward TOTAL less
    well. Census gives the total exactly. Rescaling per ward keeps the spatial
    detail and fixes the magnitude (Finding F-08).
    """
    out = cells[pop_col].astype("float64").copy()
    adjustments, unmatched, empty_wards = [], [], []

    for ward_id, target in ward_totals.items():
        m = cells["ward_id"] == ward_id
        if not m.any():
            unmatched.append(int(ward_id))
            continue
        current = float(out[m].sum())
        if current <= 0:
            # No modelled population but a real census total: distribute evenly
            # rather than dropping the ward's residents entirely.
            empty_wards.append(int(ward_id))
            out.loc[m] = float(target) / int(m.sum())
            continue
        factor = float(target) / current
        out.loc[m] = out[m] * factor
        adjustments.append(factor)

    adj = np.array(adjustments) if adjustments else np.array([1.0])
    report = {
        "wards_reconciled": len(adjustments),
        "wards_missing_cells": unmatched,
        "wards_with_no_modelled_population": empty_wards,
        "scale_factor_min": round(float(adj.min()), 4),
        "scale_factor_median": round(float(np.median(adj)), 4),
        "scale_factor_max": round(float(adj.max()), 4),
        "total_before": round(float(cells[pop_col].sum()), 1),
        "total_after": round(float(out.sum()), 1),
        "target_total": round(float(sum(ward_totals.values())), 1),
    }
    return out, report


def service_weights(cells: gpd.GeoDataFrame, *, w0: float, w1: float,
                    share_60plus: pd.Series | float) -> pd.Series:
    """EMS demand weight. ASSM A-06; swept in E-06.

    Cardiac and respiratory emergencies concentrate heavily in older residents,
    so raw headcount understates demand in ageing wards and overstates it in
    young ones.
    """
    share = (cells["ward_id"].map(share_60plus) if isinstance(share_60plus, pd.Series)
             else pd.Series(share_60plus, index=cells.index))
    return cells["population"] * (w0 + w1 * share.fillna(0.0))
