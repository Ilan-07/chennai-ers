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
| A-02 | Junction delay | 12 s signalised / 5 s degree≥3, scaled ×0.10 | **E-10 DONE — ablation supported, term should be deleted. Not yet adopted.** |
| A-03 | Emergency multiplier within the RSCH envelope | 1.0–1.20 | Step 07 calibration; E-10 ablation (not yet run) |
| A-04 | Alarm + turnout offsets | EMS 60+60 s; fire 60+80 s | Step 07 calibration |
| A-05 | Population growth 2011 → now | 1.13 city-wide | E-10 |
| A-06 | EMS demand weight `w0=0.6, w1=1.6` on 60+ share | — | E-06 |
| A-07 | Fire land-use risk multipliers | res 1.0 / com 1.8 / ind 3.0 / haz 5.0 | E-06 |
| A-08 | Flood closure depth | 0.30 m | E-09, swept {0.20, 0.30, 0.45} |
| A-09 | Wading speed factor | 0.35 | E-10 ablation (not yet run); E-09 sweep |
| A-10 | Scenario weights | dry .70 / peak .15 / f25 .10 / f100 .05 | **Now load-bearing — step 15 shows the siting recommendation depends on them (see below). The E-10 weight sweep is no longer optional.** |
| A-11 | Demand tessellation | H3 resolution 9 | Sensitivity at r10 |
| A-12 | Candidate minimum separation | 800 m | E-09 (candidate resample) |
| A-13 | Parcel snap radius | 400 m | Reported per site |
| A-15 | Station position uncertainty | 900 m (29 stations) / 60 m (4) | **E-11 DONE — moves EMS coverage ±6.7 pts P5-P95 and makes the site list irreproducible. Dominates every other effect measured. E-11b ranks the survey: 10 of 29 visits remove 60% of the noise.** |
| A-14 | Demand snap flag threshold | 300 m | Reported per cell |

## Experiment results

E-10 covers five assumptions (A-02, A-03, A-05, A-09, A-10). Only the A-02 arm
has been run; the other four remain outstanding.

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
- **OSM fire station completeness is ~48%** — 16 mapped features against 33
  authoritative stations, and two of the 16 are industrial/airport rather than
  municipal. The authoritative list is the source of truth; OSM is used only
  for coordinate corroboration.
- **No machine learning.** There is no learning problem in this system. The only
  defensible one — imputing link speeds from vehicle GPS traces — is data-gated
  and listed as future work rather than fabricated.
