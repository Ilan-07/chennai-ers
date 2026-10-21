# ADR-012 — Peak hour is answered with posts, solved on its own network

**Status:** accepted · **Date:** 2026-10-21 · **Affects:** step 15b (`scripts/stage.py`), `/api/optimise` `mode`, `/api/staging/{svc}`, the console's *Peak-hour posts* mode, A-15

## Context

Peak hour is the binding scenario. It takes ambulance coverage from 71.77% to
39.57%, a worse result than the 100-year flood (step 13), and every robust-siting
strategy names it as the design basis (step 15). Yet every answer the project
offered was a building on a land-feasible parcel, sited on the dry network.

An ambulance is not a building. During the peak window a crew can wait at a
roadside post and leave from there.

## Decision

**Solve the step 11 maximal covering problem on the peak network, with every
road-lattice candidate allowed, and publish it next to the dry-day plan scored at
the same hour.**

- `stage.py` builds the peak coverage matrix over all 948 candidates (not the 352
  land-feasible ones) and solves k = 1..10 exactly, three ways: posts (any
  candidate), stations (land-feasible only) and the dry-day station plan, re-solved
  at every k and scored at peak.
- The service gains `mode: "staging"`. Posts have their own candidate table and
  index space; `_siting_space` is the only place either is read, so a post id
  cannot be resolved against the station table.
- Posts are offered for EMS only, and only on the network they were solved on.

## What the build found

| k | posts | stations (parcels only) | dry-day plan at peak |
|---|---|---|---|
| 3 | 47.48% | 47.48% | 42.29% |
| 10 | 56.44% | 56.36% | 49.59% |

1. **The parcel requirement costs almost nothing.** Posts beat parcel-only
   stations by at most 0.08 points. The buildable sites already sit where peak
   coverage needs them.
2. **The time of day costs a lot.** The dry-day plan of the same size buys about
   a third to a half of what the posts buy at peak, and the two plans share at
   most one site at any k. A plan sized for a dry day is the wrong plan at 6 pm,
   not just a smaller one.

So the value of staging is temporal positioning, not freedom from land. That is
the claim the console makes, and `test_staging.py` fails if either finding flips.

## Rejected

- **Moving an existing crew to the post.** This is the operationally realistic
  version, but it uncovers the station the crew left, and pricing that needs the
  per-station fleet. No registered dataset carries it. Recorded as A-15
  (DATA-GATED); the additive figure is an upper bound on it.
- **A continuous time-of-day profile.** This would generalise from one peak
  scenario to 24 hourly networks. It is worth doing, but it needs hourly speed
  data the calibration (step 07) does not have.
- **Fire engines.** Not staged at a kerb in TNFRS practice. The script accepts a
  service argument, but the Makefile and console offer EMS only.
