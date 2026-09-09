"""Coverage degradation across the scenario set. Build step 13.

Runs the WHOLE routing chain once per (service, scenario): re-attributes every
arc under that scenario's network state, rebuilds the CSR, and re-solves
station->cell shortest paths. Nothing here is an overlay on the dry result.

The headline is not the coverage share. It is the split between population that
is merely SLOWER to reach and population that is UNREACHABLE — no path exists
from any of the 33 stations at any travel time. The second number is the one a
flood plan is actually written against, and only a graph-perturbation model can
produce it.

  python scripts/degradation.py [ems,fire] [--junction-scale X] [--tag NAME]

OUTPUT IS PROVISIONAL: 29 of 33 stations still carry geocoder positions.
"""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers import coverage
from ers.geo.graph import read_graph_tables
from ers.publish import publication_basis
from ers.pipeline import demand_column
from ers.provenance import config_bundle, service_bases, stamp
from ers.routing.csr import build_graph, snap
from ers.scenario import build_network, flood_arc_states, load_scenario

SCENARIOS = ["dry", "peak", "flood5", "flood25", "flood100", "f2015"]


def run(junction_scale=None, overhead_s=None, closure_depth_m=None,
        wading_factor=None, services=("ems", "fire"),
        scen_ids=SCENARIOS, quiet=False) -> dict:
    """`junction_scale` and `overhead_s` override the shipped calibration.

    They travel together: the two terms were fitted jointly, so changing one
    without refitting the other does not describe any calibrated model. That is
    the whole reason `overhead_s` is exposed here (E-10).
    """
    t0 = time.time()
    speeds = yaml.safe_load(open("config/speeds/base.yml"))
    overhead = float(speeds.get("trip_overhead_s", 0.0)) if overhead_s is None \
        else float(overhead_s)
    cfg = yaml.safe_load(open("config/city/chennai.yml"))
    metric = cfg["crs"]["metric"]
    std = yaml.safe_load(open("config/standards/sfac.yml"))

    nodes, edges = read_graph_tables("data/interim/graph")
    cells = gpd.read_parquet("data/interim/demand_cells.parquet")
    st = pd.read_csv("data/interim/stations_resolved.csv")
    pop = {s: demand_column(cells, s) for s in ("ems", "fire")}
    ward = cells["ward_id"].to_numpy()

    # Snap ONCE, on the dry topology, and reuse the node indices for every
    # scenario. Re-snapping per scenario would let a station or a cell migrate to
    # a different node as arcs are removed, and the curve would then be measuring
    # snapping noise as well as flooding.
    proj = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(metric)
    cc = gpd.GeoSeries(cells.to_crs(metric).geometry.centroid, crs=metric)
    g0 = build_graph(nodes, edges.assign(_w=1), "_w")
    s_idx, s_dist = snap(g0, proj.x.to_numpy(), proj.y.to_numpy())
    c_idx, c_dist = snap(g0, cc.x.to_numpy(), cc.y.to_numpy())

    scenarios = [load_scenario(f"config/scenarios/{s}.yml") for s in scen_ids]

    # E-09 / A-08 and A-09 sweeps. Overriding here rather than by hand-editing
    # the shipped scenario configs between passes is what makes those two
    # assumptions testable at all -- both were declared with an experiment
    # against them and neither had ever been run.
    for sc in scenarios:
        fl = sc.get("flood")
        if not fl:
            continue
        if closure_depth_m is not None and "closure_depth_m" in fl:
            fl["closure_depth_m"] = float(closure_depth_m)
        if wading_factor is not None:
            fl["wading_speed_factor"] = float(wading_factor)

    # Flood state is a property of the water, not of the vehicle: classify arcs
    # once per scenario and share the result across services.
    states = {}
    for sc in scenarios:
        t = time.time()
        states[sc["id"]] = flood_arc_states(sc, edges, metric)
        if sc.get("flood") and not quiet:
            fs = states[sc["id"]][1]
            print(f"  {sc['id']:9s} zones {fs['zones']['features']:4d} "
                  f"({fs['zones']['area_km2']:6.1f} km2)  arcs closed "
                  f"{fs['arcs']['closed']:6,d} ({fs['arcs']['length_share_closed']:6.2%} of "
                  f"network km)  wading {fs['arcs']['wading']:6,d}  "
                  f"bridges exempted {fs['arcs']['bridges_exempted_from_closure']:4d}"
                  f"   [{time.time()-t:.1f}s]", flush=True)

    out = {}
    for svc_name in services:
        svc = yaml.safe_load(open(f"config/services/{svc_name}.yml"))
        t_target = std["presets"][svc["default_standard"]]["t_target_s"]
        budget = t_target - svc["t_alarm_s"] - svc["t_turnout_s"]        # Finding F-03
        ladder = {"SFAC-5": 300 - svc["t_alarm_s"] - svc["t_turnout_s"],
                  "SFAC-7": 420 - svc["t_alarm_s"] - svc["t_turnout_s"],
                  "deck-8min": 480 - svc["t_alarm_s"] - svc["t_turnout_s"],
                  "NFPA-travel-4min": 240}
        rows = {}
        if not quiet:
            print(f"\n{svc_name.upper()}  budget {budget}s  "
                  f"({svc['default_standard']} {t_target}s - {svc['t_alarm_s']}s alarm "
                  f"- {svc['t_turnout_s']}s turnout)", flush=True)
        for sc in scenarios:
            fstates, fstats = states[sc["id"]]
            net = build_network(nodes, edges, speeds=speeds, service=svc, scenario=sc,
                                metric_crs=metric, junction_scale=junction_scale,
                                flood_states=fstates, flood_stats=fstats)
            e2 = edges[["u", "v", "key"]].copy()
            e2["tau"] = net.tau_ds
            g = build_graph(nodes, e2, "tau")
            # No cutoff: unreachable must mean unreachable, not merely truncated.
            best_s = coverage.response_seconds(g, s_idx, c_idx, c_dist,
                                               overhead_s=overhead, cutoff_ds=None)
            r = coverage.summarise(best_s, pop[svc_name], budget_s=budget,
                                   ladder=ladder)
            r["scenario"] = sc["id"]
            r["label"] = sc["label"]
            r["weight"] = float(sc["weight"])
            r["report_only"] = bool(sc.get("report_only", False))
            r["network"] = {k: net.attribution[k] for k in
                            ("arcs_usable", "mean_speed_kmh", "junction_delay_share")}
            if fstats:
                r["flood"] = fstats
            rows[sc["id"]] = r
            if not quiet:
                dry = rows.get("dry")
                dd = (f"{100*(r['coverage_share']-dry['coverage_share']):+6.1f} pts"
                      if dry and sc["id"] != "dry" else "   baseline")
                p90 = f"{r['p90_travel_s']/60:5.1f}" if r["p90_travel_s"] else "  n/a"
                print(f"  {sc['id']:9s} coverage {r['coverage_share']:6.1%} {dd}  "
                      f"P90 {p90} min  unreachable {r['unreachable_population']:>9,d} "
                      f"({r['unreachable_share']:5.2%})", flush=True)

        # Scenario-weighted expectation over the DESIGN BASIS only. Report-only
        # scenarios are excluded by construction, not by remembering to drop them.
        design = [r for r in rows.values() if not r["report_only"] and r["weight"] > 0]
        wsum = sum(r["weight"] for r in design)
        expected = (round(sum(r["weight"] * r["coverage_share"] for r in design) / wsum, 4)
                    if design and wsum > 0 else None)
        out[svc_name] = {
            "travel_budget_s": budget, "standard": svc["default_standard"],
            "scenarios": rows,
            "design_basis_weight_sum": round(wsum, 4),
            "expected_coverage_share": expected,
            "worst_design_basis": (min(design, key=lambda r: r["coverage_share"])["scenario"]
                                   if design else None),
        }
        if not quiet:
            print(f"  {'weighted':9s} expected coverage {expected:.1%} "
                  f"over design-basis weights summing to {wsum:.2f}", flush=True)

    return {
        "junction_delay_scale": (float(speeds.get("junction_delay_scale", 1.0))
                                 if junction_scale is None else float(junction_scale)),
        "trip_overhead_s": overhead,
        "shipped_calibration": (junction_scale is None and overhead_s is None
                                and closure_depth_m is None and wading_factor is None),
        "stations": len(st),
        "cells": len(cells),
        "demand_total": {s: round(float(v.sum())) for s, v in pop.items()},
        "station_snap_max_m": round(float(s_dist.max()), 1),
        "cell_snap_max_m": round(float(c_dist.max()), 1),
        "cutoff": "none (exhaustive sweep)",
        **publication_basis(),
        "provisional_reason": "29 of 33 stations are geocoder positions, not surveyed",
        "services": out,
        "seconds": round(time.time() - t0, 1),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("services", nargs="?", default="ems,fire")
    ap.add_argument("--junction-scale", type=float, default=None,
                    help="override speeds.junction_delay_scale (E-10 ablation)")
    ap.add_argument("--trip-overhead", type=float, default=None,
                    help="override speeds.trip_overhead_s; refit it whenever "
                         "--junction-scale is changed (the two were fitted jointly)")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--out", default="data/interim/degradation_report.json")
    ap.add_argument("--closure-depth", type=float, default=None,
                    help="A-08 override, metres. Swept in E-09.")
    ap.add_argument("--wading-factor", type=float, default=None,
                    help="A-09 override. Swept in E-10.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rep = run(junction_scale=args.junction_scale, overhead_s=args.trip_overhead,
              closure_depth_m=args.closure_depth, wading_factor=args.wading_factor,
              services=args.services.split(","), scen_ids=args.scenarios.split(","),
              quiet=args.quiet)

    # GATE: the dry point of this curve must reproduce the published step-09
    # baseline coverage exactly, or the curve is not comparable to it. The gate
    # only means anything at the shipped calibration -- under an override the
    # two are DIFFERENT MODELS and are supposed to disagree.
    if not rep["shipped_calibration"]:
        print(f"\n--- baseline gate skipped: calibration overridden "
              f"(junction x{rep['junction_delay_scale']}, "
              f"overhead {rep['trip_overhead_s']:.0f}s) ---")
    elif Path("data/interim/baseline_report.json").exists():
        base = json.load(open("data/interim/baseline_report.json"))
        checks = {}
        for svc, res in rep["services"].items():
            if "dry" in res["scenarios"] and svc in base["results"]:
                a = res["scenarios"]["dry"]["coverage_share"]
                b = base["results"][svc]["coverage_share"]
                checks[svc] = {"degradation_dry": a, "baseline_step09": b,
                               "match": abs(a - b) < 5e-4}
        rep["baseline_agreement"] = checks
        print("\n--- gate: dry point vs published step-09 baseline ---")
        for svc, c in checks.items():
            print(f"  {svc:4s} {c['degradation_dry']:.4f} vs {c['baseline_step09']:.4f}  "
                  f"{'MATCH' if c['match'] else 'MISMATCH'}")

    # GATE: the like-for-like 108/EMRI comparison. Their figure is an operational
    # mean across every condition, so its counterpart is the A-10 weighted mean
    # response, not the dry one. Gating on dry once let an inflated trip overhead
    # survive by cancelling against the wrong comparison.
    speeds = yaml.safe_load(open("config/speeds/base.yml"))
    tgt = speeds.get("calibration_target")
    if tgt and "ems" in rep["services"]:
        res = rep["services"]["ems"]
        svc = yaml.safe_load(open("config/services/ems.yml"))
        off = svc["t_alarm_s"] + svc["t_turnout_s"]
        db = {k: v for k, v in res["scenarios"].items()
              if not v["report_only"] and v["weight"] > 0}
        wsum = sum(v["weight"] for v in db.values())
        wmean = sum(v["weight"] * v["mean_travel_s"] for v in db.values()) / wsum
        dry = res["scenarios"]["dry"]["mean_travel_s"]
        ok = tgt["value_min_s"] <= wmean + off <= tgt["value_max_s"]
        # ADR-004: EMRI is a CROSS-CHECK, not a gate. OSRM constrains travel time
        # directly and the stage-4 overhead refit is cross-validated against it
        # (winning worst-band in 95% of splits and MedAPE in 100%); EMRI is a
        # single published range whose estimand -- which dispatches, which
        # geography, which year -- is undocumented in our sources, and it
        # compares an operational mean against modelled scenarios. Recorded and
        # reported; it does not govern the trip overhead.
        rep["emri_comparison"] = {
            "is_gate": False,
            "governs": "no - see docs/adr/004-trip-overhead-oracle.md",
            "statistic": "A-10 weighted mean EMS response across design-basis scenarios",
            "weighted_response_s": round(wmean + off, 1),
            "dry_only_response_s": round(dry + off, 1),
            "published_min_s": tgt["value_min_s"], "published_max_s": tgt["value_max_s"],
            "within_published_range": bool(ok),
            "note": "dry-only is reported for continuity but is not the test: a free-flow "
                    "scenario is the wrong counterpart to an operational mean.",
        }
        print(f"\n--- 108/EMRI cross-check (A-10 weighted; reported, not a gate) ---")
        print(f"  weighted EMS response {wmean + off:6.1f}s   vs published "
              f"{tgt['value_min_s']}-{tgt['value_max_s']}s   within range: {ok}")
        print(f"  (dry-only, for continuity: {dry + off:.1f}s — not the test)")

    _st = pd.read_csv("data/interim/stations_resolved.csv")
    rep.update(stamp(config=config_bundle("ems"), stations=_st))
    for svc, block in rep.get("services", {}).items():
        block["bases"] = service_bases(svc, _st)
    json.dump(rep, open(args.out, "w"), indent=2, sort_keys=True)
    print(f"\nwrote {args.out}  ({rep['seconds']}s)")
