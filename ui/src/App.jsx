import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import MapView, { BANDS, GAINED, LOST, REACH, STATION_SOURCES, stationSource }
  from "./components/MapView.jsx";

// How far a click may be from a buildable site before it is refused. Candidates
// sit on an 800 m lattice (A-12) and the worst in-city gap to one is ~2.2 km, so
// 3 km accepts every click inside the study area and rejects the ones that are
// really asking for a station in the sea.
const SNAP_LIMIT_M = 3000;
import { SCENARIO_LABEL, SHORT } from "./components/scenarios.js";
import Brief from "./components/Brief.jsx";
import Card from "./components/Card.jsx";
import Dial, { clock } from "./components/Dial.jsx";
import Ribbon from "./components/Ribbon.jsx";
import Tour, { STEPS } from "./components/Tour.jsx";
import Evidence from "./components/Evidence.jsx";

export default function App() {
  const [meta, setMeta] = useState(null);
  const [cells, setCells] = useState(null);
  const [basemap, setBasemap] = useState(null);
  const [stations, setStations] = useState(null);
  const [candidates, setCandidates] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [nearest, setNearest] = useState(null);
  const [error, setError] = useState(null);

  const [profile, setProfile] = useState("gcc");
  const [briefOpen, setBriefOpen] = useState(true);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [profileCoverage, setProfileCoverage] = useState({});
  const [profiles, setProfiles] = useState([]);
  const [service, setService] = useState("ems");
  const [scenario, setScenario] = useState("dry");
  const [thresholdS, setThresholdS] = useState(300);
  const [k, setK] = useState(3);
  const [forced, setForced] = useState([]);
  const [placing, setPlacing] = useState(false);
  const [snap, setSnap] = useState(null);
  const [reach, setReach] = useState(null);
  const [reaching, setReaching] = useState(false);
  const [result, setResult] = useState(null);
  const [optimising, setOptimising] = useState(false);
  const [picked, setPicked] = useState(null);
  const [focus, setFocus] = useState(null);
  // "station" sites buildings on land-feasible parcels; "staging" sites
  // peak-hour ambulance posts anywhere on the road lattice (step 15b). Two
  // candidate tables with two index spaces -- every id below is read against
  // the table of the current mode, never the other one.
  const [mode, setMode] = useState("station");
  // Paint only what the current road condition takes from a dry day.
  const [comparing, setComparing] = useState(false);
  const [comparison, setComparison] = useState(null);
  const [staging, setStaging] = useState(null);
  const [scenarioShares, setScenarioShares] = useState({});
  const [scenariosLoading, setScenariosLoading] = useState(false);
  const [tab, setTab] = useState("overview");
  // null when no tour is running; otherwise the step on screen.
  const [tourStep, setTourStep] = useState(null);
  const [layers, setLayers] = useState({
    coverage: true, stations: true, sites: true, wards: false, zones: true,
  });

  useEffect(() => {
    // Smallest study area first: the switcher then reads as zooming out, which
    // is what changing it actually does.
    api.profiles()
      .then((r) => setProfiles([...r.profiles].sort((a, b) => a.area_km2 - b.area_km2)))
      .catch(() => {});
  }, []);

  // Everything that does not depend on the current question — but it DOES depend
  // on the study area, so switching profile reloads the lot rather than leaving
  // one city's hexagons under another city's numbers.
  useEffect(() => {
    setMeta(null); setCells(null); setBasemap(null); setStations(null);
    setCoverage(null); setResult(null); setForced([]); setPicked(null);
    setFocus(null);
    Promise.all([api.meta(profile), api.cells(profile), api.basemap(profile),
                 api.stations(profile)])
      .then(([m, c, b, s]) => {
        setMeta(m);
        setCells(c);
        setBasemap(b);
        setStations(s.stations);
        setThresholdS(m.services.ems.budget_s);
        setScenario("dry");
      })
      .catch((e) => setError(String(e)));
  }, [profile]);

  // The service's own budget is the honest default whenever the service changes.
  useEffect(() => {
    if (!profiles.length) return;
    Promise.all(profiles.filter((p) => p.built).map((p) =>
      api.coverage("ems", "dry", 300, p.profile)
        .then((c) => [p.profile, { covered_share: c.covered_share,
                                   total_demand: c.total_demand }])
        .catch(() => null)))
      .then((pairs) => setProfileCoverage(Object.fromEntries(pairs.filter(Boolean))));
  }, [profiles]);

  useEffect(() => {
    if (!meta) return;
    setThresholdS(meta.services[service].budget_s);
    setResult(null);
    setForced([]);
    setMode("station");
    setStaging(null);
    // Absent is an answer, not an error: fire engines are not staged, and the
    // wider study areas have no step 15b build.
    api.staging(service, profile).then(setStaging).catch(() => setStaging(null));
    api.candidates(service, profile).then((c) => setCandidates(c.candidates)).catch(() => {});
  }, [service, meta, profile]);

  // A siting result belongs to the network state it was solved on. Keeping it on
  // screen after the scenario changes would paint dry-day gains over a flooded
  // map, which is precisely the comparison this project exists to prevent.
  useEffect(() => {
    setResult(null);
  }, [scenario]);

  // The compare view has nothing to compare on a dry day, and it answers one
  // question at one clock: it is refetched whenever either moves.
  useEffect(() => {
    if (scenario === "dry") { setComparing(false); setComparison(null); return; }
    if (!comparing || !meta) { setComparison(null); return; }
    let live = true;
    api.compare(service, scenario, thresholdS, profile)
      .then((c) => live && setComparison(c))
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [comparing, scenario, service, thresholdS, profile, meta]);

  const lostCells = useMemo(
    () => (comparing && comparison ? new Set(comparison.lost_cells) : null),
    [comparing, comparison]);

  // Which station sources this inventory actually has, for the key.
  const stationKinds = useMemo(() => {
    if (!stations) return [];
    const seen = new Set(stations.map((s) => stationSource(s).key));
    return STATION_SOURCES.filter((k) => seen.has(k.key));
  }, [stations]);

  // Posts are solved on one network. Leaving it leaves posting mode, rather
  // than solving posts against a road state they were never measured on.
  useEffect(() => {
    if (mode === "staging" && staging && scenario !== staging.scenario) setMode("station");
  }, [scenario, mode, staging]);

  // Hand-placed ids and a solve belong to one candidate table.
  useEffect(() => {
    setForced([]);
    setResult(null);
  }, [mode]);

  const chooseMode = useCallback((m) => {
    if (m === "staging" && staging) setScenario(staging.scenario);
    setMode(m);
  }, [staging]);

  const siteTable = mode === "staging" ? staging?.candidate_positions : candidates;

  useEffect(() => {
    if (!meta) return;
    let live = true;
    api.coverage(service, scenario, thresholdS, profile)
      .then((c) => live && setCoverage(c))
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [meta, service, scenario, thresholdS, profile]);

  useEffect(() => {
    if (!meta) return;
    api.nearest(service, scenario, profile).then(setNearest).catch(() => setNearest(null));
  }, [meta, service, scenario, profile]);

  // Every road state this service has, measured once so they can be read
  // against each other. Held at the SERVICE BUDGET rather than the threshold
  // slider on purpose: it is a comparison between networks, and a comparison
  // whose axis moves while you drag is not one. It also keeps this off the
  // slider's hot path — six responses per tick would make the clock stutter.
  useEffect(() => {
    if (!meta) return;
    const list = meta.services[service]?.scenarios ?? [];
    const budget = meta.services[service].budget_s;
    let live = true;
    setScenariosLoading(true);
    setScenarioShares({});
    Promise.all(list.map((sc) =>
      api.coverage(service, sc, budget, profile)
        .then((c) => [sc, c.covered_share])
        .catch(() => null)))
      .then((pairs) => {
        if (!live) return;
        setScenarioShares(Object.fromEntries(pairs.filter(Boolean)));
        setScenariosLoading(false);
      });
    return () => { live = false; };
  }, [meta, service, profile]);

  // What the hand-placed stations reach. Asked for explicitly rather than
  // fetched with every click: it is a different question from "how much does the
  // plan gain", and a planner asks it about their own placement, not the solve.
  const showReach = useCallback(async () => {
    if (!forced.length) return;
    setReaching(true);
    setError(null);
    try {
      setReach(await api.reach(service, forced, scenario, profile, mode));
    } catch (e) {
      setError(String(e));
      setReach(null);
    } finally {
      setReaching(false);
    }
  }, [forced, service, scenario, profile, mode]);

  // A reach answer belongs to one set of placed sites under one service and one
  // road state. Any of those moving makes it a picture of something else, so it
  // is dropped rather than left on screen looking current.
  useEffect(() => { setReach(null); }, [forced, service, scenario, profile]);

  // Overrides let the tour solve in the same tick it changes the question;
  // read from state alone, it would solve the question it is leaving.
  const optimise = useCallback(async (over = {}) => {
    setOptimising(true);
    setError(null);
    try {
      setResult(await api.optimise({ profile, service, scenario, k, forced,
                                     mode, exact_solve: true, ...over }));
    } catch (e) {
      setError(String(e));
    } finally {
      setOptimising(false);
    }
  }, [profile, service, scenario, k, forced, mode]);

  // Manual placement: snap the click to the nearest candidate site, because a
  // station can only go where the candidate lattice says a station can go --
  // inventing an off-network point would produce a coverage figure the
  // optimiser could never reproduce.
  // The snap is not optional, but it used to be invisible: the pin appeared
  // somewhere other than where you clicked, a median 447 m away and sometimes
  // 2 km, with nothing on screen saying why. The lattice is now drawn while
  // placing (you click a site you can see), the distance is reported, and a
  // click nowhere near a candidate is REFUSED rather than teleporting the pin
  // across the city to whatever happened to be nearest.
  const onMapClick = useCallback((lat, lon) => {
    if (!siteTable) return;
    let best = -1;
    let bestD = Infinity;
    for (let j = 0; j < siteTable.length; j++) {
      const dy = siteTable[j].lat - lat;
      const dx = (siteTable[j].lon - lon) * Math.cos((lat * Math.PI) / 180);
      const d = dy * dy + dx * dx;
      if (d < bestD) { bestD = d; best = j; }
    }
    if (best < 0) return;
    const metres = Math.round(Math.sqrt(bestD) * 111320);
    if (metres > SNAP_LIMIT_M) {
      setSnap({ ok: false, metres });
      return;
    }
    setSnap({ ok: true, metres, name: null });
    setForced((f) => (f.includes(best) ? f.filter((x) => x !== best) : [...f, best]));
  }, [siteTable]);

  const onPickCell = useCallback((i) => setPicked(i), []);

  const worstWards = useMemo(() => {
    if (!coverage || !meta) return [];
    return Object.entries(coverage.by_ward)
      .map(([id, row]) => ({
        id: Number(id),
        no: meta.wards[id]?.name
            ?? (meta.wards[id]?.no != null ? `Ward ${meta.wards[id].no}` : id),
        zone: (meta.wards[id]?.zone ?? "").replace(/_/g, " ").replace("OUTSIDE GCC", "outside GCC"),
        share: row.covered_share,
        demand: row.demand,
        fastest: row.fastest_s,
      }))
      .filter((w) => w.demand > 0)
      // Ties at 0% are common — 45 GCC wards alone. Breaking them by population
      // puts the biggest unprotected places first, which is the question a
      // planner is actually asking: not "which ward scores worst" but "where are
      // the most people nobody can reach in time".
      .sort((a, b) => a.share - b.share || b.demand - a.demand)
      .slice(0, 10)
      // Several H3 units can fall nearest the same settlement. Two rows reading
      // "Irungattukottai" with different numbers is unreadable, so repeats get
      // a suffix rather than looking like a contradiction.
      .map((w, _i, all) => {
        const dupes = all.filter((x) => x.no === w.no);
        if (dupes.length < 2) return w;
        return { ...w, no: `${w.no} ${dupes.indexOf(w) + 1}` };
      });
  }, [coverage, meta]);

  const sites = useMemo(() => {
    const forcedPts = siteTable
      ? forced.map((j, i) => ({ ...siteTable[j], label: i + 1, kind: "placed" }))
      : [];
    const solvedKind = result?.mode === "staging" ? "post" : "solved";
    const solved = result
      ? result.site_positions.map((p, i) => ({ ...p, label: i + 1, kind: solvedKind }))
      : [];
    return [...forcedPts, ...solved];
  }, [siteTable, forced, result]);

  // Fly the map to an area named in the readout. Bounds come from the area's
  // demand cells, which every profile has; the outline only where the basemap
  // carries one.
  const focusArea = useCallback((id) => {
    if (!cells) return;
    const points = [];
    for (let i = 0; i < cells.ward.length; i++) {
      if (cells.ward[i] === id) points.push([cells.lat[i], cells.lon[i]]);
    }
    setFocus({ kind: "area", id, points,
               rings: basemap?.ward_rings?.[String(id)] ?? [] });
  }, [cells, basemap]);

  const focusSite = useCallback((p) => {
    setFocus({ kind: "site", lat: p.lat, lon: p.lon });
  }, []);

  // A focus on a solved site belongs to that solve.
  useEffect(() => {
    setFocus((f) => (f?.kind === "site" ? null : f));
  }, [result]);

  // Esc backs out one layer at a time: an open card, then the inspector, then
  // the highlight -- the order they sit on screen.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (tourStep != null) setTourStep(null);
      else if (briefOpen) setBriefOpen(false);
      else if (evidenceOpen) setEvidenceOpen(false);
      else if (placing) setPlacing(false);
      else if (picked != null) setPicked(null);
      else setFocus(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [briefOpen, evidenceOpen, placing, picked, tourStep]);

  // The tour drives the console. Each step is applied once, when it is
  // reached; its caption then reads whatever the console now shows.
  const budget = meta?.services?.[service]?.budget_s ?? 300;
  useEffect(() => {
    if (tourStep == null || !meta) return;
    const actions = {
      budget: meta.services.ems.budget_s,
      setThresholdS,
      setScenario,
      setComparing,
      reset: () => {
        setService("ems"); setScenario("dry"); setComparing(false);
        setThresholdS(meta.services.ems.budget_s); setMode("station");
        setResult(null); setTab("overview"); setFocus(null); setPicked(null);
      },
      solvePosts: (n) => {
        setComparing(false); setScenario("peak"); setMode("staging");
        setK(n); setTab("plan");
        optimise({ service: "ems", scenario: "peak", k: n, forced: [], mode: "staging" });
      },
    };
    STEPS[tourStep].apply(actions);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tourStep]);

  const startTour = useCallback(() => { setBriefOpen(false); setTourStep(0); }, []);
  // Placing ends, and its toast goes, when placing stops.
  useEffect(() => { if (!placing) setSnap(null); }, [placing]);

  const gained = useMemo(
    () => (result ? new Set(result.newly_covered_cells) : null), [result]);

  // Only the cells a hand-placed station adds are painted. Showing everything it
  // touches would light up half the city in the places that already have cover,
  // which is the opposite of the question being asked.
  const reachCells = useMemo(
    () => (reach ? new Set(reach.combined.new_cells) : null), [reach]);

  const pickedInfo = useMemo(() => {
    if (picked == null || !coverage || !cells) return null;
    const resp = coverage.response_s[picked];
    const who = [];
    if (nearest) {
      const topk = nearest.topk;
      for (let r = 0; r < topk; r++) {
        const si = nearest.who[picked * topk + r];
        const sec = nearest.seconds[picked * topk + r];
        if (si >= 0 && stations?.[si]) who.push({ name: stations[si].name, sec });
      }
    }
    // `resp` is the EXISTING network's time and nothing else. A cell the
    // optimiser or a hand-placed station would reach is coloured as reached but
    // still carries its old time, so the panel used to answer "7.4 min away"
    // about a cell it had just painted as covered. Say which future the number
    // belongs to.
    const byPlaced = reach
      ? reach.sites
          .map((r, i) => ({ n: i + 1, hit: r.new_cells.includes(picked) }))
          .filter((x) => x.hit)
          .map((x) => x.n)
      : [];
    return {
      pop: cells.pop[picked],
      ward: cells.ward[picked],
      resp,
      who,
      budgetS: coverage.budget_s,
      byPlaced,
      byProposed: Boolean(gained && gained.has(picked)),
    };
  }, [picked, coverage, cells, nearest, stations, reach, gained]);

  if (error) {
    return (
      <div className="fatal">
        <h1>The service isn't answering</h1>
        <pre>{error}</pre>
        <p>
          Nothing here is drawn without the API. Start it with <code>make api</code>,
          and build the pipeline first with <code>make all</code>.
        </p>
      </div>
    );
  }

  const svcMeta = meta?.services?.[service];
  const overhead = svcMeta ? svcMeta.t_alarm_s + svcMeta.t_turnout_s : 120;
  const total = overhead + thresholdS;
  const condLabel = (SCENARIO_LABEL[scenario] ?? scenario).toLowerCase();

  return (
    <div className="app">
      <header className="topbar">
        <div className="wordmark">
          <h1>Chennai emergency response</h1>
          <span className="where">
            {meta ? `${meta.profile_info.area_km2} km², ${meta.profile_info.units}` : "loading"}
          </span>
        </div>

        <div className="seg service-seg" role="group" aria-label="Service">
          {[["ems", "Ambulance"], ["fire", "Fire engine"]].map(([id, label]) => (
            <button key={id} aria-pressed={service === id} onClick={() => setService(id)}>
              {label}
            </button>
          ))}
        </div>

        <label className="area-select">
          <span className="sr-only">Study area</span>
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            {(profiles.length ? profiles : [{ profile: "gcc", built: true }]).map((p) => (
              <option key={p.profile} value={p.profile} disabled={!p.built}>
                {SHORT[p.profile] ?? p.profile}{p.built ? "" : " (not built)"}
              </option>
            ))}
          </select>
        </label>
        <div className="topbar-right">
          <button className="about" onClick={() => setBriefOpen(true)}>About</button>
          <button className="btn primary small tour-btn" onClick={startTour}
                  disabled={!meta}>
            Tour
          </button>
        </div>
      </header>

      <div className="stage">
        <div className="mapwrap">
          <MapView
            cells={cells}
            hex={meta?.hex}
            response={coverage?.response_s}
            thresholdS={thresholdS}
            gained={gained}
            reachCells={reachCells}
            candidates={siteTable}
            basemap={basemap}
            stations={stations}
            sites={sites}
            focus={focus}
            lost={lostCells}
            layers={layers}
            placing={placing}
            onMapClick={onMapClick}
            onPickCell={onPickCell}
          />

          <div className="instrument">
            <Dial svc={svcMeta} thresholdS={thresholdS} setThresholdS={setThresholdS}
                  share={coverage?.covered_share} busy={!coverage} />
          </div>

          <div className="bottom-strip">
            <Ribbon shares={scenarioShares} scenario={scenario} setScenario={setScenario}
                    comparing={comparing} setComparing={setComparing} />

            {/* The key changes with the question. Brightness is explained once,
                because it is the one encoding a reader would not guess. */}
            <div className="legend" aria-label="Map key">
              {lostCells ? (
                <>
                  <span className="swatch"><i style={{ background: LOST.colour }} />
                    Taken by {condLabel}</span>
                  <span className="swatch"><i style={{ background: BANDS[0].colour, opacity: 0.5 }} />
                    Still in time</span>
                  <span className="swatch"><i style={{ background: "#5c636b", opacity: 0.6 }} />
                    Late either way</span>
                </>
              ) : (
                <>
                  <span className="ramp-bar" aria-hidden="true">
                    {BANDS.slice(0, 4).map((b) => <i key={b.key} style={{ background: b.colour }} />)}
                  </span>
                  <span className="ramp-words">
                    in time <em>→</em> 2 <em>→</em> 5 min late <em>→</em> more
                  </span>
                  <span className="swatch"><i style={{ background: BANDS[4].colour }} />no route</span>
                </>
              )}
              <span className="swatch dim">brighter = more people</span>
              {gained && !lostCells && (
                <span className="swatch"><i style={{ background: GAINED.colour }} />{GAINED.label}</span>
              )}
              {reachCells && !lostCells && (
                <span className="swatch"><i style={{ background: REACH.colour }} />{REACH.label}</span>
              )}
              {stationKinds.length > 0 && layers.stations && stationKinds.map((k) => (
                <span key={k.key} className="swatch">
                  <i className="st-dot" style={{ background: k.fill }} />
                  {k.key === "listing" ? "listed station" : k.key === "mapped" ? "mapped station" : "surveyed"}
                </span>
              ))}
            </div>
          </div>

          {placing && (
            <div className={`toast${snap && !snap.ok ? " bad" : ""}`} role="status">
              {snap
                ? snap.ok
                  ? `Placed, ${snap.metres < 50 ? "on" : `${snap.metres.toLocaleString("en-IN")} m from`} where you clicked. Click it again to remove it.`
                  : `Nothing within ${snap.metres.toLocaleString("en-IN")} m of that point. Nothing placed.`
                : mode === "staging"
                  ? "Click the map to post an ambulance. It snaps to the nearest road point."
                  : "Click a marked site. Stations sit on an 800 m lattice, so a click snaps to the nearest."}
            </div>
          )}

          {pickedInfo && (
            <div className="picked">
              <button className="linkish close" onClick={() => setPicked(null)}
                      aria-label="Close">×</button>
              <h3>{meta?.wards?.[pickedInfo.ward]?.name
                   ?? `Ward ${meta?.wards?.[pickedInfo.ward]?.no ?? pickedInfo.ward}`}</h3>
              <p className="picked-time">
                {pickedInfo.resp < 0 ? "No route" : clock(pickedInfo.resp + overhead)}
                <span> call to arrival, {Math.round(pickedInfo.pop).toLocaleString("en-IN")} people</span>
              </p>
              {(pickedInfo.byPlaced.length > 0 || pickedInfo.byProposed) && (
                <p className="picked-future">
                  Inside the standard once{" "}
                  {pickedInfo.byPlaced.length > 0
                    ? `your site ${pickedInfo.byPlaced.join(" and ")} ${pickedInfo.byPlaced.length > 1 ? "are" : "is"} built`
                    : "the proposals are built"}.
                </p>
              )}
              {pickedInfo.who.length > 0 && (
                <ol>
                  {pickedInfo.who.map((w, i) => (
                    <li key={i}><span>{w.name}</span><span className="ago">{clock(w.sec + overhead)}</span></li>
                  ))}
                </ol>
              )}
            </div>
          )}

          {tourStep != null && (
            <Tour step={tourStep} setStep={setTourStep} onClose={() => setTourStep(null)}
                  live={{ coverage, scenarioShares, comparison, result, staging,
                          budgetTotal: overhead + budget }} />
          )}
        </div>

        <Card
          tab={tab} setTab={setTab}
          coverage={coverage} scenario={scenario} scenarioShares={scenarioShares}
          comparison={comparison} comparing={comparing}
          worstWards={worstWards} thresholdS={thresholdS} total={total}
          focus={focus} onFocusArea={focusArea} onFocusSite={focusSite}
          layers={layers} setLayers={setLayers}
          exportHref={api.exportUrl(
            service, scenario, thresholdS,
            result ? (result.exact ?? result.greedy).sites : [], profile,
            result?.mode ?? "station")}
          onEvidence={() => setEvidenceOpen(true)}
          publication={coverage?.publication ?? meta?.publication}
          mode={mode} setMode={chooseMode} staging={staging}
          k={k} setK={setK} onSolve={optimise} optimising={optimising}
          placing={placing} setPlacing={setPlacing}
          forced={forced} clearForced={() => setForced([])}
          onShowReach={showReach} reaching={reaching} reach={reach}
          result={result}
        />

        {briefOpen && (
          <Brief
            meta={meta}
            coverage={coverage}
            worstWards={worstWards}
            thresholdS={thresholdS}
            scenarioShares={scenarioShares}
            onClose={() => setBriefOpen(false)}
            onTour={startTour}
          />
        )}

        {evidenceOpen && (
          <Evidence
            profiles={profiles.map((p) => ({ ...p, coverage: profileCoverage[p.profile] }))}
            profile={profile}
            onClose={() => setEvidenceOpen(false)}
          />
        )}
      </div>
    </div>
  );
}
