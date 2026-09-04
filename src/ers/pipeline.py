"""The one way to route a service against the existing station network.

Build steps 09-14 all need the same thing: travel time from the 33 existing
stations to every demand cell, and the resulting `precovered` mask. Four scripts
each built it inline, and they drifted:

  * `frontier.py` omitted the calibrated 45 s `trip_overhead_s`, so its ward
    figures described a model 45 s faster than every other number in the project.
  * `equity_curve.py` loaded a `precovered_{svc}.npy` that NO SCRIPT PRODUCED.
    It reported 36.3% of population precovered against the 55.7% that
    `baseline.py` and `optimise.py` both computed, which put its k=5 "efficiency"
    coverage BELOW the do-nothing baseline -- an arithmetic impossibility.

Both bugs were invisible because each script was internally consistent. There is
now exactly one implementation, and `precovered` is derived, never loaded from a
file: an array on disk with no producer cannot be replayed, and the project rule
is that no number appears unless a run can reproduce it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from ers import coverage
from ers.geo.graph import read_graph_tables
from ers.routing.csr import RoadGraph, build_graph, snap


@dataclass(frozen=True)
class ServiceContext:
    """Everything downstream of routing, for one service on the dry network."""
    service: str
    budget_s: float
    overhead_s: float
    standard: str
    metric_crs: str
    graph: RoadGraph
    cells: gpd.GeoDataFrame
    stations: pd.DataFrame
    station_idx: np.ndarray
    cell_idx: np.ndarray
    cell_snap_m: np.ndarray
    demand: np.ndarray
    ward: np.ndarray
    baseline_s: np.ndarray          # response seconds from the nearest station
    precovered: np.ndarray          # bool, covered within budget by an existing station

    @property
    def total_demand(self) -> float:
        return float(self.demand.sum())

    @property
    def baseline_share(self) -> float:
        return float(self.demand[self.precovered].sum() / self.total_demand)

    def check_baseline_share(self, recorded: float, *, tol: float = 5e-4) -> None:
        """Fail loudly when a stored report disagrees with a fresh routing.

        A downstream script that silently reuses a stale baseline produces
        numbers that look fine and are wrong -- which is exactly how the
        equity-curve figures went bad.
        """
        if abs(self.baseline_share - recorded) > tol:
            raise SystemExit(
                f"baseline share mismatch for {self.service}: recomputed "
                f"{self.baseline_share:.4f} vs recorded {recorded:.4f}. "
                f"Re-run scripts/optimise.py {self.service} before this step.")


def load_service(service: str, *, root: str | Path = ".",
                 cutoff_ds: float | None = None) -> ServiceContext:
    """Route `service` from the existing stations on the dry network."""
    root = Path(root)
    speeds = yaml.safe_load((root / "config/speeds/base.yml").read_text())
    cfg = yaml.safe_load((root / "config/city/chennai.yml").read_text())
    scfg = yaml.safe_load((root / f"config/services/{service}.yml").read_text())
    std = yaml.safe_load((root / "config/standards/sfac.yml").read_text())

    metric = cfg["crs"]["metric"]
    overhead = float(speeds.get("trip_overhead_s", 0.0))
    preset = scfg["default_standard"]
    # Finding F-03: the isochrone budget is the TARGET minus the offsets, not
    # the target. Getting this wrong flatters coverage by a whole minute.
    budget_s = std["presets"][preset]["t_target_s"] - scfg["t_alarm_s"] - scfg["t_turnout_s"]

    nodes, edges = read_graph_tables(str(root / "data/interim/graph"))
    arcs = pd.read_parquet(root / "data/interim/arc_times.parquet")
    edges = edges.merge(arcs[["u", "v", "key", "tau_ds_ems", "tau_ds_fire"]],
                        on=["u", "v", "key"], how="left")
    cells = gpd.read_parquet(root / "data/interim/demand_cells.parquet")
    stations = pd.read_csv(root / "data/interim/stations_resolved.csv")

    g = build_graph(nodes, edges, f"tau_ds_{service}")
    # Centroids MUST be taken in the projected CRS -- a centroid computed in
    # degrees is not the centroid of the real-world polygon.
    cc = gpd.GeoSeries(cells.to_crs(metric).geometry.centroid, crs=metric)
    cell_idx, cell_snap_m = snap(g, cc.x.to_numpy(), cc.y.to_numpy())
    sp = gpd.GeoSeries(gpd.points_from_xy(stations["lon"], stations["lat"]),
                       crs="EPSG:4326").to_crs(metric)
    station_idx, _ = snap(g, sp.x.to_numpy(), sp.y.to_numpy())

    baseline_s = coverage.response_seconds(g, station_idx, cell_idx, cell_snap_m,
                                           overhead_s=overhead, cutoff_ds=cutoff_ds)
    precovered = np.isfinite(baseline_s) & (baseline_s <= budget_s)

    return ServiceContext(
        service=service, budget_s=budget_s, overhead_s=overhead, standard=preset,
        metric_crs=metric, graph=g, cells=cells, stations=stations,
        station_idx=station_idx, cell_idx=cell_idx, cell_snap_m=cell_snap_m,
        demand=cells["population"].to_numpy().astype("float64"),
        ward=cells["ward_id"].to_numpy(),
        baseline_s=baseline_s, precovered=precovered,
    )


def ward_shares(ward: np.ndarray, demand: np.ndarray, covered: np.ndarray) -> pd.Series:
    """Population-weighted coverage share per ward."""
    df = pd.DataFrame({"w": ward, "d": demand, "c": covered.astype(float)})
    return df.groupby("w").apply(
        lambda x: (x["d"] * x["c"]).sum() / max(x["d"].sum(), 1e-9),
        include_groups=False)


def build_scenario_coverage(service: str, scenario_ids, *, root: str | Path = ".",
                            progress: bool = True) -> tuple[list, dict]:
    """Coverage matrix and precovered mask per scenario. Build step 15.

    The expensive part is not the shortest paths, it is that each scenario needs
    a DIFFERENT graph: flooding removes arcs, peak rescales speeds. So the arc
    attribution and the CSR are rebuilt per scenario, and the candidate sweep is
    re-run against each. Flood state is classified once per scenario and shared
    across services, since it is a property of the water, not the vehicle.

    Snapping is done ONCE on the dry topology and reused, so a station or cell
    cannot migrate to a different node as arcs are removed -- otherwise the
    comparison would measure snapping noise alongside the flood.
    """
    import geopandas as gpd
    from scipy import sparse

    from ers.model.problem import ScenarioCoverage
    from ers.routing.csr import build_graph, travel_times, to_seconds
    from ers.scenario import build_network, flood_arc_states, load_scenario

    root = Path(root)
    speeds = yaml.safe_load((root / "config/speeds/base.yml").read_text())
    cfg = yaml.safe_load((root / "config/city/chennai.yml").read_text())
    scfg = yaml.safe_load((root / f"config/services/{service}.yml").read_text())
    std = yaml.safe_load((root / "config/standards/sfac.yml").read_text())
    metric = cfg["crs"]["metric"]
    overhead = float(speeds.get("trip_overhead_s", 0.0))
    budget_s = (std["presets"][scfg["default_standard"]]["t_target_s"]
                - scfg["t_alarm_s"] - scfg["t_turnout_s"])

    nodes, edges = read_graph_tables(str(root / "data/interim/graph"))
    cells = gpd.read_parquet(root / "data/interim/demand_cells.parquet")
    stations = pd.read_csv(root / "data/interim/stations_resolved.csv")
    cand = gpd.read_parquet(root / "data/interim/candidates.parquet").to_crs(metric)

    g0 = build_graph(nodes, edges.assign(_w=1), "_w")
    cc = gpd.GeoSeries(cells.to_crs(metric).geometry.centroid, crs=metric)
    c_idx, c_snap = snap(g0, cc.x.to_numpy(), cc.y.to_numpy())
    sp = gpd.GeoSeries(gpd.points_from_xy(stations["lon"], stations["lat"]),
                       crs="EPSG:4326").to_crs(metric)
    s_idx, _ = snap(g0, sp.x.to_numpy(), sp.y.to_numpy())
    j_idx, _ = snap(g0, cand.geometry.x.to_numpy(), cand.geometry.y.to_numpy())
    access_s = c_snap / coverage.ACCESS_SPEED_MS

    # A cell beyond 3x the budget cannot be covered within it, so this cutoff is
    # exact for a coverage matrix (unlike one used to report how far away a cell is).
    cutoff = budget_s * 10 * 3

    out = []
    for sid in scenario_ids:
        sc = load_scenario(root / f"config/scenarios/{sid}.yml")
        states, fstats = flood_arc_states(sc, edges, metric)
        net = build_network(nodes, edges, speeds=speeds, service=scfg, scenario=sc,
                            metric_crs=metric, flood_states=states, flood_stats=fstats)
        e2 = edges[["u", "v", "key"]].copy()
        e2["tau"] = net.tau_ds
        g = build_graph(nodes, e2, "tau")

        pre_s = to_seconds(travel_times(g, s_idx, c_idx, cutoff_ds=cutoff).min(axis=0)) \
            + access_s + overhead
        precovered = np.isfinite(pre_s) & (pre_s <= budget_s)

        cand_s = to_seconds(travel_times(g, j_idx, c_idx, cutoff_ds=cutoff)) \
            + access_s[None, :] + overhead
        M = sparse.csr_matrix((cand_s <= budget_s).T)

        pop = cells["population"].to_numpy()
        out.append(ScenarioCoverage(
            scenario=sid, weight=float(sc["weight"]),
            coverage=M, precovered=precovered,
            report_only=bool(sc.get("report_only", False)),
            stats={"baseline_share": round(float(pop[precovered].sum() / pop.sum()), 4),
                   "matrix_nnz": int(M.nnz),
                   "cells_no_candidate_reaches": int((M.getnnz(axis=1) == 0).sum()),
                   "arcs_usable": net.attribution["arcs_usable"],
                   "flood": fstats.get("arcs", {})}))
        if progress:
            st = out[-1].stats
            print(f"  {sid:9s} baseline {st['baseline_share']:6.2%}  matrix nnz "
                  f"{st['matrix_nnz']:>7,d}  cells no candidate reaches "
                  f"{st['cells_no_candidate_reaches']:>4d}", flush=True)

    meta = {"service": service, "budget_s": budget_s, "trip_overhead_s": overhead,
            "cells": len(cells), "candidates": len(cand),
            "cell_snap_max_m": round(float(c_snap.max()), 1)}
    return out, meta
