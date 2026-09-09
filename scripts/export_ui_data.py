"""Export everything the coverage console needs, as one JSON. Build step 17.

The console is a VIEW, not a second implementation. Every number it shows is
produced here by the same pipeline code that writes the reports, so the two can
never disagree -- which is the failure this project spent F-13 to F-19 removing.

Geometry is stored as one shared hexagon outline plus 3,838 centroids. H3
resolution-9 cells over an area this size are near-identical in shape, so the
mean vertex offset reproduces them to well under a pixel and costs ~40x less
than storing every polygon.
"""
import json, sys, time, warnings
sys.path.insert(0, "src")
import geopandas as gpd, numpy as np, pandas as pd, yaml
from scipy import sparse
from ers import coverage as cov
from ers.pipeline import build_scenario_coverage, load_service, station_signature
from ers.publish import publication_basis
from ers.routing.csr import snap

SCEN = ["dry", "peak", "flood5", "flood25", "flood100", "f2015"]
t0 = time.time()
def _basis_line() -> str:
    """How the console should describe what these numbers rest on."""
    b = publication_basis()
    if b["publication_basis"] == "surveyed":
        return "All 33 station positions are surveyed"
    if b["publication_basis"] == "waived":
        w = b["waiver"]
        return (f"Published under the waiver of {w['date']} — NOT on surveyed "
                f"positions. {w['stations_unsurveyed']} of {w['stations_total']} "
                f"stations carry map-listing positions; 14 have a confirmed "
                f"identity. Review by {w['review_by']}")
    return b.get("provisional_reason", "provisional")


cfg = yaml.safe_load(open("config/city/chennai.yml"))
speeds = yaml.safe_load(open("config/speeds/base.yml"))
cells = gpd.read_parquet("data/interim/demand_cells.parquet")
cand = gpd.read_parquet("data/interim/candidates.parquet")
st = pd.read_csv("data/interim/stations_resolved.csv")

# --- shared hexagon: mean vertex offset from centroid, in degrees
#
# These centroids are taken in EPSG:4326, which `ers.pipeline` explicitly warns
# against -- "a centroid computed in degrees is not the centroid of the real-world
# polygon" -- so the deviation is justified here rather than left to be
# rediscovered as a warning in the build log.
#
# The rule matters when a centroid is SNAPPED to a road node, because an error
# there picks the wrong node. These centroids are never snapped: they are the
# lon/lat a hexagon is PAINTED at in the console, and the console does no
# routing. Measured over all 3,838 cells, the degree-space and projected
# centroids differ by 0.000 m (max) -- H3 r9 cells are small and regular enough
# that the two coincide -- against an export rounded to 5 dp, about 1.11 m.
#
# Projecting and unprojecting would therefore change no exported digit.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    cc = cells.geometry.centroid
offs = []
for geom, cx, cy in zip(cells.geometry.head(400), cc.x.head(400), cc.y.head(400)):
    xy = np.array(geom.exterior.coords)[:-1]
    if len(xy) == 6:
        order = np.argsort(np.arctan2(xy[:, 1] - cy, xy[:, 0] - cx))
        offs.append(xy[order] - [cx, cy])
hexoff = np.mean(offs, axis=0)
print(f"shared hexagon from {len(offs)} cells, "
      f"residual {np.std(offs, axis=0).max()*111000:.1f} m")

out = {
    "meta": {"city": cfg["name"], "cells": len(cells),
             "population": round(float(cells["population"].sum())),
             "trip_overhead_s": float(speeds["trip_overhead_s"]),
             "junction_delay_scale": float(speeds["junction_delay_scale"]),
             "stations_signature": station_signature(st),
             **publication_basis(),
             # One sentence the console can print verbatim, whichever basis is
             # in force. Derived rather than hardcoded: the previous fixed
             # string would have kept saying PROVISIONAL after the project had
             # decided to publish, which is the same class of error in the
             # opposite direction.
             "basis_line": _basis_line(),
             "generated_by": "scripts/export_ui_data.py"},
    "hex": [[round(float(a), 6), round(float(b), 6)] for a, b in hexoff],
    "cells": {"lat": [round(float(v), 5) for v in cc.y],
              "lon": [round(float(v), 5) for v in cc.x],
              "pop": [int(round(float(v))) for v in cells["population"]],
              "ward": [int(v) for v in cells["ward_id"]]},
    "stations": [],
    "services": {},
}

