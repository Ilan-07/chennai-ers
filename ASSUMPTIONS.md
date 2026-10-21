# Assumptions Register

Every value in this project is one of four things. Nothing is allowed to be
unlabelled, and nothing reaches a slide, an export or a report without its label.

| Class | Meaning |
|---|---|
| **FACT** | Verified against a primary source, cited below. |
| **RSCH** | Established finding from published literature. |
| **ASSM** | Engineering assumption. Has a starting value, a rationale, and an experiment that tests whether it matters. |
| **RECO** | A design decision made by the team. |

> **Rule.** No number appears in any output unless it was produced by a run ID
> that can be replayed. Until the pipeline produces it, it is a placeholder and
> is labelled as one. (Finding F-02)

---

## FACT — verified constants

| Value | Source |
|---|---|
| GCC area 426 km², 200 wards, 15 zones | Greater Chennai Corporation |
| GCC population 6,748,026 within the expanded 426 km² limits | Census of India 2011 |
| Chennai (M Corp.) held 4,621,135 residents across **155 wards over 174 km²** before the 2011 expansion | Census of India 2011 PCA, enumeration-block level (registry id 19) |
| The 42 local bodies merged in 2011 hold the remaining 2,126,891 — **no ward-level census exists for them** | Residual of the two figures above; [ADR-007](docs/adr/007-census-ward-reconciliation.md) |
| **33 fire stations** in GCC: 9 North, 9 South, 7 Central, 8 Suburban | GCC fire station listing; corroborated by TNFRS division counts |
| SFAC norm: 1 station / 10 km² urban, 1 / 50 km² rural | Standing Fire Advisory Council, MHA |
| SFAC urban response expectation 5–7 min | SFAC / DGFS |
| NFPA 1710: 80 s turnout, 240 s first-engine travel, 480 s full-alarm travel, at P90 | NFPA 1710 |
| 108/EMRI Chennai metro mean response ≈ 7.1–7.5 min | GVK EMRI / TN state reporting |
| Chennai Metropolitan Area extent is now 5,904 km² (not the 1,189 km² figure) | CMDA |

## RSCH — literature-bounded parameters

| Parameter | Bound | Source |
|---|---|---|
| Emergency vehicle speed multiplier | ≤ 1.25 on arterials, ~1.0 residential | Lights-and-siren scoping review: weighted mean saving ~159 s over a whole response, range 0.7–3.8 min |
| WorldPop unconstrained misallocation | ~10–20% of population placed in unsettled 100 m cells | WorldPop validation literature |
| Greedy MCLP guarantee | ≥ (1 − 1/e) ≈ 0.632 of optimal | Nemhauser, Wolsey & Fisher 1978 |
| EMS accessibility Gini in comparable cities | 0.45–0.75; 0.4 is the conventional warning line | Published EMS equity studies |

## ASSM — assumptions, each with the experiment that tests it

| # | Assumption | Value | Tested by |
|---|---|---|---|
| A-01 | Free-flow speed by highway class | `config/speeds/base.yml` | Step 07 calibration; E-09 (±20%) |
| A-02 | Junction delay | 12 s signalised / 5 s degree≥3, scaled ×0.10 | **UNSTABLE — the verdict has flipped three times across four input revisions (delete → retain → retain → delete). Latest, on the 39-station inventory: ablation SUPPORTED, materiality 6.20 pts, inside the pessimistic floor. Do not act on it; see "A-02 has flipped three times" below.** |
| A-03 | Emergency multiplier within the RSCH envelope | 1.0–1.20 | Step 07 calibration; **E-10 α-sweep, latest 2026-09-12 on the 39-station inventory: 7.77 pts EMS, 6.82 fire — inside the pessimistic floor** |
| A-04 | Alarm + turnout offsets | EMS 60+60 s; fire 60+80 s | Step 07 calibration |
| A-04b | Ward-total reconciliation | Census 2011 ward totals, dasymetrically re-cut from the 2008 ward geography onto the 2022 wards; the expansion area takes the residual model-proportionally ([ADR-007](docs/adr/007-census-ward-reconciliation.md)) | Mass-balance and provenance asserted in `tests/unit/test_census.py`; the re-cut's own report states the covered share |
| A-05 | Population growth 2011 → now | 1.13 city-wide | E-10 |
| A-06 | EMS demand weight `w0=0.6, w1=1.6` on 60+ share | **DATA-GATED — not applied.** No registered dataset carries a ward-level 60+ share; the EMS surface falls back to raw headcount and `demand_report.json` records that it did. ADR-007 ingests the Census 2011 ward PCA, which carries totals only — C-13/C-14 age tables are published at town level, so this stays blocked | E-06, blocked half |
| A-07 | Fire land-use risk multipliers | res 1.0 / com 1.8 / ind 3.0 / haz 5.0 — **APPLIED since 2026-09** (F-22) | **E-06 sweep, latest 2026-09-12: 2.35 pts on fire coverage, EMS control exactly inert. See F-29 for a defect the control exposed** |
| A-08 | Flood closure depth | 0.30 m | E-09, swept {0.20, 0.30, 0.45} |
| A-09 | Wading speed factor | 0.35 | E-10 sweep, latest: **5.55 pts** on flood100 |
| A-10 | Scenario weights | dry .70 / peak .15 / f25 .10 / f100 .05 | **E-10 sweep re-run 2026-09-12: LOAD-BEARING. The expected-objective site set takes 4 (EMS) / 5 (fire) distinct values across dry 0.50–0.90, and at the shipped 0.70 the expected and maximin objectives now share NOTHING. This reverses the 2026-09-10 reading.** |
| A-11 | Demand tessellation | H3 resolution 9 | Sensitivity at r10 |
| A-12 | Candidate minimum separation | 800 m | **E-09 resample, latest 2026-09-12: coverage moves 0.78 pts across 400–1200 m; the SITE LIST moves much more (6/10 retained at 400 m)** |
| A-13 | Parcel snap radius | 400 m | Reported per site |
| A-15 | Station position uncertainty | 50 m residual on the adopted Maps positions — **34 of 39 unsurveyed, only 14 with a confirmed identity**. Results are published under the ADR-006 waiver, NOT on surveyed positions | E-11 to E-11g, re-measured 2026-09-13 on the 39-station inventory. The noise floor is **±1.10 pts if the 15 unconfirmed POIs are right, ±8.55 if they are not** (E-11g, after F-32). Verification outstanding. |
| A-14 | Demand snap flag threshold | 300 m | Reported per cell |
| A-15 | A peak-hour post is an ADDITIONAL ambulance, not one moved out of a station | additive | **Not tested — DATA-GATED.** Pricing a move needs the per-station fleet, which no registered dataset carries. The additive figure is therefore an upper bound on repositioning the existing fleet ([ADR-012](docs/adr/012-peak-hour-staging.md)) |
| A-16 | Study-area density threshold | 1,500/km² urban centre (metro) / 500/km² raised cluster floor (full), EU/OECD Degree of Urbanisation ([ADR-011](docs/adr/011-study-area-boundaries.md)) | **Not swept.** `urban.py` stamps `assumption: A-16` into every area report, and the 500 floor is a compute limit rather than a chosen value — the standard 300 returns 3,463 km² and was OOM-killed |
| A-17 | Flood-layer applicability | a layer serves a study area only where its modelling domain covers ≥ 90% of it; observed-point layers declare `sourced_for` ([ADR-010](docs/adr/010-flood-layer-extent.md)) | Measured per profile in `flood_extent.json`; held by the `flood_layers_cover_their_study_area` BUILD gate |

## Experiment results

