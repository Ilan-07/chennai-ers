"""Road graph construction and persistence. Build step 05.

OSMnx produces columns whose values are sometimes scalars and sometimes lists
(a consolidated node carries every original `osmid`; a simplified edge carries
every `highway` class it merged). Arrow refuses to write such a column, so list
columns are JSON-encoded on write and decoded on read. The list semantics are
preserved because attribution genuinely needs them -- a merged way is only as
fast as its slowest tagged segment.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd


def _has_list(s: pd.Series) -> bool:
    return bool(s.map(lambda v: isinstance(v, (list, tuple))).any())


def encode_list_columns(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, list[str]]:
    """JSON-encode every column that mixes list and scalar values."""
    out = gdf.copy()
    encoded: list[str] = []
    for col in out.columns:
        if col == out.geometry.name or out[col].dtype != object:
            continue
        if _has_list(out[col]):
            out[col] = out[col].map(
                lambda v: json.dumps(list(v)) if isinstance(v, (list, tuple))
                else (None if v is None or (isinstance(v, float) and pd.isna(v)) else json.dumps(v))
            )
            encoded.append(col)
        else:
            # Uniformly non-list object columns still need a stable dtype.
            out[col] = out[col].map(lambda v: None if v is None else str(v))
    return out, encoded


def decode_list_columns(gdf: gpd.GeoDataFrame, cols: list[str]) -> gpd.GeoDataFrame:
    """Reverse `encode_list_columns` so attribution sees real lists again."""
    out = gdf.copy()
    for col in cols:
        if col not in out.columns:
            continue
        out[col] = out[col].map(lambda v: json.loads(v) if isinstance(v, str) and v else None)
    return out


def write_graph_tables(nodes: gpd.GeoDataFrame, edges: gpd.GeoDataFrame, prefix: str) -> dict:
    n_enc, n_cols = encode_list_columns(nodes.reset_index())
    e_enc, e_cols = encode_list_columns(edges.reset_index())
    n_enc.to_parquet(f"{prefix}_nodes.parquet")
    e_enc.to_parquet(f"{prefix}_edges.parquet")
    meta = {"node_list_columns": n_cols, "edge_list_columns": e_cols}
    with open(f"{prefix}_schema.json", "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
    return meta


def read_graph_tables(prefix: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    with open(f"{prefix}_schema.json") as fh:
        meta = json.load(fh)
    nodes = decode_list_columns(gpd.read_parquet(f"{prefix}_nodes.parquet"), meta["node_list_columns"])
    edges = decode_list_columns(gpd.read_parquet(f"{prefix}_edges.parquet"), meta["edge_list_columns"])
    return nodes, edges


def connectivity_report(csr) -> dict:
    """Weak AND strong connectivity.

    Weak connectivity is the wrong test for a directed road network: it ignores
    arc direction, so a node reachable only by driving the wrong way down a
    one-way street counts as connected. Vehicles cannot do that. Chennai's
    network is 100% weakly connected but 99.95% strongly connected -- the 47-node
    difference is real demand that no station can reach, and it must be reported
    rather than assumed away.
    """
    import numpy as np
    from scipy.sparse.csgraph import connected_components

    n = csr.shape[0]
    nw, lw = connected_components(csr, directed=True, connection="weak")
    ns, ls = connected_components(csr, directed=True, connection="strong")
    wsz, ssz = np.bincount(lw), np.bincount(ls)
    return {
        "nodes": int(n),
        "weak_components": int(nw),
        "largest_weak_nodes": int(wsz.max()),
        "largest_weak_share": round(float(wsz.max() / n), 5),
        "strong_components": int(ns),
        "largest_strong_nodes": int(ssz.max()),
        "largest_strong_share": round(float(ssz.max() / n), 5),
        "nodes_outside_largest_scc": int(n - ssz.max()),
        "scc_singletons": int((ssz == 1).sum()),
    }
