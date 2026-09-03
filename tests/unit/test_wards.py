"""Ward/zone boundary tests. Build step 04."""
import warnings
from pathlib import Path

import geopandas as gpd
import pytest
import yaml

from ers.geo.wards import (_clean_text, _zone_number, assign_zones, load_wards,
                           load_zones, validate)

warnings.filterwarnings("ignore")

WARD_KML = Path("data/raw/Chennai_GCC_Ward_Map_2022.kml")
ZONE_KML = Path("data/raw/Chennai_GCC_Zones_Map_2022.kml")
CFG = yaml.safe_load(Path("config/city/chennai.yml").read_text())


@pytest.mark.parametrize("raw,expected", [
    ("IV", 4), ("ZONE - IV", 4), ("zone - iv", 4), ("  XV  ", 15),
    ("I", 1), ("\n  III \n", 3),
])
def test_zone_number_normalises_inconsistent_labels(raw, expected):
    """The KML mixes 'ZONE - IV' and 'IV' in the same column."""
    assert _zone_number(raw) == expected


@pytest.mark.parametrize("bad", ["", "nan", "None", "XVI", "Zone 4"])
def test_zone_number_rejects_unparseable(bad):
    assert _zone_number(bad) is None


def test_clean_text_collapses_kml_whitespace():
    assert _clean_text("\n    168\n  ") == "168"


@pytest.fixture(scope="module")
def wards():
    w, rep = load_wards(str(WARD_KML))
    return w, rep


def test_ward_count_is_200(wards):
    w, rep = wards
    assert len(w) == 200 == CFG["wards"]
    assert rep["dropped_without_ward_number"] == 0


def test_invalid_geometries_are_repaired_and_counted(wards):
    w, rep = wards
    assert rep["invalid_geometries_repaired"] == 9   # not silently swallowed
    assert rep["invalid_geometries_remaining"] == 0
    assert bool(w.geometry.is_valid.all())


def test_ward_numbers_are_contiguous(wards):
    w, _ = wards
    assert sorted(int(x) for x in w["ward_no"]) == list(range(1, 201))


def test_zones_drop_the_empty_kml_feature():
    z, rep = load_zones(str(ZONE_KML))
    assert len(z) == 15 == CFG["zones"]
    assert rep["dropped_empty_features"] == 1
    assert sorted(z["zone_no"]) == list(range(1, 16))


def test_every_ward_is_assigned_a_zone(wards):
    w, _ = wards
    z, _ = load_zones(str(ZONE_KML))
    joined, rep = assign_zones(w, z, CFG["crs"]["metric"])
    assert rep["wards_without_zone"] == 0
    assert joined.groupby("zone_no").size().sum() == 200


def test_area_gate_against_published_gcc_area(wards):
    w, _ = wards
    z, _ = load_zones(str(ZONE_KML))
    joined, _ = assign_zones(w, z, CFG["crs"]["metric"])
    v = validate(joined, CFG)
    assert v["passes"] is True
    assert abs(v["area_delta_pct"]) <= 2.0


def test_area_gate_fails_when_tolerance_is_tightened(wards):
    """The gate must actually be capable of failing -- a check that can only
    pass is not a check."""
    w, _ = wards
    v = validate(w, CFG, tol_pct=0.5)
    assert v["area_within_tolerance"] is False
    assert v["passes"] is False


def test_persisted_wards_parquet_matches(wards):
    saved = gpd.read_parquet("data/interim/wards.parquet")
    assert len(saved) == 200
    assert set(["ward_id", "ward_no", "zone_no", "zone_name", "region"]).issubset(saved.columns)
    assert saved.crs.to_string() == "EPSG:4326"
