import { SCENARIO_LABEL } from "./scenarios.js";

/* What every road condition does to the same city, side by side.
 *
 * This project's least intuitive result is that PEAK HOUR costs more coverage
 * than a hundred-year flood — congestion is the binding design case, not
 * inundation. Until now you could only find that by changing the scenario
 * select six times and remembering six numbers, which is a way of hiding a
 * finding rather than reporting one.
 *
 * Ranked worst-first, because the worst row is the one a plan has to survive.
 * Each row is also the control: reading a scenario and switching to it are the
 * same gesture, so the comparison never becomes a picture you have to leave.
 */
// The three map bands, reused as a scale. Interpolating between them rather
// than picking one per row means the colour carries the same information as the
// length — a reader scanning the column sees the spread before reading a digit —
// and it does it in the palette the map already taught them.
const SCALE = [[208, 73, 92], [224, 177, 60], [52, 163, 107]];

function rankColour(t) {
  const x = Math.max(0, Math.min(1, t)) * (SCALE.length - 1);
  const i = Math.min(SCALE.length - 2, Math.floor(x));
  const f = x - i;
  const c = SCALE[i].map((v, j) => Math.round(v + f * (SCALE[i + 1][j] - v)));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export default function Resilience({ shares, scenario, setScenario, loading }) {
  const rows = Object.entries(shares ?? {})
    .filter(([, v]) => v != null)
    .map(([id, share]) => ({ id, share }))
    .sort((a, b) => a.share - b.share);

  if (loading && rows.length < 2) {
    return (
      <div className="resil">
        <div className="skeleton-rows">
          {[0, 1, 2].map((i) => <span key={i} className="skeleton" />)}
        </div>
      </div>
    );
  }
  if (rows.length < 2) return null;

  const worst = rows[0];
  const best = rows[rows.length - 1];
  // The bars are scaled to the best case, not to 100%. Against a full axis the
  // whole set sits in the middle and the differences — which are the entire
  // point — flatten into six bars of roughly the same length.
  const span = Math.max(best.share, 0.01);
  // Colour is ranked WITHIN this set, not against an absolute scale: the worst
  // road state this city has is the red one whether it costs five points or
  // thirty. The note underneath carries the absolute size of the gap.
  const floor = worst.share;
  const range = Math.max(best.share - floor, 1e-6);

  return (
    <div className="resil">
      <ul className="resil-rows">
        {rows.map((r) => (
          <li key={r.id} className={r.id === scenario ? "on" : ""}>
            <button onClick={() => setScenario(r.id)}
                    aria-pressed={r.id === scenario}>
              <span className="resil-name">{SCENARIO_LABEL[r.id] ?? r.id}</span>
              <span className="resil-track">
                <span className="resil-fill"
                      style={{ width: `${(100 * r.share) / span}%`,
                               background: rankColour((r.share - floor) / range) }} />
              </span>
              <span className="resil-val">{(100 * r.share).toFixed(1)}%</span>
            </button>
          </li>
        ))}
      </ul>

      <p className="resil-note">
        {worst.id === "peak" ? (
          <>
            Congestion is the binding case: <b>peak hour</b> costs{" "}
            {(100 * (best.share - worst.share)).toFixed(1)} points, more than any
            flood modelled here. A plan sized for inundation is undersized for a
            Tuesday evening.
          </>
        ) : (
          <>
            <b>{SCENARIO_LABEL[worst.id] ?? worst.id}</b> is the binding case,{" "}
            {(100 * (best.share - worst.share)).toFixed(1)} points below the dry
            network. That is the state a plan has to survive.
          </>
        )}
      </p>
    </div>
  );
}
