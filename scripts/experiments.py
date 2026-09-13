"""The declared-but-never-run experiments. E-06, E-09 and the E-10 remainder.

ASSUMPTIONS.md lists an experiment against every engineering assumption. Before
the 2026-09 repair, one arm of one experiment had actually been run:

  * E-10 covers A-02, A-03, A-05, A-09 and A-10. Only the A-02 (junction delay)
    arm existed -- and the register itself had promoted the A-10 weight sweep
    from optional to load-bearing, because step 15 showed the siting
    recommendation depends on weights that are an engineering guess.
  * E-09 -- the +/-20% speed band, the flood closure-depth sweep, the candidate
    resample -- had never been run, and the deck PUBLISHES ITS RESULT as fact:
    "class speeds varied +/-20% shift coverage by roughly +/-4 points -- the top
    three sites do not change."
  * E-06 -- the demand weights A-06 and A-07 -- could not have been run: the
    surfaces were not implemented and the land-use data was not fetched. A-07 is
    now applied and swept here; A-06 stays blocked on ward-level age tables,
    which the census publishes at town level only.

Three arms were added in 2026-09 to close the register: `candidates` (E-09/A-12),
`emergency` (E-10/A-03) and `landuse` (E-06/A-07).

    python scripts/experiments.py all
    python scripts/experiments.py weights speeds depth wading growth

Each arm writes `data/interim/experiments/<name>.json` with a provenance stamp,
and prints the one line that matters: whether the effect is larger than the
station-position noise floor it has to clear to mean anything.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from ers.provenance import config_bundle, stamp  # noqa: E402

OUT = Path("data/interim/experiments")
PY = ".venv/bin/python"


def noise_floor(svc: str = "ems") -> tuple[float, float]:
    """(optimistic, pessimistic) P5-P95 spread in points, from E-11 / E-11g."""
    def spread(name: str) -> float:
        p = Path(f"data/interim/{name}_{svc}.json")
        if not p.exists():
            return float("nan")
        return float(json.loads(p.read_text()).get("noise_floor_points", float("nan")))
    return spread("sensitivity_stations"), spread("sensitivity_mixed")


def verdict(effect_pts: float, svc: str = "ems") -> str:
    lo, hi = noise_floor(svc)
    if not np.isfinite(lo):
        return "noise floor not measured"
    if np.isfinite(hi) and effect_pts < hi:
        return (f"BELOW the pessimistic noise floor ({hi:.1f} pts) -- "
                f"{'above' if effect_pts > lo else 'below'} the optimistic one ({lo:.1f} pts)")
    return f"ABOVE both noise floors ({lo:.1f} / {hi:.1f} pts)"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    st = pd.read_csv("data/interim/stations_resolved.csv")
    payload = {**stamp(config=config_bundle(), stations=st), **payload}
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"\nwrote {OUT / f'{name}.json'}")


# --------------------------------------------------------------------- E-10
# A-10: the design-basis scenario weights.

def exp_weights() -> dict:
    """Sweep the dry weight and find where the siting recommendation flips.

    A-10 (dry .70 / peak .15 / f25 .10 / f100 .05) is planning judgement, not a
    measured frequency, and step 15 showed the maximin-vs-expected choice rests
    on it: at 0.70 the expected objective is mostly a dry-day objective and
    shares 9 of 10 sites with ignoring scenarios entirely.

    The wet weight is split among peak/f25/f100 in the A-10 proportions, so the
    sweep moves one degree of freedom rather than four.
    """
    import dataclasses

    import geopandas as gpd

    from ers.model.problem import RobustSitingProblem
    from ers.optimise import exact
    from ers.pipeline import build_scenario_coverage, demand_column

    t0 = time.time()
    SCEN = ["dry", "peak", "flood25", "flood100"]
    SHAPE = {"peak": 0.15, "flood25": 0.10, "flood100": 0.05}
    wet = sum(SHAPE.values())
    rows = []

    cand = gpd.read_parquet("data/interim/candidates.parquet")
    cells = gpd.read_parquet("data/interim/demand_cells.parquet")
    feasible = cand["land_feasible"].to_numpy().astype(bool)

    for svc in ("ems", "fire"):
        scs, _meta = build_scenario_coverage(svc, SCEN, progress=False)
        demand = demand_column(cells, svc)

        for dry_w in (0.50, 0.60, 0.70, 0.80, 0.90):
            wmap = {"dry": dry_w}
            for k, v in SHAPE.items():
                wmap[k] = (1 - dry_w) * v / wet

            scaled = tuple(dataclasses.replace(sc, weight=wmap.get(sc.scenario, sc.weight))
                           for sc in scs)
            prob = RobustSitingProblem(
                scenarios=scaled, demand=demand, k=10,
                ward_of=cells["ward_id"].to_numpy(), land_feasible=feasible)

            exp = exact.solve_robust(prob, objective="expected", time_limit_s=300)
            mm = exact.solve_robust(prob, objective="maximin", time_limit_s=300)
            shared = len(set(exp.selected) & set(mm.selected))
            rows.append({
                "service": svc, "dry_weight": dry_w,
                "expected_sites": sorted(int(x) for x in exp.selected),
                "maximin_sites": sorted(int(x) for x in mm.selected),
                "shared_sites": shared,
                "expected_objective": round(float(exp.objective), 4),
                "maximin_objective": round(float(mm.objective), 4),
                "both_proven_optimal": bool(exp.proven_optimal and mm.proven_optimal),
            })
            print(f"  {svc:4s} dry={dry_w:.2f}  expected/maximin share {shared:2d}/10 "
                  f"sites | expected {exp.objective:.4f} | maximin worst "
                  f"{mm.objective:.4f}", flush=True)

    summary = {}
    for svc in ("ems", "fire"):
        sel = [r for r in rows if r["service"] == svc]
        shipped = next(r for r in sel if r["dry_weight"] == 0.70)
        summary[svc] = {
            "shared_sites_range": [min(r["shared_sites"] for r in sel),
                                   max(r["shared_sites"] for r in sel)],
            "distinct_expected_site_sets": len({tuple(r["expected_sites"]) for r in sel}),
            "distinct_maximin_site_sets": len({tuple(r["maximin_sites"]) for r in sel}),
            "expected_set_stable_across_sweep":
                len({tuple(r["expected_sites"]) for r in sel}) == 1,
            "shipped_weight_shared_sites": shipped["shared_sites"],
        }
        print(f"\n  {svc}: expected-objective site set takes "
              f"{summary[svc]['distinct_expected_site_sets']} distinct values across "
              f"the sweep; maximin takes {summary[svc]['distinct_maximin_site_sets']}")

    return {"experiment": "E-10 / A-10 design-basis weight sweep",
            "assumption": "A-10", "shipped_dry_weight": 0.70,
            "sweep": rows, "summary": summary,
            "seconds": round(time.time() - t0, 1)}


# --------------------------------------------------------------------- E-09
# A-01: class speeds +/-20%. The deck publishes this result as fact.

def exp_speeds() -> dict:
    t0 = time.time()
    base = yaml.safe_load(open("config/speeds/base.yml"))
    rows = []
    tmp = Path("config/speeds/_e09_tmp.yml")

    try:
        for label, factor in (("minus20", 0.80), ("shipped", 1.00), ("plus20", 1.20)):
            cfg = copy.deepcopy(base)
            cfg["free_flow_kmh"] = {k: v * factor for k, v in cfg["free_flow_kmh"].items()}
            tmp.write_text(yaml.safe_dump(cfg, sort_keys=True))

            _run([PY, "scripts/attribute.py", "--speeds", str(tmp)])
            _run([PY, "scripts/baseline.py", "--quiet"])
            rep = json.loads(Path("data/interim/baseline_report.json").read_text())
            rows.append({
                "arm": label, "speed_factor": factor,
                "ems": rep["results"]["ems"]["coverage_share"],
                "fire": rep["results"]["fire"]["coverage_share"],
            })
            print(f"  speeds x{factor:.2f}: EMS {rows[-1]['ems']:.2%} "
                  f"fire {rows[-1]['fire']:.2%}", flush=True)
    finally:
        tmp.unlink(missing_ok=True)
        _run([PY, "scripts/attribute.py"])       # restore the shipped model
        _run([PY, "scripts/baseline.py"])

    span = 100 * (max(r["ems"] for r in rows) - min(r["ems"] for r in rows))
    print(f"\n  EMS coverage spans {span:.2f} points across +/-20% speeds")
    print(f"  {verdict(span)}")
    return {"experiment": "E-09 / A-01 class speeds +/-20%", "assumption": "A-01",
            "arms": rows, "ems_span_points": round(span, 2),
            "deck_claim": "roughly +/-4 points; top three sites do not change",
            "verdict_vs_noise_floor": verdict(span),
            "seconds": round(time.time() - t0, 1)}


# A-08: flood closure depth {0.20, 0.30, 0.45}.

def exp_depth() -> dict:
    """A-08 applies to the 2015 OBSERVED-POINTS layer only, and to nothing else.

    The first version of this arm swept the depth and measured `flood100`, which
    returned exactly 0.00 points -- not because A-08 does not matter but because
    the return-period layers CLASSIFY SEVERITY and carry no depth at all
    (`ers.flood`: "one invented depth for the layers that never measured it" is
    the thing the design refuses to do). Only `f2015`, whose layer carries
    measured depths, keys off `closure_depth_m`.

    Recorded because a sweep that structurally cannot move its own outcome
    reports "this assumption is inert" when what it means is "this arm measured
    the wrong scenario", and the two are indistinguishable in the output.
    """
    t0 = time.time()
    rows = []
    for d in (0.20, 0.30, 0.45):
        out = f"data/interim/experiments/_degr_depth_{d}.json"
        _run([PY, "scripts/degradation.py", "ems,fire",
              "--closure-depth", str(d), "--out", out, "--quiet"])
        rep = json.loads(Path(out).read_text())
        row = {"closure_depth_m": d}
        for svc in ("ems", "fire"):
            sc = rep["services"][svc]["scenarios"]
            row[f"{svc}_f2015"] = sc["f2015"]["coverage_share"]
            row[f"{svc}_unreachable_f2015"] = sc["f2015"]["unreachable_population"]
            # Control: the return-period layers must NOT respond to a depth
            # threshold, because they carry no depth. If this ever moves, a
            # depth has been invented somewhere.
            row[f"{svc}_f100_control"] = sc["flood100"]["coverage_share"]
        rows.append(row)
        print(f"  depth {d:.2f} m: EMS f2015 {row['ems_f2015']:.2%} "
              f"({row['ems_unreachable_f2015']:,} unreachable) | "
              f"f100 control {row['ems_f100_control']:.2%}", flush=True)

    span = 100 * (max(r["ems_f2015"] for r in rows) - min(r["ems_f2015"] for r in rows))
    control = {r["ems_f100_control"] for r in rows}
    print(f"\n  EMS f2015 coverage spans {span:.2f} points across the depth sweep")
    print(f"  control (flood100, no depth in the layer): "
          f"{'inert as expected' if len(control) == 1 else 'MOVED -- investigate'}")
    return {"experiment": "E-09 / A-08 flood closure depth", "assumption": "A-08",
            "applies_to": "f2015 only - the return-period layers carry no depth",
            "arms": rows, "ems_f2015_span_points": round(span, 2),
            "control_flood100_inert": len(control) == 1,
            "verdict_vs_noise_floor": verdict(span),
            "seconds": round(time.time() - t0, 1)}


# A-09: wading speed factor.

def exp_wading() -> dict:
    t0 = time.time()
    rows = []
    for w in (0.20, 0.35, 0.50):
        out = f"data/interim/experiments/_degr_wading_{w}.json"
        _run([PY, "scripts/degradation.py", "ems,fire",
              "--wading-factor", str(w), "--out", out, "--quiet"])
        rep = json.loads(Path(out).read_text())
        sc = rep["services"]["ems"]["scenarios"]
        rows.append({"wading_speed_factor": w,
                     "ems_f100": sc["flood100"]["coverage_share"],
                     "ems_f25": sc["flood25"]["coverage_share"]})
        print(f"  wading {w:.2f}: EMS f100 {rows[-1]['ems_f100']:.2%}", flush=True)

    span = 100 * (max(r["ems_f100"] for r in rows) - min(r["ems_f100"] for r in rows))
    return {"experiment": "E-10 / A-09 wading speed factor", "assumption": "A-09",
            "arms": rows, "ems_f100_span_points": round(span, 2),
            "verdict_vs_noise_floor": verdict(span),
            "seconds": round(time.time() - t0, 1)}


# A-05: population growth factor 2011 -> now.

def exp_growth() -> dict:
    """A-05 scales the whole demand surface, so coverage SHARES are near-invariant.

    Worth running precisely to establish that: the assumption is load-bearing for
    absolute population counts ("2.7 M residents beyond 8 minutes") and almost
    inert for the shares the project actually reports. Recording which is which
    stops a future reader treating the two as equally uncertain.
    """
    t0 = time.time()
    import geopandas as gpd
    from ers.pipeline import load_service

    cells = gpd.read_parquet("data/interim/demand_cells.parquet")
    rows = []
    for g in (1.00, 1.13, 1.25):
        scale = g / 1.13
        rows.append({"growth_factor": g,
                     "population_total": round(float(cells["population"].sum() * scale)),
                     "note": "uniform city-wide scaling leaves every SHARE unchanged"})
        print(f"  growth {g:.2f}: total {rows[-1]['population_total']:,}", flush=True)

    ctx = load_service("ems")
    return {"experiment": "E-10 / A-05 growth factor", "assumption": "A-05",
            "arms": rows,
            "coverage_share_sensitivity": 0.0,
            "finding": ("A-05 is a uniform multiplier on every cell, so it moves "
                        "absolute population counts proportionally and leaves every "
                        "coverage SHARE exactly unchanged. It is load-bearing for "
                        "'N million residents beyond 8 minutes' and inert for the "
                        "percentages this project reports."),
            "baseline_share_unchanged": round(ctx.baseline_share, 4),
            "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------- E-09
# A-12: the 800 m minimum separation between candidate sites.

def exp_candidates() -> dict:
    """Resample the candidate lattice at four separations and re-solve.

    A-12 decides how finely the city is sampled for places a station could go.
    Too coarse and the optimiser cannot express a good site; too fine and the
    MCLP grows without adding anything a planner could act on, because two
    candidates 200 m apart are the same decision.

    The site lists are NOT comparable by index -- each separation renumbers the
    candidates -- so stability is measured geographically: how many of the ten
    sites chosen at 800 m have a counterpart within 800 m in the other arm.
    """
    t0 = time.time()
    import geopandas as gpd
    from scipy import sparse
    from scipy.spatial import cKDTree

    from ers.geo.candidates import build_candidates, load_osm_parcels
    from ers.geo.graph import read_graph_tables
    from ers.model.problem import SitingProblem
    from ers.optimise import exact
    from ers.pipeline import load_service
    from ers.routing.csr import snap, to_seconds, travel_times

    cfg = yaml.safe_load(open("config/city/chennai.yml"))
    metric = cfg["crs"]["metric"]
    nodes, edges = read_graph_tables("data/interim/graph")
    parcels, _ = load_osm_parcels("data/raw/osm_parcels_overpass.json", metric)

    ctxs = {svc: load_service(svc) for svc in ("ems", "fire")}
    rows, chosen_xy = [], {}

    for sep in (400.0, 600.0, 800.0, 1200.0):
        cs = build_candidates(nodes, edges, parcels, metric, min_separation_m=sep)
        cand = cs.frame
        for svc, ctx in ctxs.items():
            c = cand.to_crs(ctx.metric_crs)
            j_idx, _ = snap(ctx.graph, c.geometry.x.to_numpy(), c.geometry.y.to_numpy())
            feas = c["land_feasible"].to_numpy().astype(bool)

            d_c = travel_times(ctx.graph, j_idx, ctx.cell_idx, cutoff_ds=ctx.budget_s * 10 * 3)
            cand_s = to_seconds(d_c) + (ctx.cell_snap_m / 1.2)[None, :] + ctx.overhead_s
            M = sparse.csr_matrix((cand_s <= ctx.budget_s).T)

            prob = SitingProblem(coverage=M, precovered=ctx.precovered, demand=ctx.demand,
                                 k=10, ward_of=ctx.ward, land_feasible=feas)
            ex = exact.solve(prob, time_limit_s=300)
            share = (ex.baseline_covered + ex.objective) / ctx.total_demand
            sel = list(ex.selected)
            chosen_xy[(sep, svc)] = np.column_stack(
                [c.geometry.x.to_numpy()[sel], c.geometry.y.to_numpy()[sel]])

            rows.append({
                "min_separation_m": sep, "service": svc,
                "candidates": int(len(cand)),
                "candidates_land_feasible": int(feas.sum()),
                "coverage_share_k10": round(float(share), 4),
                "proven_optimal": bool(ex.proven_optimal),
                "proven_gap": ex.gap,
            })
            print(f"  sep {sep:6.0f} m  {svc:4s}  {len(cand):5,} candidates "
                  f"({int(feas.sum()):,} feasible)  k=10 coverage {share:.2%}"
                  f"{'' if ex.proven_optimal else '  <- ' + ex.optimality_note}", flush=True)

    # Geographic stability against the shipped 800 m lattice.
    for r in rows:
        ref = chosen_xy[(800.0, r["service"])]
        got = chosen_xy[(r["min_separation_m"], r["service"])]
        d, _ = cKDTree(ref).query(got, k=1)
        r["sites_within_800m_of_shipped"] = int((d <= 800.0).sum())

    spans = {}
    for svc in ("ems", "fire"):
        sel = [r for r in rows if r["service"] == svc]
        spans[svc] = round(100 * (max(r["coverage_share_k10"] for r in sel)
                                  - min(r["coverage_share_k10"] for r in sel)), 2)
    span = spans["ems"]
    print(f"\n  EMS k=10 coverage spans {span:.2f} points across the lattice sweep")
    print(f"  {verdict(span)}")

    return {"experiment": "E-09 / A-12 candidate minimum separation",
            "assumption": "A-12", "shipped_min_separation_m": 800.0,
            "arms": rows, "coverage_span_points": spans,
            "ems_span_points": span,
            "stability_note": ("sites_within_800m_of_shipped counts how many of the "
                               "ten sites an arm chooses have a counterpart within "
                               "800 m in the shipped lattice; candidate indices are "
                               "not comparable across arms"),
            "verdict_vs_noise_floor": verdict(span),
            "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------- E-10
# A-03: the emergency speed multiplier, inside the RSCH envelope.

def exp_emergency() -> dict:
    """Rescale the emergency multiplier and rebuild the travel-time model.

    A-03 is bounded by the lights-and-siren literature (<= 1.25 on arterials,
    ~1.0 residential) and was set by step 07 calibration, never swept. The arm
    scales each class multiplier's DEVIATION from 1.0, which handles both
    services with one parameter: EMS multipliers are gains above 1.0, fire's are
    penalties below it for a heavy appliance on a narrow street. Alpha 0 is "no
    emergency driving effect at all", 1.0 is shipped.

    Capped at the RSCH ceiling of 1.25 so no arm leaves the envelope
    ASSUMPTIONS.md says calibration may not leave either.
    """
    t0 = time.time()
    CEILING = 1.25
    base = {svc: yaml.safe_load(open(f"config/services/{svc}.yml"))
            for svc in ("ems", "fire")}
    tmp = {svc: Path(f"config/services/_e10_tmp_{svc}.yml") for svc in base}
    rows = []

    try:
        for alpha in (0.0, 0.5, 1.0, 1.5):
            for svc, cfg in base.items():
                scaled = copy.deepcopy(cfg)
                scaled["emergency_multiplier"] = {
                    k: min(CEILING, 1.0 + alpha * (v - 1.0))
                    for k, v in cfg["emergency_multiplier"].items()}
                tmp[svc].write_text(yaml.safe_dump(scaled, sort_keys=True))

            _run([PY, "scripts/attribute.py",
                  "--service-config", f"ems={tmp['ems']}",
                  "--service-config", f"fire={tmp['fire']}"])
            _run([PY, "scripts/baseline.py", "--quiet"])
            rep = json.loads(Path("data/interim/baseline_report.json").read_text())
            rows.append({
                "alpha": alpha,
                "ems_arterial_multiplier": round(min(CEILING, 1 + alpha * 0.20), 3),
                "ems": rep["results"]["ems"]["coverage_share"],
                "fire": rep["results"]["fire"]["coverage_share"],
            })
            print(f"  alpha {alpha:.1f} (EMS motorway x"
                  f"{rows[-1]['ems_arterial_multiplier']:.2f}): "
                  f"EMS {rows[-1]['ems']:.2%}  fire {rows[-1]['fire']:.2%}", flush=True)
    finally:
        for p in tmp.values():
            p.unlink(missing_ok=True)
        _run([PY, "scripts/attribute.py"])          # restore the shipped model
        _run([PY, "scripts/baseline.py"])

    span = 100 * (max(r["ems"] for r in rows) - min(r["ems"] for r in rows))
    fspan = 100 * (max(r["fire"] for r in rows) - min(r["fire"] for r in rows))
    print(f"\n  EMS coverage spans {span:.2f} points, fire {fspan:.2f}, across A-03")
    print(f"  {verdict(span)}")
    return {"experiment": "E-10 / A-03 emergency speed multiplier",
            "assumption": "A-03", "rsch_ceiling": CEILING,
            "parameterisation": "m' = min(1.25, 1 + alpha * (m - 1)); alpha=1 is shipped",
            "arms": rows,
            "ems_span_points": round(span, 2), "fire_span_points": round(fspan, 2),
            "verdict_vs_noise_floor": verdict(span),
            "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------- E-06
# A-07: the fire land-use risk multipliers.

def exp_landuse() -> dict:
    """Sweep A-07's risk multipliers and watch the fire coverage share move.

    E-06 could not run at all before 2026-09: the land-use layer was not fetched
    and nothing read `demand_surface`. Both are fixed, so the half of E-06 that
    is not blocked on census age tables can finally be measured.

    EMS is the control. Its surface is raw headcount, so A-07 must move it by
    exactly zero points; if it ever moves, the land-use weighting has leaked
    into a service that does not use it.
    """
    t0 = time.time()
    rows = []
    try:
        for scale in (0.0, 0.5, 1.0, 2.0):
            _run([PY, "scripts/build_demand.py", "--landuse-scale", str(scale), "--quiet"])
            _run([PY, "scripts/baseline.py", "--quiet"])
            rep = json.loads(Path("data/interim/baseline_report.json").read_text())
            dem = json.loads(Path("data/interim/demand_report.json").read_text())
            w = dem["service_surfaces"]["fire"]["weighting"]
            rows.append({
                "landuse_scale": scale,
                "multipliers": w["multipliers"],
                "weighted_total": w["weighted_total"],
                "fire": rep["results"]["fire"]["coverage_share"],
                "ems_control": rep["results"]["ems"]["coverage_share"],
            })
            print(f"  scale {scale:.1f}: fire {rows[-1]['fire']:.2%}  "
                  f"EMS control {rows[-1]['ems_control']:.2%}", flush=True)
    finally:
        _run([PY, "scripts/build_demand.py", "--quiet"])     # restore the shipped surface
        _run([PY, "scripts/baseline.py"])

    span = 100 * (max(r["fire"] for r in rows) - min(r["fire"] for r in rows))
    control = {round(r["ems_control"], 6) for r in rows}
    print(f"\n  fire coverage spans {span:.2f} points across the A-07 sweep")
    print(f"  control (EMS, raw headcount): "
          f"{'inert as expected' if len(control) == 1 else 'MOVED -- investigate'}")
    print(f"  {verdict(span, 'fire')}")
    return {"experiment": "E-06 / A-07 fire land-use risk multipliers",
            "assumption": "A-07",
            "parameterisation": "m' = 1 + scale * (m - 1); scale=1 is shipped, 0 is headcount",
            "arms": rows, "fire_span_points": round(span, 2),
            "control_ems_inert": len(control) == 1,
            "a06_still_blocked": ("the EMS half of E-06 needs ward-level age tables; "
                                  "C-13/C-14 are published at town level only"),
            "verdict_vs_noise_floor": verdict(span, "fire"),
            "seconds": round(time.time() - t0, 1)}


ARMS = {"weights": exp_weights, "speeds": exp_speeds, "depth": exp_depth,
        "wading": exp_wading, "growth": exp_growth, "candidates": exp_candidates,
        "emergency": exp_emergency, "landuse": exp_landuse}

if __name__ == "__main__":
    which = sys.argv[1:] or ["all"]
    names = list(ARMS) if which == ["all"] else which
    for n in names:
        if n not in ARMS:
            raise SystemExit(f"unknown arm {n!r}; choose from {', '.join(ARMS)} or 'all'")
    for n in names:
        print(f"\n{'=' * 70}\n{n}\n{'=' * 70}", flush=True)
        _write(n, ARMS[n]())
