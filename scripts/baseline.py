"""Baseline coverage on the current station network. Build step 09.

OUTPUT IS PROVISIONAL. 29 of 33 stations still carry geocoder positions rather
than surveyed ones, so the publish gate is closed and every figure here is
stamped accordingly. The pipeline runs anyway so the whole chain is exercised.
"""
import csv, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
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

    d = travel_times(g, s_idx, c_idx, cutoff_ds=budget_s * 10 * 4)
    best_ds = d.min(axis=0)
    # Access time: centroid-to-network walk-equivalent, 1.2 m/s (ASSM A-14).
    access_s = c_dist / 1.2
    best_s = to_seconds(best_ds) + access_s + OVERHEAD

    pop = cells["population"].to_numpy()
    reach = np.isfinite(best_s)
    covered = reach & (best_s <= budget_s)
    tot = pop.sum()

    finite = best_s[reach]
    wts = pop[reach]
    order = np.argsort(finite)
    cw = np.cumsum(wts[order]) / wts.sum()
    p50 = float(finite[order][np.searchsorted(cw, 0.50)])
    p90 = float(finite[order][np.searchsorted(cw, 0.90)])

    ladder = {}
    for label, tgt in (("SFAC-5", 300), ("SFAC-7", 420), ("deck-8min", 480), ("NFPA-travel-4min", 240)):
        b = tgt - scfg["t_alarm_s"] - scfg["t_turnout_s"] if label != "NFPA-travel-4min" else 240
        cov = reach & (best_s <= b)
        ladder[label] = {"travel_budget_s": b,
                         "coverage_share": round(float(pop[cov].sum() / tot), 4)}

    results[svc] = {
        "threshold_ladder": ladder,
        "standard": preset, "t_target_s": t_target,
        "t_alarm_s": scfg["t_alarm_s"], "t_turnout_s": scfg["t_turnout_s"],
        "travel_budget_s": budget_s,
        "coverage_share": round(float(pop[covered].sum() / tot), 4),
        "population_covered": round(float(pop[covered].sum())),
        "population_outside": round(float(tot - pop[covered].sum())),
        "unreachable_cells": int((~reach).sum()),
        "unreachable_population": round(float(pop[~reach].sum())),
        "mean_travel_s": round(float(np.average(finite, weights=wts)), 1),
        "p50_travel_s": round(p50, 1), "p90_travel_s": round(p90, 1),
        "max_travel_s": round(float(finite.max()), 1),
        "station_snap_max_m": round(float(s_dist.max()), 1),
        "cell_snap_max_m": round(float(c_dist.max()), 1),
        "cells_snap_over_300m": int((c_dist > 300).sum()),
    }
    r = results[svc]
    print(f"\n{svc.upper()}  {preset}: target {t_target}s - alarm {scfg['t_alarm_s']}s "
          f"- turnout {scfg['t_turnout_s']}s = travel budget {budget_s}s", flush=True)
    print(f"  coverage      {r['coverage_share']:.1%}  ({r['population_covered']:,} of "
          f"{int(tot):,})", flush=True)
    print(f"  mean {r['mean_travel_s']/60:.1f} min | P50 {r['p50_travel_s']/60:.1f} | "
          f"P90 {r['p90_travel_s']/60:.1f} | max {r['max_travel_s']/60:.1f}", flush=True)
    print(f"  unreachable cells {r['unreachable_cells']} | snap>300m {r['cells_snap_over_300m']}",
          flush=True)

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
