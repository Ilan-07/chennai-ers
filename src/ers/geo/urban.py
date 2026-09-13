"""The built-up metro, derived rather than drawn. Build step 04b.

The GCC boundary is an administrative fact and the right study area for a
question about the corporation. It is the wrong one for "can Chennai be reached
in time", because the corporation stops at Sholinganallur while the city does
not: Tambaram, Chromepet, Pallavaram, Navalur and Siruseri are continuous
built-up Chennai and sit outside it.

Extending needs a boundary, and the honest options were poor. OSM publishes no
polygon for Tambaram Corporation, Avadi Corporation or any taluk here -- an
Overpass query for admin_level 7/8 over the metro returns the GCC and a
cantonment board, nothing else. The 2022 CMA extent (5,904 km2) has no public
GIS file. Drawing an envelope by hand would make the study area an opinion, and
every coverage share computed inside it would inherit that opinion silently.

So the boundary is MEASURED, with the published method for exactly this problem:
the EU/OECD **Degree of Urbanisation** definition of an urban centre, which the
UN Statistical Commission endorsed in 2020 and which GHSL itself is built for.

    An urban centre is the set of contiguous 1 km^2 grid cells with a density of
    at least 1,500 inhabitants per km^2, whose gaps are filled, and whose total
    population is at least 50,000.

Applied to the GHS-POP raster this project already ingests (ADR-002), that
yields the Chennai urban centre. The study area is that centre UNIONED with the
GCC boundary, because a corporation ward that happens to fall below the density
threshold is still in scope -- the authority is responsible for it either way.

The threshold is an assumption (A-16) and is swept like any other.
"""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.warp import transform as warp_transform
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

# Degree of Urbanisation, urban-centre ("city") class.
DENSITY_PER_KM2 = 1500.0
MIN_CLUSTER_POPULATION = 50_000.0
GRID_M = 1000.0


def _window(src, bbox_wgs84):
    s, w, n, e = bbox_wgs84
    xs, ys = warp_transform("EPSG:4326", src.crs, [w, e, w, e], [s, s, n, n])
    return from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)


def urban_centre(
    raster_path: str,
    bbox_wgs84: tuple[float, float, float, float],
    seed_lonlat: tuple[float, float],
    density_per_km2: float = DENSITY_PER_KM2,
    min_cluster_population: float = MIN_CLUSTER_POPULATION,
) -> tuple[gpd.GeoDataFrame, dict]:
    """The urban centre containing `seed_lonlat`, as one polygon in EPSG:4326.

    `bbox_wgs84` is (south, west, north, east) and bounds the search, not the
    result: make it generous, because a cluster clipped by the search window is
    a cluster whose extent the window decided.
    """
    with rasterio.open(raster_path) as src:
        win = _window(src, bbox_wgs84)
        arr = src.read(1, window=win).astype("float64")
        tr = src.window_transform(win)
        crs = src.crs

    arr = np.where(np.isfinite(arr) & (arr > 0), arr, 0.0)

    # GHS-POP is 100 m in Mollweide, an equal-area projection, so a 10x10 block
    # is exactly 1 km^2 and a block SUM is a density per km^2. No resampling and
    # no reprojection is involved, which is the same reason ADR-002 gives for
    # transforming pixel centroids rather than warping the grid.
    block = int(round(GRID_M / abs(tr.a)))
    if block < 1:
        raise ValueError(f"raster resolution {tr.a} m is coarser than the 1 km grid")
    h = (arr.shape[0] // block) * block
    w = (arr.shape[1] // block) * block
    km = arr[:h, :w].reshape(h // block, block, w // block, block).sum(axis=(1, 3))

    dense = km >= density_per_km2
    lab, n = ndimage.label(dense, structure=np.ones((3, 3)))   # 8-connectivity
    if n == 0:
        raise ValueError("no cell reaches the urban-centre density threshold")

    sx, sy = warp_transform("EPSG:4326", crs, [seed_lonlat[0]], [seed_lonlat[1]])
    col = int((sx[0] - tr.c) / (tr.a * block))
    row = int((sy[0] - tr.f) / (tr.e * block))
    if not (0 <= row < lab.shape[0] and 0 <= col < lab.shape[1]):
        raise ValueError("the seed point lies outside the search window")
    cid = int(lab[row, col])
    if cid == 0:
        raise ValueError("the seed point is not inside any dense cluster")

    core = lab == cid
    # Gap-filling is part of the definition: an enclosed low-density pocket -- a
    # reservoir, an airfield, a golf course -- is inside the city, not beside it.
    filled = ndimage.binary_fill_holes(core)
    population = float(km[filled].sum())
    if population < min_cluster_population:
        raise ValueError(f"cluster holds {population:,.0f}, below the "
                         f"{min_cluster_population:,.0f} urban-centre minimum")

    km_tr = rasterio.Affine(tr.a * block, tr.b, tr.c, tr.d, tr.e * block, tr.f)
    shapes = features.shapes(filled.astype("uint8"), mask=filled, transform=km_tr)
    poly = unary_union([shape(g) for g, v in shapes if v == 1])

    gdf = gpd.GeoDataFrame({"name": ["Chennai urban centre"]}, geometry=[poly], crs=crs)
    gdf = gdf.to_crs("EPSG:4326")

    report = {
        "method": "EU/OECD Degree of Urbanisation, urban-centre class",
        "density_threshold_per_km2": density_per_km2,
        "grid_m": GRID_M,
        "clusters_found": int(n),
        "cells_in_centre_km2": int(filled.sum()),
        "cells_gap_filled": int(filled.sum() - core.sum()),
        "population": round(population, 1),
        "search_bbox": list(bbox_wgs84),
        "assumption": "A-16",
    }
    return gdf, report


def study_area(
    urban: gpd.GeoDataFrame,
    authority: gpd.GeoDataFrame,
    metric_crs: str,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Urban centre ∪ the authority boundary, as the area to model.

    The union rather than the urban centre alone: a GCC ward below the density
    threshold is still the corporation's responsibility, and dropping it would
    quietly shrink the very study area whose coverage this project publishes.
    """
    u = urban.to_crs(metric_crs)
    a = authority.to_crs(metric_crs)
    ug = u.union_all() if hasattr(u, "union_all") else u.unary_union
    ag = a.union_all() if hasattr(a, "union_all") else a.unary_union

    merged = unary_union([ug, ag])
    gdf = gpd.GeoDataFrame({"name": ["Chennai metro study area"]},
                           geometry=[merged], crs=metric_crs)

    report = {
        "urban_centre_km2": round(ug.area / 1e6, 1),
        "authority_km2": round(ag.area / 1e6, 1),
        "study_area_km2": round(merged.area / 1e6, 1),
        "authority_outside_urban_centre_km2": round((ag.difference(ug)).area / 1e6, 1),
        "urban_centre_outside_authority_km2": round((ug.difference(ag)).area / 1e6, 1),
    }
    return gdf.to_crs("EPSG:4326"), report
