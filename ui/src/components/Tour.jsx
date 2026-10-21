import { useEffect } from "react";
import { fmtInt } from "../api.js";
import { clock } from "./Dial.jsx";

/* The demo, as a feature. Five steps that drive the console through the
 * project's argument: each step SETS the state it talks about (service, clock,
 * road condition, compare view, a solve) and its caption reads the live figure
 * rather than a typed one, so the tour cannot drift from the model -- the same
 * rule the brief follows. A presenter clicks Next; the map does the talking.
 */
export const STEPS = [
  {
    title: "Seven minutes, call to arrival",
    apply: (a) => a.reset(),
    say: ({ coverage, budgetTotal }) => coverage &&
      <>An ambulance reaches <b>{(100 * coverage.covered_share).toFixed(1)}%</b> of
        Chennai within {clock(budgetTotal)}. Two of those minutes go on answering the
        call and getting the crew rolling — the dial shows where the time goes.</>,
  },
  {
    title: "One more minute",
    apply: (a) => a.setThresholdS(a.budget + 60),
    say: ({ coverage, scenarioShares }) => coverage && scenarioShares.dry != null &&
      <>Give the crew one more minute and coverage rises to{" "}
        <b>{(100 * coverage.covered_share).toFixed(1)}%</b>. Drag the clock yourself:
        the city re-colours under it. Brighter hexagons hold more people.</>,
  },
  {
    title: "Rush hour is worse than a flood",
    apply: (a) => { a.setThresholdS(a.budget); a.setScenario("peak"); },
    say: ({ scenarioShares }) => scenarioShares.peak != null &&
      <>At peak hour coverage falls to <b>{(100 * scenarioShares.peak).toFixed(1)}%</b>
        {scenarioShares.flood100 != null &&
          <> — lower than a hundred-year flood, which holds{" "}
            {(100 * scenarioShares.flood100).toFixed(1)}%</>}. Congestion, not water,
        is the case a plan has to survive.</>,
  },
  {
    title: "Where congestion bites",
    apply: (a) => { a.setScenario("peak"); a.setComparing(true); },
    say: ({ comparison }) => comparison &&
      <>Red is everyone peak hour pushes outside the standard:{" "}
        <b>{fmtInt(comparison.lost_demand)} people</b> who are in time on a dry day.
        It is the inner city, where the roads are full.</>,
  },
  {
    title: "Three ambulances, placed for the peak",
    apply: (a) => a.solvePosts(3),
    say: ({ result, staging }) => {
      const s = result?.mode === "staging" ? (result.exact ?? result.greedy) : null;
      const dry = staging?.dry_plan_at_peak?.find((r) => r.k === 3);
      return s && <>Three extra ambulances waiting at the right kerbs lift peak
        coverage to <b>{(100 * s.share).toFixed(1)}%</b>, proven optimal. The
        dry-day plan's three stations would add only{" "}
        {dry ? `${dry.gain_points_at_peak.toFixed(1)} points` : "a fraction of that"}.</>;
    },
  },
];

export default function Tour({ step, setStep, onClose, live }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "ArrowRight") setStep(Math.min(STEPS.length - 1, step + 1));
      if (e.key === "ArrowLeft") setStep(Math.max(0, step - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, setStep]);

  const s = STEPS[step];
  const body = s.say(live);
  const last = step === STEPS.length - 1;

  return (
    <div className="tour" role="dialog" aria-label="Guided tour" aria-live="polite">
      <div className="tour-progress" aria-hidden="true">
        {STEPS.map((_, i) => (
          <i key={i} className={i <= step ? "on" : ""} />
        ))}
      </div>
      <h2>{s.title}</h2>
      <p>{body || <span className="tour-wait">Working it out…</span>}</p>
      <div className="tour-nav">
        <button className="linkish" onClick={onClose}>End tour</button>
        <span className="tour-count">{step + 1} of {STEPS.length}</span>
        <button className="btn ghost small" disabled={step === 0}
                onClick={() => setStep(step - 1)}>Back</button>
        <button className="btn primary small"
                onClick={() => (last ? onClose() : setStep(step + 1))}>
          {last ? "Explore" : "Next"}
        </button>
      </div>
    </div>
  );
}