# Identity state per station. 33 markers that all look equally solid would
# overstate what is known: 12 are confirmed against the official TNFRS number,
# 4 were OSM-matched from the start, 1 is provably not a municipal station, and
# the rest are assumed. The map should say which is which.
try:
    look = pd.read_csv("data/interim/stations_gmaps_lookup.csv").set_index("station_name")
except FileNotFoundError:
    look = pd.DataFrame()
STATE = {"tnfrs_landline": "confirmed", "tnfrs_cug_mobile": "confirmed",
         "osm_proximity": "corroborated", "contested_unresolved": "unresolved"}
for r in st.itertuples():
    idc = ""
    if len(look) and r.station_name in look.index:
        v = look.loc[r.station_name, "identity_confirmed_by"]
        idc = v if isinstance(v, str) else ""
    state = ("osm_source" if r.geocode_confidence == "osm"
             else STATE.get(idc, "assumed"))
    out["stations"].append({"name": r.station_name, "lat": round(r.lat, 5),
                            "lon": round(r.lon, 5), "conf": r.geocode_confidence,
                            "state": state, "via": idc})
from collections import Counter
print("station identity states:", dict(Counter(x["state"] for x in out["stations"])))

# Ward labels, so the worst-served list names real wards.
wards = gpd.read_parquet("data/interim/wards.parquet")
out["wards"] = {int(r.ward_id): {"no": int(r.ward_no), "zone": str(r.zone_name)}
                for r in wards.itertuples()}

