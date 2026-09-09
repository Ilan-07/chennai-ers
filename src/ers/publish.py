"""Whether results may be published, and on what basis.

Two different questions, kept apart on purpose:

  `stations_qa.passes_publish_gate` is a FACT -- every station carries a
  surveyed position, or it does not. Nothing in this module can change it, and
  no configuration file is allowed to make it true.

  `publication_basis()` is a DECISION -- given that fact, may these numbers be
  published, and what do they rest on? A waiver can answer yes while the fact
  stays false, because "we chose to publish on desk-research positions" and
  "the positions were verified" are not the same statement and must never
  serialise to the same thing.

Before this module, ten scripts each hardcoded `"PROVISIONAL": True`. That was
correct while it was correct, and would have been ten places to get wrong the
moment it stopped being. The stamp is now computed in one place from the
inventory and the waiver.
"""
from __future__ import annotations

import json
from pathlib import Path

WAIVER_PATH = "config/publish_waiver.yml"
QA_PATH = "data/interim/stations_qa.json"


def load_waiver(root: str | Path = ".") -> dict | None:
    """The active publication waiver, or None."""
    import yaml

    p = Path(root) / WAIVER_PATH
    if not p.exists():
        return None
    w = yaml.safe_load(p.read_text()) or {}
    return w if w.get("active") else None


def _qa(root: str | Path = ".") -> dict:
    p = Path(root) / QA_PATH
    return json.loads(p.read_text()) if p.exists() else {}


def publication_basis(root: str | Path = ".") -> dict:
    """The block every report carries, saying what its numbers rest on.

    Merge it into a report:  report = {**publication_basis(), ...}
    """
    qa = _qa(root)

    # No inventory on disk is not "nothing outstanding" -- it is not knowing.
    # A waiver permits publishing despite a KNOWN gap; it must not paper over an
    # absent one, or a missing file would read as a clean bill of health.
    if not qa:
        return {
            "PROVISIONAL": True,
            "publication_basis": "blocked",
            "provisional_reason": "station inventory not built",
        }

    open_stations = qa.get("survey_required", [])
    total = qa.get("total")

    # Surveyed: nothing to qualify.
    if not open_stations:
        return {
            "PROVISIONAL": False,
            "publication_basis": "surveyed",
            "basis_note": "Every station carries a surveyed position.",
        }

    waiver = load_waiver(root)
    if waiver is None:
        return {
            "PROVISIONAL": True,
            "publication_basis": "blocked",
            "provisional_reason": (f"{len(open_stations)} of {total} stations "
                                   f"carry unsurveyed positions"),
        }

    # Published under an explicit, dated decision. NOT the same as verified, and
    # the block says so in the artefact rather than in a document beside it.
    return {
        "PROVISIONAL": False,
        "publication_basis": "waived",
        "basis_note": (
            "Published under a recorded waiver, NOT on surveyed positions. "
            "See config/publish_waiver.yml."),
        "waiver": {
            "date": str(waiver.get("date", "")),
            "accepted_by": waiver.get("accepted_by", ""),
            "reason": " ".join((waiver.get("reason") or "").split()),
            "rests_on": " ".join((waiver.get("rests_on") or "").split()),
            "review_by": str(waiver.get("review_by", "")),
            "closes_when": " ".join((waiver.get("closes_when") or "").split()),
            "uncertainty": waiver.get("uncertainty", {}),
            "stations_unsurveyed": len(open_stations),
            "stations_total": total,
        },
    }


def is_waived(root: str | Path = ".") -> bool:
    return publication_basis(root).get("publication_basis") == "waived"
