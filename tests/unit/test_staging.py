"""Peak-hour ambulance staging. Build step 15b.

Run against the real artefacts, as the rest of the service tests are: the point
is that the console's live solve and the published curve cannot disagree.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient       # noqa: E402

from ers.api.app import app                     # noqa: E402
from ers.api.bundle import get_bundle           # noqa: E402

REQUIRED = ["ui_data.json", "ui_basemap.json", "baseline_report.json",
            "demand_cells.parquet", "staging_ems.json", "staging_ems_peak.npz"]
pytestmark = pytest.mark.skipif(
    not all((Path("data/interim") / f).exists() for f in REQUIRED),
    reason="needs a built pipeline with step 15b (make data/interim/staging_ems.json)")


@pytest.fixture(scope="module")
def client():
    get_bundle.cache_clear()
    return TestClient(app)


@pytest.fixture(scope="module")
def report():
    return json.loads(Path("data/interim/staging_ems.json").read_text())


def test_staging_baseline_is_the_console_peak_figure(client, report):
    """Posts are added to the network the console shows, not to a near copy."""
    cov = client.get("/api/coverage/ems?scenario=peak").json()
    assert report["baseline_share"] == pytest.approx(cov["covered_share"], abs=5e-4)


def test_posts_never_lose_to_stations(report):
    """Posts may use every site a station may, so they cannot do worse."""
    for a, b in zip(report["posts"], report["stations"]):
        if a["proven_optimal"] and b["proven_optimal"]:
            assert a["share"] >= b["share"] - 1e-9, a["k"]


def test_posts_curve_is_monotone(report):
    shares = [r["share"] for r in report["posts"]]
    assert shares == sorted(shares)


def test_live_solve_reproduces_the_published_curve(client, report):
    published = next(r for r in report["posts"] if r["k"] == 3)
    body = client.post("/api/optimise", json={
        "service": "ems", "scenario": "peak", "k": 3, "mode": "staging"}).json()
    assert body["mode"] == "staging"
    assert body["exact"]["share"] == pytest.approx(published["share"], abs=1e-4)


def test_post_ids_resolve_in_the_post_table(client):
    """A post id read against the station table would put the pin elsewhere."""
    st = client.get("/api/staging/ems").json()
    body = client.post("/api/optimise", json={
        "service": "ems", "scenario": "peak", "k": 2, "mode": "staging"}).json()
    for j, pos in zip(body["exact"]["sites"], body["site_positions"]):
        assert pos == st["candidate_positions"][j]


def test_posts_are_refused_off_their_network(client):
    r = client.post("/api/optimise", json={
        "service": "ems", "scenario": "dry", "k": 2, "mode": "staging"})
    assert r.status_code == 422


def test_no_staging_for_fire(client):
    assert client.get("/api/staging/fire").status_code == 404
    r = client.post("/api/optimise", json={
        "service": "fire", "scenario": "peak", "k": 2, "mode": "staging"})
    assert r.status_code == 404


def test_station_mode_is_unchanged(client):
    """Adding a mode must not move the default answer."""
    a = client.post("/api/optimise", json={"service": "ems", "scenario": "dry", "k": 2}).json()
    b = client.post("/api/optimise", json={
        "service": "ems", "scenario": "dry", "k": 2, "mode": "station"}).json()
    assert a["exact"]["sites"] == b["exact"]["sites"]
    assert a["mode"] == "station"


def test_dry_plan_is_solved_at_every_k(report):
    """The comparison line is drawn point to point; an interpolated k is invented."""
    assert [r["k"] for r in report["dry_plan_at_peak"]] == [r["k"] for r in report["posts"]]


def test_posts_beat_the_dry_plan_at_peak(report):
    """The finding the console reports. If this flips, the headline must change."""
    for p, d in zip(report["posts"], report["dry_plan_at_peak"]):
        assert p["share"] >= d["share_at_peak"] - 1e-9, p["k"]
