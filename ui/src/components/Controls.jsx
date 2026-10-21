import { fmtMin } from "../api.js";
import { SCENARIO_LABEL } from "./scenarios.js";
import TimeBudget from "./TimeBudget.jsx";
import Resilience from "./Resilience.jsx";

// "47%" when a group agrees, "47-48%" when it does not. Three layers refused for
// one reason are one fact, and printing it three times reads as three problems.
function pctRange(lo, hi) {
  const a = Math.round(100 * lo);
  const b = Math.round(100 * hi);
  return a === b ? `${a}%` : `${a}–${b}%`;
}

/* Why a study area offers fewer road conditions than another.
 *
 * This used to be a typed sentence — "the inundation layers stop at the
 * corporation boundary" — which was true, but could not go stale visibly: a new
 * layer covering Tambaram would have changed nothing on screen. It now reads the
 * measurement, so the reason arrives with its own number. */
function FloodNote({ extent }) {
  if (!extent?.measured) {
    return (
      <p className="hint">
        A flood removes links from the graph, so routes disappear rather than
        slow down.
      </p>
    );
  }
  const refused = extent.refused ?? [];
  if (refused.length === 0) {
    return (
      <p className="hint">
        A flood removes links from the graph, so routes disappear rather than
        slow down. All {extent.applicable.length} network states are modelled
        across this area's {Math.round(extent.study_area_km2).toLocaleString("en-IN")} km².
      </p>
    );
  }
  return (
    <>
      <p className="hint">
        Only dry and peak apply here. The flood layers were produced for the
        corporation, and this area is{" "}
        {Math.round(extent.study_area_km2).toLocaleString("en-IN")} km².
      </p>
      <ul className="why-list">
        {(extent.groups ?? []).map((g) => (
          <li key={g.test}>
            <b>{g.scenarios.map((id) => SCENARIO_LABEL[id] ?? id).join(", ")}</b>
            {" — "}
            {g.test === "modelling domain" ? (
              <>
                drawn for the corporation. Its modelling domain covers{" "}
                {pctRange(g.domain_share_min, g.domain_share_max)} of this area,
                leaving {Math.round(g.outside_km2_max).toLocaleString("en-IN")} km²
                a flood would be reported dry across.
              </>
            ) : (
              <>
                observed points, surveyed inside the corporation only. Beyond it an
                absent point means nobody looked, not that nothing flooded.
              </>
            )}
          </li>
        ))}
      </ul>
      <p className="hint">
        Running them anyway would report unmodelled ground as dry, which reads as
        good news exactly where the study area was widened.
      </p>
    </>
  );
}

