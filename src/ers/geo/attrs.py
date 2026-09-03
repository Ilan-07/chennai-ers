"""Arc attribution: turn road geometry into directed traversal times. Build step 06.

Every traversal time is stored as an INTEGER number of deciseconds. That is not
cosmetic: float path costs make Dijkstra's tie-breaking depend on summation
order, which makes results depend on graph iteration order. Integer weights make
ties exact and the whole pipeline reproducible (Finding F-12).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# OSM maxspeed is free text. These are the forms that actually occur in Chennai.
_MPH = re.compile(r"^\s*([\d.]+)\s*mph\s*$", re.I)
_KMH = re.compile(r"^\s*([\d.]+)\s*(?:km/?h)?\s*$", re.I)
_ZONE = re.compile(r"^\s*[A-Z]{2}:(\w+)\s*$")
# ASSM: implicit zone speeds for India. Rarely tagged; included for completeness.
_ZONE_KMH = {"urban": 50.0, "rural": 80.0, "living_street": 20.0, "motorway": 100.0}


def parse_maxspeed(value) -> float | None:
    """Best-effort km/h from an OSM `maxspeed` tag. None when unusable."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (list, tuple)):
        vals = [parse_maxspeed(v) for v in value]
        vals = [v for v in vals if v]
        return min(vals) if vals else None          # conservative: slowest applies
    s = str(value).strip()
    if not s:
        return None
    if m := _MPH.match(s):
        return float(m.group(1)) * 1.609344
    if m := _ZONE.match(s):
        return _ZONE_KMH.get(m.group(1).lower())
    if m := _KMH.match(s):
        v = float(m.group(1))
        return v if 5.0 <= v <= 130.0 else None     # reject nonsense tags
    return None


# Fastest-first. `_link` ramps rank just below their parent class and keep their
# own suffix, because the speed table has explicit entries for them.
_HW_ORDER = [
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street", "service",
]
_HW_RANK = {h: i for i, h in enumerate(_HW_ORDER)}


def primary_highway(value) -> str:
    """A simplified OSM edge can carry a list of classes. Take the fastest — it
    dominates traversal of the merged way. The returned value is a real key in
    the speed table, `_link` suffix preserved."""
    if isinstance(value, (list, tuple)):
        best, best_rank = "residential", 10_000
        for v in value:
            v = str(v)
            if (r := _HW_RANK.get(v, 9_999)) < best_rank:
                best, best_rank = v, r
        return best
    v = str(value)
    return v if v in _HW_RANK else "residential"


