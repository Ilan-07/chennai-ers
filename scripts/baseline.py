"""Baseline coverage on the current station network. Build step 09.

OUTPUT IS PROVISIONAL. 29 of 33 stations still carry geocoder positions rather
than surveyed ones, so the publish gate is closed and every figure here is
stamped accordingly. The pipeline runs anyway so the whole chain is exercised.
"""
import csv, json, sys, time
from pathlib import Path
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers import coverage
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap
from ers.io.stations import qa_report, ResolvedStation

t0 = time.time()
SPEEDS = yaml.safe_load(open("config/speeds/base.yml"))
OVERHEAD = float(SPEEDS.get("trip_overhead_s", 0.0))  # calibrated per-trip constant
cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]

nodes, edges = read_graph_tables("data/interim/graph")
arcs = pd.read_parquet("data/interim/arc_times.parquet")
edges = edges.merge(arcs[["u", "v", "key", "tau_ds_ems", "tau_ds_fire"]],
                    on=["u", "v", "key"], how="left")

cells = gpd.read_parquet("data/interim/demand_cells.parquet")
st = pd.read_csv("data/interim/stations_resolved.csv")
gate = qa_report([ResolvedStation(r.station_name, r.division, r.service, r.lat, r.lon,
                                  r.geocode_confidence, r.match_source, str(r.match_detail),
                                  r.uncertainty_m, bool(r.survey_required))
                  for r in st.itertuples()])
print(f"stations: {len(st)} | confidence {gate['by_confidence']} | "
      f"publish gate {'PASS' if gate['passes_publish_gate'] else 'BLOCKED'}", flush=True)

results = {}
for svc in ("ems", "fire"):
    scfg = yaml.safe_load(open(f"config/services/{svc}.yml"))
    std = yaml.safe_load(open("config/standards/sfac.yml"))
    preset = scfg["default_standard"]
    t_target = std["presets"][preset]["t_target_s"]
    budget_s = t_target - scfg["t_alarm_s"] - scfg["t_turnout_s"]   # Finding F-03

    g = build_graph(nodes, edges, f"tau_ds_{svc}")
    sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)
    s_idx, s_dist = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
    # Centroids MUST be computed in the projected CRS -- a centroid taken in
    # degrees is not the centroid of the real-world polygon.
    cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
    c_idx, c_dist = snap(g, cc.x.to_numpy(), cc.y.to_numpy())

    # Exhaustive sweep, no cutoff. A cutoff makes "unreachable" mean "further
    # away than the cutoff", which is a different claim -- and a false one. The
    # 4x-budget cutoff used previously reported 7 fire cells as unreachable that
    # are simply distant; population coverage was unaffected, the honesty of the
    # unreachable count was not.
    pop = cells["population"].to_numpy()
    best_s = coverage.response_seconds(g, s_idx, c_idx, c_dist,
                                       overhead_s=OVERHEAD, cutoff_ds=None)
    off = scfg["t_alarm_s"] + scfg["t_turnout_s"]
    # NFPA 1710's 240 s is already a TRAVEL figure, so the offsets are not
    # subtracted from it. The SFAC targets are total-response figures and are.
    ladder = {"SFAC-5": 300 - off, "SFAC-7": 420 - off,
              "deck-8min": 480 - off, "NFPA-travel-4min": 240}

    results[svc] = {
        **coverage.summarise(best_s, pop, budget_s=budget_s, ladder=ladder),
        "standard": preset, "t_target_s": t_target,
        "t_alarm_s": scfg["t_alarm_s"], "t_turnout_s": scfg["t_turnout_s"],
        "station_snap_max_m": round(float(s_dist.max()), 1),
        "cell_snap_max_m": round(float(c_dist.max()), 1),
        "cells_snap_over_300m": int((c_dist > 300).sum()),
    }
    tot = pop.sum()
    r = results[svc]
    print(f"\n{svc.upper()}  {preset}: target {t_target}s - alarm {scfg['t_alarm_s']}s "
          f"- turnout {scfg['t_turnout_s']}s = travel budget {budget_s}s", flush=True)
    print(f"  coverage      {r['coverage_share']:.1%}  ({r['population_covered']:,} of "
          f"{int(tot):,})", flush=True)
    print(f"  mean {r['mean_travel_s']/60:.1f} min | P50 {r['p50_travel_s']/60:.1f} | "
          f"P90 {r['p90_travel_s']/60:.1f} | max {r['max_travel_s']/60:.1f}", flush=True)
    print(f"  unreachable cells {r['unreachable_cells']} | snap>300m {r['cells_snap_over_300m']}",
          flush=True)

