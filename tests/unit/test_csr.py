"""`ers.routing.csr` -- the shortest-path layer under every number in the project.

Untested directly before the 2026-09 repair. Two of its properties are load-
bearing and easy to break silently: the sweep must run FORWARD on the directed
graph (station -> cell, not cell -> station), and `snap` must work in the metric
CRS. Both were called out in comments; neither was asserted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ers.routing.csr import (UNREACHABLE, build_graph, snap, to_seconds,
                             travel_times)


def _one_way_chain():
    """0 -> 1 -> 2, one way. Nothing routes backwards."""
    nodes = pd.DataFrame({"osmid": [10, 20, 30],
                          "x": [0.0, 100.0, 200.0],
                          "y": [0.0, 0.0, 0.0]})
    edges = pd.DataFrame({"u": [10, 20], "v": [20, 30], "key": [0, 0],
                          "tau": [100.0, 150.0]})
    return build_graph(nodes, edges, "tau")


# --------------------------------------------------------------- directedness

def test_the_sweep_runs_forward_on_a_one_way_network():
    """Routing on the reversed graph silently answers a different question."""
    g = _one_way_chain()
    d = travel_times(g, np.array([0]), np.array([0, 1, 2]))
    assert d[0].tolist() == [0.0, 100.0, 250.0]

    back = travel_times(g, np.array([2]), np.array([0, 1, 2]))
    assert np.isinf(back[0][0]) and np.isinf(back[0][1]), (
        "a one-way street must not be traversable backwards")


def test_one_row_per_source_not_a_single_merged_sweep():
    """The incremental cache in prioritise_survey depends on this shape."""
    g = _one_way_chain()
    d = travel_times(g, np.array([0, 1]), np.array([0, 1, 2]))
    assert d.shape == (2, 3)
    assert d[1][0] == np.inf, "row 1 is the field from node 1 alone"


def test_a_single_source_still_returns_a_two_dimensional_result():
    g = _one_way_chain()
    d = travel_times(g, np.array([0]), np.array([2]))
    assert d.ndim == 2 and d.shape == (1, 1)


# ---------------------------------------------------------------- the cutoff

def test_a_cutoff_leaves_infinity_not_a_truncated_number():
    """Flood scenarios turn on telling FAR apart from CUT OFF."""
    g = _one_way_chain()
    d = travel_times(g, np.array([0]), np.array([0, 1, 2]), cutoff_ds=120.0)
    assert d[0][1] == 100.0
    assert np.isinf(d[0][2]), "beyond the cutoff must read as unreachable"


# ----------------------------------------------------------- graph assembly

def test_unreachable_arcs_are_dropped_entirely():
    nodes = pd.DataFrame({"osmid": [10, 20], "x": [0.0, 1.0], "y": [0.0, 0.0]})
    edges = pd.DataFrame({"u": [10], "v": [20], "key": [0],
                          "tau": [float(UNREACHABLE)]})
    g = build_graph(nodes, edges, "tau")
    assert g.csr.nnz == 0, "an impassable arc must not become a traversable one"


def test_node_index_assignment_is_deterministic_across_row_order():
    """Index assignment sorts by osmid, so a reordered input must not shift it."""
    a = pd.DataFrame({"osmid": [30, 10, 20], "x": [2.0, 0.0, 1.0], "y": [0.0] * 3})
    b = a.sort_values("osmid").reset_index(drop=True)
    e = pd.DataFrame({"u": [10], "v": [30], "key": [0], "tau": [5.0]})
    ga, gb = build_graph(a, e, "tau"), build_graph(b, e, "tau")
    assert ga.node_ids.tolist() == gb.node_ids.tolist() == [10, 20, 30]
    assert (ga.csr.toarray() == gb.csr.toarray()).all()


# ------------------------------------------------------------------- snapping

def test_snap_finds_the_nearest_node_and_reports_the_distance():
    g = _one_way_chain()
    idx, dist = snap(g, np.array([90.0]), np.array([30.0]))
    assert idx[0] == 1
    assert dist[0] == pytest.approx(np.hypot(10.0, 30.0))


def test_the_kdtree_is_memoised_on_the_frozen_graph():
    """A third of every Monte Carlo evaluation once went on rebuilding this."""
    g = _one_way_chain()
    snap(g, np.array([0.0]), np.array([0.0]))
    first = getattr(g, "_kdtree")
    snap(g, np.array([50.0]), np.array([0.0]))
    assert getattr(g, "_kdtree") is first


def test_to_seconds_converts_deciseconds():
    assert to_seconds(np.array([1200.0]))[0] == 120.0
    assert np.isinf(to_seconds(np.array([np.inf]))[0])
