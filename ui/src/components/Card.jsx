import { fmtInt } from "../api.js";
import { clock } from "./Dial.jsx";
import { SCENARIO_LABEL } from "./scenarios.js";
import StagingCurve from "./StagingCurve.jsx";

/* The one card. Two questions, one at a time: who is left out (Overview) and
 * what would fix it (Plan). The console used to answer both at once in two
 * full-height panels, every caveat expanded, which is how a screen with good
 * findings came to read as a wall of text. Each tab now leads with its answer
 * and keeps the reasoning one click away rather than on top of it. */

// How far past the clock an area's quickest crew lands. "0% reached" is the
// same reading for a ward missed by eight seconds and one missed by four
// minutes; they are different problems, and the bar keeps them apart.
function MissesBy({ fastest, budget }) {
  if (fastest == null) return <td className="miss">no route</td>;
  const over = fastest - budget;
  if (over <= 0) return <td className="miss met">inside</td>;
  const frac = Math.min(1, over / 300);
  return (
    <td className={`miss${over <= 60 ? " near" : ""}`}>
      <span className="miss-bar" aria-hidden="true">
        <span style={{ width: `${Math.max(6, 100 * frac)}%` }} />
      </span>
      <span className="miss-val">
        {over < 90 ? `${Math.round(over)}s` : `${(over / 60).toFixed(1)}m`}
      </span>
    </td>
  );
}

function Interval({ uncertainty }) {
  const a = uncertainty?.assumed_correct;
  if (!a) return <p className="interval">No position interval measured for this area.</p>;
  const b = uncertainty.if_unconfirmed_wrong;
  return (
    <p className="interval" title="From 300 draws of where the stations actually stand">
      ± {a.spread_points.toFixed(1)} points
      {b && <span> (± {b.spread_points.toFixed(1)} if the unconfirmed listings are wrong)</span>}
    </p>
  );
}

