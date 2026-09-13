"""Service tests. Build step 19.

These run against the real artefacts in `data/interim`, not fixtures. A fixture
would let the API drift from the pipeline exactly the way the deck drifted from
the reports, and the whole point of the service is that it cannot.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient       # noqa: E402

from ers.api.app import app                     # noqa: E402
from ers.api.bundle import get_bundle           # noqa: E402

REQUIRED = ["ui_data.json", "ui_basemap.json", "baseline_report.json", "demand_cells.parquet"]
pytestmark = pytest.mark.skipif(
    not all((Path("data/interim") / f).exists() for f in REQUIRED),
    reason="needs a built pipeline (make all)")


@pytest.fixture(scope="module")
def client():
    get_bundle.cache_clear()
    return TestClient(app)


def test_health_names_the_build_it_is_serving(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    baseline = json.loads(Path("data/interim/baseline_report.json").read_text())
    assert body["run_id"] == baseline["run_id"]
    assert body["stations_signature"] == baseline["stations_signature"]


def test_meta_carries_the_publication_basis(client):
    """A client must not be able to render a coverage figure without its basis."""
    body = client.get("/api/meta").json()
    assert body["city"]["publication_basis"] in {"surveyed", "waived", "provisional"}
    assert set(body["services"]) == {"ems", "fire"}
    assert body["services"]["ems"]["budget_s"] > 0
    assert len(body["hex"]) == 6


def test_coverage_matches_the_baseline_report(client):
    """The API is a view. If it can disagree with the report, it is not one."""
    baseline = json.loads(Path("data/interim/baseline_report.json").read_text())
    for svc in ("ems", "fire"):
        body = client.get(f"/api/coverage/{svc}?scenario=dry").json()
        assert body["at_service_budget"] is True
        assert body["covered_share"] == pytest.approx(
            baseline["results"][svc]["coverage_share"], abs=5e-4)


def test_threshold_is_monotone(client):
    """A longer budget can only cover more people."""
    shares = [client.get(f"/api/coverage/ems?scenario=dry&threshold_s={t}").json()["covered_share"]
              for t in (180, 300, 600, 900)]
    assert shares == sorted(shares)


def test_unknown_service_and_scenario_are_refused(client):
    assert client.get("/api/coverage/helicopter?scenario=dry").status_code == 422
    r = client.get("/api/coverage/ems?scenario=blizzard")
    assert r.status_code == 404
    assert "blizzard" in r.json()["detail"]


def test_optimise_beats_the_baseline_and_proves_it(client):
    r = client.post("/api/optimise", json={"service": "ems", "scenario": "dry", "k": 3})
    assert r.status_code == 200
    body = r.json()
    exact, greedy = body["exact"], body["greedy"]
    assert exact["share"] >= body["baseline_share"]
    assert greedy["share"] <= exact["share"] + 1e-9        # exact is the bound
    assert len(exact["sites"]) == 3
    assert len(body["site_positions"]) == 3
    # The submodular guarantee is a floor on the GAIN, not on the share.
    gain_g = greedy["share"] - body["baseline_share"]
    gain_e = exact["share"] - body["baseline_share"]
    assert gain_g >= 0.632 * gain_e - 1e-9


def test_k_zero_is_the_do_nothing_baseline(client):
    body = client.post("/api/optimise", json={"service": "ems", "k": 0}).json()
    assert body["greedy"]["sites"] == []
    assert body["greedy"]["share"] == pytest.approx(body["baseline_share"], abs=1e-6)


def test_a_forced_site_raises_the_floor_the_optimiser_builds_on(client):
    """Manual placement is folded into precovered, not solved separately."""
    plain = client.post("/api/optimise", json={"service": "ems", "k": 2}).json()
    forced = client.post("/api/optimise",
                         json={"service": "ems", "k": 2, "forced": [7]}).json()
    assert forced["with_manual_share"] >= forced["baseline_share"]
    assert forced["baseline_share"] == pytest.approx(plain["baseline_share"])
    assert 7 not in forced["exact"]["sites"]          # already built, not re-selected


def test_forbidden_candidates_are_not_selected(client):
    plain = client.post("/api/optimise", json={"service": "ems", "k": 3}).json()
    banned = plain["exact"]["sites"][:1]
    body = client.post("/api/optimise",
                       json={"service": "ems", "k": 3, "forbidden": banned}).json()
    assert not set(body["exact"]["sites"]) & set(banned)
    assert body["exact"]["share"] <= plain["exact"]["share"] + 1e-9


def test_contradictory_and_out_of_range_requests_are_refused(client):
    assert client.post("/api/optimise",
                       json={"service": "ems", "k": 1, "forced": [10**9]}).status_code == 422
    assert client.post("/api/optimise",
                       json={"service": "ems", "k": 1, "forced": [3],
                             "forbidden": [3]}).status_code == 422
    assert client.post("/api/optimise", json={"service": "ems", "k": -1}).status_code == 422


def test_export_states_what_the_numbers_rest_on(client):
    r = client.get("/api/export.csv?svc=ems&scenario=dry&sites=1,2")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    for field in ("run_id", "stations_signature", "publication_basis",
                  "uncertainty_points_if_listings_wrong", "proposed_site_id"):
        assert field in text


def test_nearest_explains_a_cell_with_real_stations(client):
    body = client.get("/api/nearest/ems?scenario=dry").json()
    cells = client.get("/api/cells").json()
    assert len(body["who"]) == len(cells["lat"]) * body["topk"]
    assert max(body["who"]) < len(client.get("/api/stations").json()["stations"])


# --------------------------------------------------------------- profiles
#
# Added after two profile bugs reached the browser in one session: the optimise
# request model hard-coded Literal["gcc", "metro"] and rejected a third profile
# that the rest of the service already served, and two switcher buttons rendered
# the same label. Neither was caught by anything here, because nothing here
# knew profiles existed.

from ers.api.bundle import PROFILES, profile_dir      # noqa: E402
from pathlib import Path                              # noqa: E402

BUILT = [p for p in PROFILES
         if (profile_dir(Path("."), p) / "ui_data.json").exists()]


def test_every_registered_profile_is_listed(client):
    body = client.get("/api/profiles").json()
    assert {p["profile"] for p in body["profiles"]} == set(PROFILES)
    assert body["default"] in PROFILES


def test_profiles_have_distinct_labels_and_extents(client):
    """Two buttons reading the same thing is indistinguishable from a bug."""
    rows = client.get("/api/profiles").json()["profiles"]
    labels = [p["label"] for p in rows]
    assert len(set(labels)) == len(labels), f"duplicate profile labels: {labels}"
    areas = [p["area_km2"] for p in rows]
    assert len(set(areas)) == len(areas), f"duplicate profile extents: {areas}"


@pytest.mark.parametrize("profile", BUILT)
def test_each_built_profile_serves_every_endpoint(client, profile):
    for path in (f"/api/meta?profile={profile}",
                 f"/api/cells?profile={profile}",
                 f"/api/stations?profile={profile}",
                 f"/api/coverage/ems?profile={profile}",
                 f"/api/coverage/fire?profile={profile}",
                 f"/api/candidates/ems?profile={profile}"):
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("profile", BUILT)
def test_each_built_profile_can_be_optimised(client, profile):
    """The bug this exists for: a profile readable but not solvable."""
    r = client.post("/api/optimise", json={"profile": profile, "service": "ems", "k": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"] == profile
    assert body["exact"]["share"] >= body["baseline_share"]


@pytest.mark.parametrize("profile", BUILT)
def test_every_profile_states_whether_it_may_be_published(client, profile):
    """A study area with no waiver and no gates must say so, not stay silent."""
    pub = client.get(f"/api/meta?profile={profile}").json()["publication"]
    assert pub["state"] in {"waived", "cleared", "blocked"}
    assert pub["headline"]
    if pub["state"] == "blocked":
        assert pub["note"], "a blocked profile must explain what it is missing"
        assert pub["provisional"] is True
    # Only the GCC profile has gates wired to its artefacts.
    assert pub["gates_run"] is (profile == "gcc")


@pytest.mark.parametrize("profile", BUILT)
def test_coverage_carries_its_publication_status(client, profile):
    body = client.get(f"/api/coverage/ems?profile={profile}").json()
    assert body["publication"]["state"] in {"waived", "cleared", "blocked"}


def test_an_unknown_profile_is_refused_everywhere(client):
    assert client.get("/api/meta?profile=atlantis").status_code == 422
    assert client.get("/api/coverage/ems?profile=atlantis").status_code == 422
    assert client.post("/api/optimise",
                       json={"profile": "atlantis", "service": "ems", "k": 1}).status_code == 422


@pytest.mark.parametrize("profile", BUILT)
def test_profiles_do_not_share_a_demand_surface(client, profile):
    """Each profile must answer from its own build, not the default one."""
    cells = client.get(f"/api/cells?profile={profile}").json()
    meta = client.get(f"/api/meta?profile={profile}").json()
    assert len(cells["lat"]) == meta["city"]["cells"]


@pytest.mark.parametrize("profile", BUILT)
def test_the_areas_table_can_tell_a_near_miss_from_a_gap(client, profile):
    """0% coverage is not one thing: some areas miss the clock by seconds."""
    body = client.get(f"/api/coverage/ems?profile={profile}").json()
    zero = [w for w in body["by_ward"].values()
            if w["covered_share"] == 0 and w["demand"] > 0]
    if not zero:
        pytest.skip("no zero-coverage area in this profile")
    assert all("fastest_s" in w for w in zero)
    reachable = [w for w in zero if w["fastest_s"] is not None]
    assert reachable, "a zero-coverage area with no fastest time tells a reader nothing"
    assert all(w["fastest_s"] > body["budget_s"] for w in reachable)


# ------------------------------------------------- flood-layer extent (item 3)
#
# The metro and full profiles offered only dry and peak, and the console
# explained that with a sentence somebody typed. A sentence cannot go stale
# visibly: a new layer covering Tambaram would have changed nothing on screen.

@pytest.mark.parametrize("profile", BUILT)
def test_every_profile_says_which_floods_it_can_answer(client, profile):
    fx = client.get(f"/api/meta?profile={profile}").json()["flood_extent"]
    assert fx["measured"] is True, "run scripts/flood_extent_report.py"
    assert "dry" in fx["applicable"]
    for scen in fx["refused"]:
        assert fx["why"].get(scen), f"{scen} refused without a reason"


@pytest.mark.parametrize("profile", BUILT)
def test_a_profile_never_serves_a_flood_it_refuses(client, profile):
    """The defect this exists for: unmodelled ground returned as dry."""
    meta = client.get(f"/api/meta?profile={profile}").json()
    refused = set(meta["flood_extent"]["refused"])
    for svc in ("ems", "fire"):
        served = set(meta["services"][svc]["scenarios"])
        assert not (served & refused), (
            f"{profile}/{svc} serves {sorted(served & refused)}, which its own "
            f"layers cannot speak for")


def test_the_corporation_keeps_its_floods():
    """The check must not be so strict it refuses the layers it was built for."""
    fx = json.loads(Path("data/interim/flood_extent.json").read_text())
    gcc = fx["profiles"]["gcc"]
    assert gcc["refused"] == []
    assert {"flood5", "flood25", "flood100"} <= set(gcc["applicable"])


def test_a_wider_study_area_refuses_what_a_narrower_one_allows():
    """Monotone by construction: the layer does not grow when the area does."""
    fx = json.loads(Path("data/interim/flood_extent.json").read_text())["profiles"]
    if not {"gcc", "metro"} <= set(fx):
        pytest.skip("needs both gcc and metro built")
    assert set(fx["gcc"]["refused"]) <= set(fx["metro"]["refused"])
    assert (fx["metro"]["scenarios"]["flood100"]["domain_covers_study_area"]
            < fx["gcc"]["scenarios"]["flood100"]["domain_covers_study_area"])


@pytest.mark.parametrize("profile", BUILT)
def test_refusals_are_grouped_by_the_test_that_made_them(client, profile):
    """Three layers refused for one reason are one fact, not three."""
    fx = client.get(f"/api/meta?profile={profile}").json()["flood_extent"]
    groups = fx.get("groups", [])
    assert sorted(s for g in groups for s in g["scenarios"]) == sorted(fx["refused"])
    assert len({g["test"] for g in groups}) == len(groups), "a test grouped twice"
    for g in groups:
        assert g["domain_share_min"] <= g["domain_share_max"]


# ------------------------------------------------------- hand-placed reach
#
# Placing a site by hand and solving answers "how much does the PLAN gain". It
# never answered "was my station worth putting there", and with several placed by
# hand the single gain figure cannot be attributed to any one of them.

def test_reach_separates_what_a_site_touches_from_what_it_adds(client):
    """The whole point: reaching people is not the same as helping them."""
    body = client.get("/api/reach/ems?sites=54").json()
    r = body["sites"][0]
    assert r["demand"] >= r["new_demand"], "cannot add more than it reaches"
    assert len(r["new_cells"]) <= r["cells"]
    assert body["at_service_budget"] is True
    assert str(int(body["budget_s"])) in body["note"]


def test_reach_never_counts_ground_the_network_already_covers(client):
    """`new_demand` must exclude everything inside the budget today."""
    cov = client.get("/api/coverage/ems?scenario=dry").json()
    body = client.get("/api/reach/ems?sites=54,116").json()
    # Newly reached demand cannot exceed what is currently missed.
    missed = cov["total_demand"] - cov["covered_demand"]
    assert body["combined"]["new_demand"] <= missed + 1


def test_reach_is_measured_at_the_budget_not_the_slider(client):
    """A threshold_s parameter would imply a clock this cannot honour."""
    a = client.get("/api/reach/ems?sites=54").json()
    b = client.get("/api/reach/ems?sites=54&threshold_s=900")
    # The extra parameter is ignored rather than silently changing the answer.
    assert b.status_code == 200
    assert b.json()["sites"][0]["demand"] == a["sites"][0]["demand"]


def test_two_sites_on_the_same_ground_are_worth_less_than_their_sum(client):
    """Overlap is reported, because nothing else on the screen would show it."""
    body = client.get("/api/reach/ems?sites=54,116").json()
    per_site = sum(s["demand"] for s in body["sites"])
    assert body["combined"]["demand"] <= per_site
    assert body["combined"]["double_counted_demand"] == pytest.approx(
        per_site - body["combined"]["demand"], abs=1)


def test_reach_refuses_a_candidate_that_does_not_exist(client):
    assert client.get("/api/reach/ems?sites=10000000").status_code == 422
    assert client.get("/api/reach/ems?sites=-1").status_code == 422
    assert client.get("/api/reach/ems?sites=notanumber").status_code == 422


@pytest.mark.parametrize("profile", BUILT)
def test_every_profile_can_report_what_a_placed_site_reaches(client, profile):
    r = client.get(f"/api/reach/ems?profile={profile}&sites=0")
    assert r.status_code == 200, r.text
    assert r.json()["sites"][0]["cells"] >= 0
