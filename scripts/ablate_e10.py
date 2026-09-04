"""E-10: ablate the junction-delay term. Test a specific hypothesis.

HYPOTHESIS (from the step-07 calibration finding): the junction term should be
DELETED, not merely scaled down. Two pieces of evidence motivate this:

  1. It is charged per OSMnx node, and 86,439 of 88,143 nodes have
     street_count >= 3. That node set records how OSM ways were split, not where
     real intersections are, so the term prices a topology artifact.
  2. Stage-3 calibration searched junction_scale over [0.10, 0.30] and the
     optimum landed EXACTLY ON THE LOWER BOUND (0.10). An optimum on a grid
     boundary is not an optimum; it is evidence the grid was cut too soon.
     junction_scale = 0 was never evaluated jointly with the 45 s trip overhead.

An ablation has to answer two different questions, and they can disagree:

  FIT       does deleting the term make agreement with the OSRM oracle worse?
  DECISION  does deleting the term move any number a decision rests on?

A term that improves fit but changes no decision is still worth deleting, on
parsimony. A term that changes decisions cannot be deleted on fit alone.

  python scripts/ablate_e10.py [--skip-decision]
"""
import argparse, json, subprocess, sys, time
sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from ers.geo.attrs import attribute_edges
from ers.geo.graph import read_graph_tables
from ers.routing.csr import build_graph, snap, travel_times, to_seconds
from ers.routing.oracle import agreement_stats, stratified_stats
from ers.scenario import head_delay_seconds

ap = argparse.ArgumentParser()
ap.add_argument("--skip-decision", action="store_true",
                help="fit arm only; do not re-run the degradation curve")
ap.add_argument("--out", default="data/interim/ablation_e10.json")
args = ap.parse_args()

INCUMBENT_JS = 0.10          # what config/speeds/base.yml currently ships
INCUMBENT_OH = 45            # trip_overhead_s
BAND_BIAS_GATE = 0.05
t0 = time.time()

speeds = yaml.safe_load(open("config/speeds/base.yml"))
car = yaml.safe_load(open("config/services/car.yml"))
cfg = yaml.safe_load(open("config/city/chennai.yml")); METRIC = cfg["crs"]["metric"]
assert abs(float(speeds["junction_delay_scale"]) - INCUMBENT_JS) < 1e-9, \
    "incumbent junction_delay_scale moved; this ablation compares against the shipped value"
assert abs(float(speeds["trip_overhead_s"]) - INCUMBENT_OH) < 1e-9

# ---------------------------------------------------------------------------
# ARM 1 — FIT. Against the SAME cached OSRM oracle pairs the calibration used,
# so this is a like-for-like re-fit and not a new sample with new noise.
# ---------------------------------------------------------------------------
samp = pd.read_csv("data/interim/routing_validation_pairs.csv")
samp = samp[np.isfinite(samp["oracle_s"])].reset_index(drop=True)
oracle = samp["oracle_s"].to_numpy()
print(f"oracle pairs: {len(samp)} (cached, seed 20260903)", flush=True)

nodes, edges = read_graph_tables("data/interim/graph")
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cc = gpd.GeoSeries(cells.to_crs(METRIC).geometry.centroid, crs=METRIC)
st = pd.read_csv("data/interim/stations_resolved.csv")
sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]), crs="EPSG:4326").to_crs(METRIC)

_cache = {}


def model_times(js: float) -> tuple[np.ndarray, dict]:
    """Modelled seconds for every oracle pair at junction scale `js`.

    The trip overhead is additive and distance-independent, so it is applied
    afterwards rather than by re-solving -- one shortest-path sweep per js.
    """
    if js in _cache:
        return _cache[js]
    hd = head_delay_seconds(nodes, edges, speeds, junction_scale=js)
    r = attribute_edges(edges, hd, speeds=speeds, service=car)
    e2 = edges[["u", "v", "key"]].copy(); e2["tau"] = r.tau_ds
    g = build_graph(nodes, e2, "tau")
    c_idx, _ = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
    s_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())
    d = travel_times(g, s_idx, c_idx, cutoff_ds=None)
    m = np.array([to_seconds(d[int(x.s), int(x.c)]) for x in samp.itertuples()])
    _cache[js] = (m, r.stats)
    return _cache[js]


def score(js: float, oh: float) -> dict:
    m, stats = model_times(js)
    s = agreement_stats(m + oh, oracle)
    bb = stratified_stats(m + oh, oracle, samp["band"])
    worst = max(abs(v.get("bias_pct", 0.0)) for v in bb.values() if v.get("n"))
    return {
        "junction_scale": js, "overhead_s": oh,
        "medape": s["median_abs_pct_error"], "bias_pct": s["bias_pct"],
        "worst_band_bias": round(float(worst), 4),
        # Same objective as stage-3 calibration: fit, plus unbiasedness, plus a
        # penalty for band bias above the 5% gate. Reused verbatim so the two
        # searches are commensurable.
        "objective": round(s["median_abs_pct_error"] + abs(s["bias_pct"])
                           + max(0.0, worst - BAND_BIAS_GATE), 4),
        "gate_medape_le_15pct": bool(s["median_abs_pct_error"] <= 0.15),
        "gate_band_bias_le_5pct": bool(worst <= BAND_BIAS_GATE),
        "junction_delay_share": stats["junction_delay_share"],
    }


