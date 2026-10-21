// The map. Leaflet is driven imperatively from inside react-leaflet rather than
// through React children, and that is deliberate: the coverage layer is 3,838
// hexagons that restyle on every threshold tick, and putting 3,838 components
// through the reconciler to change a fill colour makes the slider stutter. The
// hexagons are created once and `setStyle`d in place; React owns the chrome.
import { useEffect, useMemo, useRef } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";

const CHENNAI = [13.06, 80.24];

// Response bands, relative to the threshold the planner is asking about. The
// top band is "covered"; the rest say how badly the cell misses, because "not
// covered" is a different fact from "unreachable at any budget".
export const BANDS = [
  { key: "covered", label: "In time", colour: "#34a36b" },
  { key: "near", label: "2 min late", colour: "#e0b13c" },
  { key: "late", label: "5 min late", colour: "#df7a35" },
  { key: "beyond", label: "Further", colour: "#d0495c" },
  { key: "unreachable", label: "No route", colour: "#5d6b76" },
];

// Cells the proposed stations would add. A separate colour rather than the
// "covered" green, because this is a projection and the green is a measurement.
export const GAINED = { label: "Gained", colour: "#4aa8e8" };

// Ground a HAND-PLACED station would newly reach. Distinct from GAINED because
// they answer different questions — GAINED is what the optimiser's whole plan
// adds, this is what one station the planner chose adds on its own — and a
// planner comparing their own placement against the solver needs to tell them
// apart at a glance.
export const REACH = { label: "Your station reaches", colour: "#b07ae0" };

// Cells a road condition takes out of the standard, in the compare view. The
// band red, because it is the same fact the red already means -- people left
// outside the clock -- narrowed to the ones this condition put there.
export const LOST = { colour: "#ff5a76" };

// How each station's position was established. Solid is a mapped feature,
// hollow is a business listing that may name the wrong station (E-11g): the
// certainty is drawn as fill rather than hue so it never competes with the
// coverage ramp underneath.
export const STATION_SOURCES = [
  { key: "surveyed", label: "Surveyed", fill: "#ffffff" },
  { key: "mapped", label: "Mapped in OpenStreetMap", fill: "#c9d6e0" },
  { key: "listing", label: "Google Maps listing", fill: "#15171a" },
];

export function stationSource(s) {
  if (s.conf === "surveyed") return STATION_SOURCES[0];
  if (String(s.conf).startsWith("osm")) return STATION_SOURCES[1];
  return STATION_SOURCES[2];
}

// Module-level on purpose: MarkerLayer rebuilds its markers whenever these
// change identity, and as inline arrows they changed on every render -- every
// tick of the threshold slider tore down and re-created all 39 stations.
const stationFill = (s) => stationSource(s).fill;
const stationPopup = (s) =>
  `<b>${s.name}</b><br/>Position: ${stationSource(s).label}`;

// Each cell is drawn with one mean hexagon, not its own H3 ring, so the tiling
// is not exact: hairline slivers open between neighbours and the dark ground
// showed through them as fine diagonal hatching across the whole city. The
// fill is pre-blended against the ground and drawn opaque, with a hairline
// stroke in the same colour that closes the slivers -- and the see-through is
// done ONCE, on the whole coverage pane (CoverageVeil), so streets and names
// show through evenly without any seam being painted twice.
const GROUND = [27, 29, 32];
const blendCache = new Map();
function blend(hex, alpha) {
  const q = Math.round(alpha * 40) / 40;
  const key = hex + q;
  let out = blendCache.get(key);
  if (!out) {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    const m = c.map((v, i) => Math.round(GROUND[i] + q * (v - GROUND[i])));
    out = `rgb(${m[0]},${m[1]},${m[2]})`;
    blendCache.set(key, out);
  }
  return out;
}

export function bandOf(resp, thresholdS) {
  if (resp < 0) return 4;
  if (resp <= thresholdS) return 0;
  if (resp <= thresholdS + 120) return 1;
  if (resp <= thresholdS + 300) return 2;
  return 3;
}

const COVERAGE_PANE = "coverage";

// How see-through the coverage is. Zooming in is what someone does when they
// are looking for a particular street, so the colours step back as the map
// comes forward; "Streets" drops them further at any zoom. Applied to the pane,
// not the cells, so every hexagon fades together.
export function veilFor(zoom, streets) {
  if (streets) return 0.18;
  if (zoom <= 11) return 0.72;
  if (zoom === 12) return 0.62;
  if (zoom === 13) return 0.52;
  if (zoom === 14) return 0.44;
  return 0.38;
}

