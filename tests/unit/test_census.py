"""Census ward-total re-cut tests. Build step 08b."""
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from ers.geo.census import census_ward_targets, ward_population_2011

M = "EPSG:32644"          # the cells below are already metric; to_crs is a no-op


@pytest.fixture
def cells():
    """Three 100 m cells in a row. A and B are in 2022 ward 1, C in ward 2."""
    return gpd.GeoDataFrame(
        {"cell_id": [1, 2, 3],
         "ward_id": [1, 1, 2],
         "population_raw": [10.0, 30.0, 5.0]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100), box(200, 0, 300, 100)],
        crs=M)


@pytest.fixture
def old_ward():
    """One 2008 ward covering cells A and B exactly."""
    return gpd.GeoDataFrame({"ward": [1]}, geometry=[box(0, 0, 200, 100)], crs=M)


def _eb(tmp_path, rows):
    p = tmp_path / "eb.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)


def test_ward_population_sums_enumeration_blocks(tmp_path):
    p = _eb(tmp_path, [{"Ward Number": 1, "Total Population": 100},
                       {"Ward Number": 1, "Total Population": 50},
                       {"Ward Number": 2, "Total Population": 7}])
    pop = ward_population_2011(p)
    assert pop.loc[1] == 150.0
    assert pop.loc[2] == 7.0


def test_ward_population_refuses_a_suppressed_total(tmp_path):
    # '-' means suppressed in the SC/ST columns. Coercing it to zero in the
    # TOTAL column would delete a ward's residents silently.
    p = _eb(tmp_path, [{"Ward Number": 1, "Total Population": "-"}])
    with pytest.raises(ValueError, match="non-numeric"):
        ward_population_2011(p)


def test_targets_conserve_the_city_total(cells, old_ward):
    pop = pd.Series({1: 1000.0})
    targets, rep = census_ward_targets(cells, old_ward, pop, 1500.0, M)
    assert sum(targets.values()) == pytest.approx(1500.0)
    assert rep["census_population"] == 1000.0
    assert rep["residual_population"] == 500.0


def test_census_area_is_allocated_by_raster_mass(cells, old_ward):
    """Within an old ward the census total follows GHS-POP, not area."""
    pop = pd.Series({1: 1000.0})
    targets, _ = census_ward_targets(cells, old_ward, pop, 1500.0, M)
    # Cells A and B are the same size; B holds 3x the modelled population, so the
    # ward's 1000 residents split 250/750 -- and both are in 2022 ward 1.
    assert targets[1] == pytest.approx(1000.0)
    assert targets[2] == pytest.approx(500.0)      # the residual, outside the old ward


def test_split_cells_are_split_not_rounded(old_ward):
    """A cell straddling the 2008 boundary is part censused, part residual."""
    cells = gpd.GeoDataFrame(
        {"cell_id": [1], "ward_id": [1], "population_raw": [10.0]},
        geometry=[box(100, 0, 300, 100)], crs=M)          # half inside old_ward
    targets, rep = census_ward_targets(cells, old_ward, pd.Series({1: 1000.0}), 1500.0, M)
    assert rep["cells_partly_inside_2008"] == 1
    assert rep["cells_fully_inside_2008"] == 0
    assert targets[1] == pytest.approx(1500.0)            # everything lands in ward 1


def test_an_unmodelled_old_ward_keeps_its_residents(cells):
    """A 2008 ward the raster thinks is empty must not lose its census total."""
    cells = cells.copy()
    cells["population_raw"] = [0.0, 0.0, 5.0]             # A and B modelled empty
    old = gpd.GeoDataFrame({"ward": [1]}, geometry=[box(0, 0, 200, 100)], crs=M)
    targets, rep = census_ward_targets(cells, old, pd.Series({1: 1000.0}), 1500.0, M)
    assert rep["wards_2008_without_modelled_population"] == [1]
    assert targets[1] == pytest.approx(1000.0)            # spread by area instead
    assert sum(targets.values()) == pytest.approx(1500.0)


def test_a_city_total_below_the_census_is_refused(cells, old_ward):
    with pytest.raises(ValueError, match="negative population"):
        census_ward_targets(cells, old_ward, pd.Series({1: 1000.0}), 900.0, M)


def test_geometry_without_a_census_total_is_refused(cells):
    old = gpd.GeoDataFrame({"ward": [1, 2]},
                           geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)], crs=M)
    with pytest.raises(ValueError, match="no census total"):
        census_ward_targets(cells, old, pd.Series({1: 1000.0}), 1500.0, M)


def test_report_measures_the_move_against_the_model(cells, old_ward):
    """The report must say how far the census pulls each ward off the model."""
    _, rep = census_ward_targets(cells, old_ward, pd.Series({1: 1000.0}), 1500.0, M)
    # Model shares are 40/45 and 5/45; census shares are 1000/1500 and 500/1500.
    assert rep["ward_target_over_model_min"] == pytest.approx(0.75, abs=1e-3)
    assert rep["ward_target_over_model_max"] == pytest.approx(3.0, abs=1e-3)
    assert rep["wards_moved_over_10pct"] == 2
