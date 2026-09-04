"""Station inventory tests. All offline -- no network in CI."""
import csv
import json
from pathlib import Path

import pytest

from ers.io.stations import (
    SURVEY_REQUIRED, _norm, _plausibility, load_authoritative,
    load_osm_points, qa_report, resolve, survey_worklist,
)

AUTH = Path("data/reference/tnfrs_stations_gcc.csv")
OSM = Path("data/raw/osm_stations_overpass.json")
BBOX = (12.80, 80.05, 13.30, 80.40)


def test_authoritative_list_has_33_stations():
    """Finding F-01: the source deck assumed five. GCC publishes 33."""
    rows = load_authoritative(AUTH)
    assert len(rows) == 33
    counts = {}
    for r in rows:
        counts[r["division"]] = counts.get(r["division"], 0) + 1
    assert counts == {
        "Chennai City North": 9,
        "Chennai City South": 9,
        "Chennai City Central": 7,
        "Chennai Suburban": 8,
    }


def test_no_duplicate_station_names():
    names = [r["station_name"] for r in load_authoritative(AUTH)]
    assert len(names) == len(set(names))


def test_norm_strips_non_discriminating_tokens():
    assert _norm("Esplanade Fire Station") == _norm("Esplanade")
    assert _norm("Washermanpet Fire & Rescue Station") == _norm("Washermanpet")
    assert _norm("Teynampet FS") == _norm("Teynampet")
    assert _norm("Mylapore") != _norm("Guindy")


@pytest.mark.parametrize("cat,typ,expected", [
    ("amenity", "fire_station", "ok"),
    ("place", "suburb", "settlement_centroid"),
    ("railway", "station", "transit_feature"),
    ("highway", "primary", "road_feature"),
    ("boundary", "administrative", "boundary_centroid"),
    ("amenity", "clinic", "unrelated_feature"),
])
def test_plausibility_taxonomy(cat, typ, expected):
    assert _plausibility({"category": cat, "type": typ}) == expected


def test_plausibility_reads_jsonv2_category_key():
    """jsonv2 returns `category`, not `class`. Reading the wrong key silently
    collapsed every result into one bucket."""
    assert _plausibility({"category": "highway", "type": "primary"}) == "road_feature"


def test_offline_resolve_matches_only_osm_and_leaves_rest_unresolved():
    rows = resolve(AUTH, OSM, BBOX, use_nominatim=False)
    assert len(rows) == 33
    matched = [r for r in rows if r.geocode_confidence == "osm"]
    assert len(matched) == 4
    assert {r.station_name for r in matched} == {
        "Esplanade", "Washermanpet", "Teynampet", "Egmore"}
    assert all(r.lat is None for r in rows if r.geocode_confidence == "inferred")


def test_osm_coverage_is_incomplete_and_that_is_recorded():
    """OSM carries 16 fire-station features over the GCC bbox against 33
    authoritative stations. The gap is a finding, not something to paper over."""
    osm = load_osm_points(OSM)
    auth = load_authoritative(AUTH)
    assert len(osm) < len(auth)


def test_publish_gate_blocks_provisional_positions():
    rows = resolve(AUTH, OSM, BBOX, use_nominatim=False)
    rep = qa_report(rows)
    assert rep["passes_publish_gate"] is False
    assert rep["total"] == 33


def test_survey_worklist_covers_every_provisional_station():
    rows = resolve(AUTH, OSM, BBOX, use_nominatim=False)
    work = survey_worklist(rows, load_authoritative(AUTH))
    provisional = [r for r in rows if r.geocode_confidence in SURVEY_REQUIRED]
    assert len(work) == len(provisional) == 29
    assert all("verified_lat" in w for w in work)


def test_committed_artifacts_are_consistent():
    """The checked-in resolution must still describe 33 stations with coords."""
    rows = list(csv.DictReader(Path("data/interim/stations_resolved.csv").open()))
    assert len(rows) == 33
    assert all(r["lat"] and r["lon"] for r in rows)
    qa = json.loads(Path("data/interim/stations_qa.json").read_text())
    assert qa["total"] == 33
    assert qa["passes_publish_gate"] is False   # 29 still provisional
    assert qa["runnable"] is True               # but the pipeline can run


# --------------------------------------------------------------------------
# Survey ingestion
# --------------------------------------------------------------------------

from ers.io.stations import ResolvedStation, haversine_m, ingest_survey


def _stub(name="Mylapore", lat=13.0316, lon=80.2700, conf="locality"):
    return ResolvedStation(name, "Chennai City South", "fire", lat, lon,
                           conf, "nominatim_locality", "d", 900.0, True,
                           "place", "suburb", "settlement_centroid")


