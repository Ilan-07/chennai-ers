"""Demand surface tests. Build step 08."""
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from ers.geo.demand import (assign_wards, cells_for_area, population_to_cells,
                            reconcile_to_wards, service_weights)

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