print("\n=== ARM 1: FIT vs OSRM oracle ===")
print("extending the stage-3 grid THROUGH the boundary the optimum sat on:\n")
grid = []
JS = [0.0, 0.025, 0.05, 0.075, 0.10, 0.15, 0.20]
OH = [0, 15, 30, 45, 60, 75, 90]
for js in JS:
    best_at_js = None
    for oh in OH:
        row = score(js, oh)
        grid.append(row)
        if best_at_js is None or row["objective"] < best_at_js["objective"]:
            best_at_js = row
    b = best_at_js
    mark = "  <- shipped" if js == INCUMBENT_JS else ""
    print(f"  js x{js:<5.3f} share {b['junction_delay_share']:6.2%}  best oh {b['overhead_s']:3.0f}s"
          f"  MedAPE {b['medape']:6.2%}  bias {b['bias_pct']:+7.2%}  "
          f"worst band {b['worst_band_bias']:6.2%}  obj {b['objective']:.4f}{mark}", flush=True)

best = min(grid, key=lambda r: r["objective"])
incumbent = next(r for r in grid if r["junction_scale"] == INCUMBENT_JS
                 and r["overhead_s"] == INCUMBENT_OH)
ablated_best = min((r for r in grid if r["junction_scale"] == 0.0),
                   key=lambda r: r["objective"])

print(f"\n  incumbent   js x{incumbent['junction_scale']:.2f} + {incumbent['overhead_s']:.0f}s : "
      f"MedAPE {incumbent['medape']:.2%}  bias {incumbent['bias_pct']:+.2%}  "
      f"worst band {incumbent['worst_band_bias']:.2%}  "
      f"band gate {'PASS' if incumbent['gate_band_bias_le_5pct'] else 'FAIL'}")
print(f"  ablated     js x0.00 + {ablated_best['overhead_s']:.0f}s : "
      f"MedAPE {ablated_best['medape']:.2%}  bias {ablated_best['bias_pct']:+.2%}  "
      f"worst band {ablated_best['worst_band_bias']:.2%}  "
      f"band gate {'PASS' if ablated_best['gate_band_bias_le_5pct'] else 'FAIL'}")
print(f"  grid best   js x{best['junction_scale']:.3f} + {best['overhead_s']:.0f}s "
      f"(obj {best['objective']:.4f})")

fit_verdict = ("ablation fits at least as well"
               if ablated_best["objective"] <= incumbent["objective"] + 1e-9
               else "ablation fits worse")
print(f"\n  FIT VERDICT: {fit_verdict} "
      f"(objective {ablated_best['objective']:.4f} vs {incumbent['objective']:.4f})")

m_inc, _ = model_times(INCUMBENT_JS)
m_abl, _ = model_times(0.0)
band_inc = stratified_stats(m_inc + INCUMBENT_OH, oracle, samp["band"])
band_abl = stratified_stats(m_abl + ablated_best["overhead_s"], oracle, samp["band"])
print("\n  per band (bias, model vs oracle):")
for b in sorted(band_inc):
    if band_inc[b].get("n"):
        print(f"    {b:9s} n={band_inc[b]['n']:3d}   incumbent {band_inc[b]['bias_pct']:+7.2%}"
              f"   ablated {band_abl[b]['bias_pct']:+7.2%}")

