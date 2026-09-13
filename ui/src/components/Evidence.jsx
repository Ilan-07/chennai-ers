import { useEffect, useState } from "react";
import { api, fmtPct } from "../api.js";

/* The basis, not the conclusion.
 *
 * A reviewer's question is not "what did it find" but "why should I believe
 * it". That evidence existed only in the repository — gates, decision records,
 * experiment verdicts — so the interface showed findings with no way to inspect
 * them. Everything below is read live from the project's own artefacts.
 */
export default function Evidence({ profiles, profile, onClose }) {
  const [ev, setEv] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setEv(null);
    api.evidence(profile).then(setEv).catch((e) => setErr(String(e)));
  }, [profile]);

  const gates = ev?.gates;
  const order = ["build", "publication", "reported"];

  return (
    <div className="brief-scrim" onClick={onClose}>
      <div className="brief evidence" role="dialog" aria-label="Method and evidence"
           onClick={(e) => e.stopPropagation()}>
        <button className="brief-close" onClick={onClose} aria-label="Close">×</button>

        <p className="brief-kicker">Method and evidence</p>
        <h2>Why these numbers can be checked</h2>

        {err && <p className="brief-note">Could not read the evidence: {err}</p>}
        {!ev && !err && <p className="brief-note">Reading the project's artefacts…</p>}

        {profiles?.length > 1 && (
          <>
            <h3 className="ev-h">The same question at three extents</h3>
            <table className="ev-table">
              <thead>
                <tr><th>Study area</th><th>Area</th><th>People</th><th>Reached</th></tr>
              </thead>
              <tbody>
                {profiles.filter((p) => p.built && p.coverage).map((p) => (
                  <tr key={p.profile}>
                    <td>{p.label}</td>
                    <td className="num">{p.area_km2.toLocaleString("en-IN")} km²</td>
                    <td className="num">
                      {(p.coverage.total_demand / 1e6).toFixed(2)} M
                    </td>
                    <td className="num">{fmtPct(p.coverage.covered_share)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="brief-note">
              Coverage falls as the boundary widens because the corporation holds
              most of the stations. The same network, asked about more of the city.
            </p>
          </>
        )}

        {gates && (
          <>
            <h3 className="ev-h">
              Publish gates — {gates.passed} of {gates.total} pass
              {gates.not_evaluated > 0 && `, ${gates.not_evaluated} could not run`}
            </h3>
            <ul className="ev-gates">
              {order.flatMap((kind) => (gates.by_kind[kind] ?? []).map((g) => (
                <li key={g.id}
                    className={g.passed ? "ok" : (g.value === "not evaluated" ? "skip" : `bad ${kind}`)}>
                  <span className="gate-mark">
                    {g.passed ? "pass" : g.value === "not evaluated" ? "—" : "fail"}
                  </span>
                  <span className="gate-id">{g.id}</span>
                  <span className="gate-kind">
                    {g.value === "not evaluated" ? "no artefact" : kind}
                  </span>
                </li>
              )))}
            </ul>
            <p className="brief-note">
              A failing <b>build</b> gate stops the build. A <b>publication</b> gate
              failing records that the stations are not surveyed — a fact about the
              evidence, not a defect in the code.
              {gates.not_evaluated > 0 && (
                <> The gates marked <b>no artefact</b> had nothing to read in this
                study area: it has no flood scenarios and no routing validation of
                its own. They are shown as unrun rather than counted as passing.</>
              )}
            </p>
          </>
        )}

        {ev?.experiments?.length > 0 && (
          <>
            <h3 className="ev-h">What was actually tested</h3>
            <table className="ev-table">
              <thead>
                <tr><th>Assumption</th><th>Moves coverage by</th><th>Against the noise floor</th></tr>
              </thead>
              <tbody>
                {ev.experiments.map((a) => (
                  <tr key={a.arm}>
                    <td>{a.assumption} · {a.arm}</td>
                    <td className="num">
                      {a.effect_points == null ? "—" : `${a.effect_points.toFixed(2)} pts`}
                    </td>
                    <td className="verdict">
                      {a.verdict ? (a.verdict.startsWith("ABOVE") ? "clears it" : "inside it") : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="brief-note">
              Every assumption in the model has an experiment that measures what it
              is worth. Only two effects clear the station-position noise floor —
              the rest are smaller than the uncertainty about where the stations are.
            </p>
          </>
        )}

        {ev?.decisions?.length > 0 && (
          <>
            <h3 className="ev-h">Decisions on the record</h3>
            <ul className="ev-adr">
              {ev.decisions.map((d) => (
                <li key={d.file}><b>{d.id}</b> {d.title}</li>
              ))}
            </ul>
          </>
        )}

        <button className="btn primary brief-go" onClick={onClose}>Back to the map</button>
      </div>
    </div>
  );
}
