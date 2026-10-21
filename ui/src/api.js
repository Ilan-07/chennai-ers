// Every number this console shows comes from the service. There is no local
// model, no cached fixture and no client-side arithmetic on coverage: if the API
// cannot answer, the console says so rather than drawing something plausible.

const base = "";

async function get(path) {
  const r = await fetch(`${base}${path}`);
  if (!r.ok) throw new Error(`${path} -> ${r.status} ${r.statusText}`);
  return r.json();
}

async function post(path, body) {
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(`${path} -> ${r.status} ${detail.slice(0, 200)}`);
  }
  return r.json();
}

// `p` is the study-area profile. It is threaded through every call rather than
// held as module state, because a stale profile on one endpoint would mix a GCC
// numerator with a metro denominator and the result would look plausible.
export const api = {
  profiles: () => get("/api/profiles"),
  evidence: (p) => get(`/api/evidence?profile=${p}`),
  meta: (p) => get(`/api/meta?profile=${p}`),
  cells: (p) => get(`/api/cells?profile=${p}`),
  basemap: (p) => get(`/api/basemap?profile=${p}`),
  stations: (p) => get(`/api/stations?profile=${p}`),
  candidates: (svc, p) => get(`/api/candidates/${svc}?profile=${p}`),
  coverage: (svc, scenario, thresholdS, p) =>
    get(`/api/coverage/${svc}?profile=${p}&scenario=${scenario}` +
        `&threshold_s=${Math.round(thresholdS)}`),
  // What hand-placed stations reach, per station. At the SERVICE budget, not
  // the threshold slider -- the response says so and the readout repeats it.
  reach: (svc, sites, scenario, p, mode = "station") =>
    get(`/api/reach/${svc}?profile=${p}&scenario=${scenario}` +
        `&sites=${sites.join(",")}&mode=${mode}`),
  // Peak-hour ambulance posts (step 15b). 404 where the build has none, which
  // the console reads as "this study area does not offer posts".
  staging: (svc, p) => get(`/api/staging/${svc}?profile=${p}`),
  // Which cells a road condition takes out of the standard, against a base.
  compare: (svc, scenario, thresholdS, p, base = "dry") =>
    get(`/api/compare/${svc}?profile=${p}&scenario=${scenario}&base=${base}` +
        `&threshold_s=${Math.round(thresholdS)}`),
  nearest: (svc, scenario, p) =>
    get(`/api/nearest/${svc}?profile=${p}&scenario=${scenario}`),
  optimise: (body) => post("/api/optimise", body),
  exportUrl: (svc, scenario, thresholdS, sites, p, mode = "station") =>
    `/api/export.csv?profile=${p}&svc=${svc}&scenario=${scenario}` +
    `&threshold_s=${Math.round(thresholdS)}&sites=${sites.join(",")}&mode=${mode}`,
};

export const fmtPct = (x) => `${(100 * x).toFixed(1)}%`;
export const fmtMin = (s) => `${(s / 60).toFixed(s % 60 === 0 ? 0 : 1)} min`;
export const fmtInt = (x) => Math.round(x).toLocaleString("en-IN");