function CoverageVeil({ streets }) {
  const map = useMap();
  useEffect(() => {
    const apply = () => {
      const pane = map.getPane(COVERAGE_PANE);
      if (pane) pane.style.opacity = String(veilFor(map.getZoom(), streets));
    };
    apply();
    map.on("zoomend", apply);
    // The pane is created by CoverageLayer once cells arrive; catch that too.
    map.on("layeradd", apply);
    return () => { map.off("zoomend", apply); map.off("layeradd", apply); };
  }, [map, streets]);
  return null;
}

function CoverageLayer({ cells, hex, response, thresholdS, gained, reachCells,
                        lost, visible }) {
  const map = useMap();
  const layerRef = useRef(null);
  const polysRef = useRef([]);

  // Brightness is people. A hexagon of paddy and a hexagon of Washermanpet are
  // the same size on the map and not the same problem, so each cell's opacity
  // rises with the square root of its population (capped at the 95th
  // percentile, so a handful of dense cells cannot wash out the rest). Colour
  // still says how late; brightness now says how many.
  const alphaRef = useRef(null);
  useEffect(() => {
    if (!cells) return;
    const pop = cells.pop;
    const sorted = [...pop].sort((a, b) => a - b);
    const p95 = Math.max(1, sorted[Math.floor(0.95 * (sorted.length - 1))]);
    alphaRef.current = Float32Array.from(pop, (p) =>
      0.42 + 0.5 * Math.sqrt(Math.min(1, p / p95)));
  }, [cells]);

  // Build once: the geometry never changes, only the fill. The cells get a
  // pane and canvas of their own so the veil can fade them as one layer.
  useEffect(() => {
    if (!cells || !hex) return;
    if (!map.getPane(COVERAGE_PANE)) {
      map.createPane(COVERAGE_PANE).style.zIndex = 390;   // under outlines and pins
    }
    const renderer = L.canvas({ pane: COVERAGE_PANE, padding: 0.3 });
    const group = L.layerGroup();
    const polys = new Array(cells.lat.length);
    for (let i = 0; i < cells.lat.length; i++) {
      const lat = cells.lat[i];
      const lon = cells.lon[i];
      const ring = hex.map(([dx, dy]) => [lat + dy, lon + dx]);
      const p = L.polygon(ring, {
        renderer,
        pane: COVERAGE_PANE,
        stroke: true,
        weight: 1,
        opacity: 1,
        fillOpacity: 0.72,
        fillColor: "#6b6b6b",
        // Not interactive, and no listener: CellPicker answers the click. See
        // the note there for why the grid must not be hit-tested by Leaflet.
        interactive: false,
      });
      polys[i] = p;
      group.addLayer(p);
    }
    polysRef.current = polys;
    layerRef.current = group;
    group.addTo(map);
    return () => {
      group.remove();
      polysRef.current = [];
    };
  }, [map, cells, hex]);

  // Restyle in place whenever the scenario, service, threshold or siting moves.
  useEffect(() => {
    const polys = polysRef.current;
    if (!polys.length || !response) return;
    // Compare view: only what the condition took is drawn at strength. What it
    // left inside the clock is a faint green, and ground outside the clock
    // either way is nearly withdrawn -- it is not this condition's doing.
    const alpha = alphaRef.current;
    const a = (i) => (alpha ? alpha[i] : 0.72);
    if (lost) {
      for (let i = 0; i < polys.length; i++) {
        const r = response[i];
        const now = r >= 0 && r <= thresholdS;
        const c = lost.has(i)
          ? blend(LOST.colour, Math.max(0.6, a(i)))
          : now
            ? blend(BANDS[0].colour, 0.32 * a(i))
            : blend("#5c636b", 0.22);
        polys[i].setStyle({ fillOpacity: 1, fillColor: c, color: c });
      }
      return;
    }
    for (let i = 0; i < polys.length; i++) {
      // Hand-placed reach outranks the solver's gain: when both apply, the
      // planner is looking at their own station and wants to see its work.
      const base = reachCells && reachCells.has(i)
        ? REACH.colour
        : gained && gained.has(i)
          ? GAINED.colour
          : BANDS[bandOf(response[i], thresholdS)].colour;
      const c = blend(base, a(i));
      polys[i].setStyle({ fillOpacity: 1, fillColor: c, color: c });
    }
  }, [response, thresholdS, gained, reachCells, lost]);

  useEffect(() => {
    const group = layerRef.current;
    if (!group) return;
    if (visible) group.addTo(map);
    else group.remove();
  }, [visible, map]);

  return null;
}