# E-11: station position uncertainty puts a measured interval under every figure
# below. A bare point estimate implies a precision this data does not have, so the
# headline is reported WITH its interval or explicitly marked as lacking one.
from ers.pipeline import station_signature
SIG = station_signature(st)
SENS, STALE = {}, {}
for svc in ("ems", "fire"):
    f = Path(f"data/interim/sensitivity_stations_{svc}.json")
    if not f.exists():
        continue
    sn = json.loads(f.read_text())
    # An interval computed for different station positions is not this model's
    # interval. Refuse it rather than print it beside a number it does not bound.
    if sn.get("stations_signature") == SIG:
        SENS[svc] = sn
    else:
        STALE[svc] = sn.get("stations_signature", "unstamped")

print("\n--- E-11 station position uncertainty ---")
if STALE:
    for svc, sig in STALE.items():
        print(f"  {svc.upper():4s} STALE INTERVAL IGNORED — computed for station positions "
              f"{sig}, current are {SIG}. Re-run scripts/sensitivity_stations.py.")
if not SENS:
    print("  NOT MEASURED for the current station positions. Run "
          "scripts/sensitivity_stations.py; until then every coverage figure above "
          "is a point estimate with an unquantified error bar.")
else:
    for svc, sn in SENS.items():
        c, r = sn["coverage"], results[svc]
        r["position_uncertainty"] = {
            "draws": sn["draws"], "seed": sn["seed"],
            "coverage_p5": c["p5"], "coverage_p95": c["p95"],
            "coverage_sd_points": round(100 * c["sd"], 2),
            "p5_p95_spread_points": c["p5_p95_spread_points"],
            "mean_bias_points": c["bias_vs_point_estimate_points"],
            "source": f"data/interim/sensitivity_stations_{svc}.json",
        }
        print(f"  {svc.upper():4s} coverage {r['coverage_share']:.1%} "
              f"[P5-P95 {c['p5']:.1%} - {c['p95']:.1%}, spread "
              f"{c['p5_p95_spread_points']:.1f} pts]")
        # The bias is the part that a confidence interval alone would hide: the
        # point estimate is not merely uncertain, it sits above the mean draw.
        if c["bias_vs_point_estimate_points"] <= -1.0:
            print(f"       point estimate is {abs(c['bias_vs_point_estimate_points']):.1f} pts "
                  f"ABOVE the mean over draws -- geocoded positions flatter coverage")

from ers.geo.graph import connectivity_report
conn = connectivity_report(build_graph(nodes, edges, "tau_ds_ems").csr)
print("\nconnectivity:", json.dumps(conn))

# GATE: does the calibrated model reproduce the operator's own published figure?
ems = results["ems"]
modelled_response_s = ems["mean_travel_s"] + ems["t_alarm_s"] + ems["t_turnout_s"]
tgt = SPEEDS["calibration_target"]
in_range = tgt["value_min_s"] <= modelled_response_s <= tgt["value_max_s"]
print(f"\n--- calibration check vs 108/EMRI published Chennai metro response ---")
print(f"  modelled EMS response = {ems['mean_travel_s']:.0f}s travel + {ems['t_alarm_s']}s alarm"
      f" + {ems['t_turnout_s']}s turnout = {modelled_response_s:.0f}s ({modelled_response_s/60:.2f} min)")
print(f"  published range        = {tgt['value_min_s']}-{tgt['value_max_s']}s "
      f"({tgt['value_min_s']/60:.1f}-{tgt['value_max_s']/60:.1f} min)")
print(f"  GATE (within published range): {in_range}")

report = {
    "connectivity": conn,
    "position_uncertainty_measured": bool(SENS),
    "stations_signature": SIG,
    "stale_intervals_ignored": STALE,
    "headline_caveat": (
        "Coverage shares carry a P5-P95 interval from E-11 station position "
        "uncertainty; see results.<svc>.position_uncertainty. The point estimate "
        "also sits above the mean draw."
        if SENS else
        "Station position uncertainty is NOT quantified for this run; the coverage "
        "shares below are point estimates with an unknown error bar."),
    "calibration_check": {
        "modelled_response_s": round(modelled_response_s, 1),
        "published_min_s": tgt["value_min_s"], "published_max_s": tgt["value_max_s"],
        "within_published_range": bool(in_range),
        "source": tgt["source"],
    },
    "PROVISIONAL": not gate["passes_publish_gate"],
    "provisional_reason": f"{len(gate['survey_required'])} of {gate['total']} stations "
                          f"are geocoder positions, not surveyed",
    "station_gate": {k: v for k, v in gate.items() if k != "survey_required"},
    "results": results,
    "demand_total": round(float(cells["population"].sum())),
    "cells": len(cells),
    "seconds": round(time.time() - t0, 1),
}
json.dump(report, open("data/interim/baseline_report.json", "w"), indent=2, sort_keys=True)
print(f"\n{'='*66}\nPROVISIONAL — {report['provisional_reason']}\n{'='*66}")
print(f"done in {report['seconds']}s")
