"""The publish-gate path -- the one code path the whole project is waiting on.

`ingest_survey` is what converts 29 field visits into an open publish gate, and
before the 2026-09 repair it had no test at all. Everything else in the project
is blocked behind it, and it was the least exercised code in the repository.

These tests are about REFUSAL. The gate exists to stop bad positions reaching a
published coverage figure, so the cases that matter are the ones where it must
say no.
"""
from __future__ import annotations

import pytest

from ers.io.stations import (UNCERTAINTY_M, ResolvedStation, ingest_survey,
                             qa_report)

BBOX = (12.80, 80.05, 13.30, 80.40)          # south, west, north, east


def _station(name="Kilpauk", lat=13.078, lon=80.241, conf="google_maps_poi"):
    return ResolvedStation(
        name, "Chennai City Central", "fire", lat, lon, conf,
        "google_maps_poi_lookup", "Kilpauk Fire Station [Fire station]",
        UNCERTAINTY_M[conf], conf != "osm", "", "", "named_fire_station", "")


def _row(name="Kilpauk", lat="13.0781", lon="80.2412", by="IY"):
    return {"station_name": name, "verified_lat": lat, "verified_lon": lon,
            "verified_by": by}


# ------------------------------------------------------------------ accepts

def test_a_verified_position_is_accepted_and_promoted_to_surveyed():
    rows = [_station()]
    merged, rep = ingest_survey(rows, [_row()], BBOX)
    assert rep["accepted"] == 1 and not rep["rejected"]
    assert merged[0].geocode_confidence == "surveyed"
    assert merged[0].survey_required is False
    assert merged[0].uncertainty_m == UNCERTAINTY_M["surveyed"]
    assert "IY" in merged[0].match_detail


def test_the_gate_opens_only_when_every_station_is_surveyed():
    rows = [_station("Kilpauk"), _station("Vepery", 13.085, 80.259)]

    _, rep = ingest_survey(rows, [_row("Kilpauk")], BBOX)
    assert rep["gate"]["passes_publish_gate"] is False, "one of two is not enough"
    assert rep["still_open"] == [] or "Vepery" not in rep["accepted"]

    merged, rep = ingest_survey(
        rows, [_row("Kilpauk"), _row("Vepery", "13.0851", "80.2591")], BBOX)
    assert rep["gate"]["passes_publish_gate"] is True


def test_an_osm_station_does_not_block_the_gate():
    """`osm` is above the survey threshold; only the 29 provisional ones block."""
    rows = [_station("Egmore", conf="osm"), _station("Kilpauk")]
    _, rep = ingest_survey(rows, [_row("Kilpauk")], BBOX)
    assert rep["gate"]["passes_publish_gate"] is True


# ------------------------------------------------------------------ refuses

def test_a_point_outside_the_city_bbox_is_rejected():
    """The failure mode this exists for: a coordinate transposed or mistyped."""
    _, rep = ingest_survey([_station()], [_row(lat="80.2412", lon="13.0781")], BBOX)
    assert rep["accepted"] == 0
    assert rep["rejected"][0]["reason"] == "outside city bbox"


def test_an_unparseable_coordinate_is_rejected_not_silently_skipped():
    _, rep = ingest_survey([_station()], [_row(lat="13,0781")], BBOX)
    assert rep["rejected"][0]["reason"] == "unparseable coordinate"


def test_an_unknown_station_name_is_rejected():
    _, rep = ingest_survey([_station()], [_row(name="Notastation")], BBOX)
    assert rep["rejected"][0]["reason"] == "unknown station name"


def test_a_rejected_row_leaves_the_previous_position_untouched():
    """A refusal must not half-apply: the old position and confidence stand."""
    rows = [_station()]
    merged, rep = ingest_survey(rows, [_row(lat="99.0", lon="99.0")], BBOX)
    assert rep["accepted"] == 0
    assert merged[0].lat == 13.078 and merged[0].geocode_confidence == "google_maps_poi"
    assert merged[0].survey_required is True


def test_a_blank_row_is_open_not_rejected():
    """A blank is honest -- the surveyor could not confirm it. Not an error."""
    _, rep = ingest_survey([_station()], [_row(lat="", lon="")], BBOX)
    assert rep["still_open"] == ["Kilpauk"]
    assert not rep["rejected"]
    assert rep["gate"]["passes_publish_gate"] is False


# ------------------------------------------------------------------- flags

def test_a_large_move_is_flagged_for_review_but_still_accepted():
    """E-11c found errors up to 25 km, so a big move is usually CORRECT.
    It must be surfaced for confirmation, not refused."""
    rows = [_station()]
    merged, rep = ingest_survey(rows, [_row(lat="13.2500", lon="80.3300")], BBOX)
    assert rep["accepted"] == 1
    assert rep["large_moves_for_review"], "a multi-km move must be surfaced"
    assert rep["large_moves_for_review"][0]["station"] == "Kilpauk"
    assert merged[0].geocode_confidence == "surveyed"


def test_large_moves_are_reported_worst_first():
    rows = [_station("Kilpauk"), _station("Vepery", 13.085, 80.259)]
    _, rep = ingest_survey(
        rows,
        [_row("Kilpauk", "13.2500", "80.3300"), _row("Vepery", "13.1300", "80.2700")],
        BBOX)
    moves = [f["moved_m"] for f in rep["large_moves_for_review"]]
    assert moves == sorted(moves, reverse=True)


def test_qa_report_counts_by_confidence_and_lists_what_blocks():
    rows = [_station("Egmore", conf="osm"), _station("Kilpauk"), _station("Vepery")]
    rep = qa_report(rows)
    assert rep["by_confidence"] == {"osm": 1, "google_maps_poi": 2}
    assert sorted(rep["survey_required"]) == ["Kilpauk", "Vepery"]
    assert rep["passes_publish_gate"] is False