// Even-odd ray cast against the hexagon painted at (clat, clon) -- the same test
// L.Polygon applied to decide whether a click was on it.
function inHex(hex, clat, clon, lat, lon) {
  let inside = false;
  for (let a = 0, b = hex.length - 1; a < hex.length; b = a++) {
    const x1 = clon + hex[a][0], y1 = clat + hex[a][1];
    const x2 = clon + hex[b][0], y2 = clat + hex[b][1];
    if ((y1 > lat) !== (y2 > lat) &&
        lon < ((x2 - x1) * (lat - y1)) / (y2 - y1) + x1) inside = !inside;
  }
  return inside;
}

// Which hexagon was clicked. This used to be 3,838 interactive polygons with a
// listener each, which is the expensive way to ask: canvas has no per-shape hit
// testing, so Leaflet emulates it by walking every interactive layer on the
// renderer -- on click, and again on every mousemove to decide the cursor. That
// walk is the whole grid and it does not stop at the first hit, so the cost was
// paid continuously, by everyone, to serve the occasional click.
//
// Asking once, on click, costs a pass over two flat arrays. The pass is not a
// nearest-centroid guess: a hexagon can only contain the click if its centre
// lies within the circumradius, so that distance is a COMPLETE filter, and the
// one or two cells that survive it get the same ray cast the polygons got.
// Nearest-centroid alone would be within a metre of right, but it disagrees
// with the old answer on about one click in 160 -- always within ~3 m of a
// shared edge, because each cell is painted with ONE mean hexagon rather than
// its own H3 ring, so the painted tiling overlaps slightly at the seams.
//
// Distances use the locally-scaled space App uses to snap a placement to the
// candidate lattice: longitude degrees narrowed by cos(lat), which over the
// ~0.25 deg the city spans is constant to within a rounding.
function CellPicker({ cells, hex, visible, onPick }) {
  const map = useMap();
  useEffect(() => {
    if (!cells || !hex || !visible || !onPick) return undefined;
    const handler = (e) => {
      const lat = e.latlng.lat, lon = e.latlng.lng;
      const k = Math.cos((lat * Math.PI) / 180);
      // Read off the geometry rather than hardcoded, so a change of grid
      // resolution stays correct here.
      let limit = 0;
      for (const [dx, dy] of hex) {
        const d = dx * k * dx * k + dy * dy;
        if (d > limit) limit = d;
      }
      // Last match wins, as it did when the canvas renderer walked the layers
      // in draw order. It decides only the seam overlaps described above.
      let hit = -1;
      for (let i = 0; i < cells.lat.length; i++) {
        const dy = cells.lat[i] - lat, dx = (cells.lon[i] - lon) * k;
        if (dx * dx + dy * dy > limit) continue;
        if (inHex(hex, cells.lat[i], cells.lon[i], lat, lon)) hit = i;
      }
      if (hit >= 0) onPick(hit);
    };
    map.on("click", handler);
    return () => map.off("click", handler);
  }, [map, cells, hex, visible, onPick]);
  return null;
}

// A ward or zone is a LIST OF PARTS, not a ring: islands, and areas split by a
// river or the port, are separate closed rings under one id. Drawing the outer
// list as if it were a single ring joins those parts with a straight line across
// the city, which is how the first build grew a diagonal streak through Chennai.
// Everything outside the study area is dimmed to half-dark. Without this, land
// the profile does not model looks identical to land it models and found empty —
// and the first question anyone asks of the map is "why is there a gap there".
function ScopeMask({ outline, visible }) {
  const map = useMap();
  useEffect(() => {
    if (!outline || !outline.length || !visible) return undefined;
    const world = [[-85, -180], [-85, 180], [85, 180], [85, -180]];
    const holes = [];
    for (const part of outline) {
      const ring = Array.isArray(part[0]) && typeof part[0][0] === "number"
        ? part : part.flat();
      holes.push(ring.map(([lon, lat]) => [lat, lon]));
    }
    const mask = L.polygon([world, ...holes], {
      stroke: false, fillColor: "#0e0f11", fillOpacity: 0.62, interactive: false,
    }).addTo(map);
    const edge = L.polygon(holes, {
      fill: false, color: "#8fb6d0", weight: 1.25, opacity: 0.5, interactive: false,
    }).addTo(map);
    return () => { mask.remove(); edge.remove(); };
  }, [map, outline, visible]);
  return null;
}

