"""Demand surface tests. Build step 08."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from ers.geo.demand import (RISK_PRIORITY, assign_wards, cells_for_area,
                            disjoint_risk_classes, landuse_risk_weights,
                            population_to_cells, reconcile_to_wards,
                            service_weights)

RES = 9


@pytest.fixture(scope="module")
def area():
    # ~2.5 km box over central Chennai.
    return gpd.GeoDataFrame(
        {"ward_id": [1]}, geometry=[box(80.26, 13.07, 80.29, 13.10)], crs="EPSG:4326")


@pytest.fixture(scope="module")
def raster(tmp_path_factory):
    """A 100 m-ish grid with a known total population."""
    p = tmp_path_factory.mktemp("r") / "pop.tif"
    h = w = 30
    arr = np.full((h, w), 10.0, dtype="float32")
    arr[0, 0] = -9999.0                                  # nodata must be excluded
    tr = from_origin(80.26, 13.10, 0.001, 0.001)
    with rasterio.open(p, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs="EPSG:4326", transform=tr,
                       nodata=-9999.0) as dst:
        dst.write(arr, 1)
    return str(p), float((h * w - 1) * 10.0)


def test_cells_cover_area_and_are_deterministic(area):
    a = cells_for_area(area, RES)
    b = cells_for_area(area, RES)
    assert len(a) > 0
    assert a["h3_index"].tolist() == b["h3_index"].tolist()      # sorted -> stable
    assert a["cell_id"].tolist() == list(range(1, len(a) + 1))
    assert a["h3_index"].is_unique


def test_cells_are_polygons_in_wgs84(area):
    a = cells_for_area(area, RES)
    assert a.crs.to_epsg() == 4326
    assert set(a.geometry.geom_type) == {"Polygon"}


def test_higher_resolution_yields_more_cells(area):
    assert len(cells_for_area(area, 10)) > len(cells_for_area(area, 9))


def test_population_aggregation_conserves_mass(area, raster):
    path, total = raster
    cells = cells_for_area(area, RES)
    pop, rep = population_to_cells(path, cells, RES)
    assert rep["raster_population"] == pytest.approx(total, rel=1e-6)
    # Every person is either placed or explicitly counted as outside.
    assert (rep["population_placed_in_cells"]
            + rep["population_outside_study_area"]) == pytest.approx(total, rel=1e-6)
    assert rep["mass_balance_ok"]


def test_nodata_pixels_are_excluded(area, raster):
    path, total = raster
    cells = cells_for_area(area, RES)
    _, rep = population_to_cells(path, cells, RES)
    assert rep["populated_pixels"] == 30 * 30 - 1        # the -9999 cell is gone
    assert rep["raster_population"] == pytest.approx(total)


def _cells(pop, wards):
    g = gpd.GeoDataFrame(
        {"cell_id": range(1, len(pop) + 1), "population": pop, "ward_id": wards,
         "h3_index": [f"c{i}" for i in range(len(pop))]},
        geometry=[Polygon([(0, 0), (0, 1), (1, 1)])] * len(pop), crs="EPSG:4326")
    return g


def test_reconciliation_makes_ward_sums_exact():
    cells = _cells([10.0, 30.0, 5.0, 5.0], [1, 1, 2, 2])
    out, rep = reconcile_to_wards(cells, {1: 200.0, 2: 50.0})
    assert out[cells["ward_id"] == 1].sum() == pytest.approx(200.0)
    assert out[cells["ward_id"] == 2].sum() == pytest.approx(50.0)
    assert rep["total_after"] == pytest.approx(250.0)


def test_reconciliation_preserves_within_ward_shape():
    """WorldPop models the within-ward distribution; only the magnitude is fixed."""
    cells = _cells([10.0, 30.0], [1, 1])
    out, _ = reconcile_to_wards(cells, {1: 400.0})
    assert out.iloc[1] / out.iloc[0] == pytest.approx(3.0)


def test_ward_with_no_modelled_population_is_not_dropped():
    """A real census ward that WorldPop shows as empty must keep its residents."""
    cells = _cells([0.0, 0.0], [1, 1])
    out, rep = reconcile_to_wards(cells, {1: 100.0})
    assert out.sum() == pytest.approx(100.0)
    assert rep["wards_with_no_modelled_population"] == [1]


def test_missing_ward_is_reported_not_silently_ignored():
    cells = _cells([10.0], [1])
    _, rep = reconcile_to_wards(cells, {1: 10.0, 99: 500.0})
    assert rep["wards_missing_cells"] == [99]


def test_ems_weight_favours_older_wards():
    cells = _cells([100.0, 100.0], [1, 2])
    w = service_weights(cells, w0=0.6, w1=1.6,
                        share_60plus=pd.Series({1: 0.05, 2: 0.20}))
    assert w.iloc[1] > w.iloc[0]
    assert w.iloc[0] == pytest.approx(100 * (0.6 + 1.6 * 0.05))


def test_ems_weight_is_monotone_in_age_share():
    cells = _cells([100.0], [1])
    prev = -1.0
    for s in (0.0, 0.05, 0.1, 0.2, 0.3):
        v = float(service_weights(cells, w0=0.6, w1=1.6, share_60plus=pd.Series({1: s})).iloc[0])
        assert v > prev
        prev = v


# -------------------------------------------------- A-07 land-use risk (F-29)
#
# The defect these exist for: OSM land-use polygons overlap, the weighting summed
# intersection areas over them, and the "area-weighted mean" it documented could
# then exceed every multiplier that went into it. 15 cells came back above 1.0
# when every multiplier was 1.0. Nothing failed; the surface just got quietly
# heavier in the commercial core.

MULT = {"residential": 1.0, "commercial": 1.8, "industrial": 3.0, "hazardous": 5.0}
METRIC = "EPSG:32644"


def _lu_cells(*boxes):
    g = gpd.GeoDataFrame(
        {"cell_id": [f"c{i}" for i in range(len(boxes))],
         "population": [100.0] * len(boxes)},
        geometry=list(boxes), crs="EPSG:4326")
    return g


def _parcels(*pairs):
    return gpd.GeoDataFrame({"risk_class": [c for c, _ in pairs]},
                            geometry=[g for _, g in pairs], crs="EPSG:4326")


def test_identity_multipliers_return_exactly_one_everywhere():
    """The E-06 control. A mean cannot escape the range of its inputs."""
    cell = box(80.26, 13.07, 80.27, 13.08)
    # Two commercial parcels describing the SAME ground, as OSM routinely does.
    p = _parcels(("commercial", box(80.262, 13.072, 80.268, 13.078)),
                 ("commercial", box(80.263, 13.073, 80.267, 13.077)))
    w, rep = landuse_risk_weights(_lu_cells(cell), p, {k: 1.0 for k in MULT}, METRIC)
    assert rep["cell_multiplier_max"] == pytest.approx(1.0, abs=1e-9)
    assert rep["cell_multiplier_min"] == pytest.approx(1.0, abs=1e-9)
    assert float(w.iloc[0]) == pytest.approx(100.0, abs=1e-6)


def test_a_parcel_drawn_twice_is_not_charged_twice():
    """A duplicate polygon must not change the surface at all."""
    cell = box(80.26, 13.07, 80.27, 13.08)
    one = _parcels(("industrial", box(80.262, 13.072, 80.268, 13.078)))
    twice = _parcels(("industrial", box(80.262, 13.072, 80.268, 13.078)),
                     ("industrial", box(80.262, 13.072, 80.268, 13.078)))
    a, _ = landuse_risk_weights(_lu_cells(cell), one, MULT, METRIC)
    b, _ = landuse_risk_weights(_lu_cells(cell), twice, MULT, METRIC)
    assert float(a.iloc[0]) == pytest.approx(float(b.iloc[0]), rel=1e-9)


def test_the_cell_multiplier_stays_inside_the_multiplier_range():
    """Heavily overlapped ground was where the old code went out of range."""
    cell = box(80.26, 13.07, 80.27, 13.08)
    stack = _parcels(*[("commercial", box(80.261 + 0.0002 * i, 13.071,
                                          80.269 - 0.0002 * i, 13.079))
                       for i in range(6)])
    _, rep = landuse_risk_weights(_lu_cells(cell), stack, MULT, METRIC)
    assert 1.0 - 1e-9 <= rep["cell_multiplier_min"]
    assert rep["cell_multiplier_max"] <= 5.0 + 1e-9


def test_priority_decides_which_class_holds_shared_ground():
    """The modelling decision, made explicit: hazardous outranks residential."""
    cell = box(80.26, 13.07, 80.27, 13.08)
    shared = box(80.262, 13.072, 80.268, 13.078)
    p = _parcels(("residential", shared), ("hazardous", shared))
    hi, _ = landuse_risk_weights(_lu_cells(cell), p, MULT, METRIC)
    lo, _ = landuse_risk_weights(_lu_cells(cell), p, MULT, METRIC,
                                 priority=["residential", "commercial",
                                           "industrial", "hazardous"])
    assert float(hi.iloc[0]) > float(lo.iloc[0])
    # Risk-ascending hands the ground to residential, which is the base rate,
    # so the cell is then indistinguishable from unmapped ground.
    assert float(lo.iloc[0]) == pytest.approx(100.0, abs=1e-6)


def test_a_class_missing_from_the_priority_list_is_not_dropped():
    """An unnamed class must rank last, not vanish from the surface."""
    cell = box(80.26, 13.07, 80.27, 13.08)
    p = _parcels(("industrial", box(80.262, 13.072, 80.268, 13.078)))
    w, rep = landuse_risk_weights(_lu_cells(cell), p, MULT, METRIC,
                                  priority=["hazardous", "commercial"])
    assert rep["overlap_resolution"]["classes_not_in_priority"] == ["industrial"]
    assert float(w.iloc[0]) > 100.0


def test_resolved_parcels_cover_no_more_ground_than_they_started_with():
    p = _parcels(("commercial", box(80.262, 13.072, 80.268, 13.078)),
                 ("industrial", box(80.264, 13.074, 80.270, 13.080)),
                 ("industrial", box(80.264, 13.074, 80.270, 13.080)))
    g, rep = disjoint_risk_classes(p.to_crs(METRIC), RISK_PRIORITY)
    assert rep["area_m2_after"] < rep["area_m2_before"]
    assert g.geometry.union_all().area == pytest.approx(rep["area_m2_after"], abs=0.05)
    # Disjoint means disjoint: the pieces must not overlap each other.
    assert float(g.area.sum()) == pytest.approx(
        g.geometry.union_all().area, rel=1e-9)
