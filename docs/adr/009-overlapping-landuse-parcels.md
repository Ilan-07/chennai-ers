# ADR-009 — Overlapping land-use parcels resolve by risk priority

**Status:** accepted · **Date:** 2026-09-12 · **Affects:** A-07, F-29, the fire demand surface

## Context

`landuse_risk_weights()` documents a cell's fire multiplier as the area-weighted
mean of the risk classes overlapping it. A mean is bounded by its inputs, so
setting every multiplier to 1.0 must return exactly 1.0 everywhere. The E-06
control did that and **15 of 3,838 cells came back above 1.0, up to 1.56**.

The cause was arithmetic, not tagging: `covered` summed intersection areas, and
OSM land-use polygons overlap. Where ground is described twice the denominator
understates the covered area and the "mean" exceeds every multiplier that went
into it. Nothing failed — the fire surface just got quietly heavier in the
commercial core, which is exactly where the optimiser is most sensitive.

F-29 left this open because resolving an overlap looked like a modelling
decision, and picking one silently is the error this register exists to prevent.

## What the overlap actually is

Measured on the shipped layer (3,081 parcels, 145.9 km² of polygon area):

| | area | needs a decision? |
|---|---|---|
| sum of parcel areas | 145.9 km² | |
| union of parcel areas | 144.6 km² | |
| **double-counted** | **1.3 km² (0.9%)** | |
| — within one class | 0.92 km² | **no** |
| — across classes | 0.40 km² | yes |

Two different problems were hiding in one number, and only the smaller one is a
modelling question. Two polygons both tagged `commercial` describe commercial
ground; dissolving them is arithmetic. That is 70% of the defect and it is fixed
without deciding anything.

The cross-class remainder is 0.40 km² — **0.27% of the mapped area**. Most of it
is an industrial estate carrying a hazardous sub-parcel (0.11 km²) or abutting
residential (0.14 km²).

## Decision

**Resolve parcels into disjoint ground before taking the mean. Within a class,
dissolve. Across classes, earlier classes in an explicit priority list claim
ground from later ones, and the default order is risk-descending:
`hazardous > industrial > commercial > residential`.**

The cell multiplier stays an area-weighted mean — over a partition, which is
what the docstring always claimed it was.

**This is not the cell-level maximum A-07 rejects.** That rejection is about a
single mis-tagged storage tank multiplying a whole residential cell by five, and
it still holds: a mis-tagged tank claims only its own footprint. What the
priority decides is narrower — which of two disagreeing descriptions of the
*same ground* is used. If a hazardous polygon and a coarse residential relation
cover the same square metre, there is a hazardous facility on that square metre,
and the coarser description should not dilute the finer one.

## Why this is safe to decide

Because the decision was measured before it was made. Re-running the surface
under risk-descending and its exact reverse brackets every possible priority
order:

| order | weighted fire demand | max cell multiplier |
|---|---|---|
| risk-descending (adopted) | 8,935,948 | 3.0681 |
| risk-ascending (the opposite extreme) | 8,927,933 | 3.0000 |

**0.090% of weighted demand, 69 of 3,838 cells.** The choice that blocked F-29
is worth nine hundredths of a percent, and the whole A-07 sweep moves fire
coverage 2.35 points — itself inside the ±8.55 station-position floor. The order
is recorded because it is a decision, not because it is load-bearing.

## Consequences

- The control passes exactly: identity multipliers return 1.0 for every cell.
- `landuse_risk_weights()` now **asserts** its own boundedness rather than
  describing it. If a future input breaks the partition the build stops instead
  of shipping a plausible-looking surface.
- `priority` is a parameter, so the alternative stays measurable rather than
  arguable.
- A class absent from the priority list ranks last and is named in the report,
  rather than silently vanishing from the surface.
- The demand report carries `overlap_resolution`: how much area each class lost
  to within-class dissolve and how much it claimed from lower-priority ground.
