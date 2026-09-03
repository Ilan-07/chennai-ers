# ADR-002 — GHS-POP replaces WorldPop as the population surface

**Status:** accepted · **Date:** 2026-09-03 · **Affects:** Finding F-08, build step 08

## Context
The blueprint specified WorldPop 100 m *constrained* as the demand surface, with
a building mask and pycnophylactic reconciliation to census ward totals.

In practice WorldPop proved unusable at build time:
- The server supports **no HTTP range requests**, so a windowed `/vsicurl` read
  of just the Chennai region fails (`Range downloading not supported`).
- It therefore requires the full **531 MB** national raster.
- Sustained throughput was **~4 kB/s** — 14.7 MB in 56 minutes, extrapolating to
  roughly **33 hours** — and resume is impossible for the same range-request reason,
  so any stall restarts from zero.

## Decision
Use **GHS-POP R2023A, 100 m, epoch 2020** (EC JRC), Mollweide tile `R8_C26`.

- Tiled: 45 MB rather than 531 MB, delivered at ~1.7 MB/s.
- **Inherently built-up-constrained**: GHS-POP disaggregates population using
  GHS-BUILT-S, a Sentinel/Landsat-derived built-up surface. This is the property
  F-08 wanted from WorldPop's constrained product, obtained more directly — so
  the separate building-footprint mask step is no longer required.
- Reprojection is avoided entirely: the raster stays in Mollweide and **pixel
  centroids** are transformed to WGS84 for H3 assignment. Warping a population
  COUNT grid resamples it, and resampling does not conserve people.

## Consequences
- GHS-POP places **7,224,731** persons inside the GCC boundary.
  Census 2011 (6,748,026) projected at the assumed 1.13 growth factor gives
  **7,625,269** — the two agree within **5.3%**. That is an independent
  cross-check on the demand surface that the plan did not originally have.
- The building-mask step is dropped as redundant. ASSUMPTIONS.md updated.
- WorldPop is retained as a **sensitivity comparator** (experiment E-06) if it
  can be obtained out-of-band; it is not on the critical path.
- Pycnophylactic reconciliation is unchanged in design but currently runs against
  a **placeholder** target (city total distributed proportionally), which is why
  every ward scale factor is identical at 1.0554. Real Census 2011 ward totals
  are still required — tracked as build step 08b.
