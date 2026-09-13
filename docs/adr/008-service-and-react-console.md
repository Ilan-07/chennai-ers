# ADR-008 — The console is a React client of a FastAPI service

**Status:** accepted · **Date:** 2026-09-12 · **Affects:** build steps 17–19, ADR-005

## Context
The DA-1 deck specified the architecture as a hosted FastAPI service with a
React + Leaflet console talking to it over REST. The project shipped something
else: one 1,050-line static HTML file built by `scripts/ui/build_console.sh`
from an exported JSON bundle. `docs/deck-figures.md` carried that gap as **NOT
BUILT** — the only claim on the architecture slide that no run could reproduce.

The static console was not a bad artefact. It opens from a file, needs no
runtime, and every number in it comes from `export_ui_data.py`. What it cannot
do is answer a question nobody precomputed. Its "Optimise" button ran a greedy
MCLP *in JavaScript*, so the console could show a site list that the project's
own optimiser had never seen and could not bound — a second implementation of
the one thing this project spent ADR-005 being careful about.

## Decision
Build the specified architecture, and use it to delete the second implementation.

**`src/ers/api/` — FastAPI, build step 19.** Two rules:

- *It serves artefacts; it does not recompute them.* Coverage, response times
  and scenario states all come from `ui_data.json`, which the same pipeline code
  writes as the reports. `tests/unit/test_api.py` asserts the API and
  `baseline_report.json` agree to 5e-4 for both services, so a drift between
  them fails the build rather than reaching a viewer.
- *Siting is solved live, by the real optimiser.* `POST /api/optimise` builds a
  `SitingProblem` over the scenario's own coverage matrix and runs greedy **and**
  the exact MIP, returning the proven gap. The console now reports optimality
  because the solver proved it, not because a slide said (1 − 1/e).

**`ui/` — React 18 + Leaflet 1.9 on Vite.** Served at `/` by the API in
production, proxied to uvicorn in development, so the front end always talks to
the real service. Leaflet is driven imperatively inside `react-leaflet`: 3,838
hexagons restyle on every threshold tick, and putting them through the
reconciler makes the slider stutter — React owns the chrome, Leaflet owns the
canvas.

## Consequences
- Every deck control is now real and server-backed: threshold slider, flood
  scenario toggle, k-slider siting, manual placement, CSV export, and the
  per-cell "which stations reach this and how fast" inspector.
- **Manual placement is no longer a separate code path.** A hand-placed site is
  folded into the precovered mask and the optimiser sites `k` more around it, so
  the reported gain is the gain over the planner's own decision.
- The uncertainty travels with every figure. `/api/meta`, `/api/coverage` and
  the CSV export all carry the publication basis and both E-11g intervals, and
  the console renders them next to the headline share. A client cannot fetch a
  coverage number from this service without also being handed what it rests on.
- **The static console stays** as `make console`, unchanged. It needs no node
  and no server, which is the right artefact to hand someone who wants to look
  at the result on a laptop with no toolchain. It is now the offline view, not
  the product.
- `all` does not build the UI. The analysis pipeline must stay runnable on a
  machine with no node and no web stack, and a coverage figure must never wait
  on a front end to compile. `make ui` and `make api` are separate targets, and
  `fastapi`/`uvicorn` are an optional dependency group.
- The deck's "Cloud: hosted FastAPI service with a cached spatial data store" is
  **still not built**, and is recorded that way. What exists runs on localhost;
  nothing here deploys it.
