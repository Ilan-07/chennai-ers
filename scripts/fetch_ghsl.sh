#!/bin/sh
# GHS-POP R2023A, 100 m, Mollweide tile R8_C26 (covers Chennai).
#
# Substituted for WorldPop: WorldPop's server sustained ~4 kB/s (~33 h for the
# 531 MB national raster) and supports neither range requests nor resume.
# GHS-POP is tiled (45 MB) and served at ~1.7 MB/s. See docs/adr/002.
set -e
B="https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles"
T="GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R8_C26"
mkdir -p data/raw/ghsl
curl -L --retry 5 --retry-all-errors --speed-limit 20000 --speed-time 60 \
     -sS -o "data/raw/ghsl/$T.zip" "$B/$T.zip"
cd data/raw/ghsl && unzip -o -q "$T.zip" && rm -f "$T.zip"
ls -la
