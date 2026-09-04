"""Scenario assembly: one scenario config -> one set of arc traversal times.

Build step 13. A scenario is not a filter applied to a finished result; it is a
DIFFERENT NETWORK. Peak congestion rescales speeds, flooding removes links
outright, and both change which demand cells are reachable at all. Everything
downstream — coverage, siting, equity — is recomputed on that network.

The three scripts that need arc times (`attribute`, `validate_routing`,
`calibrate*`) each built the junction-delay vector inline and identically. It
lives here now, because the E-10 ablation has to be able to change it in ONE
place and have every consumer see the change.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ers.flood import (classify_arcs, flood_factors, load_flood_points,
                       load_flood_zones)
from ers.geo.attrs import attribute_edges, junction_delay


def load_scenario(path: str | Path) -> dict:
    s = yaml.safe_load(Path(path).read_text())
    s.setdefault("weight", 0.0)
    s.setdefault("report_only", False)
    return s


def load_scenarios(paths) -> list[dict]:
    return [load_scenario(p) for p in paths]


def head_delay_seconds(nodes: pd.DataFrame, edges: pd.DataFrame, speeds: dict,
                       *, junction_scale: float | None = None) -> np.ndarray:
    """Junction delay in seconds credited at each arc's HEAD node.

    `junction_scale` overrides `speeds['junction_delay_scale']`. The override is
    the entire mechanism of the E-10 ablation: pass 0.0 and the junction term is
    deleted from the model, not merely reduced.
    """
    nidx = nodes.set_index("osmid") if "osmid" in nodes.columns else nodes
    deg = nidx["street_count"].fillna(0).to_numpy()
    sig = nidx["highway"].fillna("").astype(str).str.contains("traffic_signals").to_numpy()
    scale = float(speeds.get("junction_delay_scale", 1.0)) if junction_scale is None \
        else float(junction_scale)
    by_node = pd.Series(junction_delay(deg, sig, speeds) * scale, index=nidx.index)
    return edges["v"].map(by_node).fillna(0.0).to_numpy()


@dataclass(frozen=True)
class ScenarioNetwork:
    tau_ds: np.ndarray            # int32 deciseconds per arc
    flood_states: np.ndarray | None
    attribution: dict             # AttributionResult.stats
    flood: dict                   # zone + arc-classification stats, {} when dry


def flood_arc_states(scenario: dict, edges: pd.DataFrame, metric_crs: str
                     ) -> tuple[np.ndarray | None, dict]:
    """Per-arc flood state for a scenario, or (None, {}) when it is not a flood."""
    fl = scenario.get("flood")
    if not fl:
        return None, {}

    layer = fl["layer"]
    if fl.get("geometry") == "points":
        # 2015 is OBSERVED points with measured depth, not a modelled extent.
        # Each point is buffered to a disc and classified by depth against the
        # A-08 closure threshold; the result is far sparser than a return-period
        # surface and is reported, never optimised against.
        zones, zstats = load_flood_points(
            layer, metric_crs,
            buffer_m=float(fl["point_buffer_m"]),
            depth_field=fl.get("depth_field", "DEPTH"),
            depth_units=fl.get("depth_units", "inches"),
            closure_depth_m=float(fl["closure_depth_m"]),
        )
        category_field, link_state = "_state", {"closed": "closed", "wading": "wading"}
    else:
        zones, zstats = load_flood_zones(layer, metric_crs,
                                         category_field=fl.get("category_field", "CATEGORY"))
        category_field = fl.get("category_field", "CATEGORY")
        link_state = fl["link_state"]

    states, astats = classify_arcs(edges, zones, link_state=link_state,
                                   category_field=category_field,
                                   bridges_exempt=bool(fl.get("bridges_exempt", True)))
    return states, {"layer": layer, "zones": zstats, "arcs": astats}


def build_network(nodes: pd.DataFrame, edges: pd.DataFrame, *, speeds: dict, service: dict,
                  scenario: dict, metric_crs: str, junction_scale: float | None = None,
                  flood_states: np.ndarray | None = None,
                  flood_stats: dict | None = None) -> ScenarioNetwork:
    """Traversal times for one (service, scenario) pair.

    `flood_states` may be supplied by the caller so the expensive spatial join is
    done once per scenario rather than once per service — the flood state of an
    arc is a property of the water, not of the vehicle.
    """
    if flood_states is None and flood_stats is None:
        flood_states, flood_stats = flood_arc_states(scenario, edges, metric_crs)
    flood_stats = flood_stats or {}

    factor = None
    if flood_states is not None:
        wsf = float(scenario["flood"].get("wading_speed_factor", 0.35))
        factor = flood_factors(flood_states, wading_speed_factor=wsf)

    hd = head_delay_seconds(nodes, edges, speeds, junction_scale=junction_scale)
    r = attribute_edges(edges, hd, speeds=speeds, service=service,
                        peak=bool(scenario.get("peak", False)), flood_factor=factor)
    return ScenarioNetwork(r.tau_ds, flood_states, r.stats, flood_stats)
