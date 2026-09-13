"""Place the metro's stations. Build step 03b.

The GCC list gave 33 stations with positions resolved over E-11a to E-11g. The
TNFRS regional directories give 101 stations with **no positions at all** -- a
name, a phone number and an email. Extending the study area past the corporation
therefore means placing stations on exactly the evidence E-11c found wanting,
and this script is explicit about that rather than quietly widening the map.

Three position sources, in descending order of evidence:

  1. **already resolved** -- the station is in `stations_resolved.csv`, which
     carries the E-11 work. Matched by name, fuzzily, because the two sources
     disagree on spelling ("Sectariate" / "Secretariat", "Poonamalli" /
     "Poonamallee", "Washermempet" / "Washermanpet").
  2. **OSM fire feature** -- an `amenity=fire_station` within 600 m of the
     geocoded point. 60 m uncertainty, the residual E-11e measured.
  3. **map listing** -- a Google Maps place result for "<name> fire station",
     gathered by hand into `data/reference/tnfrs_metro_gmaps_lookup.csv` with the
     place id recorded so the lookup can be repeated. This is the same evidence
     class E-11c adopted for the GCC 29: better than a locality centroid by a
     factor of 40, and still not a survey, so it carries 50 m and stays
     `survey_required`. Listed here because the file existed for a day before
     anything read it -- evidence nobody consumes is the same as no evidence.
  4. **town centroid** -- the geocoder knows the TOWN, not the station. Queried
     for "Siruseri fire station" Nominatim returns nothing at all; queried for
     "Siruseri" it returns the settlement's centre. That is the locality-centroid
     failure E-11c measured and rejected, so a station placed this way carries
     2,000 m of uncertainty and is marked `survey_required`. It is placed rather
     than dropped because a station that exists and is mislocated is a different
     error from a station the map pretends does not exist -- and the second one
     would make the suburbs look emptier than they are.

    python scripts/resolve_metro_stations.py [--force]

Nothing here is a survey. Every station placed by 2 or 3 raises the survey debt,
and `stations_metro_qa.json` reports the new total.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402

from ers.io.registry import DatasetRegistry  # noqa: E402

UA = "chennai-ers/0.1 (academic emergency-response siting research; contact via repo)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSM_WIDE = "data/raw/osm_fire_metro_overpass.json"
OVERPASS = "https://overpass-api.de/api/interpreter"

OUT = Path("data/interim/stations_metro.csv")
QA = Path("data/interim/stations_metro_qa.json")

# Uncertainty by source, in metres. These are not guesses: 60 m is the OSM
# residual from E-11e and 900 m is the geocoder displacement from E-11c.
UNCERTAINTY = {"resolved": None, "osm_feature": 150.0,
               "google_maps_poi": 50.0, "town_centroid": 2000.0}
GMAPS_LOOKUP = Path("data/reference/tnfrs_metro_gmaps_lookup.csv")
OSM_SNAP_M = 1500.0        # E-11e's proximity rule, widened for a town-centre seed
KEEP_BUFFER_M = 3000.0     # a station just outside the boundary still covers into it


def squash(s: str) -> str:
    s = s.lower().replace("&nbsp;", " ")
    s = re.sub(r"\b(fs|fire|rescue|station|services?)\b", " ", s)
    s = re.sub(r"[^a-z]", "", s)
    for a, b in (("ph", "f"), ("th", "t"), ("dh", "d"), ("aa", "a"), ("ee", "i"),
                 ("oo", "u"), ("y", "i"), ("v", "w"), ("ck", "k"), ("sh", "s")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)          # collapse doubled letters


def best_match(name: str, pool: dict[str, str], cutoff: float = 0.86):
    key = squash(name)
    if key in pool:
        return pool[key], 1.0
    hit = difflib.get_close_matches(key, list(pool), n=1, cutoff=cutoff)
    if hit:
        return pool[hit[0]], difflib.SequenceMatcher(None, key, hit[0]).ratio()
    return None, 0.0


def place_of(name: str) -> str:
    """The settlement a station is named after.

    TNFRS names stations for their locality, sometimes with an industrial-estate
    qualifier ("Siruseri Sipcot", "Gummidipoondi Sipcot"). The qualifier helps a
    human and defeats a geocoder, so it is stripped for the lookup and kept in
    the record.
    """
    n = re.sub(r"&nbsp;", " ", name)
    n = re.sub(r"\bFS\b", " ", n)
    n = re.sub(r"\b(sipcot|stc|world city|temple)\b", " ", n, flags=re.I)
    n = re.sub(r"[-–]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def geocode(name: str, session: requests.Session, bbox) -> dict | None:
    """Nominatim, viewbox-bounded. One request a second, as the policy requires.

    The query is the PLACE, not the station: OSM holds no fire-station feature
    for these towns, so asking for one returns nothing and asking for the town
    returns its centre. What comes back is therefore a locality centroid and is
    recorded as one.
    """
    params = {"q": f"{place_of(name)}, Tamil Nadu, India", "format": "jsonv2",
              "limit": 5, "addressdetails": 0}
    r = session.get(NOMINATIM, params=params, headers={"User-Agent": UA}, timeout=60)
    time.sleep(1.1)
    if r.status_code != 200:
        return None
    hits = r.json()
    # A settlement, not a road or a railway platform that happens to share the
    # name. "Arcot" as a town is 100 km away; "Arcot Road" is in Chennai, and
    # accepting the road would invent a fire station in the wrong city.
    places = [h for h in hits
              if h.get("category") == "place"
              and h.get("type") in {"city", "town", "village", "suburb",
                                    "neighbourhood", "municipality", "hamlet"}]
    if not places:
        return None
    h = places[0]
    return {"lat": float(h["lat"]), "lon": float(h["lon"]),
            "display": h.get("display_name", "")[:120],
            "category": f'{h.get("category","")}/{h.get("type","")}'}


def fetch_osm_fire(bbox) -> list[dict]:
    s, w, n, e = bbox
    q = f"""[out:json][timeout:180];