def parse_dimension(value) -> float | None:
    """Metres from an OSM `width` / `maxheight` tag."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (list, tuple)):
        vals = [parse_dimension(v) for v in value]
        vals = [v for v in vals if v]
        return min(vals) if vals else None
    s = str(value).strip().lower().replace("m", "").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if 0.5 <= v <= 20.0 else None


@dataclass(frozen=True)
class AttributionResult:
    tau_ds: np.ndarray            # int32 traversal time, deciseconds
    speed_kmh: np.ndarray         # float32, effective speed actually used
    speed_source: np.ndarray      # 'maxspeed' | 'class_default'
    excluded: np.ndarray          # bool, arcs removed by the access filter
    stats: dict


def attribute_edges(
    edges: pd.DataFrame,
    node_delay_s: np.ndarray,
    *,
    speeds: dict,
    service: dict,
    peak: bool = False,
    flood_factor: np.ndarray | None = None,
) -> AttributionResult:
    """Compute directed traversal times for every arc.

    `edges` must be the OSMnx edge table (already directed) with `highway` and
    `length`. `node_delay_s` is the junction delay at each arc's HEAD node,
    aligned to `edges` row order.
    """
    n = len(edges)
    hw = np.array([primary_highway(v) for v in edges["highway"].to_numpy()], dtype=object)
    length_m = edges["length"].to_numpy(dtype="float64")

    free = speeds["free_flow_kmh"]
    peak_f = speeds["peak_factor"]
    default_kmh = np.array([free.get(h, free["residential"]) for h in hw], dtype="float64")

    # A tagged maxspeed overrides the class default.
    tagged = np.array(
        [parse_maxspeed(v) for v in edges.get("maxspeed", pd.Series([None] * n)).to_numpy()],
        dtype="float64",
    ) if "maxspeed" in edges.columns else np.full(n, np.nan)
    has_tag = ~np.isnan(tagged)
    speed = np.where(has_tag, tagged, default_kmh)
    source = np.where(has_tag, "maxspeed", "class_default")

    if peak:
        speed = speed * np.array([peak_f.get(h, peak_f["residential"]) for h in hw])

    mult = service.get("emergency_multiplier", {})
    speed = speed * np.array([mult.get(h, 1.0) for h in hw])

    if flood_factor is not None:
        speed = speed * flood_factor

    # Access filter: arcs a fire appliance physically cannot use, WHERE TAGGED.
    excluded = np.zeros(n, dtype=bool)
    af = service.get("access_filter") or {}
    if af:
        if (lim := af.get("max_height_m_below")) and "maxheight" in edges.columns:
            h = np.array([parse_dimension(v) for v in edges["maxheight"].to_numpy()], dtype="float64")
            excluded |= (~np.isnan(h)) & (h < lim)
        if (lim := af.get("width_m_below")) and "width" in edges.columns:
            wd = np.array([parse_dimension(v) for v in edges["width"].to_numpy()], dtype="float64")
            excluded |= (~np.isnan(wd)) & (wd < lim)

    with np.errstate(divide="ignore", invalid="ignore"):
        travel_s = 3.6 * length_m / speed
    travel_s = np.where(np.isfinite(travel_s), travel_s, np.inf)

    delay_s = node_delay_s * float(service.get("junction_delay_factor", 1.0))
    total_s = travel_s + delay_s

    tau_ds = np.where(
        np.isfinite(total_s),
        np.rint(np.clip(total_s, 0, 6_000_000) * 10.0),
        np.iinfo(np.int32).max,
    ).astype(np.int32)
    tau_ds[excluded] = np.iinfo(np.int32).max          # unusable arc

    usable = ~excluded & np.isfinite(total_s)
    # A scenario can legitimately leave zero usable arcs (a fully inundated
    # sub-network). Weighted means are undefined there, so report None rather
    # than dividing by zero -- this is a real state, not an error.
    if usable.any() and length_m[usable].sum() > 0:
        mean_speed = round(float(np.average(speed[usable], weights=length_m[usable])), 2)
        total_hours = round(float(total_s[usable].sum()) / 3600.0, 1)
        jd_share = round(float(delay_s[usable].sum() / max(total_s[usable].sum(), 1e-9)), 4)
    else:
        mean_speed = total_hours = jd_share = None

    stats = {
        "arcs": int(n),
        "arcs_usable": int(usable.sum()),
        "arcs_excluded_by_access_filter": int(excluded.sum()),
        "arcs_unreachable": int((~np.isfinite(total_s)).sum()),
        "maxspeed_tagged_share": round(float(has_tag.mean()), 4),
        "network_length_km": round(float(length_m.sum()) / 1000.0, 1),
        "mean_speed_kmh": mean_speed,
        "total_traversal_hours": total_hours,
        "junction_delay_share": jd_share,
    }
    return AttributionResult(tau_ds, speed.astype("float32"), source, excluded, stats)


def junction_delay(
    node_degree: np.ndarray, is_signalised: np.ndarray, speeds: dict
) -> np.ndarray:
    """Delay in seconds credited at a node. ASSM A-02; ablated in E-10."""
    jd = speeds["junction_delay_s"]
    out = np.full(len(node_degree), float(jd.get("other", 0.0)))
    out[node_degree >= 3] = float(jd["unsignalised_degree_ge_3"])
    out[is_signalised] = float(jd["signalised"])
    return out
