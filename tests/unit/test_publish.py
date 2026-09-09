"""The publication waiver, and the line it must not cross.

A waiver answers "may we publish these numbers", never "were the stations
verified". The tests that matter are the ones asserting those two stay
distinct: a decision to publish must not serialise into anything a later reader
could mistake for evidence.
"""
from __future__ import annotations

import json

import pytest
import yaml

from ers.publish import load_waiver, publication_basis

QA_OPEN = {"total": 33, "survey_required": [f"S{i}" for i in range(29)],
           "passes_publish_gate": False}
QA_DONE = {"total": 33, "survey_required": [], "passes_publish_gate": True}

WAIVER = {
    "active": True, "date": "2026-09-10", "accepted_by": "team",
    "reason": "coursework deadline", "rests_on": "google maps listings",
    "review_by": "2026-12-01", "closes_when": "the emails are answered",
    "uncertainty": {"if_unconfirmed_listings_correct_points": 0.83,
                    "if_unconfirmed_listings_wrong_points": 7.63},
}


def _root(tmp_path, qa, waiver=None):
    (tmp_path / "data/interim").mkdir(parents=True)
    (tmp_path / "data/interim/stations_qa.json").write_text(json.dumps(qa))
    if waiver is not None:
        (tmp_path / "config").mkdir(parents=True, exist_ok=True)
        (tmp_path / "config/publish_waiver.yml").write_text(yaml.safe_dump(waiver))
    return tmp_path


# ------------------------------------------------------------------ blocked

def test_without_a_waiver_an_open_survey_blocks_publication(tmp_path):
    b = publication_basis(_root(tmp_path, QA_OPEN))
    assert b["PROVISIONAL"] is True
    assert b["publication_basis"] == "blocked"
    assert "29 of 33" in b["provisional_reason"]


def test_an_inactive_waiver_does_not_open_anything(tmp_path):
    b = publication_basis(_root(tmp_path, QA_OPEN, {**WAIVER, "active": False}))
    assert b["PROVISIONAL"] is True
    assert b["publication_basis"] == "blocked"


def test_load_waiver_returns_none_when_inactive(tmp_path):
    assert load_waiver(_root(tmp_path, QA_OPEN, {**WAIVER, "active": False})) is None


# ------------------------------------------------------------------- waived

def test_an_active_waiver_permits_publication(tmp_path):
    b = publication_basis(_root(tmp_path, QA_OPEN, WAIVER))
    assert b["PROVISIONAL"] is False
    assert b["publication_basis"] == "waived"


def test_a_waived_report_is_never_labelled_surveyed(tmp_path):
    """The whole point. 'We decided to publish' must not read as 'we checked'."""
    b = publication_basis(_root(tmp_path, QA_OPEN, WAIVER))
    assert b["publication_basis"] != "surveyed"
    assert "NOT on surveyed positions" in b["basis_note"]
    assert b["waiver"]["stations_unsurveyed"] == 29


def test_a_waived_report_carries_the_reason_and_the_review_date(tmp_path):
    w = publication_basis(_root(tmp_path, QA_OPEN, WAIVER))["waiver"]
    assert w["reason"] and w["rests_on"] and w["accepted_by"]
    assert w["review_by"] == "2026-12-01"
    assert w["closes_when"]


def test_a_waived_report_carries_both_ends_of_the_interval(tmp_path):
    """Quoting the narrow figure alone is what E-11g says is unsupported."""
    u = publication_basis(_root(tmp_path, QA_OPEN, WAIVER))["waiver"]["uncertainty"]
    assert u["if_unconfirmed_listings_correct_points"] == 0.83
    assert u["if_unconfirmed_listings_wrong_points"] == 7.63


def test_the_waiver_cannot_make_the_factual_gate_pass(tmp_path):
    """`passes_publish_gate` is a fact about the data and stays false."""
    root = _root(tmp_path, QA_OPEN, WAIVER)
    qa = json.loads((root / "data/interim/stations_qa.json").read_text())
    assert qa["passes_publish_gate"] is False
    assert publication_basis(root)["PROVISIONAL"] is False, (
        "the decision changes publication, not the underlying fact")


# ----------------------------------------------------------------- surveyed

def test_a_completed_survey_needs_no_waiver(tmp_path):
    b = publication_basis(_root(tmp_path, QA_DONE))
    assert b["publication_basis"] == "surveyed"
    assert b["PROVISIONAL"] is False
    assert "waiver" not in b


def test_a_completed_survey_outranks_a_waiver(tmp_path):
    """Real evidence makes the waiver redundant rather than being overridden."""
    b = publication_basis(_root(tmp_path, QA_DONE, WAIVER))
    assert b["publication_basis"] == "surveyed"
    assert "waiver" not in b


def test_a_missing_inventory_is_blocked_not_waived(tmp_path):
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config/publish_waiver.yml").write_text(yaml.safe_dump(WAIVER))
    b = publication_basis(tmp_path)
    assert b["PROVISIONAL"] is True
    assert b["publication_basis"] == "blocked"


# --------------------------------------------------------- the shipped file

def test_the_shipped_waiver_states_everything_the_gate_requires():
    """If this file exists and is active it governs real published numbers."""
    w = load_waiver(".")
    if w is None:
        pytest.skip("no active waiver in this checkout")
    for k in ("date", "accepted_by", "reason", "rests_on", "review_by",
              "closes_when", "uncertainty"):
        assert w.get(k), f"an active waiver must state {k}"
    u = w["uncertainty"]
    assert u.get("if_unconfirmed_listings_correct_points")
    assert u.get("if_unconfirmed_listings_wrong_points")
    assert (u["if_unconfirmed_listings_wrong_points"]
            > u["if_unconfirmed_listings_correct_points"])
