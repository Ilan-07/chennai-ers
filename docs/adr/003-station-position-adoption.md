# ADR-003 — Google Maps POIs are the station positions, and the survey gate stays shut

**Status:** accepted · **Date:** 2026-09-09 · **Affects:** A-15, E-11c/d/e/f/g, build steps 02–03

## Context

The adoption of the E-11c Google Maps positions was decided in early September
2026 and applied to `data/interim/stations_resolved.csv` **by hand**. It was
recorded in ASSUMPTIONS.md and in commit `2b18e96`, but never as code:

- `ers.io.stations.resolve()` was registered as the file's provenance
  (`derived://ers.io.stations.resolve`) and called only from the test suite.
- The file drifted from its own registry checksum — 6866 bytes registered
  against 6423 on disk — and nothing checked, so nothing noticed.
- **E-11e's Tambaram resolution never reached the data.** OSM's "Tamil Nadu Fire
  and Rescue Services" feature lies 41 m from candidate B and 260 m from
  candidate A, so B was made primary in the lookup — and the hand-edited
  inventory kept candidate A. The model has been routing from the rejected
  coordinate ever since.
- The `plausibility` column described the **discarded Nominatim hits**:
  Thiruvanmiyur, whose POI is named "Thiruvanmiyur Fire Station" and is the one
  station confirmed by an exact phone match, was labelled `settlement_centroid`.

None of this changed a coverage figure by much. All of it meant the project's own
rule — no number without a replayable run — did not hold for its most
load-bearing input.

## Decision

1. **The adoption is code.** `ers.io.stations.adopt_gmaps_lookup()` applies the
   lookup to the resolved rows, and `scripts/resolve_stations.py` rebuilds the
   inventory from registered inputs only. Deterministic and network-free:
   Nominatim is not called, because E-11c falsified its positions (16 of 29
   outside their own stated uncertainty, worst error 25.5 km) and nothing
   downstream uses them.

2. **`gmaps_lat/lon` is the primary candidate** and carries every tie-break that
   has been settled. Tambaram is therefore corrected to candidate B.

3. **`plausibility` is re-derived for the adopted positions**, on the question
   that actually remains open. Every POI is already categorised `Fire station`,
   so feature type carries no information; identity does:
   `identity_confirmed` (14), `named_fire_station` (12), `ambiguous_candidates`
   (3), `contested` (1, Athipattu), `ok` (4 OSM-corroborated).

4. **`identity_confirmed_by` moves into the inventory.** It previously lived only
   in the lookup CSV, which is how the two could disagree. E-11g's error models
   need it: the noise floor is ±0.8 pts if the unconfirmed POIs name the right
   station and ±7.6 pts if they do not.

5. **The publish gate stays shut.** `google_maps_poi` remains in
   `SURVEY_REQUIRED`. A better geocode is not a verification.

## Consequences

- One coordinate moves (Tambaram, 260 m). E-11b measured Tambaram's leverage at
  **0.000 points** — it lies outside the GCC demand surface — so no coverage
  figure moves materially, but every station-dependent artefact's
  `stations_signature` changes and must be recomputed. That recomputation is
  now enforced by `tests/integration/test_artefact_freshness.py`.
- `identity_confirmed_by` counts **14**, not 15. `contested_unresolved`
  (Athipattu) was being counted as a confirmation, which is a marker of doubt
  read as evidence.
- The registry gains a second `stations_resolved` version. The first is
  **superseded, not broken** — the registry is append-only so that an old run
  stays replayable against the data it actually used, and
  `scripts/register.py --verify` distinguishes the two.

## What this does not do

It does not verify a single position. Fifteen of the 29 rest on an unchecked
assumption that a Google listing names the station we think it names. The
worklist carries a published TNFRS landline and email for every one of them;
sending those is what closes A-15, and no amount of further modelling
substitutes for it.
