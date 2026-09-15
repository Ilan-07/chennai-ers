import { fmtMin } from "../api.js";

/* Where the standard's minutes actually go.
 *
 * The single most misread thing about a response standard is that it is a
 * DRIVING budget. It is not: SFAC-7 gives seven minutes from the call being
 * answered to a crew arriving, and answering it and getting the crew rolling
 * has already spent two of them before a wheel turns. Every map on this screen
 * is drawn against what is left.
 *
 * That used to be a sentence under the service switch, which readers skip. Set
 * as a bar it is unskippable and it does a second job the sentence could not:
 * the drive segment is bound to the threshold slider, so dragging the clock
 * visibly widens the standard you are asking for. A planner asking "what if we
 * allowed eight minutes" can see that is what they just asked for.
 */
export default function TimeBudget({ svc, thresholdS }) {
  if (!svc) return null;

  const alarm = svc.t_alarm_s;
  const turnout = svc.t_turnout_s;
  const overhead = alarm + turnout;
  const drive = Math.round(thresholdS);
  const total = overhead + drive;

  // The mandated total, so the bar can show when the slider has walked past it.
  const standardTotal = overhead + svc.budget_s;
  const over = total - standardTotal;

  // Overhead is fixed, so at short thresholds it would be squeezed to a sliver
  // and at long ones to nothing. The bar is scaled to whichever is wider — the
  // standard or what is being asked for — which keeps the fixed cost a fixed
  // width and lets the drive segment be the only thing that moves.
  const span = Math.max(total, standardTotal);
  const pct = (s) => `${(100 * s) / span}%`;

  return (
    <div className="budget">
      <div className="budget-bar" role="img"
           aria-label={`Of ${fmtMin(total)} from call to arrival, ${alarm} seconds `
                     + `answering, ${turnout} seconds turning out, `
                     + `${fmtMin(drive)} driving`}>
        <span className="seg-alarm" style={{ width: pct(alarm) }} />
        <span className="seg-turnout" style={{ width: pct(turnout) }} />
        <span className={`seg-drive${over > 0 ? " over" : ""}`}
              style={{ width: pct(drive) }} />
        {/* Where the mandate sits, drawn on top of the segments rather than
            between them: once the slider goes past it the tick has to stay put
            while the green keeps growing, or it stops meaning anything. */}
        {span > standardTotal && (
          <i className="budget-mandate" style={{ left: pct(standardTotal) }} />
        )}
      </div>

      <ul className="budget-key">
        <li><i className="k-alarm" />Answer <b>{alarm}s</b></li>
        <li><i className="k-turnout" />Turn out <b>{turnout}s</b></li>
        <li><i className="k-drive" />Drive <b>{fmtMin(drive)}</b></li>
      </ul>

      <p className="budget-total">
        {over === 0 ? (
          <>
            <b>{fmtMin(total)}</b> call to arrival — the {svc.standard} standard,
            of which {Math.round((100 * overhead) / total)}% is spent before the
            appliance moves.
          </>
        ) : over > 0 ? (
          <>
            <b>{fmtMin(total)}</b> call to arrival — asking for{" "}
            <span className="budget-over">{over}s more</span> than {svc.standard}
            {" "}allows.
          </>
        ) : (
          <>
            <b>{fmtMin(total)}</b> call to arrival — holding crews to{" "}
            <span className="budget-under">{-over}s tighter</span> than {svc.standard}
            {" "}requires.
          </>
        )}
      </p>
    </div>
  );
}
