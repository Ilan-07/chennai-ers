"""Ward and zone boundaries. Build step 04.

Source: Greater Chennai Corporation ward map 2022, via the OpenCity CKAN mirror.
The GCC ArcGIS REST server (gis.chennaicorporation.gov.in) returned HTTP 500 at
build time, so the documented fallback is in use — recorded in the registry.

Nothing here silently repairs data. Every fix is counted and reported, because a
boundary correction that nobody sees becomes an unexplained area discrepancy later.
"""
from __future__ import annotations

import re
import warnings

import geopandas as gpd
import pandas as pd
from shapely.validation import make_valid

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
          "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15}


def _clean_text(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()


def _zone_number(v) -> int | None:
    """'ZONE - IV' and 'IV' must both become 4."""
    s = _clean_text(v).upper().replace("ZONE", "").replace("-", " ").strip()
    return _ROMAN.get(s)


def load_wards(path: str) -> tuple[gpd.GeoDataFrame, dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = gpd.read_file(path)

    g["ward_no"] = pd.to_numeric(
        g["name2"].map(_clean_text), errors="coerce").astype("Int64")

    dropped_no_id = int(g["ward_no"].isna().sum())
    g = g[g["ward_no"].notna()].copy()

    invalid_before = int((~g.geometry.is_valid).sum())
    if invalid_before:
        g["geometry"] = [make_valid(x) if not x.is_valid else x for x in g.geometry]
    # make_valid can yield GeometryCollections; keep only the polygonal parts.
    g["geometry"] = g.geometry.apply(
        lambda x: x if x.geom_type in ("Polygon", "MultiPolygon")
        else gpd.GeoSeries([x]).explode(index_parts=False).pipe(
            lambda s: s[s.geom_type.isin(["Polygon", "MultiPolygon"])].union_all())
    )
    invalid_after = int((~g.geometry.is_valid).sum())

    g = g[["ward_no", "geometry"]].sort_values("ward_no").reset_index(drop=True)
    g["ward_id"] = range(1, len(g) + 1)

    report = {
        "features_read": len(g) + dropped_no_id,
        "dropped_without_ward_number": dropped_no_id,
        "invalid_geometries_repaired": invalid_before,
        "invalid_geometries_remaining": invalid_after,
        "ward_count": len(g),
    }
    return g, report


def load_zones(path: str) -> tuple[gpd.GeoDataFrame, dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        z = gpd.read_file(path)

    z["zone_no"] = z["ZONE"].map(_zone_number)
    z["zone_name"] = z["ZONE_NAME"].map(_clean_text)
    z["region"] = z["Region"].map(_clean_text)

    # The KML carries one empty feature. Drop it, loudly.
    dropped = int(z["zone_no"].isna().sum())
    z = z[z["zone_no"].notna()].copy()
    z["zone_no"] = z["zone_no"].astype(int)

    z = z[["zone_no", "zone_name", "region", "geometry"]].sort_values("zone_no").reset_index(drop=True)
    return z, {"zones": len(z), "dropped_empty_features": dropped}


def assign_zones(wards: gpd.GeoDataFrame, zones: gpd.GeoDataFrame,
                 metric_crs: str) -> tuple[gpd.GeoDataFrame, dict]:
    """Attach a zone to each ward by largest-overlap, not centroid.

    A centroid join misassigns wards whose centroid falls in a neighbour across
    a river bend; largest-overlap is the correct predicate for nested admin units.
    """
    wm = wards.to_crs(metric_crs)
    zm = zones.to_crs(metric_crs)
    inter = gpd.overlay(wm[["ward_id", "geometry"]], zm[["zone_no", "zone_name", "region", "geometry"]],
                        how="intersection", keep_geom_type=True)
    inter["ov"] = inter.area
    best = inter.sort_values("ov", ascending=False).drop_duplicates("ward_id")
    out = wards.merge(best[["ward_id", "zone_no", "zone_name", "region"]], on="ward_id", how="left")
    return out, {"wards_without_zone": int(out["zone_no"].isna().sum())}


def validate(wards: gpd.GeoDataFrame, cfg: dict, tol_pct: float = 2.0) -> dict:
    """Gate for build step 04."""
    wm = wards.to_crs(cfg["crs"]["metric"])
    area_km2 = float(wm.area.sum()) / 1e6
    expected = float(cfg["area_km2"])
    delta_pct = 100.0 * (area_km2 - expected) / expected
    nums = sorted(int(x) for x in wards["ward_no"])
    checks = {
        "ward_count": len(wards),
        "ward_count_ok": len(wards) == int(cfg["wards"]),
        "ward_numbers_contiguous_1_to_n": nums == list(range(1, len(nums) + 1)),
        "duplicate_ward_numbers": len(nums) - len(set(nums)),
        "area_km2": round(area_km2, 1),
        "expected_area_km2": expected,
        "area_delta_pct": round(delta_pct, 2),
        "area_within_tolerance": abs(delta_pct) <= tol_pct,
        "invalid_geometries": int((~wards.geometry.is_valid).sum()),
    }
    checks["passes"] = bool(
        checks["ward_count_ok"] and checks["area_within_tolerance"]
        and checks["invalid_geometries"] == 0 and checks["duplicate_ward_numbers"] == 0
    )
    return checks
