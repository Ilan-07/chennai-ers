# Station position survey — procedure

**Why this exists.** 29 of the 33 GCC fire stations have no reliable coordinate.
The geocoder matched them to bus stops, railway stations, clinics and roads —
several are 9–20 km from the true location. Until they are verified, the publish
gate (`passes_publish_gate: false`) blocks every coverage figure the project
produces. This is roughly **one hour of work** and it unblocks the entire pipeline.

**Time budget:** ~2 minutes per station. Do them in worklist order — it is sorted
so the worst geocoder matches come first.

---

## What you need

- `data/interim/station_survey_worklist.csv` — 29 rows, one per station
- Satellite imagery: [Google Maps](https://maps.google.com) (best imagery for Chennai)
  and [OpenStreetMap](https://openstreetmap.org) (the `osm_link` column opens the
  provisional point directly)
- The `phone` / `mobile` columns — these are the published TNFRS numbers and are
  the strongest confirmation available

---

## Per-station procedure

**1. Search.** In Google Maps, search `<station_name> fire station chennai`.
Most TNFRS stations are present as business listings even where OSM has no feature.

**2. Confirm identity.** Match on *at least one* of:
- the listed phone number matches `phone` or `mobile` in the worklist
- the listing name contains "Fire Station" / "Fire and Rescue"
- the Tamil Nadu Fire & Rescue Services branding is visible in street imagery

Do **not** accept a match on locality name alone. That is exactly the error the
geocoder made.

**3. Verify from above.** Switch to satellite. A fire station has a distinctive
signature:
- **wide roller-shutter appliance bays** facing directly onto a road, usually
  2–4 of them side by side
- a paved **forecourt / apron** between the bays and the carriageway, with no kerb
- often a **hose-drying tower** or **drill tower** — a narrow vertical structure
- red vehicles parked on the apron
- typically a walled compound with a single vehicle entrance

If you cannot see appliance bays, you are probably looking at an administrative
office, not a responding station. Keep looking.

**4. Record the right point.** This is the part that matters for the model.

> Record the coordinate **where the appliance bay exits onto the public
> carriageway** — not the building centroid, not the compound gate on a side lane.

The travel-time model starts the vehicle at the nearest road-network node. If you
record the building centroid, the station may snap to a service road or an
internal driveway and inherit a slow, wrong first link. The apron/carriageway
junction is where the journey actually begins.

Right-click the point in Google Maps → the lat/lon appears at the top of the
context menu → click to copy.

**5. Write it down.** Fill three columns in the worklist row:

| Column | What to put |
|---|---|
| `verified_lat` | e.g. `13.10441` — 5 decimal places is ~1 m, plenty |
| `verified_lon` | e.g. `80.29112` |
| `verified_by` | your initials |

Leave the row blank if you genuinely cannot find it. A blank is honest; a guess
is not, and the ingestion step will tell you exactly which rows are still open.

---

## When you're done

```bash
PYTHONPATH=src .venv/bin/python -m ers.cli ingest-survey
```

This merges your coordinates in at confidence `surveyed`, and refuses anything
implausible:

- a verified point **> 3 km** from the provisional point is flagged for a second
  look (it is usually correct — the geocoder was that far off — but it should be
  a deliberate confirmation, not a typo slipping through)
- a point outside the GCC bounding box is **rejected**
- malformed or partial coordinates are **rejected**

It then reprints the gate. When `passes_publish_gate: true`, the baseline is
publishable and Phase 09 can produce real numbers.

---

## Two things worth doing while you're in there

**Contribute the fixes upstream.** OSM is missing ~29 of Chennai's 33 fire
stations. Adding them (`amenity=fire_station`, `operator=Tamil Nadu Fire and
Rescue Services`, `name=<station> Fire Station`) takes a minute per station in
the OSM iD editor and is a genuine public-good contribution the report can cite.

**Note anything odd.** If a station appears closed, relocated, or is clearly a
regional office rather than a responding station, put it in `verified_by` as a
note. An inventory error found now is worth more than one found in week 10.
