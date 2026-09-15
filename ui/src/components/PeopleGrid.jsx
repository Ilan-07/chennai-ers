import { fmtInt } from "../api.js";

/* The coverage share, counted out in people.
 *
 * "71.8%" and "2,152,586 people" are the same fact, and only one of them is
 * legible. A percentage is a ratio a reader has to unpack; a block of dots is a
 * quantity they can see the shape of, and the shape is the argument — roughly
 * three in ten of these squares are the people this network does not reach.
 *
 * Every dot is drawn, none are rounded away, and the caption states what one is
 * worth. A figure whose unit is hidden is a picture, not a reading.
 */
const DOTS = 100;

export default function PeopleGrid({ covered, total, isFire }) {
  if (!total) return null;

  const per = total / DOTS;
  // Floor, not round: a single uncovered person should never be absorbed into a
  // fully green grid. The remainder goes to the covered side, which is the
  // direction that understates rather than dramatises the gap.
  const missedDots = Math.min(DOTS, Math.floor(((total - covered) / total) * DOTS));

  return (
    <div className="pgrid-wrap">
      <div className="pgrid" role="img"
           aria-label={`${fmtInt(covered)} of ${fmtInt(total)} reached in time`}>
        {Array.from({ length: DOTS }, (_, i) => (
          <i key={i} className={i < DOTS - missedDots ? "in" : "out"} />
        ))}
      </div>
      <p className="pgrid-key">
        one square ≈ {fmtInt(per)} {isFire ? "demand units" : "people"}
      </p>
    </div>
  );
}
