# ADR-001 — The authoritative list is the source of truth; OSM only supplies coordinates

**Status:** accepted · **Date:** 2026-09-03 · **Closes:** Finding F-01

## Context
The source deck modelled coverage against "five existing stations". The Greater
Chennai Corporation publishes 33 fire stations (9 North / 9 South / 7 Central /
8 Suburban). An Overpass query over the GCC bounding box returns 16
`amenity=fire_station` features — roughly 48% completeness — and **zero**
`emergency=ambulance_station` features.

## Decision
1. The GCC listing determines **which** stations exist. OSM and Nominatim are
   used only to attach coordinates to that list, never to determine membership.
2. Every resolved position carries a `geocode_confidence`
   (`surveyed` > `osm` > `geocoded` > `locality` > `inferred`) and a
   `plausibility` class describing what the geocoder actually matched.
3. A **publish gate** blocks any provisional position from reaching an output.
   The pipeline stays *runnable* so everything downstream is exercised, but
   `passes_publish_gate` is false until a human verifies each point.

## Consequences
- 4 of 33 stations are matched to OSM fire-station features; 29 are provisional.
- The provisional points are demonstrably unreliable: "Secretariat" resolves to a
  bus stop, "Sembium" to a health centre, "Korukkupet"/"Royapuram"/"Tondiarpet"
  to railway stations, "Redhills" to a road ~9 km from the locality.
- `data/interim/station_survey_worklist.csv` is the hand-off for the ~2 min/station
  manual verification pass, ordered so the worst matches are done first.
- No baseline coverage figure may be published until that pass is complete.