for svc in ("ems", "fire"):
    ctx = load_service(svc)
    scs, meta = build_scenario_coverage(svc, SCEN, progress=False)
    feas = cand["land_feasible"].to_numpy().astype(bool)
    keep = np.flatnonzero(feas)                    # optimise over land-feasible only
    rec = {"budget_s": ctx.budget_s, "standard": ctx.standard,
           "t_alarm_s": int(yaml.safe_load(open(f"config/services/{svc}.yml"))["t_alarm_s"]),
           "t_turnout_s": int(yaml.safe_load(open(f"config/services/{svc}.yml"))["t_turnout_s"]),
           "scenarios": {}}
    g0 = ctx.graph
    for sc in scs:
        # response seconds from the EXISTING network, per cell, exhaustive sweep
        M = sc.coverage.tocsc()[:, keep].tocsr()
        rec["scenarios"][sc.scenario] = {
            "weight": sc.weight, "report_only": sc.report_only,
            "baseline_share": sc.stats["baseline_share"],
            # per-cell response seconds; -1 = unreachable
            "resp": None,           # filled below
            # sparse coverage: for each cell, which candidates reach it in budget
            "cov_indptr": [int(v) for v in M.indptr],
            "cov_indices": [int(v) for v in M.indices],
        }
    # response times need the per-scenario graph again; recompute cheaply
    from ers.scenario import build_network, flood_arc_states, load_scenario
    from ers.geo.graph import read_graph_tables
    from ers.routing.csr import build_graph, travel_times, to_seconds
    nodes, edges = read_graph_tables("data/interim/graph")
    metric = cfg["crs"]["metric"]
    svc_cfg = yaml.safe_load(open(f"config/services/{svc}.yml"))
    ccg = gpd.GeoSeries(cells.to_crs(metric).geometry.centroid, crs=metric)
    g_flat = build_graph(nodes, edges.assign(_w=1), "_w")
    c_idx, c_snap = snap(g_flat, ccg.x.to_numpy(), ccg.y.to_numpy())
    sp = gpd.GeoSeries(gpd.points_from_xy(st["lon"], st["lat"]),
                       crs="EPSG:4326").to_crs(metric)
    s_idx, _ = snap(g_flat, sp.x.to_numpy(), sp.y.to_numpy())
    for sid in SCEN:
        s_cfg = load_scenario(f"config/scenarios/{sid}.yml")
        states, fstats = flood_arc_states(s_cfg, edges, metric)
        net = build_network(nodes, edges, speeds=speeds, service=svc_cfg, scenario=s_cfg,
                            metric_crs=metric, flood_states=states, flood_stats=fstats)
        e2 = edges[["u", "v", "key"]].copy(); e2["tau"] = net.tau_ds
        g = build_graph(nodes, e2, "tau")
        # Per-STATION response, not just the minimum. "Which stations can reach
        # here fastest" is the question a dispatcher asks, and a min() cannot
        # answer it -- it knows the best time but not who provides it.
        dmat = travel_times(g, s_idx, c_idx, cutoff_ds=None)          # |S| x |I|
        allresp = to_seconds(dmat) + (c_snap / cov.ACCESS_SPEED_MS)[None, :] + ctx.overhead_s
        best = allresp.min(axis=0)
        # CEIL, not round. Rounding put four cells sitting at 300.0-300.5 s on the
        # covered side of a 300 s budget -- 10,398 people, and a console reading
        # 61.9% against the pipeline's 61.75%. A view that disagrees with the
        # report it is drawn from is the F-13 failure in a new costume.
        rec["scenarios"][sid]["resp"] = [(-1 if not np.isfinite(v) else int(np.ceil(v)))
                                         for v in best]
        # Top-3 responders per cell, as flat arrays. Flat integer arrays cost a
        # fraction of nested ones in JSON, and three is enough to answer "who
        # comes, and who backs them up".
        TOPK = 3
        order = np.argsort(allresp, axis=0)[:TOPK, :]                 # TOPK x |I|
        who, when = [], []
        for c in range(allresp.shape[1]):
            for r in range(TOPK):
                si = int(order[r, c]); v = allresp[si, c]
                who.append(si if np.isfinite(v) else -1)
                when.append(int(np.ceil(v)) if np.isfinite(v) else -1)
        rec["scenarios"][sid]["top_who"] = who
        rec["scenarios"][sid]["top_s"] = when
        rec["scenarios"][sid]["topk"] = TOPK
        # GATE: coverage computed from the quantised array must equal the exact one.
        pop = cells["population"].to_numpy()
        q = np.array(rec["scenarios"][sid]["resp"], dtype="float64")
        a = float(pop[np.isfinite(best) & (best <= ctx.budget_s)].sum() / pop.sum())
        bq = float(pop[(q >= 0) & (q <= ctx.budget_s)].sum() / pop.sum())
        if abs(a - bq) > 1e-9:
            raise SystemExit(f"{svc}/{sid}: quantised coverage {bq:.6f} != exact {a:.6f}")
        print(f"  {svc:4s} {sid:9s} resp done  coverage {a:.4f} (quantisation exact)",
              flush=True)
    rec["candidates"] = [{"lat": round(float(p.y), 5), "lon": round(float(p.x), 5)}
                         for p in cand.to_crs("EPSG:4326").geometry.iloc[keep]]

    # E-11g bracket: the tight interval assumes every Google POI names the right
    # station. Fifteen of the 29 are unchecked, so both ends travel with the number.
    unc = {}
    for tag, f in (("assumed_correct", f"data/interim/sensitivity_stations_{svc}.json"),
                   ("if_unconfirmed_wrong", f"data/interim/sensitivity_mixed_{svc}.json")):
        try:
            d = json.load(open(f))
            unc[tag] = {"spread_points": d["coverage"]["p5_p95_spread_points"],
                        "p5": d["coverage"]["p5"], "p95": d["coverage"]["p95"],
                        "draws": d["draws"]}
        except FileNotFoundError:
            pass
    rec["uncertainty"] = unc

    # Exact MCLP results, so the browser's greedy can be shown against a proven optimum.
    try:
        o = json.load(open(f"data/interim/optimise_{svc}.json"))
        rec["exact"] = {str(r["k"]): {"share": r["exact_share"],
                                      "greedy": r["greedy_share"],
                                      "proven": r["proven_optimal"]}
                        for r in o["runs"] if r["candidate_set"] == "land-feasible"}
    except (FileNotFoundError, KeyError):
        rec["exact"] = {}
    out["services"][svc] = rec

path = "data/interim/ui_data.json"
json.dump(out, open(path, "w"), separators=(",", ":"))
import os
print(f"\nwrote {path}  {os.path.getsize(path)/1e6:.2f} MB  ({time.time()-t0:.0f}s)")
