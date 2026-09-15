import { fmtInt, fmtMin, fmtPct } from "../api.js";
import PeopleGrid from "./PeopleGrid.jsx";

/* The tolerance, set as an instrument reading rather than an alarm.
 *
 * This used to be amber body text, which teaches the reader to dismiss it as a
 * warning. It is not a warning: it is the interval the measurement was taken
 * with, and it belongs beside the figure in the same voice. Only the GCC
 * inventory has an identity problem — 15 listings that may name the wrong
 * station — so only it carries a second, much wider bound. */
function Tolerance({ uncertainty }) {
  const a = uncertainty?.assumed_correct;
  if (!a) {
    return (
      <p className="tolerance">
        No position uncertainty has been measured for this build, so the figure
        above carries no interval.
      </p>
    );
  }
  const b = uncertainty.if_unconfirmed_wrong;
  return (
    <p className="tolerance">
      <span className="pm">± {a.spread_points.toFixed(1)} points</span> from where
      the stations actually stand, over {a.draws} draws
      {b && (
        <>
          {" "}— widening to <span className="pm">± {b.spread_points.toFixed(1)}</span>{" "}
          if the 15 unconfirmed listings name the wrong stations
        </>
      )}
      .
    </p>
  );
}

/* How far past the clock an area's quickest arrival lands.
 *
 * "0.0% reached" is the same reading for a ward a crew misses by eight seconds
 * and one it misses by four minutes, and they are not the same problem: the
 * first is a signals, turnout or one-way problem that no capital programme
 * should be spent on, the second genuinely wants a station. The table used to
 * print the raw fastest time and leave the subtraction to the reader, so the
 * distinction was there and nobody did the arithmetic to find it.
 */
function MissesBy({ fastest, budget }) {
  if (fastest == null) return <td className="miss">no route</td>;
  const over = fastest - budget;
  if (over <= 0) return <td className="miss met">inside</td>;
  // Anything past five minutes late is off the end of the bar. The scale is
  // there to separate near-misses from the rest, not to rank the hopeless.
  const frac = Math.min(1, over / 300);
  const near = over <= 60;
  return (
    <td className={`miss${near ? " near" : ""}`}>
      <span className="miss-bar" aria-hidden="true">
        <span style={{ width: `${Math.max(6, 100 * frac)}%` }} />
      </span>
      <span className="miss-val">
        {over < 90 ? `${Math.round(over)}s` : `${(over / 60).toFixed(1)}m`}
      </span>
    </td>
  );
}

