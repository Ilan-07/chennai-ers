"""E-11: how much does station POSITION UNCERTAINTY move the answers?

The publish gate has been closed since step 09 because 29 of 33 stations carry
geocoder positions, not surveyed ones, at a stated uncertainty of 900 m. Every
figure in this project is stamped PROVISIONAL for that reason — but "provisional"
is a word, and the assumptions register demands a number.

This is the experiment that produces the number, and it is a prerequisite for
believing any of the others. The effects measured so far are:

    E-10 junction term                     3.4 points of coverage
    maximin vs dry-only siting (step 15)   4.7 points
    equity cost at k=20 (step 14)          5.0 points

If perturbing the stations inside their own stated uncertainty moves coverage by
more than that, those effects are noise and the correct next action is the survey,
not more optimisation. If it moves coverage by much less, they are real. Either
answer changes what the project does next, which is what makes this worth running
before anything else.

Two arms, because they can disagree:

  COVERAGE    how far does the headline coverage share move?
  DECISION    does the RECOMMENDED SITE SET move? A recommendation can be stable
              while its coverage estimate is noisy, and vice versa. The siting
              arm re-solves the k-station MCLP per draw: the candidate coverage
              matrix does not depend on where the EXISTING stations are, but
              `precovered` does, and that is what the optimiser builds on.

  python scripts/sensitivity_stations.py [service] [draws] [--k K] [--seed S]
"""
import argparse, json, sys, time
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers import coverage as cov
from ers.model.problem import SitingProblem
from ers.optimise import exact
from ers.pipeline import load_service, station_signature
from ers.routing.csr import snap

ap = argparse.ArgumentParser()
ap.add_argument("service", nargs="?", default="ems")
ap.add_argument("draws", nargs="?", type=int, default=200)
ap.add_argument("--k", type=int, default=10, help="stations to site in the decision arm")
ap.add_argument("--seed", type=int, default=20260904)
ap.add_argument("--max-snap-m", type=float, default=300.0)
ap.add_argument("--error-model", default="disc", choices=["disc", "empirical", "gmaps", "mixed"],
                help="disc: A-15's assumed 900 m uncertainty disc (FALSIFIED by E-11c). "
                     "empirical: bootstrap the 29 displacements actually observed "
                     "between the Nominatim positions and the Google Maps POIs. "
                     "gmaps: Maps positions with a small residual, sampling between "
                     "candidates where the POI is ambiguous. "
                     "mixed: stations whose identity is confirmed against the official "
                     "TNFRS directory get a tight residual; the rest are treated "
                     "pessimistically, as if no better than the old geocode.")
ap.add_argument("--lookup", default="data/interim/stations_gmaps_lookup.csv")
ap.add_argument("--skip-decision", action="store_true")
ap.add_argument("--out", default=None)
args = ap.parse_args()
SVC, N, K = args.service, args.draws, args.k
OUT = args.out or f"data/interim/sensitivity_stations_{SVC}.json"

t0 = time.time()
ctx = load_service(SVC)
st = ctx.stations
budget, overhead = ctx.budget_s, ctx.overhead_s
demand, tot = ctx.demand, ctx.total_demand
# Exact for a coverage SHARE: a cell beyond 3x the budget cannot be inside it.
CUTOFF = budget * 10 * 3

unc = st["uncertainty_m"].to_numpy(dtype="float64")


def _project(lat, lon):
    g = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs="EPSG:4326").to_crs(ctx.metric_crs)
    return np.column_stack([g.x.to_numpy(), g.y.to_numpy()])


xy0 = _project(st["lat"].to_numpy(), st["lon"].to_numpy())
XY_ALT = None
EMPIRICAL = None

