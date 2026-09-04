"""Import a real basemap: fetch tiles, stitch, embed. Build step 19.

The console previously drew its own map from the project's vector layers,
because an artifact runs under a CSP that blocks external images -- a tile
request from the page silently fails, so Leaflet or MapLibre would load and then
have nothing to draw.

That constraint applies to the PAGE, not to this script. Tiles are fetched here,
stitched into one image, and embedded, so the console shows a real cartographic
basemap that happens to arrive as a single asset. Vector layers that are ANALYSIS
OUTPUT -- flood extents, coverage, stations -- stay vector and stay on top.

Web Mercator, not equirectangular. Tiles are Mercator, so the console's
projection has to match or the hexagons will not sit on the streets: over the
55 km of latitude this city spans the two disagree by roughly a kilometre.

Tiles: OpenStreetMap standard. Attribution is shown on the map.
"""
import io, json, math, sys, time
import requests
from PIL import Image, ImageEnhance, ImageOps

Z = 13
S, W, N, E = 12.78, 80.03, 13.32, 80.42
UA = {"User-Agent": "chennai-ers/0.1 (academic emergency-response siting study; VIT Chennai)"}
# OpenStreetMap's own tiles. CARTO's free endpoint stamps "API KEY REQUIRED"
# across every tile, which is unusable, and every other hosted style wanted a
# key. OSM's Tile Usage Policy asks for a real User-Agent, no bulk downloading
# and attribution: this is 130 tiles fetched ONCE, at two per second, for a
# single city, with attribution shown on the map.
TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
RATE_S = 0.5
DARK_TINT = (18, 30, 44)      # the dark variant is derived locally, not re-fetched


def merc(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat)))
         / math.pi) / 2 * n
    return x, y


def num2deg(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


x0f, y0f = merc(N, W, Z)
x1f, y1f = merc(S, E, Z)
X0, Y0, X1, Y1 = math.floor(x0f), math.floor(y0f), math.ceil(x1f), math.ceil(y1f)
nx, ny = X1 - X0, Y1 - Y0
print(f"zoom {Z}: {nx} x {ny} = {nx*ny} tiles -> {nx*256} x {ny*256} px")

# The stitched image covers whole tiles; record its exact corner bounds so the
# console can place it without guessing.
top_lat, left_lon = num2deg(X0, Y0, Z)
bot_lat, right_lon = num2deg(X1, Y1, Z)
meta = {"zoom": Z, "north": top_lat, "west": left_lon, "south": bot_lat, "east": right_lon,
        "width": nx * 256, "height": ny * 256, "projection": "web_mercator",
        "attribution": "© OpenStreetMap contributors"}

base = Image.new("RGB", (nx * 256, ny * 256), (241, 239, 233))
got = fail = 0
for ty in range(Y0, Y1):
    for tx in range(X0, X1):
        try:
            r = requests.get(TILE.format(z=Z, x=tx, y=ty), headers=UA, timeout=30)
            r.raise_for_status()
            base.paste(Image.open(io.BytesIO(r.content)).convert("RGB"),
                       ((tx - X0) * 256, (ty - Y0) * 256))
            got += 1
        except Exception:
            fail += 1
        time.sleep(RATE_S)
    print(f"  row {ty-Y0+1}/{ny}  ({got} tiles)", end="\r", flush=True)
print(f"  fetched {got} tiles, {fail} failed                    ")

# Dark variant, derived locally: invert luminance, then tint toward navy so the
# result sits with the console's palette instead of looking like a photo negative.
inv = ImageOps.invert(base)
dark = Image.blend(inv, Image.new("RGB", inv.size, DARK_TINT), 0.42)
dark = ImageEnhance.Color(dark).enhance(0.55)

out = {}
for name, im in (("light", base), ("dark", dark)):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72, optimize=True, progressive=True)
    path = f"data/raw/basemap_{name}_z{Z}.jpg"
    open(path, "wb").write(buf.getvalue())
    out[name] = path
    print(f"  {name}: {path}  {len(buf.getvalue())/1e6:.2f} MB")

meta["files"] = out
json.dump(meta, open("data/interim/basemap_raster_meta.json", "w"), indent=1)
print(json.dumps(meta, indent=1))
