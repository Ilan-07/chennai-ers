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
| A-02 | Junction delay | 12 s signalised / 5 s degree≥3 | E-09 (±50%); E-10 ablation |
| A-03 | Emergency multiplier within the RSCH envelope | 1.0–1.20 | Step 07 calibration; E-10 ablation |
| A-04 | Alarm + turnout offsets | EMS 60+60 s; fire 60+80 s | Step 07 calibration |
| A-05 | Population growth 2011 → now | 1.13 city-wide | E-10 |
| A-06 | EMS demand weight `w0=0.6, w1=1.6` on 60+ share | — | E-06 |
| A-07 | Fire land-use risk multipliers | res 1.0 / com 1.8 / ind 3.0 / haz 5.0 | E-06 |
| A-08 | Flood closure depth | 0.30 m | E-09, swept {0.20, 0.30, 0.45} |
| A-09 | Wading speed factor | 0.35 | E-10 ablation |
| A-10 | Scenario weights | dry .70 / peak .15 / f25 .10 / f100 .05 | E-10 |
| A-11 | Demand tessellation | H3 resolution 9 | Sensitivity at r10 |
| A-12 | Candidate minimum separation | 800 m | E-09 (candidate resample) |
| A-13 | Parcel snap radius | 400 m | Reported per site |
| A-14 | Demand snap flag threshold | 300 m | Reported per cell |

## Known omissions, declared

- **Turn restrictions** (`type=restriction` relations) are not modelled. Junction
  delay is used as a proxy. Residual error is bounded by the step-07 OSRM comparison.
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