if args.error_model != "disc":
    look = pd.read_csv(args.lookup)
    j = st[["station_name"]].merge(look, on="station_name", how="left")
    if args.error_model == "mixed":
        # The question this answers: do the stations we have NOT confirmed still
        # move the answer? Confirmed ones (a Google listing publishing the
        # station's official TNFRS number) keep a 50 m residual. Unconfirmed ones
        # are treated as pessimistically as the evidence allows -- drawn from the
        # SAME empirical displacement distribution the discredited Nominatim
        # positions had. That is a deliberate worst case: it assumes confirming
        # identity bought nothing at all for them.
        lat = j["gmaps_lat"].fillna(pd.Series(st["lat"].to_numpy())).to_numpy()
        lon = j["gmaps_lon"].fillna(pd.Series(st["lon"].to_numpy())).to_numpy()
        xy0 = _project(lat, lon)
        conf = j["identity_confirmed_by"].fillna("").isin(
            ["tnfrs_landline", "tnfrs_cug_mobile", "osm_proximity"]).to_numpy()
        EMPIRICAL = look["shift_from_provisional_m"].dropna().to_numpy(dtype="float64")
        unc = np.where(conf, 50.0, np.nan)          # NaN marks "use EMPIRICAL"
        unc = np.where(np.isnan(unc), -1.0, unc)    # -1 sentinel, handled in draw
        print(f"  mixed model: {int(conf.sum())} identity-confirmed at 50 m residual, "
              f"{int((~conf).sum())} unconfirmed drawn from the empirical error "
              f"distribution (median {np.median(EMPIRICAL):.0f} m, max {EMPIRICAL.max():.0f} m)")
    elif args.error_model == "empirical":
        # A-15 assumed a 900 m disc. E-11c falsified it: 16 of 29 true positions
        # lie outside that disc, up to 25 km. The honest error model is the
        # distribution actually observed. Magnitudes are bootstrapped across
        # stations and applied in a uniform random direction -- we know the
        # SIZE of geocoder error empirically, not its bearing, and pooling
        # assumes the 29 are exchangeable, which the suburban/city split
        # strains. Both assumptions are stated rather than hidden.
        EMPIRICAL = look["shift_from_provisional_m"].dropna().to_numpy(dtype="float64")
        print(f"  empirical displacement model: n={len(EMPIRICAL)} observed shifts, "
              f"median {np.median(EMPIRICAL):.0f} m, max {EMPIRICAL.max():.0f} m")
    else:
        # Centre on the Maps POI. Ambiguous stations sample between candidates.
        lat = j["gmaps_lat"].fillna(pd.Series(st["lat"].to_numpy())).to_numpy()
        lon = j["gmaps_lon"].fillna(pd.Series(st["lon"].to_numpy())).to_numpy()
        xy0 = _project(lat, lon)
        has_alt = j["alt_lat"].notna().to_numpy()
        XY_ALT = np.where(has_alt[:, None],
                          _project(j["alt_lat"].fillna(0).to_numpy(),
                                   j["alt_lon"].fillna(0).to_numpy()), np.nan)
        unc = j["residual_m"].fillna(60.0).to_numpy(dtype="float64")
        print(f"  gmaps model: {int(has_alt.sum())} stations sample between two "
              f"candidate POIs; residual radius {np.unique(unc)} m")

print(f"[{SVC}] {N} draws, seed {args.seed} | budget {budget}s | "
      f"error model: {args.error_model}")
print(f"  stations {len(st)} | uncertainty (m): "
      f"{dict(pd.Series(unc).value_counts().sort_index())}")
print(f"  point-estimate coverage {ctx.baseline_share:.2%} "
      f"({ctx.precovered.sum():,} cells)", flush=True)

rng = np.random.default_rng(args.seed)


MAX_ATTEMPTS = 40


