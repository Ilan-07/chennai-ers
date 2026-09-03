"""Flood as a graph perturbation. Build step 12.

Flooding is modelled as an edge-level change to the routable network, not as a
polygon drawn over a finished coverage map. The distinction matters: an overlay
can only say "this area is wet", whereas removing links can say "this area is
now UNREACHABLE, because the two bridges serving it are cut" — which is the
thing an emergency planner actually needs to know.

Link state is keyed to the Chennai Flows CATEGORY field (LOW/MODERATE/HIGH)
rather than to an assumed fording depth, because these layers classify severity
and do not carry depth.
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
