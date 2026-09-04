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
| A-02 | Junction delay | 12 s signalised / 5 s degree≥3, scaled ×0.10 | **E-10 re-run on corrected positions: ablation NOT supported. RETAIN. The earlier 'delete it' verdict is withdrawn.** |
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
| A-15 | Station position uncertainty | 900 m (29) / 60 m (4) — **FALSIFIED by E-11c: 16 of 29 lie outside 900 m, up to 25 km** | E-11 (±6.7 pts, now an UNDER-estimate), E-11b (survey ranking), E-11c (Maps lookup). Survey outstanding. |
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

**NOT ADOPTED — the two oracles now conflict head-on.** Cutting the overhead to
17.5 s drops the modelled EMS response below the published 108/EMRI range:

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
