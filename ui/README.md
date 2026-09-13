# The coverage console

React 18 + Leaflet 1.9 on Vite. It is a client of `src/ers/api`, and it holds no
model of its own: every number on screen arrives from the service, which in turn
serves what `make all` produced. There is no fixture mode and no offline demo
data — if the API cannot answer, the console says so rather than drawing
something plausible.

```bash
make ui        # npm ci && vite build  ->  ui/dist, which the API serves at /
make api       # uvicorn on :8000
```

Working on the front end:

```bash
make api       # terminal 1: the real service on :8000
make ui-dev    # terminal 2: vite on :5173, proxying /api to it
```

## Layout

```
src/App.jsx              state, data fetching, the questions the user can ask
src/api.js               the only place that talks to the service
src/components/
  MapView.jsx            Leaflet: coverage hexes, wards, zones, stations, sites
  Controls.jsx           service, scenario, threshold, k, manual placement, layers
  Summary.jsx            coverage, siting result, worst wards, publication basis
```

## Two decisions worth knowing

**Leaflet is driven imperatively.** The coverage layer is 3,838 hexagons that
restyle on every tick of the threshold slider. They are created once and
`setStyle`d in place rather than rendered as 3,838 React elements, because the
reconciler is the wrong tool for a per-frame fill change. React owns the chrome;
Leaflet owns the canvas.

**A manual placement snaps to a candidate.** Clicking the map in placement mode
picks the nearest candidate site, not the raw lat/lon. A station can only go
where the candidate lattice says one could go, and inventing an off-network
point would produce a coverage figure the optimiser could never reproduce.
