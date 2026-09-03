"""Fetch WorldPop, clip to Chennai, discard the national raster. Build step 02.

WorldPop's server does not support HTTP range requests, so a remote windowed
read is impossible and the full 506 MB national raster must be downloaded. It is
deleted immediately after clipping; its SHA-256 stays in the registry so the
clip remains provenance-traceable without keeping half a gigabyte on disk.

The CONSTRAINED product is used deliberately: the unconstrained one dasymetrically
spreads population across whole census units and is documented to misallocate
10-20% of people into unsettled cells -- a material bias in exactly the
peripheral, marshy wards this project cares about (Finding F-08).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
import numpy as np
import rasterio
import requests
import yaml
from rasterio.windows import from_bounds

from ers.hashing import sha256_file
from ers.io.registry import DatasetRegistry

URL = ("https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/"
       "2020/BSGM/IND/ind_ppp_2020_constrained.tif")
NAT = Path("data/raw/ind_ppp_2020_constrained.tif")
CLIP = Path("data/raw/worldpop_chennai_2020_constrained.tif")

cfg = yaml.safe_load(open("config/city/chennai.yml"))
south, west, north, east = cfg["bbox"]

if not CLIP.exists():
    if not NAT.exists():
        raise SystemExit(
            "national raster missing -- run scripts/fetch_worldpop.sh first.\n"
            "The download is a separate resumable shell step because WorldPop's\n"
            "server stalls mid-transfer; curl -C - resumes, a streaming client does not."
        )
    digest = sha256_file(NAT)
    print(f"national raster present, sha256={digest[:16]}", flush=True)

    with rasterio.open(NAT) as src:
        print(f"national: {src.shape} res={[round(x,7) for x in src.res]} "
              f"crs={src.crs} nodata={src.nodata}", flush=True)
        win = from_bounds(west, south, east, north, src.transform)
        arr = src.read(1, window=win)
        prof = src.profile.copy()
        prof.update(height=arr.shape[0], width=arr.shape[1],
                    transform=src.window_transform(win),
                    compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(CLIP, "w", **prof) as dst:
        dst.write(arr, 1)
    print(f"clipped -> {CLIP}", flush=True)

    DatasetRegistry().register(
        source="worldpop_ind_constrained_2020", uri=URL, local_path=NAT,
        licence="CC-BY 4.0 (WorldPop)",
        notes={"product": "Global_2000_2020_Constrained BSGM",
               "note": "national raster deleted after clipping; checksum retained"})
    NAT.unlink()
    print("deleted national raster (checksum retained in registry)", flush=True)

with rasterio.open(CLIP) as src:
    arr = src.read(1)
    nod = src.nodata
    mask = np.isfinite(arr) & (arr > 0)
    if nod is not None:
        mask &= arr != nod
    rep = {
        "shape": list(arr.shape),
        "resolution_deg": [round(x, 7) for x in src.res],
        "crs": str(src.crs),
        "nodata": None if nod is None else float(nod),
        "cells_total": int(arr.size),
        "cells_populated": int(mask.sum()),
        "population_sum": round(float(arr[mask].sum()), 1),
        "max_cell": round(float(arr[mask].max()), 2),
        "clip_bytes": CLIP.stat().st_size,
    }
DatasetRegistry().register(
    source="worldpop_chennai_clip", uri=f"clip://{URL}", local_path=CLIP,
    licence="CC-BY 4.0 (WorldPop)", notes=rep)
print(json.dumps(rep, indent=2), flush=True)
json.dump(rep, open("data/interim/worldpop_report.json", "w"), indent=2, sort_keys=True)
