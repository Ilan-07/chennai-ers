import { useState } from "react";

/* What k peak-hour posts buy, against what the dry-day plan of the same size
 * buys at the same hour. Both lines start at today's peak coverage (k = 0), and
 * the dry-day figure is drawn as a ceiling rule rather than a series: it is the
 * thing peak hour takes away, so the gap to it is "how much is left to recover".
 *
 * One axis, two series. The posts line is the projection blue; the comparison
 * is dashed as well as coloured so the pair never rests on hue alone. Palette
 * validated on the rail surface (dark, #1a2631): both in band, CVD dE 21.
 */
const POSTS = "#3a98da";
const DRYPLAN = "#c27f45";

const W = 268, H = 150;
const M = { l: 30, r: 10, t: 10, b: 22 };

export default function StagingCurve({ staging, k }) {
  const [hover, setHover] = useState(null);

  const base = staging.baseline_share;
  const posts = [{ k: 0, share: base }, ...staging.posts.map((r) => ({ k: r.k, share: r.share }))];
  const dry = [{ k: 0, share: base },
               ...(staging.dry_plan_at_peak ?? []).map((r) => ({ k: r.k, share: r.share_at_peak }))];
  const maxK = posts[posts.length - 1].k;

  const lo = Math.floor((100 * base) / 10) / 10;
  const hi = Math.ceil((100 * staging.dry_share) / 10) / 10;
  const x = (kk) => M.l + ((W - M.l - M.r) * kk) / maxK;
  const y = (s) => M.t + ((H - M.t - M.b) * (hi - s)) / (hi - lo);
  const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.k).toFixed(1)},${y(p.share).toFixed(1)}`).join("");

  const ticks = [];
  for (let t = lo; t <= hi + 1e-9; t += 0.1) ticks.push(Math.round(t * 100) / 100);

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const kk = Math.round(((px - M.l) / (W - M.l - M.r)) * maxK);
    setHover(Math.max(0, Math.min(maxK, kk)));
  };

  const hk = hover;
  const hp = hk != null ? posts.find((p) => p.k === hk) : null;
  const hd = hk != null ? dry.find((p) => p.k === hk) : null;
  const lastP = posts[posts.length - 1];
  const lastD = dry[dry.length - 1];
  const pct = (s) => `${(100 * s).toFixed(1)}%`;

  return (
    <div className="curve">
      <div className="curve-legend">
        <span><i style={{ background: POSTS }} />Peak-hour posts</span>
        <span><i className="dash" style={{ borderColor: DRYPLAN }} />Dry-day plan, at peak</span>
      </div>
      <div className="curve-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img"
             aria-label={`Coverage at peak with 0 to ${maxK} posts: ${pct(base)} rising to ${pct(lastP.share)}; the dry-day plan reaches ${pct(lastD.share)}`}
             onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} className="grid" />
              <text x={M.l - 6} y={y(t) + 3.5} className="tick" textAnchor="end">{Math.round(100 * t)}%</text>
            </g>
          ))}
          {[0, 2, 4, 6, 8, 10].filter((t) => t <= maxK).map((t) => (
            <text key={t} x={x(t)} y={H - 6} className="tick" textAnchor="middle">{t}</text>
          ))}

          {/* The ceiling: coverage on a dry day, which peak hour takes away. */}
          <line x1={M.l} x2={W - M.r} y1={y(staging.dry_share)} y2={y(staging.dry_share)}
                className="ceiling" />
          <text x={W - M.r} y={y(staging.dry_share) - 4} className="tick" textAnchor="end">
            dry day {pct(staging.dry_share)}
          </text>

          {k >= 0 && k <= maxK && (
            <line x1={x(k)} x2={x(k)} y1={M.t} y2={H - M.b} className="current" />
          )}

          <path d={path(dry)} fill="none" stroke={DRYPLAN} strokeWidth="2"
                strokeDasharray="5 3" strokeLinejoin="round" strokeLinecap="round" />
          <path d={path(posts)} fill="none" stroke={POSTS} strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" />

          {hk != null && (
            <g>
              <line x1={x(hk)} x2={x(hk)} y1={M.t} y2={H - M.b} className="cross" />
              {hd && <circle cx={x(hk)} cy={y(hd.share)} r="4" fill={DRYPLAN} className="dot" />}
              {hp && <circle cx={x(hk)} cy={y(hp.share)} r="4" fill={POSTS} className="dot" />}
            </g>
          )}
        </svg>
        {hk != null && (
          <div className="curve-tip"
               style={{ left: `${Math.min(70, Math.max(30, (100 * x(hk)) / W))}%` }}>
            <b>{hk} {hk === 1 ? "ambulance" : "ambulances"}</b>
            <span><i style={{ background: POSTS }} />posts {hp ? pct(hp.share) : "—"}</span>
            <span><i style={{ background: DRYPLAN }} />dry-day plan {hd ? pct(hd.share) : "not solved"}</span>
          </div>
        )}
      </div>
      <p className="hint">
        Ten posts recover{" "}
        {Math.round(100 * (staging.posts[staging.posts.length - 1].recovers_share_of_peak_loss ?? 0))}%
        {" "}of the {staging.peak_loss_points.toFixed(1)} points peak hour takes. Each
        post is an <em>extra</em> ambulance, so this is an upper bound on moving the
        existing fleet.
      </p>
    </div>
  );
}
