"""Candidate site generation. Build step 10.

Finding F-10: a road-network node is a point in the carriageway. A fire station
needs a land parcel with appliance-bay frontage, a forecourt and a turning
circle. Proposing bare network nodes produces coordinates in the middle of Anna
Salai, which is the fastest way to lose a planner's confidence.

So candidates are proposed on the network, thinned for spatial spread, and then
SNAPPED to a land-availability layer. A candidate with no feasible parcel within
the snap radius is kept but flagged infeasible (L_j = 0) rather than deleted —
"no buildable land near the best-serving location" is itself a finding.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon

# Only roads a fire appliance can actually turn out onto.
ARTERIAL = {"motorway", "trunk", "primary", "secondary", "tertiary",
            "primary_link", "secondary_link", "tertiary_link"}

# Land a municipality can plausibly build on. Ordered by preference: publicly
# held, low-disruption sites first.
LAND_PREFERENCE = [
    "office=government", "amenity=townhall", "amenity=community_centre",
    "landuse=brownfield", "landuse=greenfield", "landuse=recreation_ground",
    "amenity=school", "amenity=college", "amenity=university",
    "leisure=sports_centre", "leisure=park", "amenity=hospital",
    "landuse=industrial", "landuse=commercial", "landuse=military",
]
_PREF_RANK = {k: i for i, k in enumerate(LAND_PREFERENCE)}


def load_osm_parcels(path: str, metric_crs: str, min_area_m2: float = 800.0
                     ) -> tuple[gpd.GeoDataFrame, dict]:
    """Parse an Overpass `out geom` response into candidate land parcels."""
    data = json.loads(open(path).read())
    rows, geoms = [], []
    skipped_small = skipped_bad = 0

    for el in data.get("elements", []):
        geom = el.get("geometry")
        if not geom or len(geom) < 4:
            skipped_bad += 1
            continue
        try:
            poly = Polygon([(p["lon"], p["lat"]) for p in geom])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.geom_type != "Polygon":
                skipped_bad += 1
                continue
        except Exception:
            skipped_bad += 1
            continue
        tags = el.get("tags", {})
        cls = next((f"{k}={tags[k]}" for k in ("office", "amenity", "leisure", "landuse")
                    if k in tags), "unknown")
        rows.append({"osm_id": el.get("id"), "land_class": cls,
                     "name": tags.get("name", ""), "pref": _PREF_RANK.get(cls, 99)})
        geoms.append(poly)

    g = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326").to_crs(metric_crs)
    g["area_m2"] = g.area
    before = len(g)
    g = g[g["area_m2"] >= min_area_m2].copy()
    skipped_small = before - len(g)
    g = g.sort_values(["pref", "osm_id"]).reset_index(drop=True)
    g["parcel_id"] = range(1, len(g) + 1)

    return g, {"parsed": before + skipped_bad, "kept": len(g),
               "skipped_unbuildable_geometry": skipped_bad,
               "skipped_below_min_area": skipped_small,
               "min_area_m2": min_area_m2}


def propose_from_network(nodes: pd.DataFrame, edges: pd.DataFrame,
                         *, min_degree: int = 3) -> np.ndarray:
    """Node ids sitting on an arterial/collector road with a real junction."""
    from ers.geo.attrs import primary_highway

    hw = pd.Series([primary_highway(v) for v in edges["highway"]], index=edges.index)
    art = edges.loc[hw.isin(ARTERIAL), ["u", "v"]]
    on_arterial = pd.unique(np.concatenate([art["u"].to_numpy(), art["v"].to_numpy()]))

    deg = nodes.set_index("osmid")["street_count"].fillna(0)
    ok = deg.reindex(on_arterial).fillna(0) >= min_degree
    return np.sort(ok[ok].index.to_numpy())          # sorted -> deterministic


def thin(node_ids: np.ndarray, xy: np.ndarray, min_separation_m: float = 800.0
         ) -> np.ndarray:
    """Greedy spatial thinning with a deterministic order.

    Iterating a set or relying on argsort tie order would make the candidate
    list depend on memory layout. Sorting by node id first makes it exact.
    """
    from scipy.spatial import cKDTree

    order = np.argsort(node_ids, kind="stable")
    node_ids, xy = node_ids[order], xy[order]

    tree = cKDTree(xy)
    kept_mask = np.zeros(len(node_ids), dtype=bool)
    blocked = np.zeros(len(node_ids), dtype=bool)
    for i in range(len(node_ids)):
        if blocked[i]:
            continue
        kept_mask[i] = True
        for j in tree.query_ball_point(xy[i], min_separation_m):
            if j != i:
                blocked[j] = True
    return node_ids[kept_mask]


@dataclass(frozen=True)
class CandidateSet:
    frame: gpd.GeoDataFrame
    stats: dict


def build_candidates(nodes: pd.DataFrame, edges: pd.DataFrame,
                     parcels: gpd.GeoDataFrame, metric_crs: str,
                     *, min_degree: int = 3, min_separation_m: float = 800.0,
                     parcel_snap_m: float = 400.0) -> CandidateSet:
    from scipy.spatial import cKDTree

    proposed = propose_from_network(nodes, edges, min_degree=min_degree)
    nidx = nodes.set_index("osmid")
    xy = nidx.loc[proposed, ["x", "y"]].to_numpy()
    kept = thin(proposed, xy, min_separation_m)

    kxy = nidx.loc[kept, ["x", "y"]].to_numpy()
    prep = parcels.representative_point()
    ptree = cKDTree(np.column_stack([prep.x.to_numpy(), prep.y.to_numpy()]))
    dist, pidx = ptree.query(kxy, k=1)

    feasible = dist <= parcel_snap_m
    frame = gpd.GeoDataFrame({
        "candidate_id": range(1, len(kept) + 1),
        "network_node": kept,
        "x": kxy[:, 0], "y": kxy[:, 1],
        "parcel_id": np.where(feasible, parcels["parcel_id"].to_numpy()[pidx], -1),
        "land_class": np.where(feasible, parcels["land_class"].to_numpy()[pidx], "none"),
        "parcel_distance_m": np.round(dist, 1),
        "land_feasible": feasible,
    }, geometry=gpd.points_from_xy(kxy[:, 0], kxy[:, 1]), crs=metric_crs)

    stats = {
        "proposed_on_arterial": int(len(proposed)),
        "after_thinning": int(len(kept)),
        "min_separation_m": min_separation_m,
        "parcel_snap_m": parcel_snap_m,
        "land_feasible": int(feasible.sum()),
        "land_infeasible": int((~feasible).sum()),
        "feasible_share": round(float(feasible.mean()), 4),
        "land_class_counts": (frame.loc[frame["land_feasible"], "land_class"]
                              .value_counts().to_dict()),
    }
    return CandidateSet(frame, stats)
