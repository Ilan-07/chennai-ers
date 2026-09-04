"""Resolve the authoritative station inventory to verified coordinates.

Finding F-01: the source deck assumed five stations. The Greater Chennai
Corporation publishes 33 (9 North, 9 South, 7 Central, 8 Suburban). OSM carries
only 16 fire-station features over the GCC bounding box — roughly 48% complete,
two of which are industrial/airport rather than municipal.

So the AUTHORITATIVE LIST IS THE SOURCE OF TRUTH for *which* stations exist, and
OSM/Nominatim are used only to attach coordinates to it. Every resolved point
carries a confidence class, and nothing is silently invented.
"""
from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "chennai-ers/0.1 (academic emergency-response siting research)"

# Tokens that carry no discriminating information in a station name.
_NOISE = {
    "fire", "fires", "rescue", "station", "stn", "fs", "service", "services",
    "centre", "center", "and", "&", "the", "tamil", "nadu", "tamilnadu", "chennai",
}

# Ordered best -> worst. Anything below `osm` is PROVISIONAL and blocks the
# baseline gate until a human has verified it against imagery.
#
# `google_maps_poi` (E-11c) ranks between `osm` and `geocoded`: it is a precise
# third-party POI, far better than the `locality` centroid it replaces, and it
# cut the measured noise floor from +/-9.8 to +/-1.2 points. It is NEVERTHELESS
# IN SURVEY_REQUIRED. A Maps POI is somebody else's data entry, not a
# verification: five of the 29 are ambiguous between two candidate POIs, two sit
# hundreds of metres off the routable network, and exactly one was corroborated
# against an independent source (a phone-number match). Promoting a better
# geocode to "verified" would open the publish gate on desk research, which is
# the precise failure this gate exists to prevent.
CONFIDENCE = ("surveyed", "osm", "google_maps_poi", "geocoded", "locality", "inferred")
SURVEY_REQUIRED = ("google_maps_poi", "geocoded", "locality", "inferred")

# ASSM: positional uncertainty credited to each confidence class, metres.
# Used to decide whether a station's snapped network node is trustworthy.
UNCERTAINTY_M = {"surveyed": 25, "osm": 60, "google_maps_poi": 50, "geocoded": 150,
                 "locality": 900, "inferred": None}


def _norm(name: str) -> frozenset[str]:
    toks = re.split(r"[^a-z0-9]+", name.lower())
    return frozenset(t for t in toks if t and t not in _NOISE)


@dataclass
class ResolvedStation:
    station_name: str
    division: str
    service: str
    lat: float | None
    lon: float | None
    geocode_confidence: str
    match_source: str
    match_detail: str
    uncertainty_m: float | None = None
    survey_required: bool = True
    osm_class: str = ""
    osm_type: str = ""
    plausibility: str = ""


def load_authoritative(path: str | Path) -> list[dict]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} is empty")
    return rows


def load_osm_points(path: str | Path) -> list[dict]:
    """Flatten an Overpass response into name/lat/lon records."""
    data = json.loads(Path(path).read_text())
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        out.append({
            "name": tags.get("name", ""),
            "lat": float(lat),
            "lon": float(lon),
            "operator": tags.get("operator", ""),
        })
    return out


def _plausibility(r: dict) -> str:
    """How usable is a Nominatim hit as a stand-in for a station position?

    A `highway` result is a ROAD, not a settlement -- "Redhills" resolves to
    "Redhills Road" in Anna Nagar, roughly 9 km from the Red Hills locality.
    Those are the worst provisional points and are called out explicitly so the
    surveyor starts with them.
    """
    cls = r.get("category") or r.get("class") or ""   # jsonv2 uses `category`
    typ = r.get("type", "")
    if cls == "amenity" and typ == "fire_station":
        return "ok"
    if typ in {"suburb", "neighbourhood", "quarter", "town", "village", "city", "locality"}:
        return "settlement_centroid"
    if typ in {"station", "halt", "bus_stop", "tram_stop", "platform"}:
        return "transit_feature"       # e.g. "Korukkupet" -> Korukkupet RAILWAY station
    if typ in {"motorway", "trunk", "primary", "secondary", "tertiary",
               "residential", "unclassified", "service", "road"}:
        return "road_feature"          # e.g. "Redhills" -> Redhills ROAD, ~9 km off
    if typ == "administrative":
        return "boundary_centroid"
    return "unrelated_feature"         # e.g. "Sembium" -> Sembium PHC (a clinic)


