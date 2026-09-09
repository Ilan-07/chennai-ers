# ADR-006 — Publish on unsurveyed positions, under a recorded waiver

**Status:** accepted · **Date:** 2026-09-10 · **Affects:** A-15, the publish gate, every coverage figure

## Context

The publish gate has been shut since step 09. It is a single predicate —
`passes_publish_gate = len(survey_required) == 0` — and 29 of the 33 stations
carry `google_maps_poi` positions, which are in `SURVEY_REQUIRED`.

The gate is not pedantry. The previous positions came from Nominatim, looked
entirely reasonable, and E-11c found **16 of 29 outside their own stated 900 m
uncertainty, the worst wrong by 25.5 km**. Athipattu's record turned out never
to have been a municipal station at all. Nothing in the pipeline noticed,
because wrong coordinates produce clean-looking numbers.

The survey will not complete before the coursework deadline. So the choice is
between publishing nothing and publishing something whose basis is stated.

## Decision

**Publish, under an explicit waiver, without altering a single coordinate or
confidence value.**

`config/publish_waiver.yml` records the date, who accepted it, why, what the
figures rest on, both ends of the measured interval, a review date, and what
closes it. `ers.publish.publication_basis()` reads it and returns the block
every report carries.

Three properties make this a waiver rather than a fudge:

1. **The factual gate is untouched.** `passes_publish_gate` stays `false` and
   the `stations_surveyed` gate stays FAILED. A decision to publish does not
   make the stations surveyed, and the two must never serialise to the same
   thing. What changes is `publication_basis`, which reads `"waived"` — never
   `"surveyed"`.

2. **The basis travels with the numbers.** A BUILD gate
   (`publication_basis_stamped`) fails the build if any affected artefact drops
   it, and a second (`waiver_states_its_interval`) fails if the waiver omits
   either end of the E-11g interval — so the narrow ±0.8 figure cannot be
   quoted alone while 15 listings are unconfirmed.

3. **It reverts in one line.** `active: false` returns every output to
   PROVISIONAL on the next run. Real survey data arriving through
   `ers ingest-survey` makes the waiver *redundant* rather than overriding it:
   `publication_basis` checks the inventory first, so a completed survey wins.

## What was explicitly rejected

Marking the 29 stations `surveyed` and filling `verified_by`. It would have
opened the gate with one edit and produced identical coverage numbers — and it
would have put a false record in the one file whose entire purpose is recording
what has been checked. Every downstream report would then have read as verified,
and the distinction between "we looked" and "we decided not to look yet" would
have been unrecoverable from the artefacts.

## Consequences

- Coverage figures may be published, and **must** be quoted as, e.g.,
  "EMS 61.75%, ±0.8 points if the 15 unconfirmed listings name the right
  stations and ±7.6 if they do not".
- At the wider interval every effect this project has measured — the junction
  term (3.4 pts), maximin siting (4.7), equity at k=20 (5.0) — is inside the
  noise. The waiver permits publication; it does not make those effects
  decidable, and no result should be presented as though it did.
- `make gate` exits 0 with `stations_surveyed` still failing. That is the
  intended reading: publication proceeds, the gap remains visible, and nobody
  has to remember it.
- Review by **2026-12-01**, or when the 15 identity emails are answered.

## Note on precedent

Waiving a gate to publish one's own results is the move that most deserves
scrutiny, and it is the second such demotion in this project (ADR-004 demoted
the EMRI comparison). The difference worth recording: ADR-004 argued a gate was
measuring the wrong thing. This one concedes the gate is measuring exactly the
right thing and publishes anyway, for a stated reason, with the shortfall
attached to every number. Only the second kind should ever be routine, and it
should stay uncomfortable.
