import { useCallback, useRef } from "react";

/* The response clock. The console's one instrument, and its main control.
 *
 * A response standard is a clock that starts when the phone is answered, so
 * the control is drawn as one: a 270-degree stopwatch bezel from 0 to 17
 * minutes, call to arrival. The first two arcs are spent before a wheel turns
 * -- answering the call and getting the crew rolling -- and are fixed; the
 * third is the drive, and it is the part you drag. The notch marks the
 * service's own standard, so asking for "one more minute" is a visible
 * distance past it rather than a number in a slider label.
 *
 * Every map colour is cut against the hand's position: drag it and the city
 * re-colours under you. The figure in the middle is what the hand buys.
 */
const SIZE = 216;
const C = SIZE / 2;
const R = 86;
const START = 135;            // degrees, clockwise from 3 o'clock
const SWEEP = 270;
const MIN_DRIVE = 180;
const MAX_DRIVE = 900;
const STEP = 15;

const rad = (d) => (d * Math.PI) / 180;
const pt = (deg, r = R) => [C + r * Math.cos(rad(deg)), C + r * Math.sin(rad(deg))];

function arc(a0, a1, r = R) {
  if (a1 - a0 < 0.01) return "";
  const [x0, y0] = pt(a0, r);
  const [x1, y1] = pt(a1, r);
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
}

export const clock = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export default function Dial({ svc, thresholdS, setThresholdS, share, busy }) {
  const ref = useRef(null);
  const dragging = useRef(false);

  const alarm = svc?.t_alarm_s ?? 60;
  const turnout = svc?.t_turnout_s ?? 60;
  const overhead = alarm + turnout;
  const budget = svc?.budget_s ?? 300;
  const maxT = overhead + MAX_DRIVE;
  const total = overhead + thresholdS;
  const standard = overhead + budget;
  const ang = (t) => START + (SWEEP * t) / maxT;

  const setFromPointer = useCallback((e) => {
    const box = ref.current.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * SIZE - C;
    const y = ((e.clientY - box.top) / box.height) * SIZE - C;
    let rel = ((Math.atan2(y, x) * 180) / Math.PI - START + 720) % 360;
    if (rel > SWEEP) rel = rel > SWEEP + (360 - SWEEP) / 2 ? 0 : SWEEP;
    const t = (rel / SWEEP) * maxT;
    const drive = Math.round((t - overhead) / STEP) * STEP;
    setThresholdS(Math.max(MIN_DRIVE, Math.min(MAX_DRIVE, drive)));
  }, [maxT, overhead, setThresholdS]);

  const onKey = (e) => {
    const d = { ArrowRight: STEP, ArrowUp: STEP, ArrowLeft: -STEP, ArrowDown: -STEP,
                PageUp: 60, PageDown: -60 }[e.key];
    if (d != null) {
      e.preventDefault();
      setThresholdS(Math.max(MIN_DRIVE, Math.min(MAX_DRIVE, thresholdS + d)));
    } else if (e.key === "Home") {
      e.preventDefault();
      setThresholdS(budget);
    }
  };

  const over = total > standard;
  const [hx, hy] = pt(ang(total));
  const [sx0, sy0] = pt(ang(standard), R - 15);
  const [sx1, sy1] = pt(ang(standard), R + 13);

  const ticks = [];
  for (let m = 0; m * 60 <= maxT; m++) {
    const big = m % 5 === 0;
    const [x0, y0] = pt(ang(m * 60), R + 8);
    const [x1, y1] = pt(ang(m * 60), R + (big ? 15 : 11));
    ticks.push(<line key={m} x1={x0} y1={y0} x2={x1} y2={y1}
                     className={big ? "tick big" : "tick"} />);
    if (big) {
      const [lx, ly] = pt(ang(m * 60), R + 25);
      ticks.push(<text key={`l${m}`} x={lx} y={ly + 4} className="tick-label"
                       textAnchor="middle">{m}</text>);
    }
  }

  return (
    <div className={`clock-dial${busy ? " busy" : ""}`}>
      <svg
        ref={ref}
        viewBox={`-14 -14 ${SIZE + 28} ${SIZE + 28}`}
        role="slider"
        tabIndex={0}
        aria-label="Time from call to arrival"
        aria-valuemin={overhead + MIN_DRIVE}
        aria-valuemax={maxT}
        aria-valuenow={total}
        aria-valuetext={`${clock(total)} call to arrival, ${Math.round(100 * (share ?? 0))}% reached`}
        onKeyDown={onKey}
        onPointerDown={(e) => {
          dragging.current = true;
          e.currentTarget.setPointerCapture(e.pointerId);
          setFromPointer(e);
        }}
        onPointerMove={(e) => dragging.current && setFromPointer(e)}
        onPointerUp={() => { dragging.current = false; }}
        onPointerCancel={() => { dragging.current = false; }}
      >
        {ticks}
        <path d={arc(START, START + SWEEP)} className="track" />
        <path d={arc(ang(0), ang(alarm))} className="seg-answer" />
        <path d={arc(ang(alarm), ang(overhead))} className="seg-turn" />
        <path d={arc(ang(overhead), ang(total))}
              className={`seg-drive${over ? " over" : ""}`} />
        <line x1={sx0} y1={sy0} x2={sx1} y2={sy1} className="standard" />
        <circle cx={hx} cy={hy} r="11" className="hand" />
        <circle cx={hx} cy={hy} r="3.5" className="hand-pip" />

        <text x={C} y={C - 2} textAnchor="middle" className="dial-figure">
          {share == null ? "—" : (100 * share).toFixed(1)}
          <tspan className="dial-pct">%</tspan>
        </text>
        <text x={C} y={C + 22} textAnchor="middle" className="dial-sub">
          reached in {clock(total)}
        </text>
      </svg>
      <div className="dial-foot">
        <span><i className="k-answer" />Answer {alarm}s</span>
        <span><i className="k-turn" />Turn out {turnout}s</span>
        {thresholdS !== budget ? (
          <button className="linkish" onClick={() => setThresholdS(budget)}>
            Back to {clock(standard)}
          </button>
        ) : (
          <span className="dial-std">{svc?.standard ?? "standard"}</span>
        )}
      </div>
    </div>
  );
}