def _nominatim(query: str, viewbox: tuple[float, float, float, float]) -> dict | None:
    """Single bounded Nominatim lookup. Caller must rate-limit to <=1 req/s.

    Uses `requests` rather than urllib because the macOS framework Python ships
    without a CA bundle; urllib fails SSL verification and a bare `except` here
    would silently turn a transport failure into "no such place", which is
    exactly the kind of silent data loss this project must not have.
    """
    import requests  # bundles certifi

    w, s, e, n = viewbox
    params = {
        "q": query, "format": "jsonv2", "limit": 1,
        "viewbox": f"{w},{n},{e},{s}", "bounded": 1,
        "countrycodes": "in",
    }
    resp = requests.get(NOMINATIM, params=params, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()          # transport errors must NOT look like misses
    res = resp.json()
    return res[0] if res else None


def resolve(
    authoritative_csv: str | Path,
    osm_json: str | Path,
    bbox: tuple[float, float, float, float],
    *,
    use_nominatim: bool = True,
    sleep_s: float = 1.1,
) -> list[ResolvedStation]:
    """Attach coordinates to every authoritative station.

    bbox is (south, west, north, east) to match the city config.
    """
    auth = load_authoritative(authoritative_csv)
    osm = load_osm_points(osm_json)
    s, w, n, e = bbox
    viewbox = (w, s, e, n)

    # Index OSM points by their discriminating name tokens.
    osm_index: dict[frozenset[str], dict] = {}
    for p in osm:
        key = _norm(p["name"])
        if key and key not in osm_index:
            osm_index[key] = p

    resolved: list[ResolvedStation] = []
    for row in auth:
        name = row["station_name"]
        key = _norm(name)
        hit = None

        # Exact token-set match, then subset match (OSM names carry extra words).
        if key in osm_index:
            hit = osm_index[key]
        else:
            for okey, pt in osm_index.items():
                if key and (key <= okey or okey <= key):
                    hit = pt
                    break

        if hit is not None:
            resolved.append(ResolvedStation(
                name, row["division"], row["service"], hit["lat"], hit["lon"],
                "osm", "osm_name_match", hit["name"] or "(unnamed)",
                UNCERTAINTY_M["osm"], False, "amenity", "fire_station", "ok",
            ))
            continue

        if use_nominatim:
            # Query 1 — a NAMED fire station. A hit here is a real station geocode.
            time.sleep(sleep_s)
            r = _nominatim(f"{name} Fire Station, Chennai, Tamil Nadu, India", viewbox)
            if r is not None:
                resolved.append(ResolvedStation(
                    name, row["division"], row["service"],
                    float(r["lat"]), float(r["lon"]),
                    "geocoded", "nominatim_station", r.get("display_name", "")[:120],
                    UNCERTAINTY_M["geocoded"], False,
                    (r.get("category") or r.get("class") or ""), r.get("type", ""), "ok",
                ))
                continue

            # Query 2 — the LOCALITY centroid. This is a provisional position, NOT a
            # station location, and must never be labelled as one: Nominatim resolves
            # "Redhills" to a road in Anna Nagar, ~9 km from the Red Hills locality.
            # Provisional points let the pipeline run end to end; the publish gate
            # stops them reaching any output.
            time.sleep(sleep_s)
            r = _nominatim(f"{name}, Chennai, Tamil Nadu, India", viewbox)
            if r is not None:
                resolved.append(ResolvedStation(
                    name, row["division"], row["service"],
                    float(r["lat"]), float(r["lon"]),
                    "locality", "nominatim_locality", r.get("display_name", "")[:120],
                    UNCERTAINTY_M["locality"], True,
                    (r.get("category") or r.get("class") or ""), r.get("type", ""), _plausibility(r),
                ))
                continue

        resolved.append(ResolvedStation(
            name, row["division"], row["service"], None, None,
            "inferred", "unresolved", "NEEDS MANUAL SURVEY", None, True, "", "", "none",
        ))
    return resolved


def qa_report(rows: list[ResolvedStation]) -> dict:
    from collections import Counter
    c = Counter(r.geocode_confidence for r in rows)
    unresolved = [r.station_name for r in rows if r.lat is None]
    survey = [r.station_name for r in rows if r.geocode_confidence in SURVEY_REQUIRED]
    return {
        "total": len(rows),
        "with_coordinates": sum(1 for r in rows if r.lat is not None),
        "by_confidence": dict(sorted(c.items())),
        "unresolved": unresolved,
        "survey_required": survey,
        # GATE: the baseline may not be PUBLISHED while any station is provisional.
        # The pipeline may still RUN, so that everything downstream is exercised.
        "passes_publish_gate": len(survey) == 0,
        "runnable": len(unresolved) == 0,
    }


def survey_worklist(rows: list[ResolvedStation], auth_rows: list[dict]) -> list[dict]:
    """Hand-off for the ~2 min/station manual verification pass.

    Each entry carries the provisional point, the published phone number (which
    is how a surveyor confirms the station), and a ready-made map link.
    """
    phones = {r["station_name"]: (r.get("phone", ""), r.get("mobile", "")) for r in auth_rows}
    work = []
    for r in rows:
        if r.geocode_confidence not in SURVEY_REQUIRED:
            continue
        ph, mob = phones.get(r.station_name, ("", ""))
        lat, lon = r.lat, r.lon
        work.append({
            "station_name": r.station_name,
            "division": r.division,
            "provisional_lat": lat,
            "provisional_lon": lon,
            "uncertainty_m": r.uncertainty_m,
            "phone": ph,
            "mobile": mob,
            "osm_link": f"https://www.openstreetmap.org/#map=17/{lat}/{lon}" if lat else "",
            "verified_lat": "",
            "verified_lon": "",
            "verified_by": "",
        })
    return work


# --------------------------------------------------------------------------
# Survey ingestion — merges manually verified positions back into the inventory.
# --------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres. Used only for QA checks, never for routing."""
    import math
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ASSM: a verified point this far from the provisional one is usually correct
# (the geocoder was that wrong) but must be a deliberate confirmation.
LARGE_MOVE_M = 3000.0


def ingest_survey(
    resolved: list[ResolvedStation],
    worklist_rows: list[dict],
    bbox: tuple[float, float, float, float],
) -> tuple[list[ResolvedStation], dict]:
    """Merge verified coordinates into the inventory.

    Rejects rather than accepts on doubt: a malformed coordinate or a point
    outside the city bbox is an error, not a data point.
    """
    s, w, n, e = bbox
    by_name = {r.station_name: r for r in resolved}
    accepted, rejected, flagged, open_rows = [], [], [], []

    for row in worklist_rows:
        name = row["station_name"]
        raw_lat, raw_lon = (row.get("verified_lat") or "").strip(), (row.get("verified_lon") or "").strip()
        if not raw_lat or not raw_lon:
            open_rows.append(name)
            continue
        try:
            lat, lon = float(raw_lat), float(raw_lon)
        except ValueError:
            rejected.append({"station": name, "reason": "unparseable coordinate",
                             "value": f"{raw_lat},{raw_lon}"})
            continue
        if not (s <= lat <= n and w <= lon <= e):
            rejected.append({"station": name, "reason": "outside city bbox",
                             "value": f"{lat},{lon}"})
            continue
        if name not in by_name:
            rejected.append({"station": name, "reason": "unknown station name"})
            continue

        prev = by_name[name]
        moved = (haversine_m(prev.lat, prev.lon, lat, lon)
                 if prev.lat is not None else None)
        if moved is not None and moved > LARGE_MOVE_M:
            flagged.append({"station": name, "moved_m": round(moved),
                            "was": f"{prev.lat:.5f},{prev.lon:.5f}",
                            "now": f"{lat:.5f},{lon:.5f}"})

        by_name[name] = ResolvedStation(
            prev.station_name, prev.division, prev.service, lat, lon,
            "surveyed", "manual_survey",
            f"verified_by={row.get('verified_by','?')}",
            UNCERTAINTY_M["surveyed"], False,
            "amenity", "fire_station", "ok",
        )
        accepted.append({"station": name, "moved_m": None if moved is None else round(moved)})

    merged = [by_name[r.station_name] for r in resolved]
    report = {
        "accepted": len(accepted),
        "rejected": rejected,
        "still_open": open_rows,
        "large_moves_for_review": sorted(flagged, key=lambda f: -f["moved_m"]),
        "gate": qa_report(merged),
    }
    return merged, report
