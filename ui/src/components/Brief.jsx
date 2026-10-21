import { fmtInt, fmtMin } from "../api.js";
import { SCENARIO_LABEL } from "./scenarios.js";

/* The opening card.
 *
 * Someone meeting this for the first time needs three things before a single
 * control makes sense: the question, what was found, and what the finding rests
 * on. Every number here is read from the live API rather than written into the
 * copy, so the brief cannot drift from the model the way the DA-1 deck did.
 */
export default function Brief({ meta, coverage, worstWards, thresholdS,
                                scenarioShares, onClose, onTour }) {
  if (!meta || !coverage) return null;

  // The binding road state, read rather than written. The finding this project
  // is most likely to be remembered for is that congestion beats inundation,
  // and an opening card that omits it sends a reader to the map looking for the
  // wrong thing.
  const ranked = Object.entries(scenarioShares ?? {})
    .filter(([, v]) => v != null)
    .sort((a, b) => a[1] - b[1]);
  const binding = ranked.length > 1 ? ranked[0] : null;
  const dry = scenarioShares?.dry;
  const flood = scenarioShares?.flood100;

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

      <p className="brief-kicker">Design of Smart Cities, Chennai</p>
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
          people sit {Math.round(tightest.fastest - coverage.budget_s)}{" "}
          {Math.round(tightest.fastest - coverage.budget_s) === 1 ? "second" : "seconds"}{" "}
          outside the standard, which is a different problem from a neighbourhood
          that is minutes away.
        </p>
      )}

      {binding && dry != null && (
        <p className="brief-note">
          The binding case is not the one people expect.{" "}
          <b>{SCENARIO_LABEL[binding[0]] ?? binding[0]}</b> takes coverage to{" "}
          <b>{(100 * binding[1]).toFixed(1)}%</b>
          {binding[0] === "peak" && flood != null && (
            <> — worse than the hundred-year flood, which holds{" "}
              {(100 * flood).toFixed(1)}%</>)}
          . A plan sized for the dry network is not a plan.
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

      <div className="brief-actions">
        {onTour && (
          <button className="btn primary brief-go" onClick={onTour}>
            Take the five-step tour
          </button>
        )}
        <button className="btn ghost brief-go" onClick={onClose}>
          Explore on my own
        </button>
      </div>
    </div>
    </div>
  );
}
