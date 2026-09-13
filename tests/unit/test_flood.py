"""Flood-as-graph-perturbation tests. Build step 12."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from ers.flood import CLOSED, PASSABLE, WADING, classify_arcs, flood_factors

METRIC = "EPSG:32644"
LINK_STATE = {"HIGH": "closed", "MODERATE": "wading", "LOW": "passable"}


def _zone(x0, x1, category):
    return {"CATEGORY": category,
            "geometry": Polygon([(x0, -10), (x1, -10), (x1, 10), (x0, 10)])}


def _edges(spans, bridge=None):
    """One arc per (x0, x1) span, laid end to end along y=0."""
    g = [LineString([(a, 0), (b, 0)]) for a, b in spans]
    df = gpd.GeoDataFrame({"length": [abs(b - a) for a, b in spans], "geometry": g},
                          crs=METRIC)
    if bridge is not None:
        df["bridge"] = bridge
    return df


def test_arc_takes_the_worst_state_it_touches():
    """A link is only as passable as its worst point. A mean rule here would be
    dangerously optimistic: it would report a road with 50 m under water as
    mostly fine."""
    zones = gpd.GeoDataFrame([_zone(0, 100, "LOW"), _zone(90, 200, "HIGH")], crs=METRIC)
    # The arc spans both zones, one benign and one impassable.
    states, stats = classify_arcs(_edges([(0, 150)]), zones, link_state=LINK_STATE)
    assert states[0] == CLOSED
    assert stats["closed"] == 1


def test_categories_absent_from_the_mapping_are_left_passable():
    zones = gpd.GeoDataFrame([_zone(0, 100, "UNKNOWN_CATEGORY")], crs=METRIC)
    states, _ = classify_arcs(_edges([(0, 50)]), zones, link_state=LINK_STATE)
    assert states[0] == PASSABLE


def test_low_category_is_modelled_as_no_effect():
    zones = gpd.GeoDataFrame([_zone(0, 100, "LOW")], crs=METRIC)
    states, _ = classify_arcs(_edges([(0, 50)]), zones, link_state=LINK_STATE)
    assert states[0] == PASSABLE


def test_bridge_deck_is_demoted_from_closed_to_wading_not_to_passable():
    """A bridge deck stays above the water; its approach ramps may not. The
    exemption must therefore stop at 'wading' -- promoting a flooded bridge all
    the way to 'passable' would model it as unaffected."""
    zones = gpd.GeoDataFrame([_zone(0, 100, "HIGH")], crs=METRIC)
    states, stats = classify_arcs(_edges([(0, 50)], bridge=["yes"]), zones,
                                  link_state=LINK_STATE)
    assert states[0] == WADING
    assert stats["bridges_exempted_from_closure"] == 1


def test_bridges_exempt_false_leaves_the_deck_closed():
    zones = gpd.GeoDataFrame([_zone(0, 100, "HIGH")], crs=METRIC)
    states, _ = classify_arcs(_edges([(0, 50)], bridge=["yes"]), zones,
                              link_state=LINK_STATE, bridges_exempt=False)
    assert states[0] == CLOSED


def test_untagged_bridge_column_is_not_treated_as_a_bridge():
    zones = gpd.GeoDataFrame([_zone(0, 100, "HIGH")], crs=METRIC)
    states, _ = classify_arcs(_edges([(0, 50)], bridge=[None]), zones,
                              link_state=LINK_STATE)
    assert states[0] == CLOSED


def test_arcs_outside_every_zone_are_untouched():
    zones = gpd.GeoDataFrame([_zone(0, 10, "HIGH")], crs=METRIC)
    states, stats = classify_arcs(_edges([(0, 5), (100, 200)]), zones,
                                  link_state=LINK_STATE)
    assert list(states) == [CLOSED, PASSABLE]
    assert stats["length_share_closed"] == pytest.approx(5 / 105, abs=1e-4)


def test_closed_arcs_get_a_zero_factor_so_they_leave_the_graph():
    """0.0 is load-bearing: it drives the traversal time to infinity, which
    build_graph drops. A small factor would leave the road usable and turn an
    unreachable cell into a merely slow one."""
    f = flood_factors(np.array([CLOSED, WADING, PASSABLE], dtype=object),
                      wading_speed_factor=0.35)
    assert list(f) == [0.0, 0.35, 1.0]


def test_no_flooded_zones_leaves_every_arc_passable():
    zones = gpd.GeoDataFrame([_zone(0, 100, "LOW")], crs=METRIC)
    states, stats = classify_arcs(_edges([(0, 50), (50, 100)]), zones,
                                  link_state=LINK_STATE)
    assert set(states) == {PASSABLE}
    assert stats["closed"] == 0 and stats["wading"] == 0


# ------------------------------------------------------- layer extent (item 3)

from shapely.geometry import box as _box          # noqa: E402

from ers.flood import scenario_extent_coverage    # noqa: E402


def _scn(layer, **flood):
    return {"id": "test", "flood": {"layer": layer, **flood}}


def test_a_dry_scenario_needs_no_layer():
    r = scenario_extent_coverage({"id": "dry"}, _box(0, 0, 1, 1), "EPSG:32644")
    assert r["applicable"] is True
    assert r["network_state"] == "dry"


def test_a_layer_drawn_for_a_smaller_city_is_refused(tmp_path, monkeypatch):
    """The defect: a corporation flood model asked about the whole metro."""
    import ers.flood as fl

    small = gpd.GeoDataFrame(
        {"CATEGORY": ["HIGH"]}, geometry=[_box(0, 0, 1000, 1000)],
        crs="EPSG:32644")
    monkeypatch.setattr(fl, "load_flood_zones", lambda *a, **k: (small, {}))

    inside = scenario_extent_coverage(_scn("x.kml"), _box(0, 0, 1000, 1000),
                                      "EPSG:32644")
    assert inside["applicable"] is True

    # Same layer, a study area four times the size.
    wider = scenario_extent_coverage(_scn("x.kml"), _box(0, 0, 2000, 2000),
                                     "EPSG:32644")
    assert wider["applicable"] is False
    assert wider["domain_covers_study_area"] == pytest.approx(0.25, abs=1e-6)
    assert "smaller city" in wider["reason"]


def test_an_observed_point_layer_is_judged_by_its_declared_source(monkeypatch):
    """A sample's hull is not its domain, so it must not be used as one."""
    import ers.flood as fl

    pts = gpd.GeoDataFrame(
        {"state": ["closed"]}, geometry=[_box(0, 0, 100, 100)], crs="EPSG:32644")
    monkeypatch.setattr(fl, "load_flood_points", lambda *a, **k: (pts, {}))
    scn = _scn("p.kml", geometry="points", point_buffer_m=250, sourced_for="gcc")

    # Tiny hull, but it is the declared source that decides.
    assert scenario_extent_coverage(scn, _box(0, 0, 5000, 5000), "EPSG:32644",
                                    profile="gcc")["applicable"] is True
    out = scenario_extent_coverage(scn, _box(0, 0, 5000, 5000), "EPSG:32644",
                                   profile="metro")
    assert out["applicable"] is False
    assert "nobody looked" in out["reason"]
