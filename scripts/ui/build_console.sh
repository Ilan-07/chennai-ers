#!/bin/sh
# Assemble the coverage console. Data blocks are application/json, never
# JavaScript source: as source the browser must parse megabytes before it can
# paint anything, and the page looks broken while it does.
set -e
cd "$(dirname "$0")/../.."
OUT="${1:-data/interim/console.html}"
{ cat scripts/ui/con_head.html; cat scripts/ui/con_body.html
  echo '<script type="application/json" id="d-model">';  cat data/interim/ui_data.json;    echo; echo '</script>'
  echo '<script type="application/json" id="d-base">';   cat data/interim/ui_basemap.json; echo; echo '</script>'
  echo '<script type="application/json" id="d-rmeta">';  cat data/interim/ui_rmeta.json;   echo; echo '</script>'
  echo '<script type="application/json" id="d-rdata">';  cat data/interim/ui_rdata.json;   echo; echo '</script>'
  echo '<script>'
  echo 'const D=JSON.parse(document.getElementById("d-model").textContent);'
  echo 'D.base=JSON.parse(document.getElementById("d-base").textContent);'
  echo 'D.raster=JSON.parse(document.getElementById("d-rmeta").textContent);'
  echo 'D.rasterData=JSON.parse(document.getElementById("d-rdata").textContent);'
  sed '1,6d' scripts/ui/con_js.js
  echo '</script>'
} > "$OUT"
echo "wrote $OUT ($(wc -c < "$OUT" | awk '{printf "%.2f MB", $1/1e6}'))"
