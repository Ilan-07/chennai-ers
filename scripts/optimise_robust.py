"""Scenario-robust siting. Build step 15.

THE PROBLEM THIS FIXES. Every siting result in this project so far was chosen on
the dry-day network (`optimise.py`, `frontier.py`, `equity_curve.py` all route on
`tau_ds_{svc}`, which `attribute.py` writes for the dry scenario only). Step 13
then showed a 100-year flood leaves 1.11 M people with no route from any station
at all. So the project could MEASURE flood vulnerability while still SITING as
though it never floods, and the A-10 scenario weights existed with nothing
consuming them.

Three strategies, scored on every scenario rather than on the one that chose them:

  dry-only   maximise dry-day coverage.       The incumbent method.
  expected   maximise the A-10 weighted mean. Right if the weights are believed.
  maximin    maximise the worst scenario.     Right if they are not -- and A-10
                                              is an ASSM, not a measured frequency.

A strategy is only interesting if it CHANGES THE SITES. If all three pick the
same places, robustness is free and the dry-day answer was accidentally fine.

  python scripts/optimise_robust.py [service] [k] [--time-limit S]

PROVISIONAL: 29 of 33 station positions are geocoder output, not surveyed.
"""
import argparse, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, yaml
from ers.model.problem import RobustSitingProblem
from ers.optimise import exact
from ers.pipeline import build_scenario_coverage

ap = argparse.ArgumentParser()
ap.add_argument("service", nargs="?", default="ems")
ap.add_argument("k", nargs="?", type=int, default=10)
ap.add_argument("--scenarios", default="dry,peak,flood5,flood25,flood100,f2015")
ap.add_argument("--time-limit", type=float, default=600.0)
ap.add_argument("--out", default=None)
args = ap.parse_args()
SVC, K = args.service, args.k
OUT = args.out or f"data/interim/robust_{SVC}_k{K}.json"

t0 = time.time()
print(f"[{SVC}] k={K} — building per-scenario coverage", flush=True)
scs, meta = build_scenario_coverage(SVC, args.scenarios.split(","))

cand = gpd.read_parquet("data/interim/candidates.parquet")
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
prob = RobustSitingProblem(
    scenarios=tuple(scs), demand=cells["population"].to_numpy().astype("float64"),
    k=K, ward_of=cells["ward_id"].to_numpy(),
    land_feasible=cand["land_feasible"].to_numpy().astype(bool))

weights = prob.normalised_weights()
print(f"\ndesign basis {list(weights)} weights "
      f"{ {k: round(v,3) for k, v in weights.items()} }")
print(f"reported only: {[s.scenario for s in scs if s not in prob.design_basis]}",
      flush=True)


def summarise(name, selected, sol=None):
    per = prob.evaluate(selected)
    exp = sum(weights[s] * per[s] for s in weights)
    worst_id = min(weights, key=lambda s: per[s])
    return {"strategy": name, "sites": list(selected),
            "coverage_by_scenario": per,
            "expected_coverage": round(exp, 4),
            "worst_design_basis": worst_id,
            "worst_coverage": per[worst_id],
            "proven_optimal": None if sol is None else sol.proven_optimal,
            "optimality": None if sol is None else sol.optimality_note,
            "solve_s": None if sol is None else sol.wall_s}


rows = []
print(f"\n--- solving ---", flush=True)

# Incumbent: choose on the dry day alone, then score everywhere.
dry = exact.solve(prob.single("dry"), time_limit_s=args.time_limit)
rows.append(summarise("dry-only", dry.selected, dry))
print(f"  dry-only  {dry.wall_s:6.1f}s  {dry.optimality_note}", flush=True)

for kind in ("expected", "maximin"):
    sol = exact.solve_robust(prob, objective=kind, time_limit_s=args.time_limit)
    rows.append(summarise(kind, sol.selected, sol))
    print(f"  {kind:9s} {sol.wall_s:6.1f}s  {sol.optimality_note}", flush=True)

# ---------------------------------------------------------------- report
order = [s.scenario for s in scs]
w = {s.scenario: weights.get(s.scenario) for s in scs}
print(f"\n{'strategy':10s}" + "".join(f"{s:>10s}" for s in order)
      + f"{'expected':>10s}{'worst':>8s}")
print(" " * 10 + "".join(f"{('w=%.2f' % w[s]) if w[s] else 'report':>10s}" for s in order))
for r in rows:
    print(f"{r['strategy']:10s}"
          + "".join(f"{r['coverage_by_scenario'][s]:>10.2%}" for s in order)
          + f"{r['expected_coverage']:>10.2%}{r['worst_coverage']:>8.2%}")

base = rows[0]
print(f"\nsite overlap with the dry-only choice:")
for r in rows[1:]:
    a, b = set(base["sites"]), set(r["sites"])
    print(f"  {r['strategy']:9s} {len(a & b)}/{K} sites shared  "
          f"(Jaccard {len(a & b)/len(a | b):.2f})  "
          f"expected {100*(r['expected_coverage']-base['expected_coverage']):+.2f} pts  "
          f"worst {100*(r['worst_coverage']-base['worst_coverage']):+.2f} pts")

# The headline: what does siting on the dry day alone cost, and where.
best_exp = max(rows, key=lambda r: r["expected_coverage"])
best_worst = max(rows, key=lambda r: r["worst_coverage"])
print(f"\ncost of siting on the dry day alone:")
print(f"  expected coverage  {100*(best_exp['expected_coverage']-base['expected_coverage']):+.2f} pts "
      f"forgone (best: {best_exp['strategy']})")
print(f"  worst-case coverage {100*(best_worst['worst_coverage']-base['worst_coverage']):+.2f} pts "
      f"forgone (best: {best_worst['strategy']})")

report = {"PROVISIONAL": True,
          "provisional_reason": "29 of 33 stations are geocoder positions, not surveyed",
          "service": SVC, "k": K, "meta": meta,
          "design_basis_weights": weights,
          "report_only": [s.scenario for s in scs if s not in prob.design_basis],
          "scenario_stats": {s.scenario: s.stats for s in scs},
          "strategies": rows,
          "all_proven_optimal": all(r["proven_optimal"] for r in rows),
          "seconds": round(time.time() - t0, 1)}
json.dump(report, open(OUT, "w"), indent=2, sort_keys=True)
print(f"\nwrote {OUT}  ({report['seconds']}s)")