function Group({ title, children }) {
  return (
    <section className="group">
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

/* Secondary choices fold away. Six groups of equal weight make a reader hunt
 * for the path through; service, clock and stations are that path, and road
 * conditions, layers and export are adjustments you reach for afterwards. */
function Fold({ title, children, open = false }) {
  return (
    <details className="fold" open={open}>
      <summary>{title}</summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}

export default function Controls({
  meta, profile, service, setService, scenario, setScenario,
  thresholdS, setThresholdS, k, setK, layers, setLayers,
  onOptimise, optimising, placing, setPlacing, forced, clearForced, exportHref,
  onShowReach, reaching, reach, scenarioShares, scenariosLoading,
  mode, setMode, staging, comparing, setComparing,
}) {
  const posting = mode === "staging";
  const svc = meta?.services?.[service];
  const toggle = (key) => setLayers({ ...layers, [key]: !layers[key] });

  return (
    <aside className="rail" aria-label="Controls">
      <Group title="Which service">
        <div className="seg" role="group">
          {[["ems", "Ambulance"], ["fire", "Fire engine"]].map(([id, label]) => (
            <button key={id} aria-pressed={service === id} onClick={() => setService(id)}>
              {label}
            </button>
          ))}
        </div>
        <TimeBudget svc={svc} thresholdS={thresholdS} />
      </Group>

      <Group title="Time to arrive">
        <div className="dial">
          <span>Reach within</span>
          <span className="value reach">{fmtMin(thresholdS)}</span>
        </div>
        <input
          type="range" min={180} max={900} step={30} value={thresholdS}
          aria-label="Response time threshold"
          onChange={(e) => setThresholdS(Number(e.target.value))}
        />
        <p className="hint">
          Reads the same routes against a different clock. Siting always solves at
          the service's own budget.
        </p>
      </Group>

      <Fold title="Road conditions" open>
        <Resilience
          shares={scenarioShares}
          scenario={scenario}
          setScenario={setScenario}
          loading={scenariosLoading}
        />
        {scenario !== "dry" && (
          <button className="btn compare-btn" aria-pressed={comparing}
                  onClick={() => setComparing(!comparing)}>
            {comparing
              ? "Back to response times"
              : `Show what ${(SCENARIO_LABEL[scenario] ?? scenario).toLowerCase()} takes`}
          </button>
        )}
        {/* The modelling note is a reference, not a step: folded so the
            controls below it are not pushed off the first screen. */}
        <details className="subfold">
          <summary>How road conditions are modelled</summary>
          <FloodNote extent={meta?.flood_extent} />
        </details>
      </Fold>

      <Group title={posting ? "Post ambulances at peak" : "Add stations"}>
        {/* Offered only where step 15b was built: ambulances, on a build that
            has a staging result. A fire engine is not staged at a kerb. */}
        {staging && (
          <div className="seg mode-seg" role="group" aria-label="What to add">
            <button aria-pressed={!posting} onClick={() => setMode("station")}>
              Build stations
            </button>
            <button aria-pressed={posting} onClick={() => setMode("staging")}>
              Peak-hour posts
            </button>
          </div>
        )}
        {posting && (
          <p className="hint">
            An extra ambulance waiting at a roadside post through the{" "}
            {SCENARIO_LABEL[staging.scenario]?.toLowerCase() ?? staging.scenario}. A
            post needs a kerb, not a parcel, so any point on the road lattice is
            allowed. Solved on that network only.
          </p>
        )}
        <div className="dial">
          <span>{posting ? "Post" : "Build"}</span>
          <span className="value">{k} {posting ? (k === 1 ? "ambulance" : "ambulances") : "new"}</span>
        </div>
        <input
          type="range" min={0} max={12} step={1} value={k}
          aria-label="Number of new stations"
          onChange={(e) => setK(Number(e.target.value))}
        />
        <button className="btn primary" onClick={onOptimise} disabled={optimising}>
          {optimising ? "Solving…" : posting ? "Find the best posts" : "Find the best sites"}
        </button>
        <button className="btn" aria-pressed={placing} onClick={() => setPlacing(!placing)}>
          {placing ? "Stop placing by hand" : "Place one by hand"}
        </button>
        {forced.length > 0 && (
          <>
            <button className="btn" onClick={onShowReach} disabled={reaching}>
              {reaching ? "Measuring…"
                : reach ? "Reach shown on the map"
                : `Show what ${forced.length === 1 ? "it reaches" : "they reach"}`}
            </button>
            <p className="hint">
              {forced.length} site{forced.length === 1 ? "" : "s"} held fixed; the
              optimiser works around {forced.length === 1 ? "it" : "them"}.{" "}
              <button className="linkish" onClick={clearForced}>Clear</button>
            </p>
            {reach && (
              <p className="hint">
                Measured at the {fmtMin(reach.budget_s)} service budget, not the
                clock above.
              </p>
            )}
          </>
        )}
      </Group>

      <Fold title="Map layers">
        <div className="layers">
          {[
            ["coverage", "Coverage"],
            ["stations", "Stations"],
            ["sites", "Proposed"],
            ["wards", "Wards"],
            ["zones", "Zones"],
          ].map(([key, label]) => (
            <button key={key} aria-pressed={layers[key]} onClick={() => toggle(key)}>
              {label}
            </button>
          ))}
        </div>
        <a className="btn" href={exportHref} download style={{ marginTop: 9 }}>
          Export this view (CSV)
        </a>
        <p className="hint">
          Coordinates, coverage by area, the interval and the run id.
        </p>
      </Fold>
    </aside>
  );
}