function VectorLayer({ rings, style, visible, pane }) {
  const map = useMap();
  useEffect(() => {
    if (!rings || !visible) return undefined;
    const group = L.layerGroup();
    for (const parts of rings) {
      for (const ring of parts) {
        group.addLayer(L.polyline(ring.map(([lon, lat]) => [lat, lon]), { ...style, pane }));
      }
    }
    group.addTo(map);
    return () => group.remove();
  }, [map, rings, style, visible, pane]);
  return null;
}

// Open on the city, not on a guessed centre: the GCC outline is in the basemap
// artefact, so the first view is exactly the study area.
function FitToCity({ outline }) {
  const map = useMap();
  useEffect(() => {
    if (!outline || !outline.length) return;
    const pts = outline.flat().map(([lon, lat]) => [lat, lon]);
    // Fitted into the gap the panels leave: the card owns the right edge and
    // the clock the bottom-left, so centring on the window put the city under
    // the card.
    const wide = map.getContainer().clientWidth > 900;
    if (pts.length) map.fitBounds(L.latLngBounds(pts), wide
      ? { paddingTopLeft: [40, 24], paddingBottomRight: [380, 110] }
      : { padding: [12, 12] });
  }, [map, outline]);
  return null;
}

// Where a station is ALLOWED to go. Shown only while placing, because the answer
// to "why did my pin move" is that stations sit on an 800 m candidate lattice and
// a click snaps to the nearest one — which is impossible to guess if the lattice
// is invisible. With the dots on screen you aim at a site instead of at a street.
function LatticeLayer({ points, visible }) {
  const map = useMap();
  useEffect(() => {
    if (!points || !visible) return undefined;
    const group = L.layerGroup();
    for (const p of points) {
      group.addLayer(L.circleMarker([p.lat, p.lon], {
        radius: 2.5,
        weight: 1,
        color: "rgba(233,238,243,0.85)",
        fillColor: "#e9eef3",
        fillOpacity: 0.5,
        interactive: false,
      }));
    }
    group.addTo(map);
    return () => group.remove();
  }, [map, points, visible]);
  return null;
}

function MarkerLayer({ points, visible, radius, colour, edge, popup }) {
  const map = useMap();
  useEffect(() => {
    if (!points || !visible) return undefined;
    const group = L.layerGroup();
    points.forEach((p, i) => {
      const m = L.circleMarker([p.lat, p.lon ?? p.lng], {
        radius,
        weight: 2,
        color: edge,
        fillColor: typeof colour === "function" ? colour(p) : colour,
        fillOpacity: 0.95,
      });
      if (popup) m.bindPopup(popup(p, i));
      group.addLayer(m);
    });
    group.addTo(map);
    return () => group.remove();
  }, [map, points, visible, radius, colour, edge, popup]);
  return null;
}