function Overview({ coverage, scenario, scenarioShares, comparison, comparing, worstWards,
                    thresholdS, total, focus, onFocusArea, layers, setLayers, exportHref,
                    onEvidence, publication }) {
  const missed = coverage.total_demand - coverage.covered_demand;
  const isFire = coverage.service === "fire";
  const dry = scenarioShares?.dry;
  const atBudget = thresholdS === coverage.budget_s;
  const delta = scenario !== "dry" && dry != null && atBudget
    ? 100 * (coverage.covered_share - dry) : null;
  const toggle = (key) => setLayers({ ...layers, [key]: !layers[key] });

  return (
    <>
      <section className="lead">
        {comparing && comparison ? (
          <>
            <p className="lead-figure lost">{fmtInt(comparison.lost_demand)}</p>
            <p className="lead-text">
              {isFire ? "of demand" : "people"} are pushed outside {clock(total)} by{" "}
              {(SCENARIO_LABEL[scenario] ?? scenario).toLowerCase()}. They are in time on a
              dry day.
            </p>
          </>
        ) : (
          <>
            <p className="lead-figure">{fmtInt(missed)}</p>
            <p className="lead-text">
              {isFire ? "of risk-weighted demand is" : "people are"} not reached within{" "}
              {clock(total)}, out of {fmtInt(coverage.total_demand)}.
              {delta != null && (
                <> <b className="down">{delta.toFixed(1)} points</b> against a dry day.</>
              )}
            </p>
          </>
        )}
        <Interval uncertainty={coverage.uncertainty} />
      </section>

      <section className="block">
        <h3>Where most people are left</h3>
        <table className="worst">
          <tbody>
            {worstWards.slice(0, 7).map((w) => {
              const sel = focus?.kind === "area" && focus.id === w.id;
              return (
                <tr key={w.id} className={`row-link${sel ? " selected" : ""}`} tabIndex={0}
                    onClick={() => onFocusArea(w.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onFocusArea(w.id); }
                    }}>
                  <td>{w.no}</td>
                  <td className="people">{fmtInt(w.demand)}</td>
                  <MissesBy fastest={w.fastest} budget={thresholdS} />
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="fine">
          Bar: how far past the clock the quickest crew lands. Under a minute is a
          junction or a turnout, not a missing station. Pick a row to find it.
        </p>
      </section>

      <section className="block foot">
        <div className="layer-chips" role="group" aria-label="Map layers">
          {[["stations", "Stations"], ["wards", "Wards"], ["zones", "Zones"], ["sites", "Proposals"]]
            .map(([key, label]) => (
              <button key={key} aria-pressed={layers[key]} onClick={() => toggle(key)}>
                {label}
              </button>
            ))}
        </div>
        <div className="foot-links">
          <a className="linkish" href={exportHref} download>Export CSV</a>
          <button className="linkish" onClick={onEvidence}>How this was measured</button>
        </div>
        {publication && (
          <p className={`pub pub-${publication.state}`}>
            <i aria-hidden="true" />{publication.headline}
          </p>
        )}
      </section>
    </>
  );
}

function Plan({ coverage, mode, setMode, staging, k, setK, onSolve, optimising, placing,
                setPlacing, forced, clearForced, onShowReach, reaching, reach, result,
                focus, onFocusSite }) {
  const posting = mode === "staging";
  const solved = result ? (result.exact ?? result.greedy) : null;
  const gain = solved ? solved.share - result.with_manual_share : null;
  const isPosts = result?.mode === "staging";
  const dryPlan = isPosts ? staging?.dry_plan_at_peak?.find((r) => r.k === result.k) : null;
  const noun = posting ? (k === 1 ? "ambulance" : "ambulances") : (k === 1 ? "station" : "stations");

  return (
    <>
      <section className="lead">
        {staging && (
          <div className="seg plan-seg" role="group" aria-label="What to add">
            <button aria-pressed={!posting} onClick={() => setMode("station")}>New stations</button>
            <button aria-pressed={posting} onClick={() => setMode("staging")}>Peak-hour posts</button>
          </div>
        )}
        <p className="plan-q">
          {posting
            ? "Where should extra ambulances wait during peak hour?"
            : "Where should new stations go?"}
        </p>
        <div className="stepper" role="group" aria-label={`Number of ${noun}`}>
          <button onClick={() => setK(Math.max(0, k - 1))} aria-label="Fewer">−</button>
          <span><b>{k}</b> {noun}</span>
          <button onClick={() => setK(Math.min(12, k + 1))} aria-label="More">+</button>
        </div>
        <button className="btn primary" onClick={() => onSolve()} disabled={optimising}>
          {optimising ? "Solving…" : posting ? "Find the best posts" : "Find the best sites"}
        </button>
        <button className="btn ghost" aria-pressed={placing} onClick={() => setPlacing(!placing)}>
          {placing ? "Done placing" : "Place one by hand"}
        </button>
        {forced.length > 0 && (
          <p className="fine">
            {forced.length} placed by hand, held fixed.{" "}
            <button className="linkish" onClick={onShowReach} disabled={reaching}>
              {reaching ? "Measuring…" : "Show what they reach"}
            </button>{" "}
            <button className="linkish" onClick={clearForced}>Clear</button>
          </p>
        )}
      </section>

      {solved && (
        <section className="block result">
          <p className="result-figure">
            {(100 * coverage.covered_share).toFixed(1)}%
            <span className="arrow" aria-hidden="true"> → </span>
            <b>{(100 * solved.share).toFixed(1)}%</b>
          </p>
          <p className="lead-text">
            <b className="up">+{(100 * gain).toFixed(1)} points</b>,{" "}
            {fmtInt(solved.share * coverage.total_demand - coverage.covered_demand)} more people
            reached.{" "}
            {result.exact?.proven_optimal
              ? "Proven optimal: no other placement does better."
              : result.exact ? `Not proven optimal: ${result.exact.optimality}` : "Greedy solution."}
          </p>
          {dryPlan && (
            <p className="fine">
              The dry-day plan's {result.k} stations would add only{" "}
              {dryPlan.gain_points_at_peak.toFixed(1)} points at this hour, and share{" "}
              {dryPlan.sites_shared_with_posts === 0 ? "no site" : `${dryPlan.sites_shared_with_posts} site`}{" "}
              with these posts.
            </p>
          )}
          <ol className="site-list">
            {result.site_positions.map((s, i) => {
              const sel = focus?.kind === "site" && focus.lat === s.lat && focus.lon === s.lon;
              return (
                <li key={i}>
                  <button className={`site-row${sel ? " selected" : ""}`} onClick={() => onFocusSite(s)}>
                    <span className={`pin${isPosts ? " post" : ""}`}>{i + 1}</span>
                    {s.lat.toFixed(4)}, {s.lon.toFixed(4)}
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {reach && (
        <section className="block">
          <h3>What your {reach.sites.length === 1 ? "site reaches" : "sites reach"}</h3>
          <p className="lead-text">
            {reach.combined.new_demand === 0
              ? "Everyone in reach is already inside the standard. As placed, it adds nobody."
              : <><b className="up">{fmtInt(reach.combined.new_demand)}</b> people brought inside
                  the standard who are outside it today.</>}
          </p>
          <p className="fine">Measured at the service's own budget, not the clock.</p>
        </section>
      )}

      {posting && staging && (
        <section className="block">
          <h3>What posts buy at peak</h3>
          <StagingCurve staging={staging} k={k} />
        </section>
      )}
    </>
  );
}

export default function Card(props) {
  const { tab, setTab, coverage } = props;
  return (
    <aside className="card" aria-label="Results and planning">
      <div className="tabs" role="tablist">
        {[["overview", "Who is left out"], ["plan", "Plan a fix"]].map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      <div className="card-body">
        {!coverage
          ? <p className="fine pad">Reading the network…</p>
          : tab === "overview" ? <Overview {...props} /> : <Plan {...props} />}
      </div>
    </aside>
  );
}