def _row(name="Mylapore", lat="", lon="", by="IY"):
    return {"station_name": name, "verified_lat": lat, "verified_lon": lon, "verified_by": by}


def test_haversine_against_known_degree():
    # One degree of latitude is ~111.2 km anywhere on the globe.
    assert 111000 < haversine_m(13.08, 80.27, 14.08, 80.27) < 111400
    # One degree of longitude at Chennai's latitude (~13.08N) is ~108.4 km.
    assert 108000 < haversine_m(13.08, 80.27, 13.08, 81.27) < 108800


def test_accepted_survey_upgrades_confidence_and_clears_flag():
    rows = [_stub()]
    merged, rep = ingest_survey(rows, [_row(lat="13.03400", lon="80.26900")], BBOX)
    assert rep["accepted"] == 1
    m = merged[0]
    assert m.geocode_confidence == "surveyed"
    assert m.survey_required is False
    assert m.uncertainty_m == 25
    assert m.lat == pytest.approx(13.034)


def test_blank_row_stays_open_and_does_not_corrupt_the_record():
    rows = [_stub()]
    merged, rep = ingest_survey(rows, [_row()], BBOX)
    assert rep["still_open"] == ["Mylapore"]
    assert merged[0].geocode_confidence == "locality"


def test_point_outside_bbox_is_rejected():
    merged, rep = ingest_survey([_stub()], [_row(lat="19.07", lon="72.87")], BBOX)  # Mumbai
    assert rep["accepted"] == 0
    assert rep["rejected"][0]["reason"] == "outside city bbox"
    assert merged[0].geocode_confidence == "locality"


def test_unparseable_coordinate_is_rejected():
    _, rep = ingest_survey([_stub()], [_row(lat="13.0N", lon="80.2")], BBOX)
    assert rep["rejected"][0]["reason"] == "unparseable coordinate"


def test_unknown_station_name_is_rejected():
    _, rep = ingest_survey([_stub()], [_row(name="Nowhere", lat="13.03", lon="80.27")], BBOX)
    assert rep["rejected"][0]["reason"] == "unknown station name"


def test_large_move_is_flagged_but_still_accepted():
    """The geocoder was 9-20 km off for several stations, so a big move is
    expected -- it must be surfaced for confirmation, not silently applied."""
    rows = [_stub(lat=13.1075, lon=80.2062)]          # the bad "Redhills Road" hit
    merged, rep = ingest_survey(rows, [_row(lat="13.19500", lon="80.18300")], BBOX)
    assert rep["accepted"] == 1
    assert len(rep["large_moves_for_review"]) == 1
    assert rep["large_moves_for_review"][0]["moved_m"] > 3000
    assert merged[0].geocode_confidence == "surveyed"


def test_gate_opens_only_when_every_station_is_verified():
    rows = [_stub("Mylapore"), _stub("Guindy", 13.0086, 80.2126)]
    _, rep = ingest_survey(rows, [_row("Mylapore", "13.034", "80.269")], BBOX)
    assert rep["gate"]["passes_publish_gate"] is False
    _, rep2 = ingest_survey(rows, [_row("Mylapore", "13.034", "80.269"),
                                   _row("Guindy", "13.010", "80.213")], BBOX)
    assert rep2["gate"]["passes_publish_gate"] is True


def test_google_maps_poi_does_not_open_the_publish_gate():
    """E-11c adopted Google Maps POIs for the 29 unsurveyed stations. They are a
    much better geocode -- and still not a verification. If this class ever falls
    out of SURVEY_REQUIRED the gate opens on desk research, which is the exact
    failure the gate exists to prevent."""
    from ers.io.stations import CONFIDENCE, SURVEY_REQUIRED, UNCERTAINTY_M
    assert "google_maps_poi" in CONFIDENCE
    assert "google_maps_poi" in SURVEY_REQUIRED
    assert UNCERTAINTY_M["google_maps_poi"] < UNCERTAINTY_M["locality"]


def test_publish_gate_stays_closed_for_a_maps_positioned_network():
    from ers.io.stations import ResolvedStation, qa_report
    rows = [ResolvedStation("A", "d", "fire", 13.0, 80.0, "google_maps_poi",
                            "google_maps_poi_lookup", "A Fire Station", 50.0, True)]
    rep = qa_report(rows)
    assert rep["passes_publish_gate"] is False
    assert rep["survey_required"] == ["A"]


def test_only_surveyed_and_osm_clear_the_gate():
    from ers.io.stations import CONFIDENCE, SURVEY_REQUIRED
    assert set(CONFIDENCE) - set(SURVEY_REQUIRED) == {"surveyed", "osm"}
