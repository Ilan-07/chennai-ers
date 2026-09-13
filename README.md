# Chennai Emergency Response — coverage and station siting

Which parts of Greater Chennai cannot be reached by a fire engine or an
ambulance within the mandated response time, and where would the next stations
go? Travel time on the real directed road network, population-weighted coverage,
an MCLP optimiser with a proven optimality gap, and flood and peak-hour network
states.

> **Results are published under a recorded waiver, not on surveyed positions.**
> 34 of the 39 station positions are third-party map listings. Any coverage
> figure taken from this project must be quoted with its interval: **±1.10 points
> if the 15 unconfirmed listings name the right stations, ±8.55 if they do not.**
> The terms are in [`config/publish_waiver.yml`](config/publish_waiver.yml);
> setting `active: false` reverts every output to PROVISIONAL. See
> [What you can and cannot claim](#what-you-can-and-cannot-claim).

---

## Quick start

```bash
uv venv && uv pip install -r requirements.txt   # or: pip install -r requirements.txt
make test                                       # ~330 tests, ~15 s
make -n all                                     # what is stale, without running it
make all                                        # full pipeline from cached raw data, ~40 min
make gate                                       # every publish gate, non-zero on a build failure

make ui && make api                             # the console on http://127.0.0.1:8000
```

`make all` needs the OSM graph tables, which are gitignored because they are
24 MB and reproducible. Rebuild them with `make graph` (~17 min, needs network)
before the first run.

## The pipeline

The DAG lives in the [`Makefile`](Makefile), which is the authority — this table
is a reading aid.

| step | script | produces | time |
|---|---|---|---|
| 02–03 | `resolve_stations.py` | station inventory from the authoritative list | 1 s |
| 04 | `build_wards.py` | 200 wards, 15 zones | 1 s |
| 05b | `fetch_landuse.py` | A-07 land-use risk layer | 15 s |
| 06 | `build_graph.py` | OSM drive network | 17 min |
| 07 | `attribute.py`, `calibrate*.py`, `validate_routing.py` | travel time per arc, calibrated against an OSRM oracle | 1 min |
| 08a | `fetch_census_wards.py` | Census 2011 ward populations + the 2008 wards they were counted on | 5 s |
| 08 | `build_demand.py` | H3 r9 demand cells, census-reconciled, per-service weighting | 3 s |
| 09 | `baseline.py` | coverage of the existing network | 2 s |
| 10–11 | `build_candidates.py`, `optimise.py` | candidate sites, MCLP siting | 30 s |
| 12–13 | `degradation.py` | flood and peak-hour scenarios | 40 s |
| 12b | `flood_extent_report.py` | which flood scenarios each study area may honestly be asked | 10 s |
| 14 | `equity_curve.py`, `frontier.py` | ward-equity cost of siting | 4 min |
| 15 | `optimise_robust.py` | siting against a scenario distribution | 2 min |
| E-11 | `sensitivity_stations.py`, `prioritise_survey.py` | positional noise floor, survey order | 25 min |
| 17–18 | `export_*.py`, `ui/build_console.sh` | the offline single-file console | 1 min |
| 19 | `ers.api`, `ui/` | FastAPI service + React/Leaflet console (`make ui && make api`) | 10 s |
| 20 | `build_profile.sh` | one study area end to end, in an isolated tree (`sh scripts/build_profile.sh metro`) | 35 min |

Experiments live in `experiments.py` (`make experiments`, ~2 h; eight arms).

## Study areas

Three profiles, three questions, measured rather than drawn
([ADR-011](docs/adr/011-study-area-boundaries.md)):

| profile | boundary | extent | flood scenarios |
|---|---|---|---|
| `gcc` | the corporation's administrative limits | 432 km² | all four |
| `metro` | urban **centre**, ≥ 1,500/km² | 932 km² | none — see below |
| `full` | urban cluster at a 500/km² floor | 1,456 km² | none |

A profile is fully described by its file in `config/city/`; `build_profile.sh`
symlinks `src` and `scripts` from the repo so a profile build always runs current
code. **The flood layers were produced for the corporation** — their modelling
domain covers 93% of it, 47% of the metro and 28% of the full settlement — so the
wider profiles are not offered them. Running them anyway would return unmodelled
ground as *dry*, which reads as flood resilience exactly where the study area was
widened to reach the places that flood worst
([ADR-010](docs/adr/010-flood-layer-extent.md)). A BUILD gate enforces it.

Build step 19 is not part of `make all`: the analysis pipeline stays runnable on
a machine with no node and no web stack, and a coverage figure never waits on a
front end to compile. [ADR-008](docs/adr/008-service-and-react-console.md).

## What you can and cannot claim

**The binding constraint on this project is 34 unsurveyed station positions**,
and it is not a modelling problem. E-11g measured what they are worth:

| if the 15 unconfirmed map listings… | EMS coverage interval |
|---|---|
| name the right station | **±1.10 points** |
| are no better than the geocoder positions they replaced | **±8.55 points** |

Quoting the narrow figure while 15 of its inputs rest on an unchecked assumption
is not supported. Either publish the bracket, or send the 15 emails — the
addresses are already in `data/interim/station_survey_worklist.csv`, and
[`docs/station-survey.md`](docs/station-survey.md) has the procedure. At ±8.55
points exactly one measured effect clears the noise floor — the ±20% class-speed
band, at 21.3 points. Everything else this project has measured, including the
junction term and the emergency multiplier, sits inside it.

**The waiver does not change any of that.** It records a decision to publish on
the positions currently held, with the basis stated in every artefact
(`publication_basis: "waived"` plus the full terms). It does not make the
stations surveyed: `stations_qa.passes_publish_gate` stays `false`, and the
`stations_surveyed` gate stays FAILED, because that gate states a fact about the
data and a decision to publish does not change a fact. Two BUILD gates enforce
the terms — every affected artefact must carry the waiver, and the waiver must
carry both ends of the interval.

**EMS coverage is modelled from fire stations.** Every row of the authoritative
inventory is a fire station; the 108 ambulance standby points are unpublished
and absent from OSM. EMS results apply ambulance turnout offsets, speed
multipliers and response standard to the fire-station network. Every EMS result
carries a `bases` block saying so, and `make gate` fails the build if one does
not.

**A hand-placed station reports what it reaches, separately from the solve.**
Placing a site and pressing *Find the best sites* answers how much the whole plan
gains; it cannot say whether your station was worth putting there, and with
several placed by hand the single gain figure cannot be attributed to any one of
them. *Show what they reach* (`/api/reach/{svc}`) gives each placed station two
numbers — everyone it reaches, and everyone it reaches who is **not already
covered** — plus the demand two stations double-count where they overlap. The
second number is the one that decides a site: a station on top of existing cover
reaches a great many people and helps none of them. Measured at the service's own
budget, not at the threshold slider, and the response says so.

**The optimiser's site list is not identified.** Under the pessimistic error
model, 85 distinct sites competed for 10 slots and none was selected in 95% of
draws. [ADR-005](docs/adr/005-siting-objective.md) is why the project publishes a
decision frame rather than a recommendation.

## Gates

`make gate` evaluates every gate and separates three kinds:

- **BUILD** — an internal inconsistency; the build fails. Cross-script
  disagreement, a siting result below the do-nothing baseline, an artefact
  computed against superseded inputs, an unstamped EMS result, or a study area
  serving a flood scenario its own layers cannot speak for.
- **PUBLICATION** — a real-world evidence limit. The station survey is
  outstanding, so coverage may not be published as settled. This does *not* fail
  the build; what is enforced is that affected artefacts carry `PROVISIONAL`.
- **REPORTED** — a cross-check that does not govern. The 108/EMRI comparison,
  per [ADR-004](docs/adr/004-trip-overhead-oracle.md).

## Reproducibility

Every ingested file is hashed, licensed and versioned in `data/registry.json`
(`make verify`). The registry is append-only: a refresh is a new version, so a
run recorded months ago stays replayable against the data it actually used.

Every report carries a `run_id` over the code commit, config hash, input digests
and seed, plus a `stations_signature`. Two runs agreeing on a `run_id` must agree
on their numbers, and `tests/integration/test_artefact_freshness.py` fails the
build when an artefact's signature does not match the inventory on disk.

Nothing is edited by hand. If a number cannot be produced by a script, it is not
published.

## Decisions

| | |
|---|---|
| [ADR-001](docs/adr/001-authoritative-station-inventory.md) | The GCC list is the source of truth, not OSM |
| [ADR-001a](docs/adr/001-authoritative-station-inventory-amendment.md) | TNFRS supersedes the GCC page: the operator's directory names six stations the page omits |
| [ADR-002](docs/adr/002-ghsl-instead-of-worldpop.md) | GHS-POP replaces WorldPop |
| [ADR-003](docs/adr/003-station-position-adoption.md) | Map listings are the positions; the survey gate stays shut |
| [ADR-004](docs/adr/004-trip-overhead-oracle.md) | OSRM governs the trip overhead; EMRI is a cross-check |
| [ADR-005](docs/adr/005-siting-objective.md) | Report all three siting objectives; recommend none yet |
| [ADR-006](docs/adr/006-publication-waiver.md) | Publish on unsurveyed positions under a recorded waiver |
| [ADR-007](docs/adr/007-census-ward-reconciliation.md) | Census ward totals are re-cut from the 2008 wards, not looked up |
| [ADR-008](docs/adr/008-service-and-react-console.md) | The console is a React client of a FastAPI service |
| [ADR-009](docs/adr/009-overlapping-landuse-parcels.md) | Overlapping land-use parcels resolve by risk priority, so the fire weight is a mean over a partition |
| [ADR-010](docs/adr/010-flood-layer-extent.md) | A flood layer may only be asked about the area it was drawn for |
| [ADR-011](docs/adr/011-study-area-boundaries.md) | The study area is measured by Degree of Urbanisation, not drawn |

[`ASSUMPTIONS.md`](ASSUMPTIONS.md) classifies every value as FACT, RSCH, ASSM or
RECO, and records the experiment that tests each assumption.

## Layout

```
config/     city, speeds, services, standards, scenarios — all values, no code
src/ers/    the library: io, geo, routing, model, optimise, gates, provenance, api
scripts/    one build step each; the Makefile orders them
ui/         the React + Leaflet console the API serves
tests/      unit, property, integration, golden
docs/adr/   decision records
data/       raw (ingested, hashed) → interim (derived) → reference
```

## Not in scope

Real-time dispatch and vehicle routing, crew rostering and fleet sizing,
hospital capacity, signal pre-emption. Also no machine learning: there is no
learning problem here that the data supports. The one defensible candidate —
imputing link speeds from vehicle GPS traces — is data-gated and listed as
future work rather than fabricated.
