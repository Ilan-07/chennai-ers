# The pipeline DAG, executable.
#
# Before this file the ordering of 22 scripts lived only in commit messages and
# in ASSUMPTIONS.md prose. Two artefacts went stale because of it: stations_qa
# was computed against an inventory that later changed under it, and the survey
# priority ranking was computed against positions that were then replaced.
#
# Encoding the real prerequisites makes that class of defect a build property
# rather than a matter of discipline: an artefact older than its inputs is
# rebuilt, and `make -n all` shows what is stale without running anything.
#
# Long targets are marked with their measured runtime. `make graph` is 17 min
# and needs network; everything downstream of it is minutes.

PY      := .venv/bin/python
I       := data/interim
RAW     := data/raw
REF     := data/reference
SERVICES := ems fire
comma := ,
space := $(empty) $(empty)

.DEFAULT_GOAL := help
.PHONY: help all test gate verify accept-manifest clean-derived console experiments

help:
	@echo "targets:"
	@echo "  make all          full pipeline from cached raw data (~40 min)"
	@echo "  make test         pytest"
	@echo "  make gate         evaluate every publish gate; non-zero on failure"
	@echo "  make verify       registry hashes + artefact freshness"
	@echo "  make console      rebuild the coverage console"
	@echo "  make experiments  E-09 / E-10 sweeps (~1.5 h)"
	@echo "  make accept-manifest  record the current artefacts as the verify baseline"
	@echo "  make -n all       show what is stale without running it"

# ---------------------------------------------------------------- data spine

$(I)/wards.parquet $(I)/zones.parquet: scripts/build_wards.py config/city/chennai.yml
	$(PY) scripts/build_wards.py

$(I)/stations_resolved.csv: scripts/resolve_stations.py \
                            $(REF)/tnfrs_stations_gcc.csv \
                            $(RAW)/osm_stations_overpass.json \
                            $(I)/stations_gmaps_lookup.csv
	$(PY) scripts/resolve_stations.py

$(I)/demand_cells.parquet: scripts/build_demand.py $(RAW)/ghspop_chennai_2020_100m.tif $(I)/wards.parquet
	$(PY) scripts/build_demand.py

# 17 min, needs network on a cold OSM cache.
graph $(I)/graph_nodes.parquet $(I)/graph_edges.parquet:
	$(PY) scripts/build_graph.py

# ------------------------------------------------------- travel-time model

$(I)/arc_times.parquet: scripts/attribute.py $(I)/graph_edges.parquet \
                        config/speeds/base.yml config/services/ems.yml config/services/fire.yml
	$(PY) scripts/attribute.py

$(I)/routing_validation.json: scripts/validate_routing.py $(I)/arc_times.parquet $(I)/stations_resolved.csv
	$(PY) scripts/validate_routing.py 200 --reuse-oracle

# ------------------------------------------------------------- coverage

# baseline runs LAST of the coverage group, not first: it embeds the E-11
# position-uncertainty interval that sensitivity measures, and refuses to
# publish a stale one. Its own coverage numbers need none of that -- they come
# from arc_times, demand and stations directly.
$(I)/baseline_report.json: scripts/baseline.py $(I)/arc_times.parquet \
                           $(I)/demand_cells.parquet $(I)/stations_resolved.csv \
                           $(foreach s,$(SERVICES),$(I)/sensitivity_stations_$(s).json)
	$(PY) scripts/baseline.py

$(I)/candidates.parquet: scripts/build_candidates.py $(RAW)/osm_parcels_overpass.json $(I)/graph_edges.parquet
	$(PY) scripts/build_candidates.py

# NOTE: two outputs, one command. GNU make 3.81 -- which is what macOS ships --
# has no grouped-target syntax (`&:`), and a rule listing two targets there is
# read as two INDEPENDENT rules, so `make all` ran optimise.py once per output.
# The coverage matrix is therefore chained off the report rather than declared
# alongside it.
$(I)/optimise_%.json: scripts/optimise.py $(I)/candidates.parquet \
                      $(I)/arc_times.parquet $(I)/demand_cells.parquet \
                      $(I)/stations_resolved.csv
	$(PY) scripts/optimise.py $*

$(I)/coverage_%.npz: $(I)/optimise_%.json
	@test -f $@ || $(PY) scripts/optimise.py $*

# 130 s per service. The canonical invocation is NOT the default one: the
# adopted positions are Google Maps POIs (--error-model gmaps), and two of them
# (Athipattu 922 m, Raj Bhavan 383 m) sit off the routable network, so the
# plausibility filter runs at 1 km or those draws are all rejected. Those flags
# were recorded only in a prose caveat in ASSUMPTIONS.md until 2026-09; a
# re-run with the defaults dies with "found no plausible position".
SENS_FLAGS := --error-model gmaps --max-snap-m 1000

