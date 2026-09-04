"""Scenario assembly and coverage summary tests. Build step 13."""
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import yaml
from shapely.geometry import LineString, Point, Polygon

from ers import coverage
from ers.flood import CLOSED, WADING, load_flood_points
from ers.scenario import head_delay_seconds, load_scenario

METRIC = "EPSG:32644"
SCENARIO_DIR = Path("config/scenarios")
ALL_SCENARIOS = sorted(p.stem for p in SCENARIO_DIR.glob("*.yml"))


def _nodes():
    # node 1 is signalised, node 2 is a plain degree-3 junction, node 3 is degree 2.
    return pd.DataFrame({"osmid": [1, 2, 3],
                         "street_count": [4, 3, 2],
                         "highway": ["traffic_signals", None, None]})


def _edges():
    return pd.DataFrame({"u": [1, 2, 3], "v": [2, 3, 1]})


SPEEDS = {"junction_delay_s": {"signalised": 12, "unsignalised_degree_ge_3": 5, "other": 0},
          "junction_delay_scale": 0.10}


# --------------------------------------------------------------------- config

@pytest.mark.parametrize("sid", ALL_SCENARIOS)
def test_every_scenario_config_declares_what_the_runner_needs(sid):
    s = load_scenario(SCENARIO_DIR / f"{sid}.yml")
    assert s["id"] == sid, "scenario id must match its filename -- the runner keys on it"
    assert 0.0 <= s["weight"] <= 1.0
    fl = s.get("flood")
    if not fl:
        return
    assert Path(fl["layer"]).exists(), f"{sid} names a flood layer that is not present"
    if fl.get("geometry") == "points":
        assert fl["depth_units"] in ("inches", "in", "m", "cm")
        assert fl["point_buffer_m"] > 0 and fl["closure_depth_m"] > 0
    else:
        # A category mapping that omits a category silently models it as passable,
        # which is the optimistic direction. Require all three to be stated.
        assert set(fl["link_state"]) == {"HIGH", "MODERATE", "LOW"}
        assert set(fl["link_state"].values()) <= {"closed", "wading", "passable"}
    assert 0.0 < fl["wading_speed_factor"] <= 1.0


def test_design_basis_weights_sum_to_one():
    """ASSM A-10. Report-only scenarios carry weight 0 and must not dilute it --
    adding a scenario to the curve must never silently re-cut the design basis."""
    scen = [load_scenario(SCENARIO_DIR / f"{s}.yml") for s in ALL_SCENARIOS]
    design = [s for s in scen if not s["report_only"]]
    assert sum(s["weight"] for s in design) == pytest.approx(1.0)
    assert all(s["weight"] == 0.0 for s in scen if s["report_only"])


def test_report_only_scenarios_are_never_weighted():
    for sid in ALL_SCENARIOS:
        s = load_scenario(SCENARIO_DIR / f"{sid}.yml")
        if s["report_only"]:
            assert s["weight"] == 0.0, f"{sid} is report-only but carries weight"


# --------------------------------------------------------- junction ablation

def test_head_delay_is_credited_at_the_arc_head_node():
    d = head_delay_seconds(_nodes(), _edges(), SPEEDS, junction_scale=1.0)
    # arcs are 1->2, 2->3, 3->1, so the delays are those of nodes 2, 3, 1.
    assert list(d) == [5.0, 0.0, 12.0]


def test_junction_scale_override_beats_the_config_value():
    """The E-10 ablation is exactly this override. If it silently fell back to
    the config the experiment would compare the model against itself."""
    cfg = head_delay_seconds(_nodes(), _edges(), SPEEDS)
    assert cfg == pytest.approx([0.5, 0.0, 1.2])
    assert list(head_delay_seconds(_nodes(), _edges(), SPEEDS, junction_scale=0.0)) == [0, 0, 0]


def test_zero_junction_scale_deletes_the_term_rather_than_shrinking_it():
    d = head_delay_seconds(_nodes(), _edges(), SPEEDS, junction_scale=0.0)
    assert not d.any()


