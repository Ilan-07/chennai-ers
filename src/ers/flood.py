"""Flood as a graph perturbation. Build step 12.

Flooding is modelled as an edge-level change to the routable network, not as a
polygon drawn over a finished coverage map. The distinction matters: an overlay
can only say "this area is wet", whereas removing links can say "this area is
now UNREACHABLE, because the two bridges serving it are cut" — which is the
thing an emergency planner actually needs to know.

Link state is keyed to the Chennai Flows CATEGORY field (LOW/MODERATE/HIGH)
rather than to an assumed fording depth, because the return-period layers
classify severity and do not carry depth. The separate 2015 inundation-point
layer DOES carry measured depth, so `load_flood_points` keys off depth against
the A-08 closure threshold instead. Two layers, two honest mappings, rather than
one invented depth for the layers that never measured it.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

CLOSED, WADING, PASSABLE = "closed", "wading", "passable"


def load_flood_zones(path: str, metric_crs: str, category_field: str = "CATEGORY"
                     ) -> tuple[gpd.GeoDataFrame, dict]:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = gpd.read_file(path)

    invalid = int((~g.geometry.is_valid).sum())
    if invalid:
        g["geometry"] = g.geometry.buffer(0)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    g[category_field] = g[category_field].astype(str).str.upper().str.strip()
    g = g.to_crs(metric_crs)
    return g, {"features": len(g), "invalid_repaired": invalid,
               "categories": g[category_field].value_counts().to_dict(),
               "area_km2": round(float(g.area.sum()) / 1e6, 1)}


def classify_arcs(edges: gpd.GeoDataFrame, zones: gpd.GeoDataFrame, *,
                  link_state: dict[str, str], category_field: str = "CATEGORY",
                  bridges_exempt: bool = True) -> tuple[np.ndarray, dict]:
    """Assign a flood state to every arc.

    An arc takes the WORST state of any zone it intersects — a link is only as
    passable as its worst point, so a max rule is correct and a mean would be
    dangerously optimistic.
    """
    severity = {PASSABLE: 0, WADING: 1, CLOSED: 2}
    inv = {v: k for k, v in severity.items()}

    zones = zones.copy()
    zones["_sev"] = zones[category_field].map(
        lambda c: severity.get(link_state.get(c, PASSABLE), 0))
    zones = zones[zones["_sev"] > 0]

    state_num = np.zeros(len(edges), dtype=np.int8)
    if len(zones):
        joined = gpd.sjoin(edges[["geometry"]].reset_index(drop=True),
                           zones[["_sev", "geometry"]], how="inner", predicate="intersects")
        if len(joined):
            worst = joined.groupby(joined.index)["_sev"].max()
            state_num[worst.index.to_numpy()] = worst.to_numpy()

    exempted = 0
    if bridges_exempt and "bridge" in edges.columns:
        # A bridge deck normally stays above the water. Its APPROACH RAMPS may
        # not, which is why this is an exemption on the deck only and the
        # approach nodes are still subject to whatever state their own arcs take.
        isbridge = edges["bridge"].notna() & (
            edges["bridge"].astype(str).str.lower().isin(["yes", "true", "viaduct"]))
        exempted = int((isbridge & (state_num == 2)).sum())
        state_num[isbridge.to_numpy() & (state_num == 2)] = 1   # demote to wading

    states = np.array([inv[s] for s in state_num], dtype=object)
    stats = {
        "arcs": len(edges),
        "closed": int((state_num == 2).sum()),
        "wading": int((state_num == 1).sum()),
        "passable": int((state_num == 0).sum()),
        "bridges_exempted_from_closure": exempted,
        "closed_share": round(float((state_num == 2).mean()), 4),
    }
    if "length" in edges.columns:
        L = edges["length"].to_numpy()
        stats["length_km_closed"] = round(float(L[state_num == 2].sum()) / 1000.0, 1)
        stats["length_km_total"] = round(float(L.sum()) / 1000.0, 1)
        stats["length_share_closed"] = round(float(L[state_num == 2].sum() / L.sum()), 4)
    return states, stats


def flood_factors(states: np.ndarray, wading_speed_factor: float = 0.35) -> np.ndarray:
    """Multiplicative speed factor per arc. 0.0 removes the arc entirely."""
    f = np.ones(len(states), dtype="float64")
    f[states == WADING] = float(wading_speed_factor)
    f[states == CLOSED] = 0.0
    return f


def load_flood_points(path: str, metric_crs: str, *, buffer_m: float,
                      depth_field: str = "DEPTH", depth_units: str = "inches",
                      closure_depth_m: float = 0.30
                      ) -> tuple[gpd.GeoDataFrame, dict]:
    """Observed inundation POINTS with measured depth -> buffered link-state zones.

    The 2015 event is recorded as 192 surveyed points, not as a modelled extent.
    Two consequences, both declared rather than smoothed over:

    1. A point is buffered to a disc of `buffer_m`. The radius is an assumption
       about how far the reported condition extends along the street, and it is
       the dominant uncertainty in this scenario.
    2. Depth IS available here (unlike the return-period layers, which carry only
       a severity CATEGORY), so state is set by depth against the A-08 closure
       threshold instead of by a category mapping.

    192 points cannot describe a city-wide flood. This scenario is a lower bound
    on 2015 disruption and is reported, never optimised against.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = gpd.read_file(path)

    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    depth = pd.to_numeric(g[depth_field], errors="coerce")
    per_unit_m = {"inches": 0.0254, "in": 0.0254, "m": 1.0, "cm": 0.01}
    if depth_units not in per_unit_m:
        raise ValueError(f"unknown depth_units {depth_units!r}")
    depth_m = depth * per_unit_m[depth_units]

    g = g.to_crs(metric_crs)
    g["geometry"] = g.geometry.buffer(float(buffer_m))
    # An unmeasured point is still a reported inundation. Treat it as wading
    # rather than dropping it -- dropping is the optimistic error.
    g["_state"] = np.where(depth_m.to_numpy() >= closure_depth_m, CLOSED, WADING)
    g.loc[depth_m.isna().to_numpy(), "_state"] = WADING

    return g[["_state", "geometry"]], {
        "features": len(g),
        "buffer_m": float(buffer_m),
        "depth_units": depth_units,
        "closure_depth_m": float(closure_depth_m),
        "depth_m_median": round(float(depth_m.median()), 3) if depth_m.notna().any() else None,
        "depth_m_max": round(float(depth_m.max()), 3) if depth_m.notna().any() else None,
        "depth_missing": int(depth_m.isna().sum()),
        "categories": g["_state"].value_counts().to_dict(),
        "area_km2": round(float(g.area.sum()) / 1e6, 1),
    }
