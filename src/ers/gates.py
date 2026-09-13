"""Every publish gate in one place, as predicates a build can fail on.

Before the 2026-09 repair the gates existed only as fields written into report
files. `degradation_report.json` recorded `within_published_range: false` for the
project's own like-for-like EMRI comparison, and nothing anywhere read it back:
no script exited non-zero, no test asserted on it, and the failing gate sat in a
JSON file for days. A gate that nothing enforces is a comment.

Severity is the part that makes this usable rather than merely loud:

  BUILD       an internal inconsistency. The pipeline is wrong and the build
              must fail -- two scripts disagreeing about the same quantity, a
              siting result below the do-nothing baseline, an artefact computed
              against superseded inputs.

  PUBLICATION a real-world evidence limit, not a code defect. The station
              survey is outstanding, so coverage figures may not be published
              as settled numbers. This must NOT fail the build -- it would be
              red for as long as the fieldwork takes, and a permanently red
              build is one nobody reads. What IS enforced is the consequence:
              every affected artefact must state what it rests on -- PROVISIONAL
              while nothing else is decided, or the recorded waiver once one is.
              A PUBLICATION gate stays FAILED under a waiver, because it states
              a fact about the data and a decision to publish does not change
              that fact.

  REPORTED    a cross-check against an outside source that does not govern.
              Recorded, never enforced. See ADR-004.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUILD = "build"
PUBLICATION = "publication"
REPORTED = "reported"


@dataclass
class GateResult:
    id: str
    severity: str
    passed: bool
    value: Any
    threshold: Any
    note: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity == BUILD and not self.passed


def _served_scenarios(root: Path, subdir: str = "") -> list[str]:
    """Scenarios this build actually answers for, read from what it shipped.

    Read from `ui_data.json` rather than from the scenario configs: the configs
    say what exists, and the question here is what this study area SERVES. A
    scenario present in config but absent from the build cannot mislead anyone.
    """
    ui = _load(root, "ui_data.json", subdir)
    if not ui:
        return []
    out: set[str] = set()
    for svc in (ui.get("services") or {}).values():
        out.update((svc.get("scenarios") or {}).keys())
    return sorted(out)


def _load(root: Path, name: str, subdir: str = "") -> dict | None:
    p = root / "data/interim" / subdir / name if subdir else root / "data/interim" / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def evaluate(root: str | Path = ".", subdir: str = "") -> list[GateResult]:
    """Evaluate every gate against one build.

    `subdir` selects a study-area profile's artefacts. A wider profile has no
    flood scenarios and no routing validation of its own, so several gates have
    nothing to read. Those are reported as NOT EVALUATED by `skipped()` rather
    than quietly omitted: a gate that did not run is a different statement from
    a gate that passed, and a console showing "10 of 10" for a build that only
    tried four would be the most misleading number in the project.
    """
    root = Path(root)
    out: list[GateResult] = []

    def _l(name):
        return _load(root, name, subdir)

    qa = _l("stations_qa.json")
    baseline = _l("baseline_report.json")
    degr = _l("degradation_report.json")
    rv = _l("routing_validation.json")

    # ---- PUBLICATION -----------------------------------------------------
    from ers.publish import load_waiver

    waiver = load_waiver(root)
    if qa is not None:
        n_open = len(qa.get("survey_required", []))
        n_total = qa.get("total", n_open)
        surveyed = bool(qa.get("passes_publish_gate"))
        out.append(GateResult(
            "stations_surveyed", PUBLICATION, surveyed,
            f"{n_open} unsurveyed" + (" (WAIVED)" if waiver and not surveyed else ""),
            "0 unsurveyed",
            f"{n_open} of {n_total} positions are map listings, not surveyed. "
            "A better geocode is not a verification (E-11c). "
            + ("Publication proceeds under the waiver of "
               f"{waiver.get('date')}; this gate stays FAILED because it states "
               "a fact about the data, and a decision to publish does not make "
               "the stations surveyed." if waiver else "")))

    # Every affected artefact must say what it rests on. Before the waiver that
    # meant carrying PROVISIONAL; under one it means carrying the waiver itself.
    # Either way the requirement is the same: a coverage figure may not travel
    # without its basis attached.
    if qa is not None and not qa.get("passes_publish_gate"):
        AFFECTED = ("baseline_report.json", "degradation_report.json",
                    "optimise_ems.json", "optimise_fire.json")
        unstamped = []
        for name in AFFECTED:
            rep = _load(root, name)
            if rep is None:
                continue
            basis = rep.get("publication_basis")
            if waiver:
                ok = basis == "waived" and bool(rep.get("waiver"))
            else:
                ok = bool(rep.get("PROVISIONAL"))
            if not ok:
                unstamped.append(name)
        out.append(GateResult(
            "publication_basis_stamped", BUILD, not unstamped,
            unstamped or "all stamped",
            "waiver recorded in every artefact" if waiver else "no unstamped artefact",
            "The survey is outstanding, so these outputs may not present "
            "themselves as settled without saying what they rest on."))

        # A waiver that omits its own interval would let the narrow figure be
        # quoted alone, which E-11g says is exactly what is not supported.
        if waiver:
            u = (waiver.get("uncertainty") or {})
            has_both = all(k in u for k in (
                "if_unconfirmed_listings_correct_points",
                "if_unconfirmed_listings_wrong_points"))
            out.append(GateResult(
                "waiver_states_its_interval", BUILD, has_both,
                sorted(u) or "none", "both measured intervals present",
                "A figure published on unsurveyed positions must carry both "
                "ends of the E-11g interval; the narrow one alone is not "
                "supported while 15 listings are unconfirmed."))

    # ---- BUILD -----------------------------------------------------------
    if baseline is not None and degr is not None:
        agree = degr.get("baseline_agreement", {})
        bad = [s for s, v in agree.items() if not v.get("match")]
        out.append(GateResult(
            "baseline_agreement", BUILD, not bad, bad or "all services agree",
            "degradation dry == baseline",
            "F-16: four scripts once each re-implemented station-to-cell "
            "routing and drifted apart by 21 points."))

    for svc in ("ems", "fire"):
        opt = _l(f"optimise_{svc}.json")
        if opt is None:
            continue
        base = opt.get("baseline_share")
        below = [r["k"] for r in opt.get("runs", [])
                 if base is not None and r.get("exact_share", 1) < base - 1e-9]
        out.append(GateResult(
            f"siting_above_baseline_{svc}", BUILD, not below,
            below or f"all k >= {base}", "no k below the do-nothing baseline",
            "F-13: a stale precovered mask once published coverage BELOW the "
            "do-nothing baseline, which adding stations cannot cause."))

        unproven = [r["k"] for r in opt.get("runs", []) if not r.get("proven_optimal")]
        out.append(GateResult(
            f"optimality_declared_{svc}", BUILD,
            "all_runs_proven_optimal" in opt, unproven or "all proven",
            "every run states whether it was proven",
            "F-15: PuLP maps a HiGHS time-limit stop to LpStatusOptimal, so "
            "600 s timeouts were published as 'proven optimal'."))

    # Every service result must name the bases it was routed from. EMS has no
    # ambulance-base inventory -- the fire stations stand in for it -- and that
    # substitution must travel with the number, not sit in a document beside it.
    missing_bases = []
    for name, key in (("baseline_report.json", "results"),
                      ("degradation_report.json", "services")):
        rep = _load(root, name)
        for svc, block in (rep or {}).get(key, {}).items():
            if not isinstance(block, dict) or "bases" not in block:
                missing_bases.append(f"{name}:{svc}")
    for name in ("optimise_ems.json", "optimise_fire.json"):
        rep = _load(root, name)
        if rep is not None and "bases" not in rep:
            missing_bases.append(name)
    if baseline is not None:
        out.append(GateResult(
            "service_bases_declared", BUILD, not missing_bases,
            missing_bases or "all declared", "every service result names its bases",
            "EMS coverage is modelled from the 33 fire stations; no 108 standby "
            "point inventory exists. A result that does not say so reads as a "
            "measurement of an ambulance network."))

    if rv is not None:
        g = rv.get("gate", {})
        out.append(GateResult(
            "routing_medape", BUILD, bool(g.get("medape_le_15pct")),
            rv.get("overall", {}).get("median_abs_pct_error"), "<= 0.15",
            "Model vs OSRM oracle over 200 sampled OD pairs."))
        out.append(GateResult(
            "routing_band_median_ratio", BUILD,
            bool(g.get("band_median_ratio_le_5pct")),
            g.get("worst_band_median_ratio"), "<= 0.05",
            "F-19: replaces bias_pct, a ratio of sums whose bootstrap CI ran "
            "up to 25 points wide and could not support a 5% threshold."))

    # A study area must not serve a flood scenario whose layer was drawn for a
    # smaller city. Reporting unmodelled ground as dry reads as good news exactly
    # where the study area was widened, which is the opposite of the truth.
    fx = _load(root, "flood_extent.json")
    if fx is not None:
        prof = (fx.get("profiles") or {}).get(subdir or "gcc")
        if prof is not None:
            served = set(_served_scenarios(root, subdir))
            refused = set(prof.get("refused", []))
            leaked = sorted(served & refused)
            out.append(GateResult(
                "flood_layers_cover_their_study_area", BUILD, not leaked,
                f"{len(leaked)} served beyond its layer" if leaked else "none served beyond its layer",
                "no flood scenario outside its modelling domain",
                "A flood layer produced for the corporation cannot speak for the "
                "metro. Where it is asked anyway, ground nobody modelled is "
                "returned as dry: " + (", ".join(leaked) if leaked else "n/a")))

    # ---- REPORTED --------------------------------------------------------
    emri = (degr or {}).get("emri_comparison") or (degr or {}).get("emri_gate")
    if emri is not None:
        e = emri
        out.append(GateResult(
            "emri_comparison", REPORTED, bool(e.get("within_published_range")),
            e.get("weighted_response_s"),
            f"{e.get('published_min_s')}-{e.get('published_max_s')} s",
            "ADR-004: OSRM governs the trip overhead; EMRI is a cross-check, "
            "not a gate. Its estimand (which dispatches, which geography, "
            "which year) is undocumented in our sources, and it compares an "
            "operational mean against modelled scenarios."))

    present = {r.id for r in out}
    for gid, needs in (("stations_surveyed", "stations_qa.json"),
                       ("baseline_agreement", "degradation_report.json"),
                       ("routing_medape", "routing_validation.json"),
                       ("routing_band_median_ratio", "routing_validation.json")):
        if gid not in present:
            out.append(GateResult(
                gid, BUILD, False, "not evaluated", f"needs {needs}",
                f"This build has no {needs}, so the gate could not run. Not a pass."))
    return out


def summarise(results: list[GateResult]) -> dict:
    return {
        "gates": len(results),
        "passed": sum(1 for r in results if r.passed),
        "blocking_failures": [r.id for r in results if r.blocking],
        "publication_blocks": [r.id for r in results
                               if r.severity == PUBLICATION and not r.passed],
        "reported_failures": [r.id for r in results
                              if r.severity == REPORTED and not r.passed],
    }