def draw_positions():
    """Uniform within each station's own uncertainty disc.

    ASSM: uniform IN AREA (r = u*sqrt(U)), not uniform in radius -- the latter
    concentrates draws near the centre and would understate the spread, which is
    the one direction this experiment must not err in.

    A drawn position is rejected if it lands further than `--max-snap-m` from any
    road node: a fire station stands on a street, and the real 33 snap 7-249 m
    (median 63 m).

    Rejection is PER STATION, not per draw. The uncertainties are independent, so
    resampling all 33 whenever any one lands badly is both wrong and unusable:
    per-station acceptance is ~90%, which over 33 stations is 0.9^33 ~ 3%, and
    the filter rather than the uncertainty would then decide the answer.
    """
    n = len(xy0)
    # Under `gmaps`, an ambiguous station is one of two real candidates, so the
    # draw picks a candidate first and only then perturbs within it.
    centres = xy0.copy()
    if XY_ALT is not None:
        pick = rng.random(n) < 0.5
        use_alt = pick & np.isfinite(XY_ALT[:, 0])
        centres[use_alt] = XY_ALT[use_alt]
    xy = centres.copy()
    settled = np.zeros(n, dtype=bool)
    settled[unc == 0] = True
    rejected = 0
    for _ in range(MAX_ATTEMPTS):
        todo = ~settled
        if not todo.any():
            break
        m = int(todo.sum())
        u = unc[todo]
        if EMPIRICAL is not None and (u < 0).any():
            # sentinel -1 means "this station is unconfirmed": empirical draw
            r = np.where(u < 0, rng.choice(EMPIRICAL, size=m, replace=True),
                         np.abs(u) * np.sqrt(rng.random(m)))
        elif EMPIRICAL is not None:
            r = rng.choice(EMPIRICAL, size=m, replace=True)
        else:
            r = u * np.sqrt(rng.random(m))
        th = rng.random(m) * 2 * np.pi
        trial = centres[todo] + np.column_stack([r * np.cos(th), r * np.sin(th)])
        _, dist = snap(ctx.graph, trial[:, 0], trial[:, 1])
        ok = dist <= args.max_snap_m
        rejected += int((~ok).sum())
        sel = np.flatnonzero(todo)[ok]
        xy[sel] = trial[ok]
        settled[sel] = True
    if not settled.all():  # noqa: E501
        # Do not silently fall back to the unperturbed position: that would pull
        # the draw toward the point estimate and shrink the spread.
        raise SystemExit(f"{int((~settled).sum())} station(s) found no plausible "
                         f"position in {MAX_ATTEMPTS} attempts; raise --max-snap-m")
    idx, dist = snap(ctx.graph, xy[:, 0], xy[:, 1])
    return idx, dist, rejected


M = None if args.skip_decision else sparse.load_npz(f"data/interim/coverage_{SVC}.npz")
cand = gpd.read_parquet("data/interim/candidates.parquet")
feas = cand["land_feasible"].to_numpy().astype(bool)
point_sites = None
if M is not None:
    p0 = SitingProblem(coverage=M, precovered=ctx.precovered, demand=demand, k=K,
                       ward_of=ctx.ward, land_feasible=feas)
    point_sites = set(exact.solve(p0, time_limit_s=120).selected)
    print(f"  point-estimate siting at k={K}: {sorted(point_sites)}", flush=True)

shares, precov_counts, site_counts, jaccards, rejects = [], [], {}, [], 0
for n in range(N):
    s_idx, s_dist, rej = draw_positions()
    rejects += rej
    best_s = cov.response_seconds(ctx.graph, s_idx, ctx.cell_idx, ctx.cell_snap_m,
                                  overhead_s=overhead, cutoff_ds=CUTOFF)
    pre = np.isfinite(best_s) & (best_s <= budget)
    shares.append(float(demand[pre].sum() / tot))
    precov_counts.append(int(pre.sum()))

    if M is not None:
        p = SitingProblem(coverage=M, precovered=pre, demand=demand, k=K,
                          ward_of=ctx.ward, land_feasible=feas)
        sel = set(exact.solve(p, time_limit_s=60, warm_start=True).selected)
        for j in sel:
            site_counts[int(j)] = site_counts.get(int(j), 0) + 1
        jaccards.append(len(sel & point_sites) / len(sel | point_sites))

    if (n + 1) % 25 == 0:
        a = np.array(shares)
        print(f"    {n+1:4d}/{N}  coverage mean {a.mean():.2%} sd {a.std():.4f} "
              f"range {a.min():.2%}-{a.max():.2%}"
              f"{'' if M is None else f'  site overlap {np.mean(jaccards):.2f}'}",
              flush=True)

