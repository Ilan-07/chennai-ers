# Station position survey — procedure

**Why this exists.** 29 of the 33 GCC fire stations have no verified coordinate.
Until they are verified, the publish gate (`passes_publish_gate: false`) marks
every coverage figure the project produces as PROVISIONAL.

**What has changed since this document was first written.** The original version
told you to search Google Maps and then confirm from satellite imagery. Step 1
has since been done for all 29 stations (E-11c), and step 2 **failed its own
control** (E-11e) — see below. The procedure now leads with the method that
actually worked.

---

## Where the 29 stand today

| state | n | what it means |
|---|---|---|
| `identity_confirmed` | 14 | a published TNFRS phone number matches the listing, or an OSM fire feature sits within 150 m |
| `named_fire_station` | 12 | the listing is named and categorised as a fire station, but nothing independent corroborates it |
| `ambiguous_candidates` | 3 | two candidate listings, no evidence separating them (Avadi, Secretariat, Tondiarpet) |
| `contested` | 1 | Athipattu — see below |

**This is why the work still matters.** E-11g measured what the 15 unconfirmed
positions are worth: if their Google listing names the right station, the noise
floor on EMS coverage is **±0.8 points**; if they are no better than the
geocoder positions they replaced, it is **±7.6 points**. At ±7.6 every effect
this project has measured — the junction term (3.4), maximin siting (4.7), the
equity cost at k=20 (5.0) — sits below the noise. The truth is between those two
numbers and cannot be located without checking.

---

## Method 1 — the phone match. Start here.

**This is the method that has confirmed every station so far, and it needs no
site visit and no contact with anyone.**

The Tamil Nadu Fire and Rescue Services publish an official directory with
landlines, CUG mobiles and email addresses
(`data/reference/tnfrs_chennai_contacts.json`, registry id 12). Where a Google
Maps listing publishes a number matching the official record, that listing is
provably that station.

`data/interim/station_survey_worklist.csv` carries `landline`, `cug`, `email`
and `maps_phone` for every row. Twelve stations were confirmed this way, and
Avadi was resolved by it — the POI named only "Fire station" carries the
official Avadi landline.

**What remains:** the listings that publish no phone number. For those, send the
one-line email below to the address already in the `email` column.

> Subject: Station location confirmation — <station> Fire Station
>
> We are a VIT Chennai student project modelling emergency response coverage
> across the GCC area, using the TNFRS public station directory. Could you
> confirm the street address of <station> Fire Station? We want to place it
> correctly on the map. Thank you.

Record the reply in `verified_lat` / `verified_lon` / `verified_by`.

**This is the highest-value remaining action in the project.** Fifteen emails
move the headline interval from ±7.6 to ±0.8, and no amount of further modelling
substitutes for it.

---

## Method 2 — OSM corroboration. Already exhausted.

Recorded so nobody repeats it. A widened Overpass query returns **17 fire
features** against 33 authoritative stations — roughly 48% complete — and four
match a station position within 150 m (Royapuram 4 m, Mylapore 23 m, Tambaram
41 m, and the Athipattu candidate that turned out to be the power station's own
fire post). Wikidata returns **zero** fire stations for Chennai. Nominatim is
not independent — it indexes the same OSM. No data portal publishes TNFRS
station geometry.

The other 25 have no OSM feature within 150 m, median nearest 3.2 km. **That is
not evidence against them**: OSM is missing most of the network. Absence is
expected.

---

## Method 3 — satellite imagery. DO NOT RELY ON THIS.

The original version of this document led with satellite verification, looking
for appliance bays, aprons and drill towers. **It was tested against a control
and failed.**

The control was Thiruvanmiyur — the one station confirmed independently, by an
exact phone match to the published TNFRS number, so its position is known to be
right. Neither satellite (dense tree canopy) nor Street View (the station sits
back up a lane off East Coast Road) shows the appliance bays the method looks
for. A method that cannot recognise a station known to be there cannot be
trusted to judge the other 28, and **no imagery verdicts were recorded**.

Use imagery only to *support* a position already confirmed by phone, never to
establish one. A negative from imagery means nothing.

---

## Recording a confirmed position

Once identity is confirmed by phone or email, the coordinate still has to be the
right *kind* of point:

> Record the coordinate **where the appliance bay exits onto the public
> carriageway** — not the building centroid, not the compound gate on a side lane.

The travel-time model starts the vehicle at the nearest road-network node. A
building centroid may snap to a service road or an internal driveway and inherit
a slow, wrong first link. The apron/carriageway junction is where the journey
actually begins.

Fill three columns in the worklist row:

| Column | What to put |
|---|---|
| `verified_lat` | e.g. `13.10441` — 5 decimal places is ~1 m, plenty |
| `verified_lon` | e.g. `80.29112` |
| `verified_by` | your initials, or `email:<date>` for a written confirmation |

Leave the row blank if you genuinely cannot confirm it. A blank is honest; a
guess is not, and the ingestion step reports exactly which rows are still open.

---

## Two special cases

**Athipattu is unlocated, not merely ambiguous.** The TNFRS directory lists two
stations — "Athipattu - I FS" (044-27950080, our authoritative number) and
"Athipattu - II FS". OSM names Google's first candidate *NCTPS Fire Station*,
the North Chennai Thermal Power Station's own internal fire post; the second is
named "stage 2", also plant-internal. Neither listing publishes a phone. The
municipal station's earlier record — a 25.5 km error, 922 m off the routable
network — was never a municipal station at all. Email
`athipattu1fire112@gmail.com` to settle which coordinate is Athipattu-I.

**Tambaram has zero leverage.** E-11b measured it: deleting the station outright
changes modelled coverage by 0.0 points, because it lies outside the GCC demand
surface. Surveying it improves nothing *in this model*. That is a statement
about the model's boundary, not about the station — but it is the one row worth
deprioritising.

---

## Do them in worklist order

The worklist is sorted by measured leverage — the coverage spread each station
alone is responsible for, from `scripts/prioritise_survey.py`. Leverage is
heavily skewed and the EMS and fire rankings agree closely (Spearman 0.79), so
one ordering serves both. Ten of the twenty-nine remove roughly 60% of the
positional noise.

If you regenerate the ranking, the worklist ordering must be regenerated with
it — `tests/integration/test_artefact_freshness.py` enforces that they agree,
because in September 2026 they did not.

---

## When you're done

```bash
.venv/bin/python -m ers.cli ingest-survey
```

This merges your coordinates in at confidence `surveyed`, and refuses anything
implausible:

- a verified point **> 3 km** from the current position is flagged for a second
  look — usually correct, since the geocoder was that far off, but it should be
  a deliberate confirmation rather than a typo slipping through;
- a point outside the GCC bounding box is **rejected**;
- malformed or partial coordinates are **rejected**.

It then reprints the gate. When `passes_publish_gate: true`, run `make all` —
every station-dependent artefact must be recomputed, and the freshness test will
fail the build until it has been.

---

## Worth doing while you're in there

**Contribute the fixes upstream.** OSM is missing most of Chennai's 33 fire
stations. Adding them (`amenity=fire_station`, `operator=Tamil Nadu Fire and
Rescue Services`, `name=<station> Fire Station`) takes a minute per station in
the OSM iD editor, is a genuine public-good contribution the report can cite,
and would make Method 2 work for whoever repeats this.

**Note anything odd.** If a station appears closed, relocated, or is a regional
office rather than a responding station, say so in `verified_by`. An inventory
error found now is worth more than one found in week 10.
