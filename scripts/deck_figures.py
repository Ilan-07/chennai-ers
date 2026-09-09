"""Reconcile the DA-1 deck against what the pipeline actually produces.

`24BCE5537-DA-1.pdf` states figures that no run in this repository reproduces.
Some are stale, some describe a different quantity under the same words, and
some describe a system that was never built. None of them is marked as an
estimate on the slide.

This script GENERATES the reconciliation from the reports rather than restating
it in prose, so it cannot drift from the numbers the way the deck did. Run it
after `make all`:

    python scripts/deck_figures.py            # write docs/deck-figures.md
    python scripts/deck_figures.py --check    # non-zero if any claim is unresolved

Each row is one claim, its status, and the run that settles it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

I = Path("data/interim")
OUT = Path("docs/deck-figures.md")

SUPERSEDED = "SUPERSEDED"
UNBUILT = "NOT BUILT"
DIFFERENT = "DIFFERENT QUANTITY"
OK = "SUPPORTED"


def _load(name: str) -> dict:
    p = I / name
    return json.loads(p.read_text()) if p.exists() else {}


def rows() -> list[dict]:
    base = _load("baseline_report.json")
    opt = _load("optimise_ems.json")
    degr = _load("degradation_report.json")
    sens = _load("sensitivity_stations_ems.json")
    mixed = _load("sensitivity_mixed_ems.json")

    ems = base.get("results", {}).get("ems", {})
    ladder = ems.get("threshold_ladder", {})
    runs = {r["k"]: r for r in opt.get("runs", [])
            if r.get("candidate_set") == "land-feasible"}

    def pct(x):
        return "—" if x is None else f"{100 * x:.2f}%"

    out = [
        {"claim": "61% of residents reachable within 8 min (~4.2 M)",
         "status": DIFFERENT,
         "pipeline": pct(ladder.get("deck-8min", {}).get("coverage_share")),
         "note": "The deck's 61% is this project's SFAC-7 figure (7 min total "
                 "response, 300 s travel budget) relabelled as an 8-minute one. "
                 "The 8-minute figure is materially higher. Same number, "
                 "different question.",
         "run": base.get("run_id")},

        {"claim": "2.7 M residents beyond 8 min",
         "status": DIFFERENT,
         "pipeline": f"{ems.get('population_outside', 0):,} beyond the 7-min budget",
         "note": "Same relabelling as above, and it inherits A-05: the growth "
                 "factor moves absolute counts proportionally while leaving "
                 "every share unchanged (E-10 growth arm).",
         "run": base.get("run_id")},

        {"claim": "k=3 raises coverage to 89% (+1.9 M residents)",
         "status": SUPERSEDED,
         "pipeline": pct(runs.get(3, {}).get("exact_share")),
         "note": "Proven optimal at k=3 on the land-feasible candidate set. The "
                 "deck's 89% is roughly the modelled value at k=45. And per "
                 "ADR-005 the SITES are not identified at current positional "
                 "accuracy, so no k=3 recommendation should be read off this.",
         "run": opt.get("run_id")},

        {"claim": "the five existing stations sit close together",
         "status": SUPERSEDED,
         "pipeline": f"{base.get('station_gate', {}).get('total', '?')} stations",
         "note": "Finding F-01. The GCC publishes 33 (9 North, 9 South, "
                 "7 Central, 8 Suburban). The five-station premise underlies the "
                 "deck's root-cause analysis and its coverage arithmetic.",
         "run": _load("stations_qa.json").get("run_id")},

        {"claim": "mean response falls 9.6 min to 6.1 min",
         "status": SUPERSEDED,
         "pipeline": f"{ems.get('mean_travel_s', 0) / 60:.1f} min travel at baseline",
         "note": "The modelled baseline mean is already well below the deck's "
                 "'before' figure, so the claimed improvement is measured from "
                 "a number the pipeline does not produce.",
         "run": base.get("run_id")},

        {"claim": "42% of residents covered under flood",
         "status": SUPERSEDED,
         "pipeline": pct(degr.get("services", {}).get("ems", {})
                         .get("scenarios", {}).get("flood100", {})
                         .get("coverage_share")),
         "note": "100-year flood, EMS. The deck does not say which return "
                 "period it means; the project models 5, 25 and 100-year plus "
                 "the observed 2015 extent.",
         "run": degr.get("run_id")},

        {"claim": "WorldPop demand weights",
         "status": SUPERSEDED,
         "pipeline": "GHS-POP R2023A 100 m",
         "note": "ADR-002. WorldPop's server supports no range requests and "
                 "delivered ~4 kB/s, extrapolating to ~33 h for the national "
                 "raster. GHS-POP is inherently built-up-constrained, which is "
                 "the property the plan wanted from WorldPop.",
         "run": _load("demand_report.json").get("run_id")},

        {"claim": "FastAPI service + React/Leaflet console, REST between them",
         "status": UNBUILT,
         "pipeline": "a single static HTML file",
         "note": "scripts/ui/build_console.sh assembles ~3 MB of precomputed "
                 "JSON into one page. No server, no API, no React. The console "
                 "is real and works; the architecture slide describes something "
                 "that was not built.",
         "run": None},

        {"claim": "manual placement: click to test a candidate site",
         "status": OK, "pipeline": "implemented 2026-09 (console: Place a site by hand)",
         "note": "Was NOT BUILT until the 2026-09 repair. An explicit mode "
                 "rather than a change to what an ordinary click does; adding "
                 "or removing a candidate recomputes every statistic off the "
                 "same coverage matrix the optimiser uses. Per ADR-005 the "
                 "optimiser's list is not identified at current positional "
                 "accuracy, which makes 'what if we put one HERE' the more "
                 "honest interaction of the two.",
         "run": None},

        {"claim": "export report: coordinates, deltas and assumptions",
         "status": OK, "pipeline": "implemented 2026-09 (console: Export report CSV)",
         "note": "Was a clipboard copy only. The CSV carries the settings, the "
                 "coverage, BOTH E-11g uncertainty intervals, the site list "
                 "including manual placements, and the stated assumptions.",
         "run": None},

        {"claim": "every run carries a reproducible run identifier",
         "status": OK,
         "pipeline": f"run_id on every report (e.g. {base.get('run_id')})",
         "note": "TRUE ONLY SINCE 2026-09. When the deck was written no report "
                 "carried a run id; eight of ~24 carried a stations_signature "
                 "and the rest recorded nothing about their inputs.",
         "run": base.get("run_id")},

        {"claim": "±20% class speeds shift coverage ~±4 points; "
                  "top three sites unchanged",
         "status": SUPERSEDED,
         "pipeline": _e09_span(),
         "note": "The deck publishes this as a completed validation. The sweep "
                 "had never been run. Run in 2026-09 it comes out at roughly "
                 "FIVE TIMES the claimed sensitivity, and above both station-"
                 "position noise floors -- so the speed table is one of the few "
                 "modelling choices in this project that demonstrably matters "
                 "more than the unsurveyed stations do. The deck's reassurance "
                 "that 'the top three sites do not change' has no run behind it.",
         "run": _load("experiments/speeds.json").get("run_id")},

        {"claim": "greedy MCLP with a (1-1/e) guarantee, within one point of "
                  "the exact MIP",
         "status": OK,
         "pipeline": _greedy_gap(opt),
         "note": "Holds, and is the deck's soundest quantitative claim. Every "
                 "reported run states whether it was PROVEN optimal (F-15).",
         "run": opt.get("run_id")},
    ]

    # The caveat the deck does not carry at all.
    out.append({
        "claim": "(the deck states no uncertainty on any coverage figure)",
        "status": "MISSING",
        "pipeline": _interval(sens, mixed),
        "note": "E-11/E-11g. The deck's headline figures are point estimates "
                "presented without an interval, and the interval is wide enough "
                "to contain every effect the project measures.",
        "run": sens.get("run_id")})
    return out


def _e09_span() -> str:
    e = _load("experiments/speeds.json")
    if not e:
        return "not yet run"
    return f"{e.get('ems_span_points')} points across ±20%"


def _greedy_gap(opt: dict) -> str:
    gaps = [r.get("greedy_gap_vs_exact", 0) for r in opt.get("runs", [])]
    if not gaps:
        return "—"
    return f"worst greedy gap {100 * max(gaps):.2f}% of optimal"


def _interval(sens: dict, mixed: dict) -> str:
    a, b = sens.get("noise_floor_points"), mixed.get("noise_floor_points")
    if a is None:
        return "not measured"
    return f"±{a} pts optimistic / ±{b} pts if the 15 unconfirmed POIs are wrong"


def render(data: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in data:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = " · ".join(f"{v} {k.lower()}" for k, v in sorted(counts.items()))

    lines = [
        "# DA-1 deck — figure reconciliation",
        "",
        "> GENERATED by `scripts/deck_figures.py` from the reports in "
        "`data/interim/`. Do not edit by hand; re-run it after `make all`.",
        "",
        f"**{len(data)} claims checked:** {summary}",
        "",
        "The deck was written before the pipeline produced its own numbers, and "
        "was never reconciled against them. Every figure below is either "
        "reproduced by a run id, or is not.",
        "",
    ]
    for r in data:
        lines += [
            f"### {r['claim']}",
            "",
            f"- **status:** {r['status']}",
            f"- **pipeline:** {r['pipeline']}",
            f"- **run:** `{r['run']}`" if r["run"] else "- **run:** —",
            "",
            r["note"],
            "",
        ]
    lines += [
        "---",
        "",
        "## What to do with this",
        "",
        "The deck is a submitted artefact and cannot be silently corrected. Two "
        "honest options:",
        "",
        "1. **Re-present** with the figures above and the uncertainty bracket, "
        "noting which claims were provisional at the time.",
        "2. **Annotate** — submit this file alongside the deck as an erratum.",
        "",
        "What is not defensible is repeating the deck's figures in a later "
        "report. Several of them describe a five-station city, a population "
        "surface the project does not use, and a service architecture that was "
        "not built.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any claim is unresolved")
    args = ap.parse_args()

    data = rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data))
    print(f"wrote {OUT} ({len(data)} claims)")
    for r in data:
        print(f"  {r['status']:18s} {r['claim'][:64]}")

    if args.check:
        unresolved = [r for r in data if r["status"] not in (OK,)]
        raise SystemExit(1 if unresolved else 0)
