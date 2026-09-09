"""Artefacts must record the inputs they were computed from, and match them.

The 2026-09 audit found two artefacts that had gone stale in place:

  * `stations_qa.json` published `by_confidence: {locality: 29}` against an
    inventory that read `google_maps_poi: 29`, and `plausibility` labels
    (`settlement_centroid`, `unrelated_feature`) that described the discarded
    Nominatim positions rather than the adopted ones;
  * `survey_priority.json`, which ranks which stations to visit first, was
    computed 68 minutes before the positions it ranks were replaced -- and the
    worklist copied its ordering forward.

Neither is visible to a test that checks numbers agree with each other, because
each file was internally consistent. They are visible the moment an artefact has
to name the inventory it used.

`tests/integration/test_pipeline_consistency.py` asserts that consumers agree
with EACH OTHER. This file asserts they agree with the INPUTS ON DISK.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ers.pipeline import station_signature
from ers.provenance import STATION_DEPENDENT

ROOT = Path(__file__).resolve().parents[2]
INTERIM = ROOT / "data/interim"
RESOLVED = INTERIM / "stations_resolved.csv"

pytestmark = pytest.mark.skipif(
    not RESOLVED.exists(), reason="pipeline artefacts not built in this checkout")


def _current_signature() -> str:
    return station_signature(pd.read_csv(RESOLVED))


def _reports() -> list[Path]:
    return [INTERIM / n for n in STATION_DEPENDENT if (INTERIM / n).exists()]


def test_at_least_the_core_reports_are_present():
    names = {p.name for p in _reports()}
    missing = {"baseline_report.json", "degradation_report.json",
               "optimise_ems.json", "optimise_fire.json"} - names
    assert not missing, f"core artefacts absent: {sorted(missing)}"


@pytest.mark.parametrize("path", _reports(), ids=lambda p: p.name)
def test_station_dependent_artefact_names_its_inventory(path: Path):
    """Every station-dependent report must carry a stations_signature.

    Without one, an interval computed for the old positions is
    indistinguishable from one computed for the new (pipeline.station_signature).
    """
    rep = json.loads(path.read_text())
    assert isinstance(rep, dict), f"{path.name} is not a report object"
    assert rep.get("stations_signature"), (
        f"{path.name} does not record which station inventory produced it. "
        f"Add ers.provenance.stamp(..., stations=st) to the script that writes it.")


@pytest.mark.parametrize("path", _reports(), ids=lambda p: p.name)
def test_station_dependent_artefact_is_not_stale(path: Path):
    rep = json.loads(path.read_text())
    sig = rep.get("stations_signature")
    if not sig:
        pytest.skip("covered by test_station_dependent_artefact_names_its_inventory")
    assert sig == _current_signature(), (
        f"{path.name} was computed against station inventory {sig}, but the "
        f"inventory on disk is {_current_signature()}. Re-run the script that "
        f"writes it (see the Makefile), or the numbers describe positions that "
        f"are no longer in use.")


def test_survey_worklist_ordering_matches_the_priority_run():
    """The worklist's ordering is a computed result, not a label.

    `station_survey_worklist.csv` carries `survey_priority` and
    `leverage_points` copied from `survey_priority.json`. If that file is stale
    the fieldwork order is stale too -- which is what the audit found, on the
    project's own stated next action.
    """
    wl, pri = INTERIM / "station_survey_worklist.csv", INTERIM / "survey_priority.json"
    if not (wl.exists() and pri.exists()):
        pytest.skip("survey artefacts not built")

    ranks = json.loads(pri.read_text()).get("ranking", [])
    if not ranks:
        pytest.skip("survey_priority.json carries no ranking block")

    expected = {r["station"]: r["survey_priority"] for r in ranks}
    rows = pd.read_csv(wl)
    for _, row in rows.iterrows():
        name = row["station_name"]
        if name in expected and pd.notna(row.get("survey_priority")):
            assert int(row["survey_priority"]) == int(expected[name]), (
                f"worklist ranks {name} at {row['survey_priority']} but the "
                f"priority run puts it at {expected[name]}")
