"""Graph table serialisation. Regression test for the Arrow failure that lost
25 minutes of intersection consolidation."""
import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from ers.geo.graph import decode_list_columns, encode_list_columns


def _gdf(**cols):
    n = len(next(iter(cols.values())))
    return gpd.GeoDataFrame(cols, geometry=[Point(i, i) for i in range(n)], crs="EPSG:4326")


def test_mixed_list_and_scalar_column_survives_roundtrip():
    """`osmid_original` holds a list for consolidated nodes and a scalar for
    the rest. Arrow rejects that column outright."""
    g = _gdf(osmid_original=[123, [456, 789], 101])
    enc, cols = encode_list_columns(g)
    assert "osmid_original" in cols
    assert enc["osmid_original"].map(type).eq(str).all()   # uniform dtype for Arrow
    dec = decode_list_columns(enc, cols)
    assert dec["osmid_original"].tolist() == [123, [456, 789], 101]


def test_mixed_column_is_writable_by_arrow(tmp_path):
    g = _gdf(osmid_original=[123, [456, 789], 101])
    with pytest.raises(Exception):
        g.to_parquet(tmp_path / "raw.parquet")     # the original failure
    enc, _ = encode_list_columns(g)
    enc.to_parquet(tmp_path / "ok.parquet")        # now writes
    assert (tmp_path / "ok.parquet").exists()


def test_highway_lists_are_preserved_for_attribution():
    """Attribution needs the real list -- a merged way is only as fast as its
    slowest tagged segment, so flattening here would change travel times."""
    from ers.geo.attrs import parse_maxspeed, primary_highway
    g = _gdf(highway=["residential", ["tertiary", "primary"]],
             maxspeed=["40", ["30", "50"]])
    enc, cols = encode_list_columns(g)
    dec = decode_list_columns(enc, cols)
    assert primary_highway(dec["highway"].iloc[1]) == "primary"
    assert parse_maxspeed(dec["maxspeed"].iloc[1]) == 30.0


def test_scalar_only_object_column_is_left_usable():
    g = _gdf(name=["Anna Salai", "Mount Road", None])
    enc, cols = encode_list_columns(g)
    assert "name" not in cols
    assert enc["name"].iloc[0] == "Anna Salai"


def test_geometry_column_is_never_encoded():
    g = _gdf(osmid_original=[1, [2, 3]])
    enc, cols = encode_list_columns(g)
    assert enc.geometry.iloc[0].geom_type == "Point"
    assert "geometry" not in cols


def test_nulls_survive_roundtrip():
    g = _gdf(maxheight=[None, [3.5], "4.0"])
    enc, cols = encode_list_columns(g)
    dec = decode_list_columns(enc, cols)
    assert dec["maxheight"].iloc[0] is None
    assert dec["maxheight"].iloc[1] == [3.5]


def test_connectivity_report_distinguishes_weak_from_strong():
    """A one-way pair A->B with no return path is weakly connected but not
    strongly connected. Using weak connectivity would call B reachable from
    A *and* A reachable from B, which a vehicle cannot do."""
    import numpy as np
    from scipy import sparse
    from ers.geo.graph import connectivity_report

    # 0 -> 1 -> 2, no return arcs.
    m = sparse.csr_matrix((np.array([1.0, 1.0]), (np.array([0, 1]), np.array([1, 2]))),
                          shape=(3, 3))
    rep = connectivity_report(m)
    assert rep["weak_components"] == 1
    assert rep["largest_weak_share"] == 1.0
    assert rep["strong_components"] == 3          # every node its own SCC
    assert rep["nodes_outside_largest_scc"] == 2


def test_connectivity_report_on_a_cycle():
    import numpy as np
    from scipy import sparse
    from ers.geo.graph import connectivity_report
    m = sparse.csr_matrix((np.ones(3), (np.array([0, 1, 2]), np.array([1, 2, 0]))), shape=(3, 3))
    rep = connectivity_report(m)
    assert rep["strong_components"] == 1
    assert rep["largest_strong_share"] == 1.0