(
  node["amenity"="fire_station"]({s},{w},{n},{e});
  way["amenity"="fire_station"]({s},{w},{n},{e});
  relation["amenity"="fire_station"]({s},{w},{n},{e});
  node["emergency"="fire_station"]({s},{w},{n},{e});
  way["emergency"="fire_station"]({s},{w},{n},{e});
);
out tags center;"""
    r = requests.post(OVERPASS, data={"data": q}, headers={"User-Agent": UA}, timeout=300)
    r.raise_for_status()
    return r.json().get("elements", [])


ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true", help="re-geocode even if cached")
args = ap.parse_args()

t0 = time.time()
cfg = yaml.safe_load(open("config/city/chennai.yml"))
METRIC = cfg["crs"]["metric"]
BBOX = (12.40, 79.80, 13.60, 80.60)

area = gpd.read_parquet("data/interim/metro_area.parquet").to_crs(METRIC)
poly = area.geometry.iloc[0]
keep_zone = poly.buffer(KEEP_BUFFER_M)

resolved = pd.read_csv("data/interim/stations_resolved.csv")
pool = {squash(n): n for n in resolved["station_name"]}
by_name = resolved.set_index("station_name")
wards_m = gpd.read_parquet("data/interim/wards.parquet").to_crs(METRIC)
gcc_poly = wards_m.union_all() if hasattr(wards_m, "union_all") else wards_m.unary_union
resolved_m = gpd.GeoDataFrame(
    resolved, geometry=gpd.points_from_xy(resolved.lon, resolved.lat),
    crs="EPSG:4326").to_crs(METRIC)
SAME_STATION_M = 400.0        # a centroid this close to a resolved station IS it

# ------------------------------------------------------------------ OSM layer
if Path(OSM_WIDE).exists() and not args.force:
    osm = json.loads(Path(OSM_WIDE).read_text())
else:
    print("querying Overpass for fire stations over the metro ...", flush=True)
    osm = fetch_osm_fire(BBOX)
    Path(OSM_WIDE).write_text(json.dumps({"elements": osm}, indent=1, sort_keys=True))
osm = osm["elements"] if isinstance(osm, dict) else osm
osm_pts = []
for el in osm:
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is not None:
        osm_pts.append({"lat": lat, "lon": lon, "name": el.get("tags", {}).get("name", "")})
osm_gdf = gpd.GeoDataFrame(
    osm_pts, geometry=gpd.points_from_xy([p["lon"] for p in osm_pts],
                                         [p["lat"] for p in osm_pts]),
    crs="EPSG:4326").to_crs(METRIC) if osm_pts else None
print(f"{len(osm_pts)} OSM fire features available for cross-check", flush=True)

# ------------------------------------------------------------- map listings
#
# Hand-gathered place results, keyed by squashed station name. Rows without a
# position are the ones Google had no place for either: they are kept in the
# file as a record that the lookup was DONE and came back empty, which is not
# the same as never having been tried.
gmaps: dict[str, dict] = {}
gmaps_empty: list[str] = []
if GMAPS_LOOKUP.exists():
    for r in pd.read_csv(GMAPS_LOOKUP).to_dict("records"):
        key = squash(str(r["station_name"]))
        if pd.isna(r.get("lat")) or pd.isna(r.get("lon")):
            gmaps_empty.append(str(r["station_name"]))
            continue
        gmaps[key] = r                      # a positioned row wins over an empty one
    print(f"{len(gmaps)} map listings available, {len(gmaps_empty)} looked up "
          f"and empty", flush=True)
else:
    print(f"no map-listing file at {GMAPS_LOOKUP}", flush=True)

# ------------------------------------------------------------- the directories
directory = []
for region in ("northern", "north_western"):
    p = Path(f"data/raw/tnfrs_region_{region}.json")
    if not p.exists():
        raise SystemExit(f"{p} absent. Run: python scripts/fetch_tnfrs_regions.py")
    for row in json.loads(p.read_text()):
        directory.append({**row, "region": region,
                          "station_name": row["station"].replace("&nbsp;", " ").strip()})

session = requests.Session()
rows, unplaced, alias, ambiguous = [], [], [], []
used_osm: set[int] = set()
for i, d in enumerate(directory, 1):
    name = d["station_name"]
    match, score = best_match(name, pool)

    if match is not None:
        r = by_name.loc[match]
        rows.append({"station_name": match, "division": r["division"], "service": "fire",
                     "lat": float(r["lat"]), "lon": float(r["lon"]),
                     "position_source": "resolved",
                     "uncertainty_m": float(r["uncertainty_m"]),
                     "geocode_confidence": r["geocode_confidence"],
                     "identity_confirmed_by": r.get("identity_confirmed_by"),
                     "directory_name": name, "region": d["region"],
                     "landline": d.get("landline"), "cug": d.get("cug"),
                     "email": d.get("email"), "name_match_score": round(score, 3)})
        continue

    g = geocode(name, session, BBOX)
    if g is None:
        unplaced.append(name)
        print(f"  [{i:3d}/{len(directory)}] {name:32s} NOT FOUND", flush=True)
        continue

    lat, lon = g["lat"], g["lon"]
    pt = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs="EPSG:4326").to_crs(METRIC).iloc[0]

    # Place names repeat across Tamil Nadu -- there is an Oragadam in Ambattur
    # and an Oragadam industrial estate near Sriperumbudur, 40 km apart. The
    # directory says which is meant: a NORTH WESTERN region station is not in
    # Chennai city, so a centroid inside the GCC boundary is the wrong namesake.
    if d["region"] == "north_western" and pt.within(gcc_poly):
        ambiguous.append({"station": name, "rejected_at": [round(lat, 5), round(lon, 5)],
                          "reason": "north-western station geocoded inside the GCC boundary; "
                                    "the name is shared with a Chennai locality"})
        print(f"  [{i:3d}/{len(directory)}] {name:32s} AMBIGUOUS NAME - rejected", flush=True)
        continue

    # The name matcher misses spelling drift the geometry catches: a centroid
    # landing on top of an already-resolved station is that station under
    # another spelling, not a new one.
    dres = resolved_m.geometry.distance(pt)
    if len(dres) and float(dres.min()) <= SAME_STATION_M:
        k = int(dres.to_numpy().argmin())
        alias.append((name, str(resolved_m.iloc[k]["station_name"]), round(float(dres.min()))))
        continue

    source, unc = "town_centroid", UNCERTAINTY["town_centroid"]
    detail = f"centroid of {place_of(name)}: {g['display']}"

    # A map listing beats the town centre by a factor of 40 on E-11c's own
    # measurement, so it is taken before the centroid and before the OSM sweep
    # below can only improve on it.
    if (hit := gmaps.get(squash(name))) is not None:
        lat, lon = float(hit["lat"]), float(hit["lon"])
        pt = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]),
                           crs="EPSG:4326").to_crs(METRIC).iloc[0]
        source, unc = "google_maps_poi", UNCERTAINTY["google_maps_poi"]
        detail = (f"map listing '{hit.get('place_name')}' "
                  f"({hit.get('result_kind')}), place id {hit.get('google_place_id')}")

    # An OSM fire feature near the geocode is better evidence than the geocode:
    # E-11e measured a 60 m residual on those, against 900 m on this geocoder.
    if osm_gdf is not None and len(osm_gdf):
        dist = osm_gdf.geometry.distance(pt)
        j = int(dist.to_numpy().argmin())
        # An OSM feature already sitting on a resolved station belongs to that
        # station; claiming it again would duplicate one station into two.
        claimed = float(resolved_m.geometry.distance(osm_gdf.geometry.iloc[j]).min()) <= SAME_STATION_M
        if float(dist.iloc[j]) <= OSM_SNAP_M and not claimed and j not in used_osm:
            used_osm.add(j)
            lat, lon = float(osm_pts[j]["lat"]), float(osm_pts[j]["lon"])
            source, unc = "osm_feature", UNCERTAINTY["osm_feature"]
            detail = (f"OSM {osm_pts[j]['name'] or '(unnamed)'} "
                      f"at {float(dist.iloc[j]):.0f} m from the geocode")

    rows.append({"station_name": name.replace(" FS", "").strip(), "division": d["region"],
                 "service": "fire", "lat": lat, "lon": lon,
                 "position_source": source, "uncertainty_m": unc,
                 "geocode_confidence": source, "identity_confirmed_by": None,
                 "directory_name": name, "region": d["region"],
                 "landline": d.get("landline"), "cug": d.get("cug"),
                 "email": d.get("email"), "name_match_score": None,
                 "match_detail": detail})
    print(f"  [{i:3d}/{len(directory)}] {name:32s} {source:12s} {lat:.5f},{lon:.5f}", flush=True)

# The inventory is the UNION of the two sources, not their intersection. Building
# it from the directory alone would silently DROP any GCC station whose name no
# directory row matched -- losing a station the project had already surveyed.
have = {r["station_name"] for r in rows}
for _, r in resolved.iterrows():
    if r["station_name"] in have:
        continue
    rows.append({"station_name": r["station_name"], "division": r["division"],
                 "service": "fire", "lat": float(r["lat"]), "lon": float(r["lon"]),
                 "position_source": "resolved", "uncertainty_m": float(r["uncertainty_m"]),
                 "geocode_confidence": r["geocode_confidence"],
                 "identity_confirmed_by": r.get("identity_confirmed_by"),
                 "directory_name": None, "region": "gcc_list",
                 "landline": None, "cug": None, "email": None,
                 "name_match_score": None,
                 "match_detail": "in the GCC inventory; no TNFRS directory row matched its name"})

df = pd.DataFrame(rows).drop_duplicates(subset=["station_name"], keep="first")
g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat),
                     crs="EPSG:4326").to_crs(METRIC)
# EVERY positioned station is written, not just the ones near the metro.
#
# This used to drop the rest before writing, which made the file a metro artefact
# wearing a general name -- and the FULL profile, 1,456 km2 and half a district
# wider, could only ever be built from stations the metro already had. Its outer
# ring would have been scored as unserved because the stations serving it were
# filtered out two steps upstream, overstating exactly the gaps this project
# exists to find. Filtering per study area is `project_stations_to_profile.py`'s
# job, and it needs a table to filter.
inside = g.within(keep_zone).to_numpy()
kept = df.copy().reset_index(drop=True)
kept["in_metro_keep_zone"] = inside
kept["in_study_area"] = g.within(poly).to_numpy()

kept.to_csv(OUT, index=False)

metro_rows = kept[kept["in_metro_keep_zone"]]
counts = {k: int(v) for k, v in metro_rows["position_source"].value_counts().items()}
qa = {
    "directory_entries": len(directory),
    "unique_stations": int(len(df)),
    "stations_written": int(len(kept)),
    "inside_metro_plus_buffer": int(metro_rows.shape[0]),
    "inside_study_area": int(kept["in_study_area"].sum()),
    "by_position_source": counts,
    "surveyed": 0,
    "survey_debt": int(metro_rows.shape[0]),
    "not_found_by_geocoder": unplaced,
    "rejected_ambiguous_name": ambiguous,
    "matched_to_a_resolved_station_by_position": [
        {"directory_name": a, "resolved_as": b, "metres": m} for a, b, m in alias],
    "keep_buffer_m": KEEP_BUFFER_M,
    "osm_snap_m": OSM_SNAP_M,
    "uncertainty_m_by_source": UNCERTAINTY,
    "passes_publish_gate": False,
    "note": ("Extending the study area past the GCC means placing stations on "
             "geocoder output for the first time since E-11c discredited it. "
             "Positions sourced 'geocoder' carry the 900 m displacement that "
             "experiment measured."),
    "seconds": round(time.time() - t0, 1),
}
QA.write_text(json.dumps(qa, indent=2, sort_keys=True))

print(f"\n{len(kept)} positioned stations written; {metro_rows.shape[0]} within "
      f"the metro study area + {KEEP_BUFFER_M/1000:.0f} km buffer")
for k, v in sorted(counts.items()):
    print(f"  {k:14s} {v:3d}  (uncertainty {UNCERTAINTY.get(k)} m)")
if unplaced:
    print(f"  geocoder found nothing for {len(unplaced)}: {', '.join(unplaced[:6])}")

DatasetRegistry().register(source="stations_metro", uri="derived://resolve_metro_stations",
                           local_path=OUT, licence="derived",
                           notes={"stations": int(len(kept)),
                                  "by_position_source": counts,
                                  "survey_debt": int(metro_rows.shape[0])})
print(f"\nwrote {OUT} ({time.time() - t0:.1f}s)")
