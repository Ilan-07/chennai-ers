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
from collections import Counter
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

# `identity_confirmed_by` values that are NOT a confirmation. `contested_unresolved`
# is Athipattu: the TNFRS directory lists two stations there, neither Google
# listing publishes a phone, and OSM names the nearer candidate as the power
# station's own fire post. Counting that as confirmed put the total at 15 where
# A-15 records 14, by treating a marker of doubt as evidence.
IDENTITY_UNCONFIRMED = {"", "contested_unresolved"}
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
    # E-11f/E-11g: WHICH station a position names, as distinct from how precise
    # it is. The noise floor is +/-0.8 pts if the unconfirmed POIs name the right
    # station and +/-7.6 pts if they do not, so the error model cannot be built
    # without this. It previously lived only in a side lookup file, which is why
    # the two could drift apart.
    identity_confirmed_by: str = ""


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


def _plausibility_gmaps(row: dict) -> str:
    """How usable is a Google Maps POI as a station position?

    NOT the same question `_plausibility` asks. That one grades a geocoder hit
    by what KIND of feature it landed on, because the failure mode there was
    landing on a road or a railway station. Every POI here is already
    categorised `Fire station`, so feature type carries no information and the
    residual doubt is about IDENTITY: does this listing name the station we
    think it names?

    Carrying the geocoder's labels over to these positions -- which is what the
    hand-edited inventory did -- describes the discarded Nominatim points, not
    the adopted ones. It read `settlement_centroid` for Thiruvanmiyur, whose POI
    is literally named "Thiruvanmiyur Fire Station" and is the one station
    confirmed by an exact phone match.
    """
    name = (row.get("gmaps_name") or "").strip()
    note = (row.get("note") or "")
    confirmed = (row.get("identity_confirmed_by") or "").strip()

    if confirmed == "contested_unresolved" or note.startswith("UNRESOLVED"):
        return "contested"
    if (row.get("ambiguous") or "").strip().lower() == "true":
        # Two candidate listings and no evidence separating them.
        return "ambiguous_candidates"
    if confirmed:
        return "identity_confirmed"
    if not name or name.casefold() in {"fire station", "fire and rescue station"}:
        return "generic_name"
    return "named_fire_station"


def adopt_gmaps_lookup(
    resolved: list[ResolvedStation],
    lookup_rows: list[dict],
) -> tuple[list[ResolvedStation], dict]:
    """Adopt the E-11c Google Maps positions over the provisional geocodes.

    This step existed as a decision (E-11c, E-11e, commit 2b18e96) but never as
    code: `stations_resolved.csv` was edited by hand, so it matched no script,
    drifted from its own registry checksum, and -- as this function's own
    acceptance check found -- never picked up E-11e's Tambaram resolution.

    `gmaps_lat/lon` is the PRIMARY candidate and already carries every tie-break
    that has been settled; `alt_lat/lon` is the rejected one, kept for audit.
    Adoption does NOT open the publish gate: `google_maps_poi` is in
    SURVEY_REQUIRED, because a better geocode is not a verification.
    """
    by_name = {r.station_name: r for r in resolved}
    adopted, unknown, moved = [], [], []

    for row in lookup_rows:
        name = row["station_name"]
        if name not in by_name:
            unknown.append(name)
            continue
        prev = by_name[name]
        lat, lon = float(row["gmaps_lat"]), float(row["gmaps_lon"])

        # `residual_m` is the per-station uncertainty the lookup assigns: 50 m
        # for a normal POI, wider where the listing itself is doubtful (Avadi,
        # 300 m, whose POI is named only "Fire station").
        unc = float(row.get("residual_m") or UNCERTAINTY_M["google_maps_poi"])

        p_lat, p_lon = prev.lat, prev.lon
        if p_lat is not None and p_lon is not None:
            d = haversine_m(p_lat, p_lon, lat, lon)
            if d > 1.0:
                moved.append({"station": name, "moved_m": round(d),
                              "was": f"{p_lat:.7f},{p_lon:.7f}",
                              "now": f"{lat:.7f},{lon:.7f}"})

        detail = f"{(row.get('gmaps_name') or '').strip()} [{(row.get('gmaps_category') or '').strip()}]"
        if (row.get("note") or "").strip():
            detail = f"{detail} {row['note'].strip()}"

        by_name[name] = ResolvedStation(
            prev.station_name, prev.division, prev.service, lat, lon,
            "google_maps_poi", "google_maps_poi_lookup", detail[:400],
            # int where integral, so the CSV round-trips to the same text and a
            # diff against it shows real changes rather than "50" vs "50.0".
            int(unc) if float(unc).is_integer() else unc,
            True,
            # A Maps POI is not an OSM feature. The previous inventory carried
            # the discarded Nominatim hit's tags here (`place/suburb`,
            # `railway/station`), which described a position no longer in use.
            # Empty is the truth: these columns describe an OSM match, and there
            # is none.
            "", "",
            _plausibility_gmaps(row),
            (row.get("identity_confirmed_by") or "").strip(),
        )
        adopted.append(name)

    merged = [by_name[r.station_name] for r in resolved]
    report = {
        "adopted": len(adopted),
        "unknown_station_names": sorted(unknown),
        "kept_osm_positions": sorted(r.station_name for r in merged
                                     if r.geocode_confidence == "osm"),
        "moved_from_previous": sorted(moved, key=lambda m: -m["moved_m"]),
        "identity_confirmed": sorted(r.station_name for r in merged
                                     if r.identity_confirmed_by not in IDENTITY_UNCONFIRMED),
        "by_plausibility": dict(Counter(r.plausibility for r in merged)),
    }
    return merged, report


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
        p_lat, p_lon = prev.lat, prev.lon
        moved = (haversine_m(p_lat, p_lon, lat, lon)
                 if p_lat is not None and p_lon is not None else None)
        if moved is not None and moved > LARGE_MOVE_M:
            flagged.append({"station": name, "moved_m": round(moved),
                            "was": f"{p_lat:.5f},{p_lon:.5f}",
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