$(I)/sensitivity_stations_%.json: scripts/sensitivity_stations.py $(I)/coverage_%.npz \
                                  $(I)/stations_gmaps_lookup.csv
	$(PY) scripts/sensitivity_stations.py $* 300 $(SENS_FLAGS)

# E-11g: the same draw under the pessimistic identity model -- the 15 stations
# whose Google listing is unconfirmed are drawn from the discredited geocoder's
# displacement distribution instead of a 50 m residual.
$(I)/sensitivity_mixed_%.json: scripts/sensitivity_stations.py $(I)/coverage_%.npz
	$(PY) scripts/sensitivity_stations.py $* 300 --error-model mixed \
		--max-snap-m 1000 --out $(I)/sensitivity_mixed_$*.json

# There is NO cycle here, and an earlier version of this file wrongly claimed
# one and used recursive $(MAKE) to work around it -- which made optimise.py run
# three times per build. optimise computes its own baseline share through
# ers.pipeline.load_service and never reads baseline_report.json, so the real
# dependency is a straight line: optimise -> sensitivity -> baseline.
.PHONY: coverage
coverage: $(I)/baseline_report.json \
          $(foreach s,$(SERVICES),$(I)/optimise_$(s).json)

$(I)/degradation_report.json: scripts/degradation.py $(I)/baseline_report.json \
                              $(RAW)/chennai_flows_25yr.kml $(RAW)/chennai_flows_100yr.kml
	$(PY) scripts/degradation.py $(subst $(space),$(comma),$(SERVICES))

# ------------------------------------------------------------- siting

$(I)/frontier_%.json: scripts/frontier.py $(I)/optimise_%.json
	$(PY) scripts/frontier.py $* 10

$(I)/equity_curve_%.json: scripts/equity_curve.py $(I)/optimise_%.json
	$(PY) scripts/equity_curve.py $*

$(I)/robust_%_k10.json: scripts/optimise_robust.py $(I)/candidates.parquet $(I)/degradation_report.json
	$(PY) scripts/optimise_robust.py $* 10

# 9.1 h before the incremental-min rewrite; ~20 min after.
$(I)/survey_priority.json: scripts/prioritise_survey.py $(I)/stations_resolved.csv $(I)/coverage_ems.npz
	$(PY) scripts/prioritise_survey.py

# ------------------------------------------------------------- console

$(I)/ui_data.json: scripts/export_ui_data.py $(I)/optimise_ems.json $(I)/optimise_fire.json \
                   $(I)/sensitivity_stations_ems.json $(I)/sensitivity_stations_fire.json \
                   $(I)/sensitivity_mixed_ems.json $(I)/sensitivity_mixed_fire.json \
                   $(I)/stations_resolved.csv
	$(PY) scripts/export_ui_data.py

$(I)/ui_basemap.json: scripts/export_basemap.py $(I)/wards.parquet $(I)/zones.parquet
	$(PY) scripts/export_basemap.py

console $(I)/console.html: $(I)/ui_data.json $(I)/ui_basemap.json scripts/ui/con_js.js \
                           scripts/ui/con_head.html scripts/ui/con_body.html
	sh scripts/ui/build_console.sh

# ------------------------------------------------------------- aggregate

all: coverage $(I)/degradation_report.json $(I)/routing_validation.json \
     $(foreach s,$(SERVICES),$(I)/frontier_$(s).json) \
     $(foreach s,$(SERVICES),$(I)/equity_curve_$(s).json) \
     $(foreach s,$(SERVICES),$(I)/robust_$(s)_k10.json) \
     $(foreach s,$(SERVICES),$(I)/sensitivity_mixed_$(s).json) \
     $(I)/survey_priority.json $(I)/console.html
	$(MAKE) gate

experiments:
	$(PY) scripts/experiments.py all

test:
	$(PY) -m pytest -q

gate:
	$(PY) scripts/gate.py

verify:
	$(PY) scripts/register.py --verify
	$(PY) scripts/manifest.py diff data/manifest.json

# `verify` answers "what has changed since the state we last accepted". Run this
# once you have reviewed a run's output and want it to become that baseline.
# data/manifest_pre_repair_2026-09.json is kept as the historical record of what
# the tree looked like before the reproducibility repair, and is not updated.
accept-manifest:
	$(PY) scripts/manifest.py write data/manifest.json

# Derived artefacts only. Never touches data/raw or data/reference: those are
# ingested, hashed and registered, and some cost a 17-minute network fetch.
clean-derived:
	rm -f $(I)/*.json $(I)/*.npz $(I)/console.html
	@echo "raw and reference data untouched; run 'make all' to rebuild"
