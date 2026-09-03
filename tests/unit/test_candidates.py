"""Candidate generation tests. Build step 10."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from ers.geo.candidates import ARTERIAL, build_candidates, propose_from_network, thin


def test_thinning_respects_minimum_separation():
    ids = np.array([10, 20, 30, 40])
    xy = np.array([[0., 0.], [100., 0.], [900., 0.], [1800., 0.]])
    kept = thin(ids, xy, min_separation_m=800.0)
    # 20 sits 100 m from 10 and is blocked; 30 and 40 are >= 800 m clear.
    assert list(kept) == [10, 30, 40]
    for a in range(len(kept)):
        for b in range(a + 1, len(kept)):
            ia, ib = list(ids).index(kept[a]), list(ids).index(kept[b])
            assert np.linalg.norm(xy[ia] - xy[ib]) >= 800.0


def test_thinning_is_deterministic_regardless_of_input_order():
    rng = np.random.default_rng(4)
    ids = np.arange(60)
    xy = rng.random((60, 2)) * 5000
    a = thin(ids, xy, 800.0)
    perm = rng.permutation(60)
    b = thin(ids[perm], xy[perm], 800.0)
    assert list(a) == list(b)


def test_thinning_keeps_lowest_id_among_close_points():
    ids = np.array([77, 5])
    xy = np.array([[0., 0.], [10., 0.]])
    assert list(thin(ids, xy, 800.0)) == [5]


def _net():
    nodes = pd.DataFrame({"osmid": [1, 2, 3, 4], "x": [0., 500., 1500., 3000.],
                          "y": [0., 0., 0., 0.], "street_count": [4, 2, 3, 3]})
    edges = pd.DataFrame({"u": [1, 2, 3], "v": [2, 3, 4],
                          "highway": ["primary", "residential", "tertiary"],
                          "length": [500., 1000., 1500.]})
    return nodes, edges


def test_proposal_requires_arterial_and_a_real_junction():
    nodes, edges = _net()
    got = propose_from_network(nodes, edges, min_degree=3)
    assert 1 in got            # primary, degree 4
    assert 2 not in got        # degree 2 -- not a junction
    assert 3 in got and 4 in got   # tertiary, degree 3
    assert list(got) == sorted(got)


def test_proposal_excludes_purely_residential_nodes():
    nodes = pd.DataFrame({"osmid": [1, 2], "x": [0., 100.], "y": [0., 0.],
                          "street_count": [5, 5]})
    edges = pd.DataFrame({"u": [1], "v": [2], "highway": ["residential"],
                          "length": [100.]})
    assert len(propose_from_network(nodes, edges)) == 0


def test_arterial_set_excludes_local_streets():
    for h in ("residential", "service", "living_street", "unclassified"):
        assert h not in ARTERIAL


def _parcels(coords, crs="EPSG:32644"):
    polys = [Polygon([(x, y), (x + 50, y), (x + 50, y + 50), (x, y + 50)]) for x, y in coords]
    return gpd.GeoDataFrame(
        {"parcel_id": range(1, len(polys) + 1),
         "land_class": ["amenity=school"] * len(polys)},
        geometry=polys, crs=crs)


def test_candidate_near_a_parcel_is_feasible_and_far_one_is_not():
    nodes, edges = _net()
    parcels = _parcels([(0, 0)])           # only near node 1
    cs = build_candidates(nodes, edges, parcels, "EPSG:32644",
                          min_separation_m=100.0, parcel_snap_m=400.0)
    f = cs.frame.set_index("network_node")
    assert bool(f.loc[1, "land_feasible"]) is True
    assert bool(f.loc[4, "land_feasible"]) is False


def test_infeasible_candidates_are_kept_and_flagged_not_deleted():
    """'No buildable land near the best-serving location' is a finding, so the
    candidate must survive into the output rather than vanish."""
    nodes, edges = _net()
    cs = build_candidates(nodes, edges, _parcels([(0, 0)]), "EPSG:32644",
                          min_separation_m=100.0, parcel_snap_m=400.0)
    assert cs.stats["land_infeasible"] > 0
    assert len(cs.frame) == cs.stats["after_thinning"]
    assert (~cs.frame["land_feasible"]).any()
    assert (cs.frame.loc[~cs.frame["land_feasible"], "land_class"] == "none").all()


def test_candidate_ids_are_contiguous_and_stats_consistent():
    nodes, edges = _net()
    cs = build_candidates(nodes, edges, _parcels([(0, 0), (3000, 0)]), "EPSG:32644",
                          min_separation_m=100.0)
    assert cs.frame["candidate_id"].tolist() == list(range(1, len(cs.frame) + 1))
    assert cs.stats["land_feasible"] + cs.stats["land_infeasible"] == len(cs.frame)


def test_real_candidate_set_is_usable():
    c = gpd.read_parquet("data/interim/candidates.parquet")
    assert len(c) > 200
    assert c["candidate_id"].is_unique
    assert c["land_feasible"].sum() > 100
    assert c.loc[c["land_feasible"], "parcel_distance_m"].max() <= 400.0
