# ADR-004 — OSRM governs the trip overhead; 108/EMRI is a cross-check

**Status:** accepted · **Date:** 2026-09-09 · **Affects:** A-01/A-04, stage-4 calibration, F-19

## Context

Two oracles constrain the travel-time model and they cannot both be satisfied.

**OSRM.** 200 sampled origin–destination pairs, scored per distance band.
F-19 showed the gated statistic was itself broken: `bias_pct` is a ratio of
sums, dominated inside each band by the longest trips there, and its bootstrap
95% CI runs 5.5 to 25.2 points wide. A 5% threshold on a quantity with a ±12
point interval is not a test — which is why the same configuration flipped
between "pass" at 4.38% and "fail" at 5.04% across runs. Replacing it with
`band_median_ratio` exposed a systematic short-trip bias that the sum-ratio had
washed out: **+15.05% in the 0–2 km band**, falling monotonically with distance
— the signature of a flat per-trip overhead that is simply too large.

The stage-4 refit cuts the overhead from 45 s to **17.5 s**, and is
cross-validated 40× on held-out halves: it wins on worst-band in **95%** of
splits and on MedAPE in **100%**. A two-part `a + b·km` overhead was fitted and
rejected — it does not beat a single smaller constant out of sample.

**108/EMRI.** A published Chennai metro mean response of 426–450 s.

| overhead | dry-only response | A-10 weighted response |
|---|---|---|
| 45 s | 448.7 s — inside | 480.1 s — outside |
| 17.5 s | 421.2 s — outside | 452.6 s — outside by 2.6 s |

No configuration satisfies both. ASSUMPTIONS.md recorded this as an open
decision needing a human, and marked the refit **"NOT ADOPTED"** — while commit
`4a8db2a` had already adopted it and `baseline_report.json` had been carrying
`modelled_response_s: 421.2` ever since. The decision was made in the code and
denied in the register.

## Decision

**OSRM governs the trip overhead. The 17.5 s refit stands. EMRI is reported as a
cross-check and gates nothing.**

Three reasons, in order of weight:

1. **The overhead is a travel-time parameter, and OSRM constrains travel time
   directly.** EMRI constrains a *whole response* — call-taking, dispatch,
   turnout, travel, and whatever operational reality is folded into a published
   average. Fitting a travel-time term to a total-response statistic makes it
   absorb everything else that is wrong.
2. **The estimands are not comparable.** OSRM's is defined by us: these OD
   pairs, this profile, this network. EMRI's is not documented in any source we
   hold — which dispatches, which geography, which years, whether it is a mean
   over incidents or over stations. A gate whose estimand is unknown cannot be
   failed informatively.
3. **The evidence is asymmetric.** The refit is cross-validated on held-out data
   and wins 95%/100% of splits. EMRI is a single published range with no
   dispersion, no sample size, and no method note.

The counter-argument is real and is recorded here rather than buried: **demoting
a gate to make one's own result pass is exactly the move that needs scrutiny.**
What makes it defensible here is that the demotion was argued from the estimand
mismatch *before* the refit was run — the dry-day EMRI comparison had already
been marked `is_gate: false` in `baseline.py` on precisely this ground — and
that the refit is independently validated against the oracle that does govern.

## Consequences

- `degradation.py` writes `emri_comparison` with `is_gate: false` and
  `governs: "no"`, replacing the key named `emri_gate`.
- `ers.gates` classes it as **REPORTED**: evaluated, printed, never allowed to
  fail a build. It currently reads 452.6 s against 426–450 s, and will continue
  to be reported as outside the published range.
- The routing gates that DO govern — MedAPE ≤ 15%, worst-band median ratio ≤ 5%
  — both pass, at 7.23% and 2.57%.
- The stage-4 section of ASSUMPTIONS.md is corrected to record adoption.

## What would reverse this

An EMRI release documenting its estimand — dispatch set, geography, period, and
whether the figure is scene-arrival or call-to-door. If that turned out to be
comparable with a modelled free-flow travel time plus offsets, it would become
a second usable oracle and the conflict would have to be resolved on the merits
rather than by precedence.
