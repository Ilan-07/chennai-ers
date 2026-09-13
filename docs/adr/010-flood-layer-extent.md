# ADR-010 — A flood layer may only be asked about the area it was drawn for

**Status:** accepted · **Date:** 2026-09-13 · **Affects:** the metro and full profiles, the scenario menu, a new BUILD gate

## Context

The corporation profile models six network states. The metro and full profiles
modelled two, and the console explained the difference with a sentence somebody
typed into it:

> Only dry and peak are modelled here — the inundation layers stop at the
> corporation boundary.

The sentence was true. The problem is that nothing measured it, so nothing could
notice it becoming false: a new layer covering Tambaram would have changed
nothing on screen, and a careless later edit could have switched the floods on
for the metro with no test objecting.

Worse, the failure mode is silent and flattering. A flood scenario run over
ground the layer never covered returns that ground as **dry** — not as unknown.
The metro's extra 500 km² would have reported perfect flood resilience, and the
full profile's extra 1,149 km² likewise, exactly where the study area had been
widened to include the places that flood worst in practice.

## The measurement

The naive test — how much of the layer falls inside the study area — is useless,
because a layer is always almost entirely inside its own study area whatever that
area is. All four layers score 98–100% on it for every profile.

The question runs the other way: **does the layer's modelling domain span the
ground being asked about?** Approximating the domain by the convex hull of the
layer:

| layer | domain | covers GCC | covers metro | covers full |
|---|---|---|---|---|
| flood5 | 459 km² | 92.9% | 47.2% | 28.4% |
| flood25 | 463 km² | 93.1% | 47.6% | 28.7% |
| flood100 | 469 km² | 93.4% | 47.8% | 28.9% |

Chennai Flows was produced for the corporation. It covers 93% of it and under
half the built-up metro.

**Observed-point layers cannot be tested this way at all.** The 2015 replay is
192 surveyed points; its hull is 234 km², but that is where flooding was *found*,
not where the survey could have looked. Inferring a domain from where a sample
found something is how a sample becomes a map. Those layers declare
`sourced_for:` in their config and are applicable only to the study area they were
produced for.

## Decision

**A flood scenario is served for a study area only when its layer was drawn for
that area — by modelling domain for modelled extents, by declaration for observed
samples. Refusals carry their measurement, and a BUILD gate enforces it.**

- `ers.flood.scenario_extent_coverage()` returns the geometry of the question:
  the domain, what share of the study area it covers, and how much ground is left
  outside it.
- `scripts/flood_extent_report.py` writes the verdict per profile per scenario
  into `data/interim/flood_extent.json`, and runs as part of `make all`.
- `/api/meta` carries `flood_extent`, and the console renders the **reason** —
  "its modelling domain covers only 47.8% of this study area, leaving 486 km²
  where a flood would be reported as dry" — in place of the typed sentence.
- The gate `flood_layers_cover_their_study_area` fails the build if a profile
  ever serves a scenario its own layers cannot speak for.

## Consequences

- The corporation keeps all six states; nothing shipped changes.
- The metro and full profiles keep dry and peak, but now **say why with a
  number**, and the number updates when the data does.
- Extending flood modelling to the metro is now a data task with a stated
  target — a return-period layer whose domain covers ≥ 90% of 932 km² — rather
  than a sentence to be edited.
- The refusal is monotone by construction: a wider study area cannot accept a
  layer a narrower one rejected, which is asserted in the tests.

## What this does not fix

The metro and full profiles still have no flood results. This ADR does not
manufacture them; it records that the project declines to, and why. The places
the study area was widened to reach — Tambaram, Pallavaram, Chromepet — are
exactly the places 2015 hit hardest, so their absence from the flood picture is a
real gap in the work and is listed as one under *Known omissions*.
