import { fmtInt, fmtMin } from "../api.js";

/* The opening card.
 *
 * Someone meeting this for the first time needs three things before a single
 * control makes sense: the question, what was found, and what the finding rests
 * on. Every number here is read from the live API rather than written into the
 * copy, so the brief cannot drift from the model the way the DA-1 deck did.
 */
export default function Brief({ meta, coverage, worstWards, thresholdS, onClose }) {
  if (!meta || !coverage) return null;

  const tightest = worstWards
    .filter((w) => w.share === 0 && w.fastest != null)
    .sort((a, b) => a.fastest - b.fastest)[0];

  const missed = coverage.total_demand - coverage.covered_demand;
  const unc = coverage.uncertainty?.assumed_correct;
  const wide = coverage.uncertainty?.if_unconfirmed_wrong;

  return (
    <div className="brief-scrim" onClick={onClose}>
    <div className="brief" role="dialog" aria-label="About this project"
         onClick={(e) => e.stopPropagation()}>
      <button className="brief-close" onClick={onClose} aria-label="Close">×</button>

      <p className="brief-kicker">Design of Smart Cities · Chennai</p>
      <h2>Who can an ambulance or fire engine actually reach in time?</h2>

      <p className="brief-lead">
        Travel time is measured on the real directed road network — not circles on
        a map — for all {meta.city.cells.toLocaleString("en-IN")} demand cells of the{" "}
        {meta.profile_info.label} area. Where the network falls short, the
        optimiser places new stations and proves no better placement exists.
      </p>

      <dl className="brief-figures">
        <div>
          <dt>Reached within {fmtMin(thresholdS)}</dt>
          <dd>{(100 * coverage.covered_share).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>Left outside it</dt>
          <dd className="bad">{fmtInt(missed)}</dd>
        </div>
        {tightest && (
          <div>
            <dt>{tightest.no} misses by</dt>
            <dd>{Math.round(tightest.fastest - coverage.budget_s)}s</dd>
          </div>
        )}
      </dl>

      {tightest && (
        <p className="brief-note">
          That last figure is the one worth arguing about: {fmtInt(tightest.demand)}{" "}
          people sit {Math.round(tightest.fastest - coverage.budget_s)} seconds outside
          the standard, which is a different problem from a neighbourhood that is
          minutes away.
        </p>
      )}

      <p className="brief-note">
        {unc ? (
          <>
            Every figure carries its interval: <b>± {unc.spread_points.toFixed(1)} points</b>{" "}
            from station-position uncertainty
            {wide && <>, widening to <b>± {wide.spread_points.toFixed(1)}</b> if the 15
              unconfirmed map listings name the wrong stations</>}
            . Nothing here is published as settled that isn't.
          </>
        ) : (
          <>No position uncertainty has been measured for this study area yet.</>
        )}
      </p>

      <button className="btn primary brief-go" onClick={onClose}>
        Explore the map
      </button>
    </div>
    </div>
  );
}