// Sites as numbered pins. The readout lists them 1..n by coordinate, and a list
// of coordinates beside a cluster of identical dots leaves the reader to work
// out which is which; the number on the pin is the same number as the row, so
// the map and the list can be read against each other. Hand-placed and solved
// sites are numbered separately, as the readout numbers them, and coloured
// apart because they answer different questions.
function SiteLayer({ points, visible }) {
  const map = useMap();
  useEffect(() => {
    if (!points || !visible) return undefined;
    const group = L.layerGroup();
    points.forEach((p) => {
      const placed = p.kind === "placed";
      const m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({
          className: `site-pin${placed ? " placed" : p.kind === "post" ? " post" : ""}`,
          html: `<span>${p.label}</span>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        }),
        keyboard: false,
      });
      const title = placed ? "Your site" : p.kind === "post" ? "Peak-hour post" : "Proposed site";
      m.bindPopup(`<b>${title} ${p.label}</b>` +
                  `<br/>${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}`);
      group.addLayer(m);
    });
    group.addTo(map);
    return () => group.remove();
  }, [map, points, visible]);
  return null;
}

// Where the reader asked the map to look: an area picked from the readout's
// table, or a proposed site picked from its list. A table row that names
// "Ward 188" with no way to find it on a map of 200 wards is half an answer.
//
// The bounds come from the area's own demand cells rather than its outline, so
// this works in every study area -- the wider profiles report H3 units that have
// no ward geometry at all. The outline is drawn where one exists.
function FocusLayer({ focus }) {
  const map = useMap();
  useEffect(() => {
    if (!focus) return undefined;
    if (focus.kind === "site") {
      map.flyTo([focus.lat, focus.lon], Math.max(map.getZoom(), 14), { duration: 0.6 });
      const ring = L.circleMarker([focus.lat, focus.lon], {
        radius: 18, weight: 2, color: "#ffffff", fill: false,
        dashArray: "4 4", interactive: false,
      }).addTo(map);
      return () => ring.remove();
    }
    if (!focus.points?.length) return undefined;
    // The rail and readout float over the map on a wide screen, so the area is
    // fitted into the gap between them rather than behind them.
    const wide = map.getContainer().clientWidth > 1080;
    map.flyToBounds(L.latLngBounds(focus.points), {
      duration: 0.6, maxZoom: 15,
      paddingTopLeft: wide ? [330, 60] : [30, 30],
      paddingBottomRight: wide ? [340, 90] : [30, 30],
    });
    const group = L.layerGroup();
    for (const ring of focus.rings ?? []) {
      group.addLayer(L.polyline(ring.map(([lon, lat]) => [lat, lon]), {
        color: "#ffffff", weight: 2.5, opacity: 0.95, interactive: false,
      }));
    }
    group.addTo(map);
    return () => group.remove();
  }, [map, focus]);
  return null;
}

function ClickCapture({ enabled, onMapClick }) {
  const map = useMap();
  useEffect(() => {
    if (!enabled) return undefined;
    const handler = (e) => onMapClick(e.latlng.lat, e.latlng.lng);
    map.on("click", handler);
    L.DomUtil.addClass(map.getContainer(), "placing");
    return () => {
      map.off("click", handler);
      L.DomUtil.removeClass(map.getContainer(), "placing");
    };
  }, [map, enabled, onMapClick]);
  return null;
}

export default function MapView({
  cells, hex, response, thresholdS, gained, reachCells, basemap, stations, sites,
  candidates, focus, lost, streets,
  layers, placing, onMapClick, onPickCell,
}) {
  const wardRings = useMemo(
    () => (basemap ? Object.values(basemap.ward_rings) : null), [basemap]);
  const zoneRings = useMemo(
    () => (basemap ? Object.values(basemap.zone_rings) : null), [basemap]);

  return (
    <MapContainer
      center={CHENNAI}
      zoom={11}
      preferCanvas
      className="map"
      zoomControl
    >
      {/* OpenStreetMap's standard tiles, darkened in CSS (.map .leaflet-tile-pane)
        * rather than swapped for a hosted dark style: the hosted ones now want
        * an API key, and a basemap that can stop rendering on someone else's
        * billing decision is not one to build a demo on. updateWhenZooming /
        * keepBuffer: see 7c82ee6 -- a stalled tile stacks every level a zoom
        * passed through. */}
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
        updateWhenZooming={false}
        keepBuffer={1}
      />
      <FitToCity outline={basemap?.outline} />
      <ScopeMask outline={basemap?.outline} visible={layers.coverage} />
      <CoverageLayer
        cells={cells}
        hex={hex}
        response={response}
        thresholdS={thresholdS}
        gained={gained}
        reachCells={reachCells}
        lost={lost}
        visible={layers.coverage}
      />
      <CoverageVeil streets={streets} />
      <CellPicker
        cells={cells}
        hex={hex}
        visible={layers.coverage}
        onPick={onPickCell}
      />
      <VectorLayer
        rings={wardRings}
        visible={layers.wards}
        style={{ color: "#eeeae2", weight: 0.8, opacity: 0.3 }}
      />
      <VectorLayer
        rings={zoneRings}
        visible={layers.zones}
        style={{ color: "#eeeae2", weight: 1.4, opacity: 0.38 }}
      />
      <MarkerLayer
        points={stations}
        visible={layers.stations}
        radius={5}
        colour={stationFill}
        edge="#ffffff"
        popup={stationPopup}
      />
      <LatticeLayer points={candidates} visible={placing} />
      <SiteLayer points={sites} visible={layers.sites} />
      <FocusLayer focus={focus} />
      <ClickCapture enabled={placing} onMapClick={onMapClick} />
    </MapContainer>
  );
}
