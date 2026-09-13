# ADR-005 — Report all three siting objectives; recommend none until A-10 is swept

**Status:** accepted · **Date:** 2026-09-09 · **Affects:** A-10, step 15, E-10 weight sweep
**Updated:** 2026-09-09 with the A-10 sweep result, which redirects the argument.

## Context

`scripts/optimise_robust.py` scores three strategies on every design-basis
scenario rather than on the one that chose them (EMS, k=10, all solves proven
optimal):

| strategy | dry (.70) | peak (.15) | f25 (.10) | f100 (.05) | expected | worst |
|---|---|---|---|---|---|---|
| dry-only | **75.23%** | 35.43% | 58.43% | 52.49% | 66.44% | 35.43% |
| expected | 74.88% | 37.26% | 58.92% | 52.94% | **66.54%** | 37.26% |
| maximin | 70.59% | **40.11%** | 57.43% | 51.24% | 63.73% | **40.11%** |

Two problems sit under any recommendation drawn from this table.

**The objectives disagree about what to build.** Maximin moves 7 of 10 sites
(Jaccard 0.18) and buys 4.68 points in the worst scenario for 2.71 points of
expected coverage. The "expected" strategy is nearly indistinguishable from
ignoring scenarios altogether — it shares 9 of 10 sites with dry-only and gains
0.10 points — because a 0.70 weight on dry makes the expected objective mostly a
dry-day objective.

**The disagreement is decided by an assumption, not a measurement.** A-10's
weights (dry .70 / peak .15 / f25 .10 / f100 .05) are an engineering judgement.
No frequency analysis produced them. They were introduced when nothing consumed
them, and step 15 made them load-bearing without their status changing.

And both sit under the noise floor. E-11d measured the maximin-vs-dry-only
effect at 4.68 points against a station-position noise floor of ±0.83 points if
the 15 unconfirmed Google listings name the right stations, and **±7.63 points
if they do not** (E-11g). Under the pessimistic model the entire table is noise.

## Decision

**Publish all three strategies with their full cross-scenario scorecard. Do not
name a recommended objective until the A-10 weight sweep has run.**

Specifically:

1. `robust_{svc}_k10.json` reports every strategy scored on every scenario —
   already true, and now required rather than incidental.
2. **No single "recommended sites" list is published from this analysis.** The
   E-11d finding stands: at current positional accuracy the optimiser chose 14
   distinct sites for 10 slots under the optimistic error model and 106 under
   the pessimistic one. A named site list implies an identification the data
   does not support.
3. The **expected** objective must be reported with its flatness. For fire it
   shares only 6 of 10 sites with dry-only while differing by 0.21 points: many
   quite different site sets are near-optimal, and a single answer read off it
   would be an artefact of tie-breaking.
4. The **A-10 weight sweep has now been run** (`scripts/experiments.py weights`,
   `data/interim/experiments/weights.json`), and it redirects this ADR's own
   concern.

## What the sweep found

Sweeping the dry weight over 0.50–0.90, both services, k=10, every solve proven
optimal:

| | EMS | fire |
|---|---|---|
| distinct **maximin** site sets across the sweep | **1** | **1** |
| distinct **expected** site sets across the sweep | 2 | 2 |
| sites shared between the two objectives | 2–3 of 10 | 4 of 10 |

**The maximin recommendation does not depend on A-10 at all.** Its site set is
identical at every weight, and its objective value is unchanged to four decimals
(EMS 0.4963, fire 0.3329) — as it must be, since maximin optimises the worst
design-basis scenario and the weights change neither which scenario is worst nor
that it is included.

**The expected recommendation moves, but barely.** It takes two values across the
whole range, switching between dry ≤ 0.60 and dry ≥ 0.70, and differing in 3 of
10 slots. *(Superseded 2026-09-12: on the census-reconciled surface it takes four
values for EMS and five for fire. See the corroborations at the end of this
record — the conclusion below is unaffected, its "or only weakly" qualifier is.)*

**The register's worry was aimed at the wrong parameter.** ASSUMPTIONS.md
promoted this sweep to load-bearing on the grounds that "the siting
recommendation depends on them". What the recommendation depends on *first* is
**which objective you choose** — the two agree on only 0–4 of 10 sites at *every*
weight in the range, and no value of A-10 brings them together. Resolving A-10 to
a measured frequency would therefore not settle the siting question; it would
leave it exactly where it is.

That strengthens the decision below rather than weakening it: the fork is a
genuine choice about risk posture, not an artefact of an unmeasured input.

## Consequences

- The project publishes a *decision frame* — here is what each objective buys
  and costs — rather than a *decision*, until the two things that would make a
  decision meaningful exist: swept weights and surveyed stations.
- This is a weaker output than the deck promises ("Ranked, coordinate-level
  siting recommendations"). It is the output the evidence supports.
- The worst design-basis scenario is `peak`, not `flood100`, for every strategy
  and both services. Congestion rather than inundation binds a robust plan —
  which is worth stating regardless of which objective wins, and does not depend
  on A-10 for its direction.

**2026-09-12 — two further corroborations, from directions unrelated to station
positions.** Both came out of experiment arms that had never been run.

- **The weights are load-bearing after all.** Re-run on the census-reconciled
  demand surface (ADR-007), the expected-objective site set takes four distinct
  values across dry weights 0.50–0.90 for EMS and five for fire, and at the
  shipped 0.70 the expected and maximin objectives share **no sites at all**.
  The 2026-09-10 run of the same sweep found the expected set stable at two
  values; that reading is withdrawn. The maximin set remains invariant.
- **The candidate lattice moves the site list without moving the number.**
  Rebuilding the lattice at 400 m instead of the shipped 800 m raises k=10
  coverage by 0.19 points and keeps only 6 of 10 EMS sites (3 of 10 fire) near
  where the shipped lattice put them (E-09 / A-12).

Neither involves a station coordinate. The site list is therefore under-determined
by at least three independent things — the unsurveyed positions, the objective,
and the lattice — and the decision-frame output stands.
