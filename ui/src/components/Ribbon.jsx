import { SCENARIO_LABEL } from "./scenarios.js";

/* Road conditions as one strip along the bottom of the map.
 *
 * Read left to right it is a decline: the dry day first, then every other
 * condition by how much it holds. Each chip is the control as well as the
 * reading, so comparing two conditions is one click, not a menu. The bar in
 * each chip is scaled to the dry day, so peak hour visibly holds a bit more
 * than half of it.
 */
export default function Ribbon({ shares, scenario, setScenario, comparing, setComparing }) {
  const dry = shares?.dry;
  const rows = Object.entries(shares ?? {})
    .filter(([id, v]) => v != null && id !== "dry")
    .sort((a, b) => b[1] - a[1]);
  if (dry == null) return <div className="ribbon loading" aria-hidden="true" />;
  const all = [["dry", dry], ...rows];
  const worst = rows.length ? rows[rows.length - 1][0] : null;

  return (
    <div className="ribbon" role="group" aria-label="Road conditions">
      {all.map(([id, v]) => (
        <button key={id} className="chip-cond" aria-pressed={scenario === id}
                onClick={() => setScenario(id)}>
          <span className="cond-name">
            {SCENARIO_LABEL[id] ?? id}
            {id === worst && <em className="cond-flag">worst</em>}
          </span>
          <span className="cond-val">{(100 * v).toFixed(1)}%</span>
          <span className="cond-bar"><i style={{ width: `${(100 * v) / dry}%` }} /></span>
        </button>
      ))}
      {scenario !== "dry" && (
        <button className="cond-compare" aria-pressed={comparing}
                onClick={() => setComparing(!comparing)}>
          {comparing ? "Show response times" : "Show what it takes"}
        </button>
      )}
    </div>
  );
}