a = np.array(shares)
lo, hi = np.percentile(a, [5, 95])
spread_pts = 100 * (hi - lo)
report = {
    "experiment": "E-11", "service": SVC, "draws": N, "seed": args.seed,
    "error_model": args.error_model,
    # Signature of the station positions this interval was computed FROM. A
    # consumer that finds a different signature is holding a stale interval --
    # which is how fire briefly published a 40.5% point estimate under a
    # 33.2-38.7% band computed for superseded positions.
    "stations_signature": station_signature(st),
    "k": K, "max_snap_m": args.max_snap_m, "rejected_station_draws": rejects,
    "rejection_rate_per_station_draw": round(rejects / (rejects + N * len(xy0)), 4),
    "uncertainty_m": {str(k): int(v) for k, v in
                      pd.Series(unc).value_counts().sort_index().items()},
    "point_estimate_coverage": round(ctx.baseline_share, 4),
    "coverage": {
        "mean": round(float(a.mean()), 4), "sd": round(float(a.std()), 4),
        "min": round(float(a.min()), 4), "max": round(float(a.max()), 4),
        "p5": round(float(lo), 4), "p95": round(float(hi), 4),
        "p5_p95_spread_points": round(spread_pts, 2),
        "bias_vs_point_estimate_points": round(100 * (a.mean() - ctx.baseline_share), 2),
    },
    "PROVISIONAL": True,
}

print(f"\n=== COVERAGE under station position uncertainty ===")
print(f"  point estimate      {ctx.baseline_share:.2%}")
print(f"  mean over {N} draws  {a.mean():.2%}  (sd {100*a.std():.2f} pts)")
print(f"  P5-P95              {lo:.2%} - {hi:.2%}   spread {spread_pts:.2f} points")
print(f"  full range          {a.min():.2%} - {a.max():.2%}")
print(f"  rejected station-draws {rejects} of {rejects + N*len(xy0)} "
      f"({100*rejects/max(1,rejects + N*len(xy0)):.1f}%)")

if M is not None:
    freq = {j: c / N for j, c in sorted(site_counts.items(), key=lambda kv: -kv[1])}
    always = [j for j, f in freq.items() if f >= 0.95]
    never_stable = [j for j, f in freq.items() if f < 0.5]
    report["decision"] = {
        "point_estimate_sites": sorted(point_sites),
        "site_selection_frequency": {str(j): round(f, 3) for j, f in freq.items()},
        "sites_selected_in_95pct_of_draws": sorted(always),
        "distinct_sites_ever_selected": len(freq),
        "mean_jaccard_vs_point_estimate": round(float(np.mean(jaccards)), 3),
        "draws_reproducing_the_point_estimate_set": int(sum(1 for j in jaccards if j == 1.0)),
    }
    d = report["decision"]
    print(f"\n=== DECISION: does the recommendation move? (k={K}) ===")
    print(f"  distinct sites ever chosen        {d['distinct_sites_ever_selected']} "
          f"(for {K} slots)")
    print(f"  chosen in >=95% of draws          {len(always)} of {K}")
    print(f"  mean overlap with point estimate  {d['mean_jaccard_vs_point_estimate']:.2f} Jaccard")
    print(f"  draws reproducing it exactly      {d['draws_reproducing_the_point_estimate_set']}/{N}")

# The verdict this experiment exists to deliver.
EFFECTS = {"E-10 junction term": 3.4, "maximin vs dry-only siting": 4.7,
           "equity cost at k=20": 5.0}
print(f"\n=== IS THE MODELLING WORK ABOVE THE NOISE FLOOR? ===")
print(f"  noise floor (P5-P95 coverage spread): {spread_pts:.2f} points")
verdict = {}
for name, size in EFFECTS.items():
    ok = size > spread_pts
    verdict[name] = {"effect_points": size, "above_noise": bool(ok)}
    print(f"    {name:32s} {size:4.1f} pts  {'ABOVE' if ok else 'BELOW'} the noise floor")
report["noise_floor_points"] = round(spread_pts, 2)
report["effects_vs_noise"] = verdict
report["seconds"] = round(time.time() - t0, 1)
json.dump(report, open(OUT, "w"), indent=2, sort_keys=True)
print(f"\nwrote {OUT}  ({report['seconds']}s)")