E-10 covers five assumptions (A-02, A-03, A-05, A-09, A-10). **All five have now
been run**, along with E-09 and the unblocked half of E-06 — see
[Experiments — all eight arms](#experiments--all-eight-arms-re-run-2026-09-12)
for the current numbers. The section immediately below is the ORIGINAL A-02
ablation and its later reversal, kept in place because the reasoning is the
record; its materiality figure was superseded by the 2026-09-12 re-run.

### E-10a — junction-delay ablation (A-02). Hypothesis SUPPORTED.

`scripts/ablate_e10.py` → `data/interim/ablation_e10.json`

The junction term is charged at every OSMnx node, and 86,439 of 88,143 nodes
have `street_count >= 3`. That node set records how OSM ways happen to have been
split, not where intersections are, so the term prices a topology artifact.

Deleting it entirely and refitting the trip overhead (45 s → 60 s) improves
agreement with the OSRM oracle on every measure, and clears the ≤5% per-band
bias gate that the shipped calibration fails:

| model | MedAPE | bias | worst band bias | band gate |
|---|---|---|---|---|
| shipped `×0.10 + 45 s` | 9.13% | +2.06% | 5.04% | FAIL |
| ablated `×0.00 + 60 s` | **7.91%** | **−0.92%** | **4.38%** | **PASS** |

The stage-3 calibration grid ran `junction_scale` over [0.10, 0.30] and selected
0.10 — the lower bound. Extending the grid through that boundary found the
optimum at zero. Zero had been evaluated in stage 2, but never jointly with the
trip overhead, which is the only configuration in which it can win.

**Materiality.** Adopting it lowers coverage by 1.5–3.4 points across all twelve
(service, scenario) cells — the shipped model is optimistic — while leaving the
scenario severity ranking unchanged for both services. The recommendation is
therefore to delete the term, but adoption is a full re-run of steps 06, 09, 13
and every optimisation downstream, and has NOT been applied.

**Method note.** Deleting the term while holding `trip_overhead_s` at 45 s
appears to *raise* coverage by ~2 points. That is an artifact of freezing one
half of a jointly-fitted pair, not a result. The ablation refits the overhead.

## Corrections — defects found and fixed

Recorded here because the numbers they touched had already been written down.

### F-13 — `equity_curve.py` consumed an artefact nothing produced

`data/interim/precovered_{svc}.npy` was **loaded** by `equity_curve.py` and
**saved by no script in the repository**. It had gone stale: for EMS it held 906
cells / 36.3% of population, which is the FIRE mask (911 cells / 36.75%) under
the EMS name, against the 55.7% that `baseline.py` and `optimise.py` both
compute. The visible symptom was arithmetically impossible — efficiency coverage
of 47.5% at k=5, *below* the 55.7% do-nothing baseline, when adding stations
cannot reduce coverage.

Fixed: `precovered` is derived from `ers.pipeline.load_service`, never loaded.
The orphan arrays are deleted. Violated Finding F-02 (no unreplayable numbers).

**The corrected curve tells a different story from the one it replaced.** The
maximin ward floor does not climb with k; it jumps to 22.19% at k=20 and then
stops dead — 22.19% at k=20, 30, 45 and 60, every one proven optimal.

| k | floor (was) | floor (now) | city coverage (was) | city coverage (now) |
|---|---|---|---|---|
| 5 | 0% | 0% | 47.48% | **68.09%** |
| 10 | 0% | 0% (unproven) | 56.01% | **75.23%** |
| 20 | 0% | **22.19%** | 66.75% | **82.71%** |
| 30 | 14.17% | **22.19%** | 74.30% | **86.61%** |
| 45 | 20.77% | **22.19%** | 81.06% | **89.67%** |

That ceiling is STRUCTURAL, not a solver artifact: opening all 352 land-feasible
candidates at once still leaves **ward 21 at 22.19%**, with wards 7 (24.0%) and
18 (24.6%) just above it. So the binding constraint on ward-level equity is the
CANDIDATE SET, not the station budget — past k=20 more stations buy city-wide
coverage and buy the worst ward nothing. The old "equity costs 8.63 points at
k=30" was an artifact of the stale precovered mask.

### F-17 — a structural bound closes the maximin floor at small k

The k=10 maximin ran its full 600 s without proving its own answer, and was
correctly recorded as an incumbent rather than a proven floor (F-15). Waiting
longer was the wrong fix. Proving the floor is 0 means ruling out every way of
covering 43 zero-coverage wards with 10 sites — combinatorially hard for the MIP,
and trivial as a covering question.

`exact.min_sites_for_positive_floor` solves the location set covering problem
instead: the fewest candidates that give EVERY demand-bearing ward some coverage.
The worst-ward share is positive only if no ward is left at zero, so that minimum
is a hard lower bound on any k with a positive floor. For EMS it is **12**,
proven in milliseconds. Every k below 12 therefore has a floor of exactly 0, by
construction rather than by search, and `equity_curve.py` no longer solves those
MIPs at all — k=5 fell from 70 s to instant, k=10 from an unproven 600 s to
proven instantly.

The bound is TIGHT: k=12 is the first k with a positive floor, at 1.18%.

| k | worst-ward floor | city coverage (efficiency) | equity cost | settled by |
|---|---|---|---|---|
| 5 | 0% | 68.09% | 0.00 pts | structural bound |
| 10 | 0% | 75.23% | 0.00 pts | structural bound |
| **12** | **1.18%** | 77.12% | 6.40 pts | MIP, 111 s |
| 15 | 8.67% | 79.54% | 5.42 pts | MIP, 32 s |
| 20 | **22.19%** | 82.71% | 5.00 pts | MIP, 4 s |
| 30 | 22.19% | 86.61% | 0.74 pts | MIP, 1 s |
| 45 | 22.19% | 89.67% | 0.10 pts | MIP, 1 s |
| 60 | 22.19% | 91.36% | 0.01 pts | MIP, 0 s |

Every row is now proven optimal. The curve is bracketed at both ends by
structure, not by solver effort: **below 12 sites no positive ward floor is
possible, and above 20 none better than 22.19% is possible**, because ward 21
cannot be reached beyond that share even with all 352 candidates open. Ward-level
equity is bought entirely between k=12 and k=20; past that, stations buy
city-wide coverage and buy the worst ward nothing.

That is the answer to the question `equity_curve.py` was written to ask — "how
many stations does equity cost at all" — and it is a candidate-set problem, not
a budget problem.

### F-14 — `frontier.py` routed on a different model from the rest of the project

It computed `pre_s` without the calibrated 45 s `trip_overhead_s`, so every ward
figure it published described a network 45 s faster than `baseline.py`,
`optimise.py` and `degradation.py`. Its beta=0 rung recorded 47.5% city coverage
where the identical unconstrained MCLP in `optimise.py` recorded 68.1% — two
files in the same repository disagreeing by 21 points about the same quantity.

Fixed: shared routing, plus a hard cross-check that the beta=0 rung equals
`optimise.py` at the same k.

### F-15 — a HiGHS time-limit stop was published as "proven optimal"

PuLP maps `HighsModelStatus.kTimeLimit` to `LpStatusOptimal`, so
`LpStatus[prob.status]` reads "Optimal" for a solve that merely ran out of time.
The previous equity curve recorded 600.3 s and 601.6 s solves as
`status: "Optimal"`. `_best_bound` keyed off the same string, so it returned
`bound = objective` and published `proven_gap: 0.0` for solves that never closed.

Fixed: optimality is now read from `sol_status`; `SitingSolution` carries
`proven_optimal` and `optimality_note`, and every report states which solves were
proven. An unproven maximin floor is a lower bound, not a maximum.

### F-16 — four scripts each re-implemented station-to-cell routing

The root cause of F-13 and F-14. Each copy was internally consistent, so unit
tests could not see the drift. There is now one implementation
(`src/ers/pipeline.py` + `src/ers/coverage.py`) and a cross-script consistency
suite in `tests/integration/` that asserts every consumer reports the same
baseline share, applies the same trip overhead, and never publishes a siting
result below the do-nothing baseline.

### E-11 — station position sensitivity. THE NOISE FLOOR.

`scripts/sensitivity_stations.py` → `data/interim/sensitivity_stations_{svc}.json`

29 of 33 stations carry locality-geocoded positions at a stated uncertainty of
**900 m**; 4 are OSM-corroborated at 60 m. The publish gate has been closed on
that basis since step 09, but "PROVISIONAL" is a word and the register demands a
number. Perturbing each station uniformly-in-area inside its OWN stated
uncertainty, 300 draws, seed 20260904, rejecting positions further than 300 m
from any road node (the real 33 snap 7-249 m, median 63 m; rejection is
per-station and bites on ~11% of draws, so the filter is not the binding
constraint):

| | EMS | fire |
|---|---|---|
| point estimate | 55.68% | 36.75% |
| mean over 300 draws | 52.53% | 35.69% |
| sd | 1.96 pts | 1.65 pts |
| **P5–P95 spread** | **6.66 pts** | **5.55 pts** |
| full range | 46.76–57.70% | 31.51–40.56% |
| bias vs point estimate | **−3.16 pts** | −1.05 pts |

**Every effect this project has measured is inside that noise floor.**

| effect | size | vs EMS noise floor of 6.66 pts |
|---|---|---|
| E-10 junction term | 3.4 pts | BELOW |
| maximin vs dry-only siting (step 15) | 4.7 pts | BELOW |
| equity cost at k=20 (step 14) | 5.0 pts | BELOW |

**The recommendation is not reproducible either.** Re-solving the k=10 siting
problem under each draw, the optimiser chose **64 distinct sites for 10 slots**
(EMS; 58 for fire). Exactly **one** site was selected in ≥95% of draws (three for
fire), mean overlap with the point-estimate set is Jaccard 0.47, and the
published site list was reproduced exactly in **1 of 300 draws**. The specific
sites named in `optimise_{svc}.json` are, at present station uncertainty,
arbitrary.

**The point estimate is also optimistic, not merely uncertain.** EMS coverage
averages 3.16 points BELOW the published figure across the draws. Locality
centroids sit in dense central places; dispersing stations to plausible real
positions moves them away from the population they are credited with covering.

**Consequence.** No further modelling refinement is defensible until the station
survey is done. The E-10 adoption decision, the robust-siting objective choice,
and the equity frontier are all sub-noise at current positional accuracy. The
binding constraint on this project is 29 unsurveyed station positions —
`docs/station-survey.md` and `data/interim/station_survey_worklist.csv` already
exist and are unfilled. That is the work.

This does not invalidate the METHOD; the pipeline, the gates and the corrections
(F-13 to F-17) stand. It bounds what the current OUTPUTS can be used to claim.

### F-19 — the band-bias gate was untestable, and it hid a real defect

The gate `no band bias > 5%` was scored on `bias_pct`, a ratio of SUMS. Inside a
band that is dominated by the longest trips there, and at n~50 its bootstrap 95%
CI runs **5.5 to 25.2 points wide**:

| band | n | sum-ratio bias | bootstrap 95% CI | CI width |
|---|---|---|---|---|
| 0–2 km | 46 | +4.42% | [−7.74%, +17.43%] | **25.2 pts** |
| 2–5 km | 49 | −6.99% | [−14.43%, +0.46%] | 14.9 pts |
| 5–10 km | 50 | +3.12% | [−1.11%, +7.15%] | 8.3 pts |
| 10–20 km | 50 | +2.75% | [+0.09%, +5.60%] | 5.5 pts |

Every band is statistically indistinguishable from zero bar the last. A 5%
threshold on a quantity with a ±12 point CI is not a test — which is why the
same configuration flipped between "pass" at 4.38% and "fail" at 5.04% across
runs, and why nothing on the grid could clear it. **Both E-10 verdicts used this
gate as a criterion.**

It also HID a real defect. Because long trips dominate the sums, it washed out a
systematic short-trip bias that the median ratio shows plainly — and three of
four of those CIs exclude zero:

| band | median ratio − 1 | 95% CI | flat 45 s overhead as share of trip |
|---|---|---|---|
| 0–2 km | **+15.05%** | [+7.4%, +26.9%] | **21.1%** |
| 2–5 km | +3.98% | [−6.1%, +7.1%] | 9.5% |
| 5–10 km | **+5.27%** | [+4.0%, +7.2%] | 5.5% |
| 10–20 km | **+3.18%** | [+1.3%, +5.6%] | 3.2% |

The bias falls monotonically with distance: the signature of a flat per-trip
overhead that is simply too large. `band_median_ratio` replaces `bias_pct` as
the gated statistic and returns a bootstrap CI alongside, so an under-sampled
band can be told from a failing one.

### Stage 4 — refit on the sound statistic. THE OVERHEAD IS TOO BIG.

`scripts/calibrate4.py` → `data/interim/calibration_stage4.json`

| | junction | overhead | worst band (median ratio) | MedAPE |
|---|---|---|---|---|
| shipped | ×0.10 | 45 s | 15.05% | 9.37% |
| **refit** | **×0.10** | **17.5 s** | **2.57%** | **7.23%** |

Cross-validated 40× on held-out halves: the refit wins on worst-band in **95%**
of splits and on MedAPE in **100%**. All four band CIs now straddle or nearly
straddle zero, and the gate passes for the first time.

**The junction scale is unchanged at ×0.10**, which independently confirms the
E-10 "retain" verdict on a statistic that can actually support it.

A two-part overhead `a + b·km` was fitted and **rejected**: it does not beat a
single smaller constant out of sample (winning only 40% / 18% of splits), so the
simpler model stands. What looked like a distance-dependent effect was just 45 s
being too large.

**ADOPTED 2026-09-04 (commit `4a8db2a`); the governing decision is recorded in
[ADR-004](docs/adr/004-trip-overhead-oracle.md).** The paragraph below described
this refit as NOT ADOPTED for five days after it had in fact been adopted and
was shipping in `baseline_report.json` as `modelled_response_s: 421.2`. The
conflict it describes is real and is resolved in ADR-004: **OSRM governs the
trip overhead and EMRI is demoted to a reported cross-check**, because the
overhead is a travel-time parameter, the OSRM estimand is defined by us while
EMRI's is undocumented, and the refit is cross-validated on held-out data. The
EMRI comparison is still evaluated and still reported as outside its published
range; it no longer gates anything.

Cutting the overhead to 17.5 s drops the modelled EMS response below the
published 108/EMRI range:

| overhead | dry-only response | A-10 weighted response |
|---|---|---|
| 45 s (shipped) | 448.7 s — inside 426–450 | 480.1 s — outside |
| 17.5 s (refit) | 421.2 s — outside | 452.6 s — outside (by 2.6 s) |

No combination satisfies both. Note that the current "pass" is dry-only: it
compares an OPERATIONAL mean response, measured across real dispatches in real
traffic, against a scenario defined as free-flow. That is not a like-for-like
test, and it flatters two errors into agreement — an inflated overhead against
the wrong comparison scenario.

The decision this needs is which oracle governs the trip overhead. OSRM
constrains travel time directly and the refit is cross-validated; EMRI is a
single published range whose estimand (which dispatches, which geography, which
year) is not documented in our sources. The defensible reading is that the
overhead is a travel-time parameter and belongs to the travel-time oracle, with
EMRI demoted to a reported cross-check against the WEIGHTED response. But
demoting a gate to make one's own result pass is exactly the move that needs a
human decision, so it has not been made.

### F-18 — the validation script scored a model the pipeline does not ship

Found while restoring the calibration chain after E-11c. `validate_routing.py`
built its junction delay WITHOUT `junction_delay_scale` and never added
`trip_overhead_s`, so it validated the UNCALIBRATED model. It could therefore
never show the shipped model passing its own gate, and its 42% MedAPE read as a
routing failure when it was a bookkeeping one:

| `validate_routing.py` | MedAPE | bias | MedAPE gate |
|---|---|---|---|
| as written (uncalibrated) | 42.0% | +36.4% | FAIL |
| scoring the shipped model | **9.4%** | **+1.2%** | **PASS** |

(`calibrate.py` and `calibrate2.py` legitimately omit the scale — they FIT it.
Only the validator was wrong.) Both terms now come from `head_delay_seconds`,
the same source every other consumer uses. A `--reuse-oracle` mode re-scores the
model against durations already fetched, so fixing a model-side bug no longer
costs 199 queries against a public service.

### E-10 REVERSED — the junction term should be RETAINED

The E-10 verdict recorded earlier in this file was **SUPPORTED**: delete the
junction term. That result was obtained against OD pairs sampled from the
Nominatim station positions, which E-11c showed were wrong by up to 25 km, and
scored by a validator that had the calibration wrong (F-18). Re-run on corrected
positions, a re-queried oracle and a fixed validator, the answer flips:

| model | MedAPE | bias | worst-band bias | objective |
|---|---|---|---|---|
| incumbent `×0.10 + 45 s` | 9.37% | +1.23% | 6.99% | **0.1259** |
| ablated `×0.00 + 60 s` | 8.60% | −1.67% | 8.60% | 0.1387 |
| grid best `×0.075 + 45 s` | 8.42% | +0.00% | 8.09% | 0.1151 |

Deleting the term now fits WORSE on the stated objective, and it fails the
band-bias gate it previously cleared. **Verdict: NOT SUPPORTED — retain the
junction term.** The earlier recommendation to delete it, and to retire A-02, is
withdrawn.

Two further notes. The grid optimum is no longer on the boundary — it sits at
×0.075, interior, which was the original reason for suspecting ×0.10. And no
configuration now clears the band-bias gate: the best worst-band bias available
anywhere on the grid is 6.99%, against a 5% gate. That is an open calibration
problem, not a settled one.

**The lesson is about ordering, not about junctions.** A parameter ablation was
run, concluded, written up and nearly adopted while the inputs it depended on
were wrong by kilometres. E-11 said the modelling was below the noise floor;
this is what that looks like in practice.

### E-11f — the official TNFRS directory confirms 12 identities, contact-free

`data/reference/tnfrs_chennai_contacts.json` (registered, id 12).

The Tamil Nadu Fire and Rescue Services publish their own station directory:
43 Chennai stations with **official landlines, CUG mobiles and email addresses**.
The GCC page this project started from carried neither addresses nor, for nine
stations, anything but the generic `101`.

That makes a verification possible that needs no contact with anyone. Where a
Google Maps listing publishes a number matching the official TNFRS record, the
listing is provably that station — the method that confirmed Thiruvanmiyur, now
applicable to all 29:

| confirmed on the official landline | confirmed on the official CUG mobile |
|---|---|
| Thiruvanmiyur, Poonamallee, Ambattur, Villivakkam, Korukkupet, J.J. Nagar, Ennore, **Avadi** | Koyambedu, Mylapore, Guindy, Manali |

**12 of 29 confirmed, zero contradicted.** Avadi is resolved by it: the POI named
only "Fire station" carries the official Avadi landline, so it is the station.

This confirms IDENTITY, not the pin's precision — a listing can name the right
station and still sit tens of metres off the building. It does, however, remove
the failure that actually mattered: a 25 km error of the kind Nominatim made.

Two revisions it forces:

- **Athipattu.** TNFRS lists TWO — "Athipattu - I FS" (044-27950080, our
  authoritative number) and "Athipattu - II FS" — which explains Google's two
  candidates, one named "stage 2". E-11e's conclusion that *neither* is municipal
  was therefore too strong; both may be TNFRS, with OSM's "NCTPS Fire Station"
  a colloquial label. Neither listing publishes a phone, so it stays unresolved.
- **Nine stations gained a real landline** where the GCC page had only `101`:
  Ashok Nagar, Mylapore, T Nagar, Guindy, V.O.C Nagar, Royapuram, Saidapet,
  Tondiarpet, Secretariat. The worklist now carries the published number and an
  email address for every one of the 29.

### E-11g — what the 15 UNCONFIRMED stations are worth

The narrow noise floor reported after E-11c is an ASSUMPTION for 15 of the
29 — that their Google POI really is that station. Nobody has checked. So the
`mixed` error model measures the cost of being wrong: identity-confirmed
stations keep a 50 m residual, unconfirmed ones are drawn from the same
empirical displacement distribution the discredited Nominatim positions had.

Re-measured 2026-09-12 on the census-reconciled surface (ADR-007); the earlier
run of the same experiment gave ±0.83 and ±7.63.

| error model | assumes | EMS P5–P95 | distinct sites for 10 slots | draws reproducing the point estimate |
|---|---|---|---|---|
| gmaps | all 29 POIs are correct | **±0.87 pts** | 11 | 279 of 300 |
| **mixed** | the 15 unconfirmed are no better than the old geocode | **±8.05 pts** | **69** | **3 of 300** |

At ±8.05 the site list is unidentified again — **69 distinct sites competed for
10 slots and only 3 draws in 300 reproduced the published set** — and all but two
measured effects fall back inside the noise. The two that clear it are the ±20%
class-speed band (20.4 points) and the junction term (10.8).

`mixed` is a deliberate worst case: it assumes identity confirmation bought those
15 nothing, when a POI named "Kilpauk Fire Station" and categorised as a fire
station is plainly better evidence than a locality centroid. The truth lies
between the two rows, and it cannot be located without checking.

**What this licenses.** Reporting `65.8% ±0.9` as a bare number is not supported.
Two honest options: send the 15 emails and earn the tighter figure, or publish
the bracket —

> Assuming the 15 unverified POIs correctly identify their stations, EMS coverage
> is 65.8% ±0.87. If they are no better than the geocoder positions they
> replaced, the interval is ±8.05.

The bracket needs no contact with anyone and is consistent with the project's
existing PROVISIONAL discipline. What is not defensible is quoting the narrow
figure while 15 of its inputs rest on an unchecked assumption.

### E-11e — independent cross-check. Only OSM exists, and it settles two.

Google Maps is one source. A position confirmed by one source is a lookup; a
position two independent sources agree on is evidence. So: what else is there?

| source | result |
|---|---|
| **OpenStreetMap** (Overpass, widened query) | **17 fire features** — the original query filtered by name and dropped the unnamed ones, which is where 3 of the 4 matches came from |
| Wikidata (SPARQL, 30 km radius) | **0** fire stations |
| Nominatim (structured `amenity=fire_station`) | **0** — and not independent anyway: it indexes the same OSM |
| data portals | no TNFRS station geometry found |

**4 of 29 corroborated within 150 m**, and two of them are the contested ones:

| station | nearest OSM feature | distance | effect |
|---|---|---|---|
| Royapuram | (unnamed) | 4 m | confirms |
| Mylapore | (unnamed) | 23 m | confirms |
| **Tambaram** | Tamil Nadu Fire and Rescue Services | **41 m from candidate B** | **RESOLVED — B is now primary** |
| **Athipattu** | **NCTPS Fire Station** | **8 m from candidate A** | **REJECTED — see below** |

**Athipattu is not merely ambiguous, it is unlocated.** OSM names candidate A
exactly: *NCTPS Fire Station* — the North Chennai Thermal Power Station's own
internal fire post. Candidate B is named "stage 2", also plant-internal. Neither
shows a building on satellite. So the municipal TNFRS Athipattu station has no
position from any source we have, and its earlier record — the largest
displacement in the set at 25.5 km, and 922 m off the routable network — was
never a municipal station at all. Phone 044-27950080 is the only route left.

The other 25 have no OSM feature within 150 m, median nearest 3.2 km. That is
**not** evidence against them: OSM holds 17 fire features against 33
authoritative stations, so absence is expected. Note also that OSM contains
stations absent from the authoritative list (Moolakothalam, NCTPS, the airport),
so the two inventories are each incomplete with respect to the other.

**Imagery failed its own control.** Before the dataset search, the satellite
method was tried on Thiruvanmiyur — the one station confirmed independently, by
an exact phone match to the published TNFRS number. Neither satellite (dense tree
canopy) nor Street View (the station sits back up a lane off East Coast Road)
shows the appliance bays `docs/station-survey.md` looks for. A method that cannot
recognise a station known to be there cannot judge the other 28, so no imagery
verdicts were recorded. The protocol's own fallback — the published phone number
— is the reliable route, and 18 of 29 have one.

### E-11c — Google Maps lookup. A-15's 900 m ERROR MODEL IS WRONG.

`data/interim/stations_gmaps_lookup.csv`. All 29 unsurveyed stations looked up as
Google Maps POIs. **This is a better geocode, NOT a survey** — the positions carry
confidence `google_maps_poi`, `verified_lat/lon/by` remain empty, and the publish
gate stays closed.

The finding is not the new coordinates, it is the size of the old error:

| displacement from the Nominatim provisional position | stations |
|---|---|
| within the assumed 900 m | 13 |
| 900 m – 5 km | 11 |
| **over 5 km** | **5** |

Median 1,042 m; maximum **25.5 km** (Athipattu), then J.J. Nagar 23.0 km, Avadi
13.6 km, Redhills 10.7 km, Poonamallee 10.1 km. Every one of those is a Suburban
division station whose Nominatim result had landed somewhere in the city centre
instead of in the town it is named after.

**Consequence for E-11.** A-15 assumed a 900 m uncertainty disc, and E-11 drew
perturbations from it. That model is falsified: 16 of 29 true positions lie
outside the disc entirely, so the +/-6.7 point noise floor is an UNDER-estimate,
computed from an error model narrower than the real error.

**But the coverage effect is small,** because the errors substantially cancel:

| | published | with Google Maps positions | change |
|---|---|---|---|
| EMS | 55.68% | 55.07% | **−0.61 pts** |
| fire | 36.75% | 40.50% | **+3.75 pts** |

The badly-misplaced stations are suburban: their wrong positions sat inside the
city adding coverage they should not have had, while their true positions sit at
or beyond the GCC edge. Some of that loss is offset by other stations moving to
better positions inside the city. A 25 km error in a single station's position
therefore moved the city-wide total by less than a point — which is a statement
about how redundant the network is at the periphery, not about the error being
harmless.

**Five remain ambiguous** and are flagged in the file: Avadi (POI named only
"Fire station"), Athipattu (two candidates 700 m apart), Tondiarpet (two 1.9 km
apart), Secretariat (two 330 m apart), Tambaram (two 280 m apart). One useful
disambiguation: the second "Vyasarpadi Fire Station" POI is categorised
*Apartment building* and was discarded as mis-tagged.

**What this does and does not change.** It does not open the publish gate: a
Maps POI is somebody else's data entry, not a verified position, and the
Thiruvanmiyur phone match (Maps `044 2440 1213` = authoritative `044-24401213`)
is corroboration for one station, not for twenty-nine. What it does change is
the error model: A-15's 900 m is not defensible and the E-11 noise floor should
be re-derived, or the survey done.

### E-11d — E-11 re-run under a corrected error model

E-11 drew perturbations from A-15's assumed 900 m disc, which E-11c falsified.
Re-run with the error distribution ACTUALLY OBSERVED — the 29 displacements
between the Nominatim positions and the Maps POIs, bootstrapped by magnitude and
applied in a uniform random direction — and again with the Maps positions
themselves. 300 draws each, seed 20260904.

| error model | svc | mean coverage | P5–P95 | bias | distinct sites (10 slots) | stable ≥95% |
|---|---|---|---|---|---|---|
| disc — A-15, falsified | EMS | 52.53% | 6.66 pts | −3.16 | 64 | 1 |
| **empirical — observed** | **EMS** | **50.69%** | **9.83 pts** | **−5.00** | **106** | **0** |
| gmaps positions | EMS | 54.86% | **1.20 pts** | −0.82 | 14 | 6 |
| disc — A-15, falsified | fire | 35.69% | 5.55 pts | −1.05 | 58 | 3 |
| **empirical — observed** | **fire** | **33.81%** | **8.80 pts** | **−2.94** | **85** | **0** |
| gmaps positions | fire | 40.09% | **1.38 pts** | +3.35 | 17 | 5 |

**E-11 understated the problem, as E-11c predicted.** Under the real error
distribution the EMS noise floor is **±9.8 points, not ±6.7**, and the published
point estimate sits **5.0 points above** the mean draw rather than 3.2. The site
list is worse still: **106 distinct sites competed for 10 slots and NOT ONE was
selected in 95% of draws.** The published recommendation is not weakly
identified, it is unidentified.

The conclusion of E-11 is unchanged and strengthened: every effect measured in
this project (E-10 3.4 pts, maximin 4.7, equity 5.0) sits far below a 9.8 point
noise floor.

**Adopting the Maps positions would do most of what the survey was for.** The
noise floor collapses to ±1.2 points — an 88% reduction, and below all three
effect sizes, which is the threshold at which the modelling becomes decidable.
Distinct sites fall from 106 to 14, with 6 of 10 slots stable at ≥95%.

Provenance: the `disc` row's artefact was overwritten when the canonical
`sensitivity_stations_{svc}.json` was regenerated against the adopted positions.
Those numbers are preserved in this table and in git at commit `c30e3b4`. The
`gmaps` row is now reproduced by the canonical file itself.

Three caveats, none of which the numbers show on their own:

1. The `exact reproduction` and Jaccard columns compare against the site set
   chosen from the OLD positions, which is not the right reference under the
   gmaps model. Read `distinct sites` and `stable ≥95%` instead.
2. Two Maps POIs sit off the routable network — Athipattu at 922 m and
   Raj Bhavan at 383 m — so the plausibility filter had to be relaxed to 1 km
   for that model. Athipattu is also the largest displacement (25 km) AND
   ambiguous; it is the least trustworthy position in the set.
3. Five stations remain ambiguous. A ±1.2 point noise floor assumes the POI
   chosen for each is the right one, which for those five is an open question.

**This still does not open the publish gate.** It replaces a bad geocode with a
good one; it does not verify anything. What it does establish is that the survey
would buy less than E-11b suggested IF the Maps positions are adopted first —
the remaining uncertainty after adoption is ±1.2 points, not ±6.3.

### E-11b — which stations to survey first

`scripts/prioritise_survey.py` → `data/interim/survey_priority.json`, and
`data/interim/station_survey_worklist.csv` rewritten in priority order.

29 site visits are not equally worth making. Perturbing ONE station at a time
inside its own uncertainty, holding the other 32 fixed, gives the coverage spread
each station alone is responsible for. **Leverage is heavily skewed**, and the
EMS and fire rankings agree closely (Spearman 0.79), so one ordering serves both:

| rank | station | division | leverage (pts) |
|---|---|---|---|
| 1 | Thiruvanmiyur | City South | 0.736 |
| 2 | Ashok Nagar | City South | 0.643 |
| 3 | Kilpauk | City Central | 0.629 |
| 4 | Koyambedu | City Central | 0.545 |
| 5 | Poonamallee | Suburban | 0.510 |
| … | | | |
| 28 | Ennore | Suburban | 0.039 |
| 29 | **Tambaram** | Suburban | **0.000** |

**Tambaram's zero is real, not a rounding artifact.** Deleting the station
outright changes modelled coverage by 0.0 points and leaves zero population
uniquely dependent on it: it lies outside the GCC demand surface. Surveying it
would improve nothing *in this model* — which is a statement about the model's
boundary, not about the station.

**What the fieldwork buys.** Perturbing only the stations outside the top N —
i.e. simulating having surveyed the top N — gives the decision curve:

| surveyed | still uncertain | EMS P5–P95 | fire P5–P95 | EMS noise removed |
|---|---|---|---|---|
| 0 | 29 | 6.28 pts | 6.00 pts | — |
| **5** | 24 | 3.98 | 4.20 | **37%** |
| **10** | 19 | **2.52** | 3.17 | **60%** |
| 15 | 14 | 1.64 | 2.22 | 74% |
| 20 | 9 | 1.31 | 1.15 | 79% |
| 29 | 0 | 0.00 | 0.00 | 100% |

**Ten visits of twenty-nine remove 60% of the noise**, taking the EMS interval
from ±6.3 to ±2.5 points — below the E-10 (3.4 pt) and maximin (4.7 pt) effects,
which is the threshold at which the modelling work becomes decidable again.
Twenty visits reach ±1.3 points.

Caveat, stated rather than buried: this is the residual SPREAD. Surveying also
moves the centre, by however wrong each geocode proves to be, and that part
cannot be known in advance. The −3.2 point bias measured in E-11 suggests the
centre will move down.

The baseline P5–P95 here (6.28 EMS / 6.00 fire, 200 draws) and E-11's
(6.66 / 5.55, 300 draws) are independent estimates of the same quantity; their
~0.5 point disagreement is the precision of a spread estimate at these draw counts
and should be read as such.

## Step 15 — scenario-robust siting

Until now every siting result was chosen on the DRY-DAY network alone
(`optimise.py`, `frontier.py` and `equity_curve.py` all route on `tau_ds_{svc}`,
which `attribute.py` writes for the dry scenario only), while step 13 showed a
100-year flood leaves 1.11 M people with no route from any station. The project
could measure flood vulnerability while still siting as though it never floods,
and the A-10 weights had no consumer. `scripts/optimise_robust.py` closes that.

Three strategies, each scored on EVERY scenario rather than on the one that chose
it. EMS, k=10, all solves proven optimal:

| strategy | dry (.70) | peak (.15) | f25 (.10) | f100 (.05) | expected | worst |
|---|---|---|---|---|---|---|
| dry-only | **75.23%** | 35.43% | 58.43% | 52.49% | 66.44% | 35.43% |
| expected | 74.88% | 37.26% | 58.92% | 52.94% | **66.54%** | 37.26% |
| maximin | 70.59% | **40.11%** | 57.43% | 51.24% | 63.73% | **40.11%** |

**The two objectives disagree about what to build.** Optimising the weighted mean
is nearly indistinguishable from ignoring scenarios altogether — it shares 9 of
10 sites with the dry-only choice and gains 0.10 points — because a 0.70 weight
on dry makes the expected objective mostly a dry-day objective. Maximin moves
**7 of 10 sites** (Jaccard 0.18) and buys 4.68 points in the worst scenario at a
cost of 2.71 points of expected coverage. Fire behaves the same way: expected
+0.21 points, maximin 8 of 10 sites changed for +2.93 points worst-case.

**The worst design-basis scenario is `peak`, not `flood100`** — for every
strategy and both services. Congestion, not inundation, is what binds a robust
plan, which is consistent with step 13: peak costs more average coverage than a
100-year flood, even though only the flood severs anyone.

So the recommendation now rests on whether the 0.70 dry weight is credible, and
A-10 is an engineering assumption, not a measured frequency. That makes the E-10
weight sweep load-bearing rather than a nicety.

**Caveat.** The expected objective is weakly identified: for fire it shares only
6 of 10 sites with the dry-only solution while differing by 0.21 points, so many
quite different site sets are near-optimal. A single "expected" recommendation
should not be read as *the* answer without reporting that flatness.

## Experiments — all eight arms, re-run 2026-09-12

`scripts/experiments.py`, one JSON per arm in `data/interim/experiments/`, each
with a run id. Effects are judged against the E-11g noise floor: **±0.87 points**
if the 15 unconfirmed station listings name the right stations, **±8.05** if not.

> **Superseded the same day.** Every figure in this section was measured on the
> 33-station GCC inventory. ADR-001a added the six stations TNFRS operates that
> the GCC page omits, and all eight arms were re-run against the 39-station
> inventory — see [the ADR-001a re-run](#2026-09-12-later--adr-001a-the-inventory-grew-and-every-experiment-was-re-run)
> at the end of this file for the shipped numbers. This section is kept as the
> record of what the smaller inventory said, because the comparison is what
> shows how much of this project's measured effect is really inventory
> uncertainty.

> **Every arm below was re-run after the census re-cut (ADR-007).** The
> reconciliation moved 186 of 200 ward totals, so results measured against the
> old demand surface describe a surface the project no longer ships. One
> conclusion reversed outright (A-10), one effect trebled (the junction term),
> and the three arms that had never run are now measured.

### E-09 / A-01 — class speeds ±20%. THE DECK'S FIGURE IS WRONG BY 5x.

| arm | EMS | fire |
|---|---|---|
| speeds ×0.80 | 53.67% | 39.70% |
| **shipped** | **65.75%** | **50.25%** |
| speeds ×1.20 | 74.11% | 60.47% |

EMS coverage spans **20.44 points** — the only effect this project has measured
that clears **both** noise floors. The deck states this sweep as a completed
validation ("class speeds varied ±20% shift coverage by roughly ±4 points — the
top three sites do not change") and it had never been run. The true sensitivity
is roughly **five times** the published claim.

A-01 is calibrated against the OSRM oracle, so it is not free to move ±20% — but
the claim that it could and would not matter is retired.

### E-10 / A-10 — design-basis weights. **LOAD-BEARING. THIS REVERSES THE 2026-09-10 FINDING.**

Dry weight swept 0.50–0.90, k=10, both services, every solve proven optimal.

| | EMS | fire |
|---|---|---|
| distinct **maximin** site sets | **1** | **1** |
| distinct **expected** site sets | **4** | **5** |
| sites shared by the two objectives, at the shipped 0.70 | **0 of 10** | **2 of 10** |
| shared-site range across the sweep | 0–3 of 10 | 2–3 of 10 |

The earlier run of this arm concluded **NOT LOAD-BEARING**: the expected site set
took two values and the two objectives shared 2–4 sites. On the census-reconciled
surface the expected set takes **four** values for EMS and **five** for fire, and
at the shipped weight the two objectives now share **nothing at all**.

Both readings agree on the part that matters for [ADR-005](docs/adr/005-siting-objective.md)
— the objective dominates the weights, and the maximin recommendation is
invariant to A-10 — but the weight sweep can no longer be called inert. **A
conclusion that survived one demand surface and not the other is itself the
finding**: neither run was wrong, and the earlier one was reported without a
sensitivity to the input it turned out to depend on.

### E-10 / A-03 — emergency speed multiplier. FIRST RUN. MATERIAL.

Never run before 2026-09-12; `scripts/attribute.py --service-config` exists so it
can be swept without hand-editing the shipped config. Each class multiplier's
deviation from 1.0 is scaled by α and capped at the RSCH ceiling of 1.25, which
handles both services with one parameter: EMS multipliers are gains above 1.0,
fire's are penalties below it for a heavy appliance on a narrow street.

| α | EMS motorway | EMS | fire |
|---|---|---|---|
| 0.0 — no emergency driving effect | ×1.00 | 61.06% | 54.56% |
| 0.5 | ×1.10 | 63.37% | 52.52% |
| **1.0 (shipped)** | **×1.20** | **65.75%** | **50.25%** |
| 1.5 — at the RSCH ceiling | ×1.25 | 68.37% | 48.50% |

EMS spans **7.31 points**, fire **6.06** — the second-largest effect measured,
above the optimistic noise floor and just below the pessimistic one. The two
services move in **opposite directions**, which is the point of the
parameterisation: the same α that speeds an ambulance up slows a fire appliance
down, so a single "emergency driving" fudge factor cannot be tuned to flatter
both.

A-03 is calibrated (step 07) rather than assumed, so the envelope is narrower
than this sweep. What the sweep retires is the idea that it is a detail.

### E-09 / A-12 — candidate minimum separation. FIRST RUN. THE SITES MOVE; THE NUMBER DOES NOT.

Never run before 2026-09-12. The lattice is rebuilt at four separations and the
k=10 problem re-solved from scratch for each, every solve proven optimal. Site
lists are not comparable by index — each separation renumbers the candidates — so
stability is geographic: how many of the ten sites have a counterpart within
800 m of the shipped lattice's choice.

| separation | candidates | feasible | EMS k=10 | fire k=10 | EMS sites near shipped | fire |
|---|---|---|---|---|---|---|
| 400 m | 2,354 | 986 | 84.08% | 69.04% | 6/10 | 3/10 |
| 600 m | 1,395 | 539 | 83.92% | 68.64% | 9/10 | 6/10 |
| **800 m (shipped)** | **948** | **352** | **83.89%** | **68.07%** | 10/10 | 10/10 |
| 1200 m | 519 | 174 | 83.03% | 68.44% | 5/10 | 6/10 |

Coverage spans **1.05 points** (EMS) and **0.97** (fire) — a quarter of a point
of headline coverage per doubling of the lattice, and below the pessimistic noise
floor. **The site identities are a different story.** Refining the lattice to
400 m keeps only 6 of 10 EMS sites and 3 of 10 fire sites near where the shipped
lattice put them, at a coverage gain of 0.19 points.

This is independent corroboration of [ADR-005](docs/adr/005-siting-objective.md)
from a direction that has nothing to do with station positions: the coverage
*attainable* at k=10 is robust, and the *list of places to build* is not. A
planner given the 800 m list is being given one of many near-identical optima.

### E-06 / A-07 — fire land-use risk multipliers. FIRST RUN (the half that is not blocked).

Never run before 2026-09-12: the surface was not implemented until F-22 and the
land-use layer was not fetched. Each multiplier's deviation from 1.0 is scaled,
so 0.0 is pure headcount and 2.0 doubles the spread between a residential block
and a fuel depot.

| scale | multipliers (com / ind / haz) | fire coverage | EMS control |
|---|---|---|---|
| 0.0 — headcount | 1.0 / 1.0 / 1.0 | 51.11% | 65.75% |
| 0.5 | 1.4 / 2.0 / 3.0 | 50.64% | 65.75% |
| **1.0 (shipped)** | **1.8 / 3.0 / 5.0** | **50.25%** | 65.75% |
| 2.0 | 2.6 / 5.0 / 9.0 | 49.61% | 65.75% |

Fire coverage spans **1.50 points** and falls monotonically: weighting demand
toward industrial and hazardous land moves demand *away* from the well-covered
residential core. The EMS control is **exactly inert** at every scale, as it must
be — EMS demand is raw headcount, and any movement there would mean the fire
weighting had leaked into a service that does not use it.

**A-06 remains blocked and this arm does not touch it.** Ward-level age tables
(C-13/C-14) are published at town level only, so the EMS age weighting still
falls back to headcount and `demand_report.json` still records that it did.

### E-10 / A-09 — wading speed factor. MATERIAL.

| wading factor | EMS flood100 coverage |
|---|---|
| 0.20 | 44.25% |
| **0.35 (shipped)** | **47.61%** |
| 0.50 | 49.67% |

Span **5.42 points** on the 100-year flood — above the optimistic noise floor,
below the pessimistic one. A-09 is an unmeasured engineering assumption and it
moves the flood result by more than the flood siting decision is worth. It should
be bounded from literature or from TNFRS operational practice before any flood
figure is quoted as settled.

### E-09 / A-08 — flood closure depth. APPLIES TO ONE SCENARIO ONLY.

| closure depth | EMS f2015 coverage | unreachable | flood100 control |
|---|---|---|---|
| 0.20 m | 57.04% | 359,593 | 47.61% |
| **0.30 m (shipped)** | **57.92%** | 168,553 | 47.61% |
| 0.45 m | 58.28% | 39,106 | 47.61% |

Span **1.24 points**, above the optimistic noise floor and well below the
pessimistic one.

**Method note, recorded because the first attempt got it wrong.** This arm
initially swept the depth and measured `flood100`, which returned exactly 0.00
points — not because A-08 is inert but because the return-period layers classify
SEVERITY and carry no depth at all. Only `f2015`, an observed-points layer with
measured depths, keys off `closure_depth_m`. A sweep that structurally cannot
move its own outcome reports "this assumption does not matter" when it means
"this arm measured the wrong thing", and the two are indistinguishable in the
output. `flood100` is now carried as an explicit control and asserted inert.

### E-10 / A-05 — growth factor. INERT FOR EVERY SHARE.

A-05 is a uniform multiplier on every cell, so it scales absolute population
counts proportionally and leaves **every coverage share exactly unchanged**.
It is load-bearing for statements of the form "N million residents beyond 8
minutes" — which is precisely the form the deck uses — and inert for the
percentages the pipeline reports. Recording which is which stops a future reader
treating the two as equally uncertain.

### E-10a / A-02 — junction delay. RE-RUN. THE EFFECT TREBLED.

`scripts/ablate_e10.py`, re-run against the census-reconciled surface. The
verdict is unchanged — **hypothesis NOT SUPPORTED, retain the term** — because
deleting it fails the band-bias criterion. What changed is its materiality:
the largest coverage move across the 12 (service, scenario) cells is now
**10.76 points**, against 3.4 before.

That matters for how the noise floor is read. Under the old numbers every
measured effect sat inside the pessimistic ±8.05; now the junction term and the
±20% speed band both clear it. The register's summary sentence has been corrected
in `config/publish_waiver.yml` accordingly.

### Nothing is left unrun

All eight arms in `ARMS` have results with run ids, plus the E-10a ablation.
The only outstanding experiment is the blocked half of E-06 (A-06), which needs
a dataset that does not exist at ward level.

---

## The 2026-09 repair — F-20 to F-26

An audit of the whole project found six defects of one kind: **a decision that
had been made, recorded, and never turned into code that anyone could re-run.**
Each is now a script, a registry entry and a test. None of them moved a headline
number by much, which is the point — they were invisible precisely because the
outputs looked fine.

### F-20 — the station inventory was hand-edited and unreproducible

`data/interim/stations_resolved.csv` is read by `ers.pipeline` and eight
scripts, and **was produced by no script at all.**
`ers.io.stations.resolve()` was registered as its provenance and called only
from the test suite. It had drifted from its own registry checksum: 6866 bytes
registered against 6423 on disk.

This is a direct violation of the rule at the top of this file, on the single
most load-bearing input in the project.

Fixed: `ers.io.stations.adopt_gmaps_lookup()` + `scripts/resolve_stations.py`,
deterministic and network-free, with `--check` diffing a fresh resolve against
the file on disk. [ADR-003](docs/adr/003-station-position-adoption.md).

**It also found a real drift.** E-11e resolved Tambaram to candidate B — OSM's
"Tamil Nadu Fire and Rescue Services" lies 41 m from B and 260 m from A — and
the hand-edited inventory still carried **candidate A**. The model had been
routing from the rejected coordinate. Tambaram's leverage is 0.000 points
(E-11b: it lies outside the GCC demand surface) so no coverage figure moves,
but every `stations_signature` downstream does.

A second error: `identity_confirmed_by` counted **15** confirmations where A-15
records 14, because `contested_unresolved` — Athipattu, a marker of doubt — was
being counted as evidence.

### F-21 — ward and zone geometry had no provenance at all

`wards.parquet` and `zones.parquet` were likewise written by no script and
appeared in **no registry entry**: no source, no licence, no checksum — for the
geometry every ward-equity result in the project is grouped by.
`ers.geo.wards` had existed and been unit tested since step 04; nothing called
it. `scripts/build_wards.py` now does, and regenerates both files
**byte-identically**, which is what makes the fix provable rather than merely
plausible.

### F-22 — two demand surfaces were declared in config and read by nothing

`config/services/ems.yml` declares `demand_surface: age_weighted` and
`fire.yml` declares `landuse_weighted`. **Nothing read the key.** Every coverage
figure in the project, both services, was weighted by raw headcount, so EMS and
fire differed only in turnout offset and speed multiplier — the two assumptions
meant to distinguish their demand did nothing.

`demand.service_weights()` had existed and been unit tested since step 05 and
was called from no script. And it could not have worked: the registered parcels
layer was fetched to find *candidate sites*, so it carries schools, parks and
industrial estates — **no residential, no commercial, no hazardous class**,
three of A-07's four categories. The data to honour A-07 had never been fetched.

Fixed: `scripts/fetch_landuse.py` (registry id 17, 3,100 features),
`demand.landuse_risk_weights()`, and dispatch in `build_demand.py` where an
unimplementable `demand_surface` now **raises** instead of being ignored.

- **A-07 is applied.** 1,455 cells above residential, cell multiplier max 3.67,
  fire demand total 8.95 M against a raw 7.63 M. On the census-reconciled surface
  (ADR-007) fire coverage moves from 51.11% headcount to **50.25%** weighted —
  the E-06 sweep's `scale = 0` arm now measures that gap directly.
- **A-06 is not.** No registered dataset carries a ward-level 60+ share.
  The EMS surface falls back to headcount and says so in `demand_report.json`.

### F-23 — graded coverage (formulation E) was declared and unused

Both service configs have carried `bands` since step 05 — EMS
`[{300,1.0},{420,0.7},{600,0.3}]` — and nothing read them. Every published
figure was binary: a cell 301 seconds away counted exactly as much as one 30
minutes away, which is zero.

`coverage.graded_share()` implements it, reported ALONGSIDE the binary share and
not in place of it. Switching the headline definition would move every number in
the repository, the console and the deck at once, and the difference could not
then be attributed to anything.

### F-24 — the gates existed only as fields in JSON files

`degradation_report.json` recorded `within_published_range: false` for the
project's own like-for-like EMRI comparison, and nothing read it back: no script
exited non-zero, no test asserted on it. A gate that nothing enforces is a
comment.

`ers.gates` now evaluates every gate with a severity — **BUILD** (fails the
build), **PUBLICATION** (the survey is outstanding; enforced by requiring the
PROVISIONAL stamp rather than by going red for months), **REPORTED** (a
cross-check that does not govern). `scripts/gate.py` exits non-zero on a BUILD
failure and runs in CI.

### F-25 — two artefacts had gone stale in place

Both were internally consistent, which is why no consistency test could see
them:

- **`stations_qa.json`** published `by_confidence: {locality: 29}` against an
  inventory reading `google_maps_poi: 29`, with `plausibility` labels
  (`settlement_centroid`, `unrelated_feature`) describing the **discarded**
  Nominatim positions. Thiruvanmiyur — the one station confirmed by an exact
  phone match, whose POI is named "Thiruvanmiyur Fire Station" — was labelled
  `settlement_centroid`.
- **`survey_priority.json`**, which decides which stations to visit first, was
  computed 68 minutes *before* the positions it ranks were replaced. The
  worklist copied its ordering forward. The project's own stated next action was
  ordered by a calculation on superseded coordinates.

Fixed by making provenance cheap and staleness detectable:
`ers.provenance.stamp()` puts a `run_id` (code commit + config hash + input
digests + seed) and a `stations_signature` on every report, and
`tests/integration/test_artefact_freshness.py` fails the build when an
artefact's signature does not match the inventory on disk. The `run_id` is the
mechanism this file's opening rule always assumed and never had.

### F-26 — a 9.1-hour job that did not need to be

`survey_priority.json` recorded **32,654 s**. `scipy.csgraph.dijkstra` runs one
sweep PER SOURCE, so re-routing all 33 stations to move one of them costs 33
times what it needs to — and the leverage loop moves exactly one at a time.

`coverage.leave_one_out_min()` caches the best-time field over the unmoved
stations; a draw then costs one Dijkstra and an elementwise minimum. Verified
**exactly equal** to the full re-route on the real graph over 12 trials
(max difference 0.0), at a measured **33.1x** speedup.

---

## 2026-09-12 — F-27 and F-28: the two things the register still called placeholders

Both were recorded honestly and neither was built. That is the same defect class
as F-20 to F-26, one level up: not a decision that never became code, but a
**gap that was documented so well it stopped being a task**.

### F-27 — the ward reconciliation reconciled nothing

`build_demand.py` carried the string `PLACEHOLDER city-total scaling; needs
Census 2011 ward totals` for nine days, and ADR-002 pointed at it. What the code
actually did was distribute the census CITY total across wards *in proportion to
the model*, which gives every ward the identical scale factor — 1.0554, all 200
of them — so the census fixed the magnitude and GHS-POP alone decided where in
Chennai people live.

The reason it stayed unbuilt is that the obvious fix is impossible. Census 2011
enumerated **155 wards over 174 km²**; this project maps **200 wards over
426 km²**, the difference being the 42 local bodies merged in the expansion of
that same year. There is no published crosswalk, and no ward-wise Census 2011
table for the modern wards exists or can exist.

Fixed by going through the demand cells instead of through a ward table
([ADR-007](docs/adr/007-census-ward-reconciliation.md)): each 2008 ward's census
total is spread over the H3 cells intersecting it, weighted by GHS-POP mass in
the intersection, then summed back up to the 2022 wards.

`scripts/fetch_census_wards.py` (registry ids 19 and 20), `ers.geo.census`,
`tests/unit/test_census.py`.

- **The reconciliation now moves the map.** Ward scale factors run **0.38 to
  3.43** (median 0.91) where all 200 were 1.0554, and **186 of 200 wards** shift
  by more than 10% against the targets they had.
- **Every coverage number moved with them.** EMS baseline **61.75% → 65.75%**,
  fire **47.02% → 50.25%**. Both moves are far outside the optimistic ±0.87-point
  station-position noise floor and comparable to the pessimistic ±8.05.
- **The city total is untouched** — targets sum to the configured 2011
  population exactly, so this is a redistribution, not a re-magnitude.
- **One third of the city is still not ward-reconciled.** The expansion area's
  2,126,891 residents have no ward-level census and take the residual
  model-proportionally. `demand_report.json.census_recut.residual_share_of_city`
  reports it as 0.3152 rather than describing the whole city as reconciled.
- **A-06 is unaffected and still blocked.** Ward-level age tables do not exist;
  C-13/C-14 are published at town level.

### F-28 — the architecture slide described software that was not written

The DA-1 deck specified a FastAPI service with a React + Leaflet console over
REST. `docs/deck-figures.md` carried it as **NOT BUILT** — the project shipped
one static HTML file — and left it there.

That mattered for a reason beyond the slide being wrong: the static console's
"Optimise" button ran **a greedy MCLP in JavaScript**. The console could show a
planner a site list that this project's optimiser had never seen and could not
bound, which is the second-implementation problem F-16 removed from routing,
reintroduced in the one place a user actually clicks.

Built: `src/ers/api` (FastAPI) and `ui/` (React 18 + Leaflet 1.9 on Vite),
[ADR-008](docs/adr/008-service-and-react-console.md). Siting is now solved
server-side by `ers.optimise` — greedy **and** the exact MIP — so the console
reports a proven gap because the solver proved it. `tests/unit/test_api.py`
asserts the service agrees with `baseline_report.json` to 5e-4 on both services,
so API-versus-report drift fails the build.

The deck's hosting claim — "cloud, cached spatial data store" — remains NOT
BUILT, and is recorded that way rather than quietly satisfied by a localhost
server.

### F-29 — overlapping land-use parcels were double-counted (CLOSED, ADR-009)

Found by the E-06 control, not by inspection. `landuse_risk_weights()` documents
its cell multiplier as an **area-weighted mean** of the risk classes overlapping
a cell, with unmapped area charged at the residential rate. A mean is bounded by
its inputs, so setting every multiplier to 1.0 must return exactly 1.0 for every
cell. The sweep's `scale = 0.0` arm does exactly that, and **15 cells came back
above 1.0, up to 1.56**.

The cause was that `covered` summed intersection areas, and OSM land-use polygons
overlap — a retail way inside a commercial relation is counted twice. Where that
happens the denominator understates the covered area and the "mean" exceeds every
multiplier that went into it.

**Closed 2026-09-12 by [ADR-009](docs/adr/009-overlapping-landuse-parcels.md).**
The register held this open because resolving an overlap looked like a modelling
decision. Measuring it first showed that most of it is not:

| | area | needs a decision? |
|---|---|---|
| sum of parcel areas | 145.9 km² | |
| union | 144.6 km² | |
| **double-counted** | **1.3 km² (0.9%)** | |
| — within one class | 0.92 km² | **no — arithmetic** |
| — across classes | 0.40 km² (0.27% of mapped area) | yes |

Two polygons both tagged commercial describe commercial ground, so dissolving
them decides nothing, and that is 70% of the defect. The cross-class remainder
now resolves by an explicit priority — risk-descending by default — and the
cell multiplier is an area-weighted mean over a **partition**, which is what the
docstring always claimed.

**The decision was bracketed before it was taken.** Running the surface under
risk-descending and its exact reverse bounds every possible priority order:
weighted fire demand 8,935,948 against 8,927,933, **0.090% apart, 69 of 3,838
cells**. The rule is recorded because it is a decision, not because it is
load-bearing.

The function now **asserts** its own boundedness instead of describing it, so a
future input that breaks the partition stops the build rather than shipping a
plausible-looking surface. Six tests in `tests/unit/test_demand.py` hold the
properties, including the E-06 control itself.

**The published fire coverage did not move: 54.43% before the fix and 54.43%
after.** The share is a ratio, and the defect inflated numerator and denominator
together across 15 of 3,838 cells. That is the outcome this entry predicted when
it was opened, and it is the reason the fix is recorded as a correctness repair
rather than a restatement of results. Had the number moved, the repair would have
been the same and the headline would have changed with it — which is the point of
fixing it before asking whether it mattered.

## 2026-09-12 (later) — ADR-001a: the inventory grew, and every experiment was re-run

[ADR-001a](docs/adr/001-authoritative-station-inventory-amendment.md) resolved a
conflict between two authorities. The GCC page lists 33 fire stations inside the
corporation; the TNFRS Northern and North Western regional directories list
those 33 **and six more** — Velachery, Thuraipakkam, Medavakkam, Kolathur,
Maduravoyal, Virugambakkam — all with an official landline and all inside the
corporation boundary. The operator's own directory is the better authority for
what the operator runs, so the inventory is now **39 stations**, and everything
measured against 33 was measured against an inventory that was missing 15% of
its stations.

### What moved

| | 33 stations | 39 stations |
|---|---|---|
| EMS coverage at 8 min | 65.75% | **71.77%** |
| Fire coverage at 10 min | 50.25% | **54.43%** |
| Noise floor, listings correct | ±0.87 pts | **±1.11 pts** (±1.10 after F-32) |
| Noise floor, listings wrong | ±8.05 pts | **±8.55 pts** |
| Distinct site sets across draws | 11 / 69 | **14 / 85** |
| Unsurveyed positions | 29 of 33 | **34 of 39** |

The headline moved **6.02 points** on EMS and 4.18 on fire — which is to say
that finding six stations on a directory page moved the published figure by more
than every measured effect in this project except the class-speed band. The
uncertainty interval widened rather than narrowed, because five of the six new
stations are themselves map listings.

### Every arm, re-run

| arm | assumption | span | vs ±1.10 | vs ±8.55 |
|---|---|---|---|---|
| class speeds ±20% | A-01 | **21.29 pts** | clears | **clears** |
| emergency multiplier | A-03 | 7.77 pts | clears | inside |
| junction ablation | A-02 | 6.20 pts | clears | inside |
| equity cost at k=10 | — | 6.29 pts | clears | inside |
| wading factor | A-09 | 5.55 pts | clears | inside |
| maximin siting | A-10 | 3.35 pts | clears | inside |
| land-use multipliers | A-07 | 2.35 pts | clears | inside |
| flood closure depth | A-08 | 1.28 pts | clears | inside |
| equity cost at k=20 | — | 0.84 pts | inside | inside |
| candidate lattice | A-12 | 0.78 pts | inside | inside |
| growth multiplier | A-05 | 0.00 pts | inert on shares | inert |

**Exactly one effect this project has measured clears the pessimistic floor.**
That is the finding, and it is not a comfortable one: until the 34 unsurveyed
positions are checked, almost every modelling decision here is smaller than the
uncertainty in where the stations are.

### A-02 has flipped three times. Stop acting on it.

| run | inputs | verdict | materiality |
|---|---|---|---|
| 2026-09-09 | original demand surface | delete | 3.4 pts |
| 2026-09-10 | OSRM-resampled OD pairs | **retain** | 10.8 pts |
| 2026-09-12 (a) | census-reconciled surface (ADR-007) | **retain** | 10.76 pts |
| 2026-09-12 (b) | 39-station inventory (ADR-001a) | delete | 6.20 pts |

The latest run says the ablation fits at least as well (objective 0.0953 ablated
against 0.0971 incumbent, MedAPE 6.8% against 6.9%) and recommends deleting the
junction term with `trip_overhead_s = 45`.

**The recommendation is not adopted, and A-02 stays as it is.** Not because the
run is wrong, but because a criterion that has returned a different answer on
four consecutive input revisions is not measuring the junction term — it is
measuring whatever changed most recently. The two configurations sit 0.0018
apart on an objective whose value moves by more than that when six stations are
added to the inventory. Deleting a modelled term on that basis would be reading
noise as evidence.

What would settle it is an input the ablation is not sensitive to: the station
survey. Until then A-02 is recorded as **unstable**, the junction term is
retained at ×0.10 because it is what the calibration selected, and the flip
history above travels with it.

### The stage-4 refit moved too, and the same reasoning applies

Re-running `calibrate4.py` on the 39-station inventory selects **×0.05 + 22.5 s**
where the previous run selected ×0.10 + 17.5 s — the same halving of the junction
scale the ablation reports, arrived at independently. Both points clear both
gates on the same pairs:

| configuration | worst band \|median ratio−1\| | MedAPE | gates |
|---|---|---|---|
| stage-3 reference (×0.10 + 45 s) | 14.48% | 9.90% | fails the band gate |
| **shipped (×0.10 + 17.5 s)** | **3.07%** | **6.92%** | **both pass** |
| refit on 39 stations (×0.05 + 22.5 s) | 0.72% | 5.61% | both pass |

The shipped point stays. It clears both gates with margin, and the refit's
preference for a different point is the same flatness the ablation keeps
tripping over: the junction scale and the trip overhead trade off against each
other, so the pair that wins depends on which station-to-cell pairs happen to be
in the sample — and the sample changed because the inventory did.

Two defects were fixed on the way to finding this:

- **`calibration_stage4.json` was outside the build DAG.** It is
  station-dependent (it fits on station-to-cell pairs) but no Makefile rule
  produced it, so ADR-001a left it carrying the old inventory signature and only
  `test_artefact_freshness` noticed. It now has a target and is part of `make all`.
- **The script called the stage-3 point "shipped".** It compared every refit
  against a hard-coded ×0.10 + 45 s, which stopped being what the project ships
  the moment stage 4 first ran. It now reads the shipped values from
  `config/speeds/base.yml`, scores them, and states whether they still clear the
  gates — which is the question a reader of this file actually has.

---

## 2026-09-13 — the three items the register still carried open

### F-30 — a file of evidence that nothing read

`data/interim/stations_metro_gmaps_lookup.csv` held 15 hand-gathered Google
Maps place results for metro stations, with place ids recorded so the lookups
could be repeated. **No script in the repository wrote it and no script read
it.** It was produced by hand during one session and orphaned in the next — the
F-20 class of defect this register is named for, one step worse: not a dataset
consumed by nothing, but *evidence* consumed by nothing.

The consequence was visible in the inventory and nobody looked. **Maraimalai
Nagar** sat at a town centroid with 2,000 m of uncertainty while a single
unambiguous POI for "Maraimalai Nagar Fire Station" sat in that file at 50 m.

Fixed: the file moved to `data/reference/tnfrs_metro_gmaps_lookup.csv`, beside
the GCC supplement it is a sibling of, and `resolve_metro_stations.py` now reads
it as position source 3 — ahead of the town centroid, behind OSM and the E-11
work. Maraimalai Nagar moved 700 m and its uncertainty fell by a factor of 40.

### The metro's unresolved positions, closed out

Re-running the resolver after ADR-001a and with the map listings wired in:

| position source | before | after | uncertainty |
|---|---|---|---|
| resolved (E-11 work) | 33 | **39** | 50 m |
| map listing | 5 | 1 | 50 m |
| OSM fire feature | 2 | 1 | 150 m |
| **town centroid** | **6** | **2** | **2,000 m** |

The six ADR-001a stations propagated into the metro inventory as `resolved`
rather than being re-derived, which is what took Maduravoyal off a centroid.

**Two centroids remain, and neither can be improved with the evidence that
exists.** Tambaram STC and Irungattukottai Sipcot both return
`no_place_result_search_page_only` — Google has no place for them either — and
only Tambaram STC is inside the study area. The nearest OSM fire feature to
Tambaram STC's centroid is 2.9 km away and sits **40 m from the already-resolved
Tambaram station**, so it belongs to that station and claiming it would duplicate
one station into two. The resolver's `claimed` check is what refused it; this is
the Athipattu lesson holding.

What closes them is a phone call. Both carry an official TNFRS landline in the
directory, and that is now the recorded next action rather than a better guess.

### A-17 — flood layers may only be asked about the area they were drawn for

New assumption, and the honest close on the metro's missing floods. See
[ADR-010](docs/adr/010-flood-layer-extent.md).

The metro and full profiles offered only dry and peak, explained by a sentence
typed into the console. Measuring it instead: Chennai Flows' modelling domain
covers **93% of the corporation, 47% of the built-up metro and 28% of the full
settlement**. It was produced for the corporation.

Running it anyway would not have failed — it would have returned the metro's
extra 486 km² and the full profile's extra 1,124 km² as **dry**, which reads as
flood resilience exactly where the study area was widened to include the places
2015 hit hardest.

The refusal is now measured, served through `/api/meta`, rendered in the console
with its number, and held by a BUILD gate
(`flood_layers_cover_their_study_area`). The naive test — how much of the layer
lies inside the study area — was tried first and discarded: it scores 98–100%
for every profile and therefore distinguishes nothing.

| | A-17 |
|---|---|
| **Assumption** | A flood layer's convex hull approximates its modelling domain, and a domain covering < 90% of a study area cannot speak for it |
| **Why a hull** | Absence of a polygon *inside* the domain means modelled-and-dry; absence *outside* means nobody modelled it. The two must not report as one |
| **Exception** | Observed-point layers declare `sourced_for` instead. A sample's hull is where it found something, not where it looked |
| **Tested by** | `tests/unit/test_flood.py` (3), `tests/unit/test_api.py` (4), and the gate |

---

### F-31 — a 22.92-point equity cost measured against a solution that was never found

Surfaced by the F-29 rebuild, which changed the fire demand surface enough to
push one solve over a line it had been sitting just inside.

`equity_curve.py` computes the equitable siting in two stages: maximise the worst
ward's share (maximin), then re-solve for maximum coverage **subject to** the
floor that achieved, so the reported "equity" column is the best equitable
solution rather than an arbitrary tie. At fire **k=20** the second stage came
back `Infeasible`.

**Nothing noticed.** An infeasible pulp solve returns `objective = 0.0` and an
empty site list, so `(baseline_covered + 0) / total` evaluated to **exactly the
do-nothing baseline**, 54.43%. The curve published a 22.92-point equity cost —
five times any neighbouring k — computed against a siting the solver never
found. The existing invariant could not catch it: it tests for points falling
*below* the baseline, and this one landed precisely *on* it.

**Root cause: the solver's objective is not a property of its own solution.**

| | |
|---|---|
| `z` reported by the maximin solve | 0.13339714534867728 |
| worst ward actually achieved by that siting | 0.13339614534867728 |
| difference | **exactly 1.000e-06** |

That is HiGHS's primal feasibility tolerance. The maximin constraints are
satisfied to within it, so the reported `z` sits a tolerance *above* what the
integer solution delivers — and re-imposing `z` as a hard floor is infeasible
against the very siting that produced it. A relative slack does not fix this:
`z * (1 - 1e-6)` is still 1.3e-7 short of a 1e-6 absolute gap, and it failed too.

**Fixed three ways, because one was not enough:**

1. The floor is now **recomputed from the maximin siting** rather than read off
   the objective. A number that is true of the solution cannot be infeasible for
   it, at any tolerance. Both values are recorded, with their difference.
2. A failed second stage **falls back to the maximin siting** — feasible by
   construction — and the row says so in `equity_coverage_from` instead of
   quietly publishing a baseline.
3. A new invariant: **a curve point that spends k stations must name them.**
   An empty siting scores the baseline exactly, which is why the existing
   below-baseline test was blind to it.

**What changed in the published numbers:** fire k=20 equity coverage 54.43% →
**72.36%**, equity cost 22.92 → **4.99 points**, which sits where the curve says
it should (k=15: 5.11, k=30: 2.35). The fire curve now has **0 unproven** points.
Every EMS figure was already correct and is unchanged — the fix altered nothing
that was right, which is the check that it is a fix and not a new choice.

---

### F-32 — a 2,000 m town centroid drawn as though it were known to 60 m

Found by running the profile build end to end for the first time, which is also
how it had stayed hidden: the metro profile's sensitivity had only ever been run
by hand.

E-11's `gmaps` error model perturbs each station inside its own uncertainty disc.
The radius came from the Google-position lookup, with a flat fallback:

```python
unc = j["residual_m"].fillna(60.0)
```

That is correct for the corporation, where **every** station is in the lookup.
It is wrong for every wider study area, where it is not. The metro's two
town-centroid stations carry **2,000 m** in the station table and were being
drawn at **60 m** — understating their spread by a factor of 33, in the one
direction `draw_positions` explicitly says this experiment must not err in.

The fallback now reads the station's **own** recorded uncertainty before
reaching for a constant, so a station is drawn at the radius its own evidence
supports.

**It moved the published GCC interval too.** Five of the six stations ADR-001a
added are not in the 29-row lookup, so they were being charged the flat 60 m —
the OSM proximity residual — when their evidence is a map listing at 50 m. The
optimistic noise floor narrows **±1.11 → ±1.10 points**; the pessimistic ±8.55 is
unchanged, because the mixed model sets its radii from identity confirmation
rather than from the lookup and never touched this line.

A hundredth of a point is not a material correction to the headline. It is
recorded because the *reason* was material: a constant standing in for evidence,
in the experiment whose entire job is to say how much the evidence is worth.

> **A second defect, found while fixing the first.** Re-running the four
> sensitivity arms by hand overwrote `sensitivity_stations_ems.json` with the
> mixed-model result, because the output path defaults to the gmaps name and only
> the Makefile passes `--out`. The waiver-freshness test added earlier today
> caught it immediately — it compares the shipped interval against the file that
> measured it, and 1.10 against 8.55 is not a rounding difference. The rebuild
> runs through `make`, which passes the flag.

---

### F-33 — the metro study area grew from its own output on every rebuild

The worst of the four found by making the profile build reproducible, and the
one that could only ever appear on a **second** run — which, until this script
existed, never happened.

Two scripts share one filename:

- `build_metro_area.py` unions the measured urban centre with the **authority**
  boundary, read from `data/interim/wards.parquet`.
- `build_metro_units.py` then **overwrites** `wards.parquet` with the profile's
  287 reporting units — 200 GCC wards plus 87 outer H3 cells covering the whole
  metro.

So the authority a rebuild reads is the previous run's *study area*, not the
corporation. Rebuilding the metro produced:

| | authority read | study area |
|---|---|---|
| as shipped (built once, fresh tree) | 431.9 km² — the corporation | **931.7 km²** |
| first rebuild | 889.6 km² — its own 287 units | **1,004.7 km²** |

**+73 km² per rebuild, compounding.** The urban-centre derivation is stable at
910 km²; every bit of the growth came from re-reading the output as an input.
Nothing would have failed. The number in `config/city/chennai_metro.yml` would
simply have drifted further from the number the pipeline produced each time
anyone re-ran it, and the study area would have quietly annexed whatever the
last run reached.

**Fixed by making the authority a thing that is kept rather than inferred.**
`build_metro_units.py` now snapshots the corporation boundary to
`gcc_wards.parquet` *before* overwriting `wards.parquet`, and refuses outright if
it is asked to run against a file that already holds profile units with no
snapshot to recover from. `build_metro_area.py` prefers that snapshot, takes an
explicit `--authority`, prints which boundary it used, and rejects a file
carrying a `unit_kind` column — because unioning the urban centre with the
profile's own units is exactly the mistake, and it is cheap to detect.

The snapshot existed in the shipped tree only because somebody had copied it
there by hand. Nothing wrote it, so nothing would have restored it.

**Verified idempotent:** the metro rebuild now reports authority 431.9 km² and
study area 931.7 km², the same numbers as the original build and the same as the
config declares.

**The full profile was already wrong when it shipped.** The metro survived
because it happened to be built once from a clean tree. The full profile was not:
rebuilt against the authority snapshot it measures **1,455.7 km², not the 1,581
km² recorded in its config** — an 8.6% overstatement, carried in every figure
that named its extent.

The arithmetic gives it away once the authority is printed. The urban cluster at
500/km² is 1,451.6 km² and it already contains all but **4.1 km²** of the
corporation, so the union can only add about 4 km². Reaching 1,581 required
unioning the cluster with the profile's own 413 reporting units (1,576.9 km²).
`config/city/chennai_full.yml` now records 1,456 km² and states why it moved.

---

### F-34 — the flood refusal was advisory, and the gate proved it

Found the way a gate is supposed to find things: it failed a build.

A-17 measures which flood layers were drawn for a study area and refuses the
rest. `flood_extent_report.py` wrote the verdict, `/api/meta` served it, and the
console rendered it with its numbers. **Nothing acted on it.**
`export_ui_data.py` carried a hard-coded list of six scenarios and computed all
of them regardless, so the rebuilt metro shipped flood coverage for 486 km² of
ground no layer covers — reported as *dry*.

The gate `flood_layers_cover_their_study_area` caught it on the first build that
produced the data, named all four scenarios, and failed:

```
FAIL  flood_layers_cover_their_study_area   4 served beyond its layer
      ... ground nobody modelled is returned as dry: f2015, flood100, flood25, flood5
```

This is worth recording for what it says about the order the work was done in.
The refusal was measured, published and explained a day before anything enforced
it, and in that state it was **decoration** — a study area that describes its own
limits accurately while serving numbers that ignore them is worse than one that
says nothing, because the caveat buys the figures credibility they have not
earned.

The export now reads the verdict for the profile it is building and skips what
was refused, printing which and why. The previously shipped metro was correct by
accident: it had been exported before the wider scenarios were ever computed for
it.

---

### F-35 — the widest study area could only see the narrowest one's stations

`resolve_metro_stations.py` places every station in the two TNFRS regional
directories, then writes **only those within the metro study area plus 3 km**.
The file is named `stations_metro.csv`, so this looked like scoping rather than
loss — but it is the only table of positioned directory stations the project
produces, and the full profile is built from it.

The full profile is **1,456 km²**, half a district wider than the metro. Every
station serving only its outer ring — Chengalpattu, Kanchipuram, Padappai,
Kalavakkam, Mahindra World City — was filtered out two steps upstream. Those
places would then have been scored as **unserved**, because the stations that
serve them had been deleted before the coverage run began.

That is the worst direction for this particular error to point. Gaps are this
project's product; the optimiser is aimed at ground no station reaches, and the
headline claim is about how much of Chennai cannot be reached in time. An
upstream filter that removes stations from the widest map **manufactures the
finding the project is looking for**.

The resolver now writes **86 positioned stations** instead of 43, flags
`in_metro_keep_zone` rather than acting on it, and
`project_stations_to_profile.py` does the per-profile filtering — which is its
entire job, and it needs a table to do it on. The profiles now draw:

| profile | extent | stations |
|---|---|---|
| gcc | 432 km² | 39 |
| metro | 932 km² | 43 |
| full | 1,456 km² | **45** |

The two the full profile gains over the metro are the ones serving its outer
ring. The previously shipped full profile had **47**, but that count belongs to
the inflated 1,581 km² boundary of F-33 — two of those stations were only ever
inside a study area that should not have existed. Against the corrected extent
the number is 45, and both corrections had to be made before either figure could
be trusted.

The manual process got the station scoping right by happening to run the resolver
against the full boundary that day. Nothing recorded that it had to, so the
scripted build got 43 and would have shipped it.

---

### F-36 — the hand-placed pin appeared somewhere other than where you clicked

Reported by the user, which is the only way this one was ever going to be found:
every test passed, and the behaviour was correct.

A station may only be placed where the candidate lattice allows one, because an
off-network point produces a coverage figure the optimiser could never reproduce.
So a map click snaps to the nearest candidate. That is right, and it was
**completely invisible** — the pin simply appeared somewhere else, and the
console said nothing about why.

Measured, the snap is not small. Clicking on a demand cell, the nearest candidate
is a median **447 m** away, 956 m at the 95th percentile and up to **2.2 km**;
against land-feasible candidates only, up to 3.1 km. And the search had **no
distance limit at all**, so a click on the sea or in the next district snapped to
whatever candidate happened to be nearest — one test click 17 km offshore would
have planted a station in the city.

Three changes, because the cause is one thing and the symptom is another:

1. **The lattice is drawn while placing.** 948 candidate sites as small dots. The
   question "why did my pin move" cannot arise when the sites you may click are
   on screen — you aim at one instead of at a street.
2. **The snap reports itself**: "Snapped 149 m to the nearest buildable site."
3. **A click too far from any candidate is refused**, with the distance, instead
   of placing a station somewhere the user never indicated. The limit is 3 km —
   wider than the worst in-city gap to a candidate, so every click inside the
   study area still works.

The lesson is not about the snap. It is that a correct rule applied silently is
indistinguishable from a bug, and no test was ever going to say so.

---

### F-37 — a profile build registered its output into a registry nobody keeps

Found by CI, on the first push. `make verify` failed:

```
FAIL id=34 metro_study_area: data/interim/full_area.parquet
     does not match its registered hash
```

The hash was not wrong. The **file** had legitimately changed — F-33 corrected
the full profile's boundary from 1,581 km² to 1,456 — and the registry had never
been told.

`build_profile.sh` seeds the isolated tree by copying the repo's
`registry.json` into it. The tree's `build_metro_area.py` then registers the
study area it writes... into that copy. The copy is discarded when the build
ends. The **artefact**, meanwhile, is copied back to the repo. So the repo ended
up holding a boundary newer than its own registration, and the append-only
registry — whose entire job is to make a run replayable against the data it
actually used — was quietly describing a file that no longer existed.

Same shape as F-30 (evidence nothing read) and F-34 (a refusal nothing enforced):
a step whose output goes somewhere nobody looks. Three in one audit is not a
coincidence; it is what happens when a pipeline is assembled by hand often enough
that each piece is verified in isolation and the seams never are.

**Fixed by registering the artefact where it lands.** The copy-back step now
registers each study area in the *repo's* registry, from the repo, and prints the
version it assigned. Registration is idempotent on the digest, so a rebuild that
changes nothing adds nothing.

`make verify`: 22 current sources, 0 failures.

> **Why CI caught this and the local suite did not.** Registry integrity is not a
> unit test — it compares committed files against recorded hashes, so it can only
> fail on a tree where both exist together. That is exactly what a first push
> produces, and it is the argument for CI running the same four commands the
> Makefile does rather than the tests alone.

---

### F-38 — the console header showed an extent the project had already corrected

Found while taking screenshots for the README, which is a reminder that looking
at the thing is a test no suite replaces.

The full profile's header read **1581 km²**. F-33 had corrected that boundary to
1,456 km² hours earlier, the config said 1456, the parquet measured 1455.7 — and
the console said 1581, because `ers.api.bundle.PROFILES` carries a hand-written
`area_km2` per profile and nobody edits a constant twice.

Two copies of one fact, and the transcribed one was what a reader saw. The API
now derives the extent from `{profile}_area_report.json` — written by the run
that produced the boundary, so it cannot disagree with it — and reports whether
the number is `measured by the build` or merely `declared`.

A second copy of the same omission turned up in the fix: `build_profile.sh`
copied the boundary back to the repo but **not the report describing it**, so the
repo held a report saying 1,581 beside a parquet measuring 1,456. Both now
travel together, the way the artefact and its registration now do (F-37).

**The corporation keeps its declared 426 km².** That is the authority's own
figure for its administrative area, not a measurement of a rendered polygon
(431.9 km²), and the two are allowed to differ — which is why the fix prefers a
measured value where one exists rather than asserting one everywhere.

---

## Known omissions, declared

- **Turn restrictions** (`type=restriction` relations) are not modelled. Junction
  delay was offered as the proxy for them — E-10 shows that proxy does no work
  (see above), and that the residual is absorbed by the flat `trip_overhead_s`
  instead. Turn cost is therefore modelled as a per-trip constant, not per turn.
  Residual error is bounded by the step-07 OSRM comparison.
- **108 ambulance standby points** are not published and are absent from OSM
  (an Overpass query over the GCC bbox returns **zero** `emergency=ambulance_station`
  features). EMS results therefore carry an explicit completeness caveat until
  EMRI supplies the list.
- **OSM fire station completeness is ~41%** — 16 mapped features against 39
  authoritative stations, and two of the 16 are industrial/airport rather than
  municipal. The authoritative list is the source of truth; OSM is used only
  for coordinate corroboration.
- **The metro and full profiles have no flood results.** The Chennai Flows
  layers and the 2015 replay were produced for the corporation and their
  modelling domain covers 47% / 28% of the wider study areas, so asking them is
  refused rather than answered with unmodelled ground reported as dry (A-17,
  [ADR-010](docs/adr/010-flood-layer-extent.md)). This is a real gap, not a
  technicality: Tambaram, Pallavaram and Chromepet are among the places the
  study area was widened to reach *and* among the places 2015 hit hardest.
  Closing it needs a return-period layer whose domain covers ≥ 90% of 932 km².
- **Two metro stations are placed on a town centroid** at 2,000 m uncertainty —
  Tambaram STC (in the study area) and Irungattukottai Sipcot (outside it).
  Neither has an OSM feature or a map listing; both have an official TNFRS
  landline, so what closes them is a phone call rather than more geocoding.
- **No machine learning.** There is no learning problem in this system. The only
  defensible one — imputing link speeds from vehicle GPS traces — is data-gated
  and listed as future work rather than fabricated.
