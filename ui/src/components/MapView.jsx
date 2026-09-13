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

export function bandOf(resp, thresholdS) {
  if (resp < 0) return 4;
  if (resp <= thresholdS) return 0;
  if (resp <= thresholdS + 120) return 1;
  if (resp <= thresholdS + 300) return 2;
  return 3;
}

function CoverageLayer({ cells, hex, response, thresholdS, gained, reachCells,
                        visible, onPick }) {
  const map = useMap();
  const layerRef = useRef(null);
  const polysRef = useRef([]);

  // Build once: the geometry never changes, only the fill.
  useEffect(() => {
    if (!cells || !hex) return;
    const group = L.layerGroup();
    const polys = new Array(cells.lat.length);
    for (let i = 0; i < cells.lat.length; i++) {
      const lat = cells.lat[i];
      const lon = cells.lon[i];
      const ring = hex.map(([dx, dy]) => [lat + dy, lon + dx]);
      const p = L.polygon(ring, {
        stroke: false,
        fillOpacity: 0.72,
        fillColor: "#6b6b6b",
        interactive: true,
      });
      p.on("click", () => onPick && onPick(i));
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
  }, [map, cells, hex, onPick]);

  // Restyle in place whenever the scenario, service, threshold or siting moves.
  useEffect(() => {
    const polys = polysRef.current;
    if (!polys.length || !response) return;
    for (let i = 0; i < polys.length; i++) {
      polys[i].setStyle({
        // Hand-placed reach outranks the solver's gain: when both apply, the
        // planner is looking at their own station and wants to see its work.
        fillColor: reachCells && reachCells.has(i)
          ? REACH.colour
          : gained && gained.has(i)
            ? GAINED.colour
            : BANDS[bandOf(response[i], thresholdS)].colour,
      });
    }
  }, [response, thresholdS, gained, reachCells]);

  useEffect(() => {
    const group = layerRef.current;
    if (!group) return;
    if (visible) group.addTo(map);
    else group.remove();
  }, [visible, map]);

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
      stroke: false, fillColor: "#070d12", fillOpacity: 0.58, interactive: false,
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
    if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [12, 12] });
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
  candidates,
  layers, placing, onMapClick, onPickCell,
}) {
  const wardRings = useMemo(
    () => (basemap ? Object.values(basemap.ward_rings) : null), [basemap]);
  const zoneRings = useMemo(
    () => (basemap ? Object.values(basemap.zone_rings) : null), [basemap]);

  const stationColour = (s) =>
    s.conf === "surveyed" ? "#1a9850" : s.conf === "gmaps" ? "#2c7fb8" : "#8856a7";

  return (
    <MapContainer
      center={CHENNAI}
      zoom={11}
      preferCanvas
      className="map"
      zoomControl
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
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
        visible={layers.coverage}
        onPick={onPickCell}
      />
      <VectorLayer
        rings={wardRings}
        visible={layers.wards}
        style={{ color: "#ffffff", weight: 1, opacity: 0.55 }}
      />
      <VectorLayer
        rings={zoneRings}
        visible={layers.zones}
        style={{ color: "#111111", weight: 2, opacity: 0.7 }}
      />
      <MarkerLayer
        points={stations}
        visible={layers.stations}
        radius={5}
        colour={stationColour}
        edge="#ffffff"
        popup={(s) =>
          `<b>${s.name}</b><br/>position: ${s.conf}` +
          (s.state ? `<br/>identity: ${s.state}` : "")}
      />
      <LatticeLayer points={candidates} visible={placing} />
      <MarkerLayer
        points={sites}
        visible={layers.sites}
        radius={8}
        colour="#f46d43"
        edge="#000000"
        popup={(s, i) => `<b>Proposed site ${i + 1}</b><br/>${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}`}
      />
      <ClickCapture enabled={placing} onMapClick={onMapClick} />
    </MapContainer>
  );
}
