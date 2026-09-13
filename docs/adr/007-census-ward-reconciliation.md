# ADR-007 — Census ward totals are re-cut from the 2008 wards, not looked up

**Status:** accepted · **Date:** 2026-09-12 · **Affects:** ADR-002, Finding F-08, build step 08b

## Context
ADR-002 left the pycnophylactic reconciliation running against a **placeholder**:
the city total distributed across wards in proportion to the modelled
population. That is not a reconciliation. It gives every ward the identical
scale factor (1.0554 in the superseded run), so the census fixed the city
magnitude and contributed nothing to the *distribution* — which was GHS-POP's
opinion alone, on all 200 wards.

Closing it needs Census 2011 population per ward. It does not exist for the
wards this project models, and it never will:

- The project maps the **200 wards over 426 km²** of the Greater Chennai
  Corporation (registry id 14, the 2022 GCC ward map).
- Census 2011 enumerated the **155 wards over 174 km²** the corporation had
  *before* the 2011 expansion that merged 42 local bodies into it. The merged
  areas were counted as separate towns and villages, in two other districts.

No published crosswalk relates the two ward sets, and they share neither
numbering nor boundaries. A literal "load the ward totals" step is impossible,
which is why it sat unbuilt behind the word PLACEHOLDER for nine days.

## Decision
Re-cut the census onto the modelled wards **areally, through the demand cells**,
and reconcile to the result.

1. `data/raw/census2011_chennai_ward_eb.csv` — 8,802 enumeration blocks over the
   155 pre-expansion wards, 4,621,135 residents (OpenCity's transcription of the
   Chennai PCA).
2. `data/raw/chennai_wards_2008.geojson` — the 155-ward geography those blocks
   were counted on, 173.5 km² (Transparent Chennai via DataMeet).
3. Each 2008 ward's total is spread over the H3 cells intersecting it, weighted
   by **GHS-POP mass in the intersection**, not by area: the census says how many
   people a ward holds, the raster says where inside it they live. The 2008
   boundary only has to be right enough to decide which cells are in the ward.
4. Cells outside the 2008 corporation take the **residual** — the GCC-limits
   census total minus what the 155 wards hold, 2,126,891 people — distributed by
   raster mass, which is the old placeholder logic applied to the 32% of the city
   where it is the only option left.
5. Cell values sum back up to the 2022 wards and become the reconciliation
   target, after A-05's growth factor.

`ers.geo.census`, `tests/unit/test_census.py`, fetched by
`scripts/fetch_census_wards.py`.

## Consequences
- The reconciliation now moves the map. Ward scale factors run **0.38 to 3.43**
  (median 0.91) where before all 200 were 1.0554, and **186 of 200 wards** shift
  by more than 10% against the model-proportional targets they had. Every
  coverage number downstream moves with them; the run that published the
  superseded figures is still replayable by its `run_id`.
- The city total is untouched: targets sum to the configured 2011 population
  exactly, so this changes *distribution*, never magnitude. GHS-POP's 5.3%
  agreement with the census city total (ADR-002) still stands as written.
- **Two-thirds of the city is now census-reconciled and one-third is not.** The
  expansion area's 2,126,891 residents are still allocated model-proportionally.
  This is reported in `demand_report.json.census_recut`
  (`residual_share_of_city: 0.3152`) rather than described as a ward
  reconciliation, because it is not one. Closing it needs town- and
  village-level PCA for the 42 merged bodies plus their 2011 boundaries; none of
  it is machine-accessible today.
- Three vintages are now mixed by construction: 2011 counts, on 2008 ward
  boundaries, cut to 2022 wards. The dasymetric weighting absorbs boundary error
  in the *interior* of old wards, and cells straddling the old boundary are split
  rather than assigned wholly to one side. What it cannot absorb is real
  population change between 2011 and the modelling year, which A-05 treats as a
  single city-wide multiplier and E-10's growth arm shows is inert for every
  coverage share and load-bearing for every absolute count.
- Neither input is a censusindia.gov.in download. Both are third-party
  transcriptions, registered with that basis stated, and the EB table's sum is
  0.6% below the published town total of 4,646,732. A better provenance for the
  same numbers would not change the method.
- **A-06 is still blocked.** Ward-level age tables (C-13/C-14) are published at
  town level, not ward level, so the EMS age weighting remains data-gated exactly
  as `build_demand.py` records it. This ADR closes the F-08 reconciliation, not A-06.
