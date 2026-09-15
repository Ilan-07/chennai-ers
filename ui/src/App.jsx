import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmtMin } from "./api.js";
import MapView, { BANDS, GAINED, REACH } from "./components/MapView.jsx";

// How far a click may be from a buildable site before it is refused. Candidates
// sit on an 800 m lattice (A-12) and the worst in-city gap to one is ~2.2 km, so
// 3 km accepts every click inside the study area and rejects the ones that are
// really asking for a station in the sea.
const SNAP_LIMIT_M = 3000;
import Controls from "./components/Controls.jsx";
import { SCENARIO_LABEL, SHORT } from "./components/scenarios.js";
import Summary from "./components/Summary.jsx";
import Brief from "./components/Brief.jsx";
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
  const [scenarioShares, setScenarioShares] = useState({});
  const [scenariosLoading, setScenariosLoading] = useState(false);
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
    api.candidates(service, profile).then((c) => setCandidates(c.candidates)).catch(() => {});
  }, [service, meta, profile]);

  // A siting result belongs to the network state it was solved on. Keeping it on
  // screen after the scenario changes would paint dry-day gains over a flooded
  // map, which is precisely the comparison this project exists to prevent.
  useEffect(() => {
    setResult(null);
  }, [scenario]);

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
      setReach(await api.reach(service, forced, scenario, profile));
    } catch (e) {
      setError(String(e));
      setReach(null);
    } finally {
      setReaching(false);
    }
  }, [forced, service, scenario, profile]);

  // A reach answer belongs to one set of placed sites under one service and one
  // road state. Any of those moving makes it a picture of something else, so it
  // is dropped rather than left on screen looking current.
  useEffect(() => { setReach(null); }, [forced, service, scenario, profile]);

  const optimise = useCallback(async () => {
    setOptimising(true);
    setError(null);
    try {
      setResult(await api.optimise({ profile, service, scenario, k, forced,
                                     exact_solve: true }));
    } catch (e) {
      setError(String(e));
    } finally {
      setOptimising(false);
    }
  }, [profile, service, scenario, k, forced]);

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
    if (!candidates) return;
    let best = -1;
    let bestD = Infinity;
    for (let j = 0; j < candidates.length; j++) {
      const dy = candidates[j].lat - lat;
      const dx = (candidates[j].lon - lon) * Math.cos((lat * Math.PI) / 180);
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
  }, [candidates]);

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
    const forcedPts = candidates ? forced.map((j) => candidates[j]) : [];
    const solved = result ? result.site_positions : [];
    return [...forcedPts, ...solved];
  }, [candidates, forced, result]);

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

  return (
    <div className="app">
      <header className="topbar">
        <div className="wordmark">
          <h1>Chennai emergency response</h1>
          <span className="where">
            {meta
              ? `${meta.profile_info.area_km2} km² · ${meta.profile_info.units}`
              : "loading"}
          </span>
        </div>
        {/* What the map is currently answering, spelled out where it cannot be
            scrolled away from. The service and the road state live in the rail,
            one of them inside a fold, so a reader who collapsed it was looking
            at a hundred-year flood with nothing on screen saying so. */}
        {meta && coverage && (
          <div className="state-strip" aria-label="Current query">
            <span className="chip">
              {service === "ems" ? "Ambulance" : "Fire engine"}
            </span>
            <span className={`chip${scenario === "dry" ? "" : " stressed"}`}>
              {SCENARIO_LABEL[scenario] ?? scenario}
            </span>
            <span className="chip mono">{fmtMin(thresholdS)}</span>
          </div>
        )}

        <div className="topbar-right">
        <button className="about" onClick={() => setBriefOpen(true)}
                aria-label="About this project">About</button>
        <button className="about" onClick={() => setEvidenceOpen(true)}
                aria-label="Method and evidence">Evidence</button>
        <div className="seg topseg" role="group" aria-label="Study area">
          {(profiles.length ? profiles : [{ profile: "gcc", built: true }]).map((p) => (
            <button
              key={p.profile}
              aria-pressed={profile === p.profile}
              disabled={!p.built}
              title={p.built ? p.label : "not built"}
              onClick={() => setProfile(p.profile)}
            >
              {SHORT[p.profile] ?? p.profile}
            </button>
          ))}
        </div>
        </div>
      </header>

      <div className="stage">
        <MapView
          cells={cells}
          hex={meta?.hex}
          response={coverage?.response_s}
          thresholdS={thresholdS}
          gained={gained}
          reachCells={reachCells}
          candidates={candidates}
          basemap={basemap}
          stations={stations}
          sites={sites}
          layers={layers}
          placing={placing}
          onMapClick={onMapClick}
          onPickCell={onPickCell}
        />

        <Controls
          meta={meta}
          profile={profile}
          service={service} setService={setService}
          scenario={scenario} setScenario={setScenario}
          thresholdS={thresholdS} setThresholdS={setThresholdS}
          k={k} setK={setK}
          layers={layers} setLayers={setLayers}
          onOptimise={optimise} optimising={optimising}
          placing={placing} setPlacing={setPlacing}
          forced={forced} clearForced={() => setForced([])}
          onShowReach={showReach} reaching={reaching} reach={reach}
          scenarioShares={scenarioShares} scenariosLoading={scenariosLoading}
          exportHref={api.exportUrl(
            service, scenario, thresholdS,
            result ? (result.exact ?? result.greedy).sites : [], profile)}
        />

        <Summary
          coverage={coverage}
          result={result}
          reach={reach}
          meta={meta}
          worstWards={worstWards}
          thresholdS={thresholdS}
        />

        {briefOpen && (
          <Brief
            meta={meta}
            coverage={coverage}
            worstWards={worstWards}
            thresholdS={thresholdS}
            scenarioShares={scenarioShares}
            onClose={() => setBriefOpen(false)}
          />
        )}

        {evidenceOpen && (
          <Evidence
            profiles={profiles.map((p) => ({ ...p, coverage: profileCoverage[p.profile] }))}
            profile={profile}
            onClose={() => setEvidenceOpen(false)}
          />
        )}

        {placing && (
          <div className="placing-note">
            Click a marked site. Stations sit on an 800&nbsp;m lattice, so a
            click snaps to the nearest one.
          </div>
        )}

        {snap && (
          <div className={`snap-note${snap.ok ? "" : " bad"}`} role="status">
            {snap.ok
              ? `Snapped ${snap.metres < 50 ? "onto" : `${snap.metres.toLocaleString("en-IN")} m to`} the nearest buildable site.`
              : `No buildable site within ${snap.metres.toLocaleString("en-IN")} m of that point — nothing placed.`}
            <button className="linkish" onClick={() => setSnap(null)}>Dismiss</button>
          </div>
        )}

        {/* The first four bands are one scale — degrees of lateness against the
            clock — and used to be drawn as four unrelated chips beside two that
            genuinely are categories. Set as a continuous ramp it reads as an
            isochrone key, and "no route" and the projections sit apart from it,
            which is what they are: not a worse time, a different kind of fact. */}
        <div className="legend" aria-label="Map key">
          <span className="ramp">
            <span className="ramp-bar">
              {BANDS.slice(0, 4).map((b) => (
                <i key={b.key} style={{ background: b.colour }} title={b.label} />
              ))}
            </span>
            {/* Each label sits under its own step rather than at the ends: the
                ramp is ordered but not evenly spaced in time, and a bare
                "in time → later" would invite reading the orange as twice the
                amber when it is a band two and a half times as wide. */}
            <span className="ramp-ends">
              <em>in time</em><em>+2 min</em><em>+5 min</em><em>more</em>
            </span>
          </span>
          <span className="swatch">
            <i style={{ background: BANDS[4].colour }} />
            {BANDS[4].label}
          </span>
          {gained && (
            <span className="swatch">
              <i style={{ background: GAINED.colour }} />
              {GAINED.label}
            </span>
          )}
          {reachCells && (
            <span className="swatch">
              <i style={{ background: REACH.colour }} />
              {REACH.label}
            </span>
          )}
        </div>

        {pickedInfo && (
          <div className="picked">
            <button className="linkish close" onClick={() => setPicked(null)}
                    aria-label="Close">×</button>
            <h3>{meta?.wards?.[pickedInfo.ward]?.name
                 ?? `Ward ${meta?.wards?.[pickedInfo.ward]?.no ?? pickedInfo.ward}`}</h3>
            <p className="sub">
              {Math.round(pickedInfo.pop).toLocaleString("en-IN")} residents ·{" "}
              {pickedInfo.resp < 0
                ? "no route today"
                : `${(pickedInfo.resp / 60).toFixed(1)} min away today`}
            </p>
            {(pickedInfo.byPlaced.length > 0 || pickedInfo.byProposed) && (
              <p className="picked-future">
                Within {(pickedInfo.budgetS / 60).toFixed(0)} min once{" "}
                {pickedInfo.byPlaced.length > 0
                  ? `your site ${pickedInfo.byPlaced.join(" and ")} ${
                      pickedInfo.byPlaced.length > 1 ? "are" : "is"} built`
                  : "the proposed stations are built"}.
                <span className="picked-caveat">
                  Reachability is modelled at the budget, so the new time is
                  known to be inside it, not to the second.
                </span>
              </p>
            )}
            {pickedInfo.who.length > 0 && (
              <>
                <p className="picked-label">Nearest stations today</p>
                <ol>
                  {pickedInfo.who.map((w, i) => (
                    <li key={i}>
                      <span>{w.name}</span>
                      <span className="ago">{(w.sec / 60).toFixed(1)} min</span>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
