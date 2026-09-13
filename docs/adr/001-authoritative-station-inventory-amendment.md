# ADR-001a — TNFRS supersedes the GCC page as the station inventory

**Status:** accepted · **Date:** 2026-09-12 · **Amends:** [ADR-001](001-authoritative-station-inventory.md)

## Context
ADR-001 made the Greater Chennai Corporation's fire-station page the source of
truth over OSM, and for the question it was answering — *is OSM complete enough
to enumerate the network?* — that was right. OSM held 16 features against 33
authoritative stations.

Extending the study area past the corporation forced a different question, and
it exposed the first answer as incomplete. The **TNFRS Northern Region station
directory** (registry id 12, already used by E-11f to confirm station
identities) lists **43** stations where the GCC page lists 33. Ten are absent
from the GCC page, and **five of those stand inside the corporation's own
boundary**:

| station | position | evidence | inside GCC |
|---|---|---|---|
| Velachery | 12.976853, 80.227634 | OSM `amenity=fire_station` | yes |
| Thuraipakkam | 12.948648, 80.240938 | Google Maps POI | yes |
| Kolathur | 13.117149, 80.219221 | Google Maps POI | yes |
| Maduravoyal | 13.060276, 80.162701 | Google Maps POI | yes |
| Virugambakkam | 13.035004, 80.173024 | Google Maps POI | yes |
| Medavakkam | 12.915180, 80.192526 | Google Maps POI | 1.0 km outside, covers in |

This is not a tie between two sources of equal standing. **TNFRS operates the
stations**; the corporation publishes a page about them. An operator's own
directory is the better authority on which stations exist, and the GCC page is
demonstrably missing six that do.

## Decision
The station inventory is **the union** of the GCC list and the TNFRS regional
directories, with TNFRS treated as the authority on EXISTENCE and the existing
E-11 work retained as the authority on POSITION.

`data/reference/tnfrs_gcc_supplementary.csv` carries the six, each with the
evidence that placed it. `scripts/resolve_stations.py` merges them, so the
inventory stays script-produced and re-runnable (Finding F-02).

## Consequences
- **Published GCC coverage was understated.** Every figure this project has
  published for the corporation was routed from 33 stations while TNFRS operates
  at least 38 in the same area. Coverage rises; the direction was predictable
  but the size was not, and is recorded with this amendment's rebuild.
- The survey debt grows. Five of the six are map listings, not surveys, so they
  join the 29 already covered by the ADR-006 waiver rather than reducing it.
  `stations_qa.passes_publish_gate` stays `false`.
- **The GCC page is retained as a cross-check, not discarded.** Where the two
  sources disagree on a station's existence, the disagreement is the finding —
  it is what surfaced this amendment.
- Four stations in the Northern directory remain unplaced: Tambaram STC,
  Athipattu-II, and two whose names did not resolve to an unambiguous listing.
  They are absent from the inventory rather than guessed at.
