"""Sparse graph assembly and multi-source shortest paths. Build step 09.

The workload is NOT routing. We never need a turn-by-turn route -- we need, per
scenario, the full matrix of travel times from every candidate and station to
every demand cell, truncated at a cutoff. That is bulk many-to-many shortest
path, and contraction hierarchies buy nothing for it: the sweep visits nearly
every node within the cutoff from every source, so there is nothing to prune,
and CH preprocessing would have to be redone for every scenario graph.

`scipy.sparse.csgraph.dijkstra` is compiled, deterministic on integer weights,
in-process, and rebuilt trivially per scenario.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

UNREACHABLE = np.iinfo(np.int32).max


@dataclass(frozen=True)
class RoadGraph:
    csr: sparse.csr_matrix          # directed, weights in deciseconds
    node_ids: np.ndarray            # graph node id per dense index
    xy: np.ndarray                  # (N, 2) projected coordinates, metric CRS
    index_of: dict[int, int]

    @property
    def n(self) -> int:
        return self.csr.shape[0]


def build_graph(nodes: pd.DataFrame, edges: pd.DataFrame, tau_col: str,
                *, id_col: str = "osmid") -> RoadGraph:
    """Assemble a directed CSR matrix. Arcs at UNREACHABLE are dropped entirely."""
    node_ids = nodes[id_col].to_numpy()
    order = np.argsort(node_ids, kind="stable")      # deterministic index assignment
    node_ids = node_ids[order]
    index_of = {int(v): i for i, v in enumerate(node_ids)}

    xy = np.column_stack([
        nodes["x"].to_numpy()[order], nodes["y"].to_numpy()[order]
    ]).astype("float64")

    u = edges["u"].map(index_of).to_numpy()
    v = edges["v"].map(index_of).to_numpy()
    w = edges[tau_col].to_numpy()

    keep = np.isfinite(u.astype("float64")) & np.isfinite(v.astype("float64")) & (w < UNREACHABLE)
    u, v, w = u[keep].astype(np.int32), v[keep].astype(np.int32), w[keep].astype(np.float64)

    n = len(node_ids)
    csr = sparse.csr_matrix((w, (u, v)), shape=(n, n))
    return RoadGraph(csr=csr, node_ids=node_ids, xy=xy, index_of=index_of)


def snap(graph: RoadGraph, x: np.ndarray, y: np.ndarray,
         ) -> tuple[np.ndarray, np.ndarray]:
    """Nearest graph node to each point, in the METRIC CRS.

    Snapping in degrees is a classic silent error: a degree of longitude is
    ~108 km at Chennai's latitude, so a degree-space nearest-neighbour search
    is anisotropic and picks the wrong node.
    """
    tree = cKDTree(graph.xy)
    dist, idx = tree.query(np.column_stack([x, y]), k=1)
    return idx.astype(np.int32), dist


def travel_times(graph: RoadGraph, sources: np.ndarray, targets: np.ndarray,
                 *, cutoff_ds: float | None = None) -> np.ndarray:
    """Travel time in deciseconds from each source to each target.

    Direction matters: we need time FROM a station TO a demand cell, so the
    sweep runs forward on the directed graph from the source. Running it on the
    reversed graph (or an undirected one) silently answers a different question
    on a network with one-way streets.
    """
    d = dijkstra(graph.csr, directed=True, indices=sources,
                 limit=np.inf if cutoff_ds is None else float(cutoff_ds))
    if d.ndim == 1:
        d = d[None, :]
    return d[:, targets]


def to_seconds(ds: np.ndarray) -> np.ndarray:
    return ds / 10.0