export default function Summary({ coverage, result, reach, meta, worstWards, thresholdS }) {
  if (!coverage) {
    return <aside className="readout"><p className="loading">Reading the network…</p></aside>;
  }

  const solved = result ? (result.exact ?? result.greedy) : null;
  const gain = solved ? solved.share - result.with_manual_share : null;
  const missed = coverage.total_demand - coverage.covered_demand;
  const isFire = coverage.service === "fire";
  const caveat = meta?.profile_info?.note;
  const pub = coverage.publication ?? meta?.publication;

  return (
    <aside className="readout" aria-label="Results">
      <section className="headline">
        <p className="clock">
          Reached within <span className="t">{fmtMin(thresholdS)}</span>
        </p>
        <p className="figure">
          {(100 * coverage.covered_share).toFixed(1)}<span className="pct">%</span>
        </p>
        <p className="reached">
          {fmtInt(coverage.covered_demand)} of {fmtInt(coverage.total_demand)}{" "}
          {isFire ? "risk-weighted demand" : "residents"}
        </p>

        <PeopleGrid
          covered={coverage.covered_demand}
          total={coverage.total_demand}
          isFire={isFire}
        />

        <p className="left-out">
          <b>{fmtInt(missed)}</b> {isFire ? "of that demand" : "people"} cannot be
          reached in time
          {coverage.unreachable_cells > 0 &&
            `, and ${coverage.unreachable_cells} cells cannot be reached at all`}
          .
        </p>

        <Tolerance uncertainty={coverage.uncertainty} />

        {pub?.state === "blocked" && (
          <p className="status status-blocked headline-status">
            <span className="dot" aria-hidden="true" />
            Provisional — not cleared for publication
          </p>
        )}
      </section>

      {result && (
        <section className="group result">
          <h2>
            With {result.k} more station{result.k === 1 ? "" : "s"}
            {result.forced.length ? ` beside your ${result.forced.length} placed` : ""}
          </h2>
          <p className="figure" style={{ fontSize: 34 }}>
            {(100 * solved.share).toFixed(1)}<span className="pct">%</span>
          </p>
          <p className="reached">
            <span className="delta">
              {gain >= 0 ? "+" : ""}{(100 * gain).toFixed(1)} points
            </span>{" "}
            — {fmtInt(solved.share * coverage.total_demand - coverage.covered_demand)} more
            reached
          </p>
          <p className="proof">
            {result.exact
              ? result.exact.proven_optimal
                ? "No other placement of this many stations does better — proven, not estimated."
                : `Not proven optimal: ${result.exact.optimality}`
              : "Greedy solution only."}
          </p>
          <ol className="sites">
            {result.site_positions.map((s, i) => (
              <li key={i}>
                <span className="pin">{i + 1}</span>
                {s.lat.toFixed(5)}, {s.lon.toFixed(5)}
              </li>
            ))}
          </ol>
        </section>
      )}

      {reach && (
        <section className="group result">
          <h2>
            {reach.sites.length === 1
              ? "What your station reaches"
              : "What your stations reach"}
          </h2>
          <p className="hint" style={{ margin: "0 0 8px" }}>
            Within {fmtMin(reach.budget_s)} of driving — the service's own budget,
            not the clock on the left.
          </p>
          <table>
            <thead>
              <tr><th>Site</th><th>Reaches</th><th>Not already covered</th></tr>
            </thead>
            <tbody>
              {reach.sites.map((r, i) => (
                <tr key={r.site}>
                  <td><span className="pin">{i + 1}</span></td>
                  <td className="people">{fmtInt(r.demand)}</td>
                  <td className="people">{fmtInt(r.new_demand)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="proof">
            {reach.combined.new_demand === 0
              ? (reach.sites.length === 1
                  ? "Everyone it reaches is already inside the standard today. As placed, it adds nobody."
                  : "Everyone they reach is already inside the standard today. As placed, they add nobody.")
              : (
                <>
                  {reach.sites.length === 1 ? "It puts " : "Together they put "}
                  <b>{fmtInt(reach.combined.new_demand)}</b> people inside the
                  standard who are outside it today
                  {reach.combined.double_counted_demand > 0 && <>, after{" "}
                    {fmtInt(reach.combined.double_counted_demand)} counted twice
                    where they overlap</>}.
                </>
              )}
          </p>
          <p className="hint">
            The second column is the one that decides a site. A station on top of
            existing cover reaches a great many people and helps none of them.
          </p>
        </section>
      )}

      <section className="group">
        <h2>Where the most people are left</h2>
        <p className="hint" style={{ margin: "0 0 8px" }}>
          How far past the clock the quickest crew lands. An area shown in amber
          misses by under a minute — that is a junction or a turnout, not a
          station.
        </p>
        <table className="worst">
          <thead>
            <tr><th>Area</th><th>People</th><th>Misses by</th><th>Reached</th></tr>
          </thead>
          <tbody>
            {worstWards.map((w) => (
              <tr key={w.id}>
                <td>{w.no}</td>
                <td className="people">{fmtInt(w.demand)}</td>
                <MissesBy fastest={w.fastest} budget={thresholdS} />
                <td>{fmtPct(w.share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="group">
        <h2>What this rests on</h2>
        {pub && (
          <p className={`status status-${pub.state}`}>
            <span className="dot" aria-hidden="true" />
            {pub.headline}
          </p>
        )}
        {pub?.note && <p className="hint">{pub.note}</p>}
        {caveat && <p className="caveat">{caveat}</p>}
        <p className="hint">
          {pub?.gates_run
            ? "Every publish gate is evaluated against this build."
            : "The publish gates have not been run against this study area."}
          {" "}Run {meta?.city?.stations_signature}
        </p>
      </section>
    </aside>
  );
}
