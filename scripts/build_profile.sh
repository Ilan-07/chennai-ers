#!/bin/sh
# Build one study-area profile in an isolated tree. Build step 20.
#
# The metro and full profiles were built by hand: copy the repo somewhere, symlink
# data/raw, swap the city config, run the steps in order, copy the outputs back.
# That worked once and then drifted -- the copies kept their own `src` and
# `scripts`, so a fix made in the repo did not reach them, and the only way to
# notice was to diff two station tables by eye. That is what this script exists to
# stop.
#
# `src`, `scripts` and `config/scenarios` are SYMLINKED rather than copied, so a
# profile build always runs the code the repo currently has. Only the city config
# differs between profiles, which is the one thing that should.
#
#   sh scripts/build_profile.sh metro [tree-dir]
#   sh scripts/build_profile.sh full
set -e
cd "$(dirname "$0")/.."
REPO="$(pwd)"
PROFILE="${1:?usage: build_profile.sh <metro|full> [tree]}"
TREE="${2:-${TMPDIR:-/tmp}/chennai-ers-profile-$PROFILE}"
PY="$REPO/.venv/bin/python"

case "$PROFILE" in
  metro) CITY=config/city/chennai_metro.yml ;;
  full)  CITY=config/city/chennai_full.yml ;;
  *) echo "unknown profile: $PROFILE (expected metro or full)" >&2; exit 2 ;;
esac
[ -f "$REPO/$CITY" ] || { echo "missing $CITY" >&2; exit 2; }

echo "==> tree $TREE"
mkdir -p "$TREE/data" "$TREE/config"
# Code and inputs come from the repo, always. A stale copy of either is the
# defect this script replaces.
for link in src scripts tests Makefile; do
  rm -rf "$TREE/$link"; ln -s "$REPO/$link" "$TREE/$link"
done
for link in raw reference; do
  rm -rf "$TREE/data/$link"; ln -s "$REPO/data/$link" "$TREE/data/$link"
done
rm -rf "$TREE/config"; mkdir -p "$TREE/config"
# `[ x ] && continue` under `set -e` is a footgun: the list returns non-zero on
# the common path. Spelled out instead.
for d in "$REPO"/config/*; do
  b="$(basename "$d")"
  if [ "$b" != "city" ]; then
    ln -s "$d" "$TREE/config/$b"
  fi
done
# The city config is the ONLY thing a profile changes, so it is the only thing
# copied. `chennai.yml` is the name every script reads; the profile's file is
# copied over it rather than passed as a flag, so no script needs to know that
# profiles exist.
mkdir -p "$TREE/config/city" "$TREE/data/interim"
cp "$REPO/$CITY" "$TREE/config/city/chennai.yml"
if [ -f "$REPO/data/registry.json" ]; then
  cp "$REPO/data/registry.json" "$TREE/data/registry.json"
fi

cd "$TREE"
echo "==> building $PROFILE from $(readlink config/city 2>/dev/null || echo "$CITY")"
run() { echo "--- $*"; "$PY" "$@"; }

# The density floor comes from the city config copied above, so a profile
# is fully described by its config rather than by remembered flags.
run scripts/build_metro_area.py --out "data/interim/${PROFILE}_area.parquet"
run scripts/build_metro_units.py

# Which stations serve THIS boundary. Previously a manual copy, done once: the
# metro profile kept a table produced before ADR-001a and before the map-listing
# lookups were wired in, and it used a rule that quietly dropped a station
# covering into the area from 3 km outside it.
run scripts/project_stations_to_profile.py \
    --stations "$REPO/data/interim/stations_metro.csv" \
    --area "data/interim/${PROFILE}_area.parquet"
# The road graph depends only on the study-area polygon, and it is the one step
# here that costs 17 minutes and several GB. Reuse it when it is already built
# for this tree; FORCE_GRAPH=1 rebuilds.
if [ -f data/interim/graph_edges.parquet ] && [ -z "${FORCE_GRAPH:-}" ]; then
  echo "--- reusing data/interim/graph_edges.parquet (FORCE_GRAPH=1 to rebuild)"
else
  run scripts/build_graph.py
fi
run scripts/attribute.py
run scripts/fetch_parcels.py
run scripts/build_demand.py
run scripts/build_candidates.py
run scripts/baseline.py
for svc in ems fire; do
  run scripts/optimise.py "$svc"
  # The Google-position lookup is a GCC artefact and lives in the repo, not in
  # this tree. Stations it does not name (the ones the directories add outside
  # the corporation) fall back to their own adopted position, which is what the
  # error model's fillna is for -- and they keep their OWN uncertainty, so a
  # town-centroid station is still drawn at 2,000 m and not at 50.
  run scripts/sensitivity_stations.py "$svc" 300 --error-model gmaps \
      --max-snap-m 1000 --lookup "$REPO/data/interim/stations_gmaps_lookup.csv"
done
run scripts/flood_extent_report.py
run scripts/export_ui_data.py

echo "==> copying results into $REPO/data/interim/$PROFILE"
mkdir -p "$REPO/data/interim/$PROFILE"
for f in ui_data.json ui_basemap.json baseline_report.json demand_cells.parquet \
         candidates.parquet wards.parquet stations_resolved.csv \
         optimise_ems.json optimise_fire.json \
         sensitivity_stations_ems.json sensitivity_stations_fire.json \
         "${PROFILE}_area.parquet" flood_extent.json; do
  if [ -f "data/interim/$f" ]; then
    cp "data/interim/$f" "$REPO/data/interim/$PROFILE/$f"
  else
    echo "    (missing: $f)"
  fi
done
# The study-area polygon also belongs at the repo root, where the flood-extent
# report and anything else asking "how big is the full profile?" looks for it.
# Copying it only into the profile subdirectory left a stale boundary at the root
# that still answered that question -- with the pre-F-33 number.
cp "data/interim/${PROFILE}_area.parquet" \
   "$REPO/data/interim/${PROFILE}_area.parquet"
echo "==> refreshed $REPO/data/interim/${PROFILE}_area.parquet"

echo "==> done: $PROFILE"
