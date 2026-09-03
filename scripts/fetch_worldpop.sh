#!/bin/sh
# Download the WorldPop India constrained raster (531 MB).
#
# This server supports neither HTTP range requests nor resume (`curl -C -`
# returns 33, and GDAL /vsicurl windowed reads fail for the same reason), so a
# stalled transfer must be restarted from zero. --speed-limit/--speed-time abort
# a transfer that drops below 20 kB/s for 60 s; --retry then starts it again.
set -e
URL="https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/IND/ind_ppp_2020_constrained.tif"
OUT="data/raw/ind_ppp_2020_constrained.tif"
TMP="$OUT.part"
rm -f "$TMP"
curl -L --retry 8 --retry-delay 5 --retry-all-errors \
     --speed-limit 20000 --speed-time 60 \
     -sS -o "$TMP" "$URL"
mv "$TMP" "$OUT"
echo "download complete: $(wc -c < "$OUT") bytes"
