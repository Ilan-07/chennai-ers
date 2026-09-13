# ADR-011 — The study area is measured, not drawn

**Status:** accepted · **Date:** 2026-09-12 (recorded 2026-09-13) · **Affects:** the metro and full profiles, A-11, every coverage figure outside the GCC

> **Why this is numbered after the decisions it precedes.** The metro and full
> profiles were built first and this ADR was referenced from
> `config/city/chennai_metro.yml` before it existed — the config pointed at
> "ADR-009", which nothing occupied until an unrelated decision took that number.
> A dangling pointer in a config is how a measured boundary comes to look like a
> drawn one, so the reference is corrected and the decision written down.

## Context

The corporation administers 426 km². Chennai does not stop there: Tambaram,
Chromepet, Pallavaram, Avadi, Poonamallee, Navalur and Siruseri are continuous
built-up ground that the 2011 expansion did not reach. A coverage study bounded
by the corporation reports those places as though they were not there, and the
gaps this project exists to find are disproportionately in them.

The tempting fix is to draw a bigger boundary. That would make every figure
outside the GCC a function of where somebody put the line.

## Decision

**Use the EU/OECD Degree of Urbanisation, computed from the population grid, and
take whatever boundary it returns.**

| profile | rule | extent |
|---|---|---|
| `gcc` | the administrative boundary | 432 km² |
| `metro` | urban **centre**: ≥ 1,500/km², contiguous, gap-filled, ≥ 50,000 people, unioned with the GCC | 932 km² |
| `full` | urban **cluster** at a raised floor: ≥ 500/km², same contiguity rules, unioned with the GCC | 1,456 km² |

Implemented in `ers.geo.urban` and `scripts/build_metro_area.py`. The density
floor is the only parameter that separates metro from full.

## Why `full` stops at 500/km² and not the standard 300

**Because 300/km² does not build.** It returns 3,463 km², whose road graph has
657k edges, and the build was OOM-killed on the 8 GB machine this project runs
on. It also reaches Kanchipuram, which is a different city with its own fire
service, not a suburb of Chennai.

500/km² is the largest extent that builds here. That is a **compute limit, not a
definition**, and it is recorded as one in the config rather than presented as a
principled threshold. A reader with more memory should raise it and will get a
different — and better — answer.

## Consequences

- **No census reconciliation outside the GCC.** The 155-ward Census 2011 table
  ADR-007 uses covers the pre-expansion corporation only. Population outside is
  GHS-POP as modelled, unreconciled, and every artefact says so.
- **Wards exist only inside the GCC.** Outside, the equity unit is an H3 r7 cell
  (~5.2 km², about 2.4 wards) labelled by its nearest named settlement, because
  no adjoining local body publishes ward geometry as GIS.
- **Flood scenarios do not extend outward** — see
  [ADR-010](010-flood-layer-extent.md). The boundary moved; the flood layers did
  not, and the project refuses rather than reporting unmodelled ground as dry.
- The three profiles are built by `scripts/build_profile.sh`, which symlinks
  `src` and `scripts` from the repo so a profile build always runs current code.
  The first two profiles were built from copies, which drifted.