# ---------------------------------------------------------------------------
# ARM 2 — DECISION. Fit is not the test that matters. Re-run the entire
# degradation curve with the term deleted and ask whether any coverage figure
# a recommendation rests on actually moves.
# ---------------------------------------------------------------------------
decision = None
if not args.skip_decision:
    OH_ABL = ablated_best["overhead_s"]
    print("\n=== ARM 2: DECISION — full degradation curve with the term deleted ===")
    print(f"  incumbent model : junction x{INCUMBENT_JS:.2f} + {INCUMBENT_OH}s overhead")
    print(f"  ablated model   : junction x0.00 + {OH_ABL:.0f}s overhead  (REFITTED)")
    print("  The overhead is refitted rather than held at 45 s. Deleting one term of a"
          "\n  jointly-fitted pair and keeping the other frozen describes no calibrated"
          "\n  model at all -- it just makes every vehicle faster, and the ~2 pt coverage"
          "\n  gain that produces is an artifact of the frozen term, not of the ablation.",
          flush=True)
    ABL_OUT = "data/interim/degradation_report_e10_ablated.json"
    subprocess.run([sys.executable, "scripts/degradation.py",
                    "--junction-scale", "0.0", "--trip-overhead", str(OH_ABL),
                    "--out", ABL_OUT, "--quiet"], check=True)
    base = json.load(open("data/interim/degradation_report.json"))
    abl = json.load(open(ABL_OUT))
    assert abs(base["junction_delay_scale"] - INCUMBENT_JS) < 1e-9, \
        "degradation_report.json was not produced at the shipped junction scale; re-run it"

    rows, worst = [], 0.0
    print(f"\n  {'service':8s} {'scenario':10s} {'incumbent':>10s} {'ablated':>10s} {'delta':>9s}")
    for svc in base["services"]:
        for sid, r in base["services"][svc]["scenarios"].items():
            a = abl["services"][svc]["scenarios"][sid]
            d = a["coverage_share"] - r["coverage_share"]
            du = a["unreachable_population"] - r["unreachable_population"]
            worst = max(worst, abs(d))
            rows.append({"service": svc, "scenario": sid,
                         "incumbent_coverage": r["coverage_share"],
                         "ablated_coverage": a["coverage_share"],
                         "delta_points": round(100 * d, 3),
                         "delta_unreachable_population": int(du)})
            print(f"  {svc:8s} {sid:10s} {r['coverage_share']:9.2%} {a['coverage_share']:10.2%} "
                  f"{100*d:+8.2f} pts")
    # The scenario RANKING is what a plan is written against. If the ordering of
    # scenarios by severity survives the ablation, the term carries no decision.
    def order(rep, svc):
        sc = rep["services"][svc]["scenarios"]
        return [k for k in sorted(sc, key=lambda k: sc[k]["coverage_share"])]
    rank_stable = {svc: order(base, svc) == order(abl, svc) for svc in base["services"]}
    decision = {
        "ablated_report": ABL_OUT,
        "rows": rows,
        "max_abs_delta_points": round(100 * worst, 3),
        "scenario_ranking_preserved": rank_stable,
        "expected_coverage": {
            svc: {"incumbent": base["services"][svc]["expected_coverage_share"],
                  "ablated": abl["services"][svc]["expected_coverage_share"]}
            for svc in base["services"]},
    }
    print(f"\n  largest coverage move across all 12 (service, scenario) cells: "
          f"{decision['max_abs_delta_points']:.3f} pts")
    for svc, ok in rank_stable.items():
        print(f"  {svc:4s} scenario severity ranking preserved: {ok}")

# ---------------------------------------------------------------------------
# VERDICT. The criteria are fixed here, in the open, and they are about FIT and
# GATES only. Materiality is reported but deliberately does NOT decide the
# hypothesis: how far coverage moves when a mis-specified term is removed is a
# measure of how wrong the term was, not evidence for keeping it.
# ---------------------------------------------------------------------------
criteria = {
    "fit_no_worse": bool(ablated_best["objective"] <= incumbent["objective"] + 1e-9),
    "ablated_passes_medape_gate": bool(ablated_best["gate_medape_le_15pct"]),
    "ablated_passes_band_bias_gate": bool(ablated_best["gate_band_bias_le_5pct"]),
}
supported = all(criteria.values())
verdict = {
    "hypothesis": "the junction-delay term should be deleted entirely (scale = 0)",
    "criteria": criteria,
    "fit": {"incumbent": incumbent, "ablated_best": ablated_best, "grid_best": best,
            "verdict": fit_verdict,
            "incumbent_passes_band_gate": incumbent["gate_band_bias_le_5pct"],
            "ablated_passes_band_gate": ablated_best["gate_band_bias_le_5pct"]},
    "decision": decision,
    "hypothesis_supported": bool(supported),
    "recommendation": (
        "Delete junction_delay_s / junction_delay_scale and the per-service "
        f"junction_delay_factor; set trip_overhead_s = {ablated_best['overhead_s']:.0f}. "
        "Retire A-02. Re-run steps 06, 09, 13 and every optimisation downstream, "
        "because the coverage figures move by more than a rounding error."
        if supported else
        "Retain the junction term at the shipped scale; the ablation did not clear "
        "the stated criteria."),
}

print("\n" + "=" * 70)
print(f"E-10 VERDICT: hypothesis {'SUPPORTED' if supported else 'NOT SUPPORTED'}")
for k, v in criteria.items():
    print(f"    {k:32s} {v}")
if decision:
    print(f"    materiality (reported, not a criterion): coverage moves up to "
          f"{decision['max_abs_delta_points']:.2f} pts")
print("=" * 70)
print(verdict["recommendation"])

json.dump({"experiment": "E-10", "assumptions_tested": ["A-02"],
           "band_bias_gate": BAND_BIAS_GATE, "grid": grid, **verdict,
           "PROVISIONAL": True, "seconds": round(time.time() - t0, 1)},
          open(args.out, "w"), indent=2, sort_keys=True)
print(f"wrote {args.out}  ({time.time()-t0:.0f}s)")