def test_nodes_missing_from_the_node_table_contribute_no_delay():
    edges = pd.DataFrame({"u": [1], "v": [999]})
    assert list(head_delay_seconds(_nodes(), edges, SPEEDS, junction_scale=1.0)) == [0.0]


# ------------------------------------------------------------- 2015 points

def _point_kml(tmp_path, depths):
    g = gpd.GeoDataFrame(
        {"DEPTH": depths,
         "geometry": [Point(80.2 + 0.01 * i, 13.0) for i in range(len(depths))]},
        crs="EPSG:4326")
    p = tmp_path / "pts.geojson"
    g.to_file(p, driver="GeoJSON")
    return p


def test_point_depths_are_converted_from_inches_before_the_threshold_is_applied(tmp_path):
    """The layer is in INCHES and A-08 is in METRES. Comparing the two raw
    numbers would classify a 0.13 m puddle as closed and is the single most
    likely silent error in this scenario."""
    # 6 in = 0.152 m (below 0.30), 20 in = 0.508 m (above).
    z, stats = load_flood_points(_point_kml(tmp_path, [6.0, 20.0]), METRIC,
                                 buffer_m=250, closure_depth_m=0.30)
    assert list(z["_state"]) == [WADING, CLOSED]
    assert stats["depth_m_median"] == pytest.approx(0.33, abs=0.01)


def test_unmeasured_points_are_treated_as_wading_not_dropped(tmp_path):
    z, stats = load_flood_points(_point_kml(tmp_path, [np.nan, 40.0]), METRIC,
                                 buffer_m=250, closure_depth_m=0.30)
    assert list(z["_state"]) == [WADING, CLOSED]
    assert stats["depth_missing"] == 1
    assert stats["features"] == 2, "a reported inundation with no depth is still an inundation"


def test_points_are_buffered_in_the_metric_crs(tmp_path):
    z, _ = load_flood_points(_point_kml(tmp_path, [6.0]), METRIC, buffer_m=250)
    assert z.crs.to_string() == METRIC
    assert z.area.iloc[0] == pytest.approx(np.pi * 250 ** 2, rel=0.01)


def test_unknown_depth_units_are_rejected_rather_than_assumed(tmp_path):
    with pytest.raises(ValueError):
        load_flood_points(_point_kml(tmp_path, [6.0]), METRIC, buffer_m=250,
                          depth_units="furlongs")


# ---------------------------------------------------------------- coverage

def test_unreachable_population_is_reported_separately_from_uncovered():
    """The flood question is 'who is cut off', not 'who is slow'. Collapsing the
    two loses the only number a flood plan is written against."""
    best = np.array([100.0, 500.0, np.inf])
    pop = np.array([10.0, 20.0, 30.0])
    r = coverage.summarise(best, pop, budget_s=300)
    assert r["population_covered"] == 10
    assert r["unreachable_population"] == 30
    assert r["population_outside"] == 50          # slow AND cut off
    assert r["unreachable_share"] == pytest.approx(0.5)


def test_percentiles_are_population_weighted_not_cell_weighted():
    # One populous fast cell and many empty slow ones: the median response of a
    # PERSON is fast, the median response of a CELL is slow.
    best = np.array([100.0, 900.0, 900.0, 900.0])
    pop = np.array([1000.0, 1.0, 1.0, 1.0])
    r = coverage.summarise(best, pop, budget_s=300)
    assert r["p50_travel_s"] == pytest.approx(100.0)


def test_a_fully_severed_network_reports_rather_than_divides_by_zero():
    r = coverage.summarise(np.array([np.inf, np.inf]), np.array([5.0, 5.0]), budget_s=300)
    assert r["coverage_share"] == 0.0
    assert r["unreachable_share"] == 1.0
    assert r["p90_travel_s"] is None


def test_threshold_ladder_is_monotone_in_the_budget():
    best = np.array([100.0, 250.0, 400.0, np.inf])
    pop = np.ones(4)
    r = coverage.summarise(best, pop, budget_s=300,
                           ladder={"tight": 240, "loose": 420})
    assert (r["threshold_ladder"]["tight"]["coverage_share"]
            <= r["threshold_ladder"]["loose"]["coverage_share"])
