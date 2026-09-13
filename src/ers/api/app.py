"""The coverage and siting service. Build step 19.

The DA-1 deck promised a FastAPI service with a React/Leaflet console talking to
it over REST, and `docs/deck-figures.md` carried that claim as NOT BUILT for as
long as the project shipped a single static HTML file. This is the service.

Two rules hold it to the rest of the project:

  * **It serves artefacts, it does not recompute them.** Every coverage number
    comes from `ui_data.json`, which `scripts/export_ui_data.py` writes with the
    same pipeline code that writes the reports. A visitor cannot be shown a
    figure that no run produced.
  * **Siting is solved live, with the real optimiser.** `POST /api/optimise`
    builds a `SitingProblem` over the scenario's own coverage matrix and runs
    greedy plus the exact MIP, so what the console reports is a proven bound and
    not a JavaScript approximation of one.

Run it with `make api` (uvicorn, port 8000). The built React console is served
at `/` when `ui/dist` exists.
"""
from __future__ import annotations

import csv
import io
import json
import time
from typing import Annotated, Literal, TypeAlias

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ers.api.bundle import (PROFILES, SERVICES, Bundle, get_bundle,
                            profile_info)
from ers.model.problem import SitingProblem
from ers.optimise import exact, greedy

MAX_K = 20
EXACT_TIME_LIMIT_S = 20.0

app = FastAPI(
    title="Chennai emergency response — coverage and siting",
    description=__doc__ or "",
    version="0.1.0",
)


def bundle(profile: str = "gcc") -> Bundle:
    """The build being asked about. `?profile=metro` selects the wider study area."""
    if profile not in PROFILES:
        raise HTTPException(422, f"unknown profile {profile!r}; have {list(PROFILES)}")
    try:
        return get_bundle(profile=profile)
    except FileNotFoundError as e:      # a missing build is a server fault, not a 404
        raise HTTPException(status_code=503, detail=str(e)) from e


Dep: TypeAlias = Annotated[Bundle, Depends(bundle)]
Service: TypeAlias = Literal["ems", "fire"]


def _service(b: Bundle, svc: str) -> dict:
    try:
        return b.service(svc)
    except KeyError:
        raise HTTPException(404, f"unknown service {svc!r}; have {list(SERVICES)}")


def _scenario(b: Bundle, svc: str, scen: str) -> dict:
    try:
        return b.scenario(svc, scen)
    except KeyError:
        raise HTTPException(404, f"unknown scenario {scen!r}; have {b.scenarios(svc)}")


# --------------------------------------------------------------------- meta

@app.get("/api/profiles", tags=["meta"])
def profiles() -> dict:
    """The study areas this service can answer for, and what each one is.

    Two profiles are not two versions of one answer. Their denominators differ by
    3.2 M people, so a figure from one is not comparable with a figure from the
    other, and the caveats travel with the row.
    """
    from ers.api.bundle import profile_dir
    from pathlib import Path
    out = []
    for key in PROFILES:
        built = (profile_dir(Path("."), key) / "ui_data.json").exists()
        out.append({"profile": key, "built": built, **profile_info(".", key)})
    return {"profiles": out, "default": "gcc"}


@app.get("/api/evidence", tags=["meta"])
def evidence(profile: str = "gcc") -> dict:
    """How the numbers were arrived at, read from the project's own artefacts.

    A reviewer assessing whether to believe this needs the gates, the decisions
    and the experiments — and until now those existed only in the repository, so
    the interface showed conclusions with no way to inspect their basis. Nothing
    here is written by hand: gates are evaluated live, decision records are read
    off disk, and experiment verdicts come from the JSON each arm wrote.
    """
    import re
    from dataclasses import asdict
    from pathlib import Path

    from ers.gates import evaluate

    if profile not in PROFILES:
        raise HTTPException(422, f"unknown profile {profile!r}; have {list(PROFILES)}")
    root = Path(".")
    results = [asdict(r) for r in evaluate(root, PROFILES[profile]["subdir"])]
    by_kind: dict[str, list] = {}
    for r in results:
        by_kind.setdefault(r.get("severity", "OTHER"), []).append(r)
    not_evaluated = sum(1 for r in results if r.get("value") == "not evaluated")

    adrs = []
    for f in sorted((root / "docs" / "adr").glob("*.md")):
        head = f.read_text().splitlines()[0].lstrip("# ").strip()
        num, _, title = head.partition("—")
        adrs.append({"id": num.strip(), "title": title.strip() or head, "file": f.name})

    arms = []
    for f in sorted((root / "data" / "interim" / "experiments").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue          # a half-written arm is skipped; a bug is not
        if "experiment" not in d:
            continue          # the per-sweep scratch files carry no verdict
        span = next((v for k, v in d.items()
                     if k.endswith("span_points") and isinstance(v, (int, float))), None)
        arms.append({
            "arm": f.stem,
            "experiment": d["experiment"],
            "assumption": d.get("assumption"),
            "effect_points": span,
            "verdict": d.get("verdict_vs_noise_floor"),
        })

    return {
        "profile": profile,
        "gates": {
            "passed": sum(1 for r in results if r["passed"]),
            "total": len(results),
            "not_evaluated": not_evaluated,
            "by_kind": by_kind,
        },
        "decisions": adrs,
        "experiments": sorted(arms, key=lambda a: -(a["effect_points"] or 0)),
    }


@app.get("/api/health", tags=["meta"])
def health(b: Dep) -> dict:
    """Liveness plus the identity of the build being served."""
    return {"status": "ok",
            "profile": b.profile,
            "run_id": b.baseline.get("run_id"),
            "stations_signature": b.baseline.get("stations_signature"),
            "publication_basis": b.ui["meta"].get("publication_basis"),
            "services": list(SERVICES)}


@app.get("/api/meta", tags=["meta"])
def meta(b: Dep) -> dict:
    """Everything the console needs before it can draw anything.

    The publication basis travels with it deliberately: a client that renders a
    coverage figure without the waiver terms is showing a number this project
    does not stand behind on its own.
    """
    return {
        "profile": b.profile,
        "profile_info": profile_info(b.root, b.profile),
        "city": b.ui["meta"],
        "publication": b.publication(),
        "services": {
            svc: {
                "label": "Ambulance (108 EMS)" if svc == "ems" else "Fire engine (TNFRS)",
                "budget_s": b.service(svc)["budget_s"],
                "standard": b.service(svc)["standard"],
                "t_alarm_s": b.service(svc)["t_alarm_s"],
                "t_turnout_s": b.service(svc)["t_turnout_s"],
                "scenarios": b.scenarios(svc),
                "uncertainty": b.service(svc)["uncertainty"],
                "candidates": len(b.service(svc)["candidates"]),
                "total_demand": b.total_demand[svc],
            } for svc in SERVICES
        },
        "hex": b.ui["hex"],
        "wards": b.ui["wards"],
        "flood_extent": b.flood_extent(),
    }


@app.get("/api/basemap", tags=["meta"])
def basemap(b: Dep) -> dict:
    """Ward and zone outlines, as the build exported them."""
    return b.basemap


@app.get("/api/cells", tags=["data"])
def cells(b: Dep) -> dict:
    """Demand cells: centroid, population and ward, as parallel arrays."""
    return b.ui["cells"]


@app.get("/api/stations", tags=["data"])
def stations(b: Dep) -> dict:
    """The station inventory, each with how its position was established."""
    return {"stations": b.ui["stations"],
            "note": b.ui["meta"].get("basis_note")}


@app.get("/api/candidates/{svc}", tags=["data"])
def candidates(svc: Service, b: Dep) -> dict:
    return {"service": svc, "candidates": _service(b, svc)["candidates"]}


# ----------------------------------------------------------------- coverage

@app.get("/api/coverage/{svc}", tags=["coverage"])
def coverage(
    svc: Service,
    b: Dep,
    scenario: str = "dry",
    threshold_s: Annotated[int | None, Query(ge=60, le=1800)] = None,
) -> dict:
    """Per-cell response time and the coverage share it implies.

    `threshold_s` re-cuts the SAME routed response times at a different budget,
    which is what the threshold slider does. It does not re-route: a threshold
    above the longest exhaustive sweep would be answered from truncated data, so
    unreachable cells stay unreachable at every threshold.
    """
    sc = _scenario(b, svc, scenario)
    resp = b.response_s(svc, scenario)
    budget = float(_service(b, svc)["budget_s"])
    thr = float(threshold_s if threshold_s is not None else budget)

    demand = b.demand[svc]
    reachable = resp >= 0
    covered = reachable & (resp <= thr)
    total = float(demand.sum())

    ward = b.ward_of
    by_ward: dict[int, dict] = {}
    for w in np.unique(ward):
        m = ward == w
        dw = float(demand[m].sum())
        # The fastest cell in the area. Without it a reader cannot tell an area
        # that misses the budget by six seconds from one that misses by three
        # minutes -- both report 0.0% covered, and only one of them is a siting
        # problem rather than a rounding one.
        reach = resp[m & reachable]
        by_ward[int(w)] = {
            "demand": round(dw, 1),
            "covered_share": round(float(demand[m & covered].sum() / dw), 4) if dw else 0.0,
            "fastest_s": round(float(reach.min()), 1) if reach.size else None,
        }

    return {
        "service": svc,
        "scenario": scenario,
        "threshold_s": thr,
        "budget_s": budget,
        "at_service_budget": thr == budget,
        "scenario_weight": sc["weight"],
        "report_only": sc["report_only"],
        "response_s": sc["resp"],
        "covered_share": round(float(demand[covered].sum() / total), 4),
        "covered_demand": round(float(demand[covered].sum()), 1),
        "total_demand": round(total, 1),
        "unreachable_cells": int((~reachable).sum()),
        "baseline_share_at_budget": sc["baseline_share"],
        "by_ward": by_ward,
        "uncertainty": _service(b, svc)["uncertainty"],
        "publication_basis": b.ui["meta"].get("publication_basis"),
        "publication": b.publication(),
    }


@app.get("/api/nearest/{svc}", tags=["coverage"])
def nearest(svc: Service, b: Dep, scenario: str = "dry") -> dict:
    """Which existing stations reach each cell first, and in how long.

    This is what makes a selected ward explicable rather than merely coloured:
    the answer to "why is this ward red" is a list of the stations that are
    closest to it and the minutes each one needs.
    """
    sc = _scenario(b, svc, scenario)
    return {"service": svc, "scenario": scenario, "topk": sc["topk"],
            "who": sc["top_who"], "seconds": sc["top_s"]}


@app.get("/api/reach/{svc}", tags=["coverage"])
def reach(svc: Service, b: Dep, sites: str, scenario: str = "dry") -> dict:
    """What a hand-placed station would actually reach, per station.

    Placing a site by hand and pressing solve answers "how much does the whole
    plan gain". It does not answer the question a planner asks first, which is
    "was MY station worth putting there" -- and with several placed by hand the
    optimiser's single gain figure cannot be attributed to any one of them.

    Reach here is the candidate's own column of the coverage matrix: the cells it
    puts inside the service budget, split into ground the existing network
    already covers and ground it does not. The second number is the one that
    matters; a station placed on top of existing coverage reaches a great many
    people and adds nobody.

    AT THE SERVICE BUDGET, NOT THE SLIDER. The matrix is built once at the
    service's own budget, so this cannot answer "what would it reach in 6
    minutes" without re-routing. The response says which clock it used rather
    than letting the caller assume it followed the threshold.
    """
    try:
        want = [int(x) for x in sites.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, f"sites must be comma-separated integers: {sites!r}")
    M = b.coverage_matrix(svc, scenario)
    n_cand = M.shape[1]
    bad = [j for j in want if not 0 <= j < n_cand]
    if bad:
        raise HTTPException(422, f"candidate id(s) out of range 0..{n_cand - 1}: {bad}")

    pre = b.precovered(svc, scenario)
    demand = np.asarray(b.ui["cells"]["pop"], dtype="float64")
    cand = b.service(svc)["candidates"]
    budget = float(b.service(svc)["budget_s"])

    col = M.tocsc()
    out, union = [], np.zeros(M.shape[0], dtype=bool)
    for j in want:
        hit = np.zeros(M.shape[0], dtype=bool)
        hit[col.indices[col.indptr[j]:col.indptr[j + 1]]] = True
        new = hit & ~pre
        union |= hit
        out.append({
            "site": j,
            "position": cand[j],
            "cells": int(hit.sum()),
            "demand": round(float(demand[hit].sum())),
            "new_cells": [int(i) for i in np.flatnonzero(new)],
            "new_demand": round(float(demand[new].sum())),
        })

    # Two hand-placed stations covering the same ground are worth less together
    # than apart, and nothing else on this screen would show it.
    combined_new = union & ~pre
    overlap = sum(r["demand"] for r in out) - float(demand[union].sum())
    return {
        "service": svc, "scenario": scenario,
        "budget_s": budget,
        "at_service_budget": True,
        "note": (f"Reach is measured at the {svc.upper()} service budget of "
                 f"{budget:.0f}s of travel, not at the threshold slider."),
        "sites": out,
        "combined": {
            "cells": int(union.sum()),
            "demand": round(float(demand[union].sum())),
            "new_cells": [int(i) for i in np.flatnonzero(combined_new)],
            "new_demand": round(float(demand[combined_new].sum())),
            "double_counted_demand": round(float(overlap)),
        },
    }


# ----------------------------------------------------------------- optimise

class OptimiseRequest(BaseModel):
    # A plain string validated against the registry, not a Literal: a Literal has
    # to be edited every time a profile is added, and the first time it was not,
    # the console could read a profile it could not optimise.
    profile: str = "gcc"
    service: Literal["ems", "fire"] = "ems"
    scenario: str = "dry"
    k: int = Field(3, ge=0, le=MAX_K)
    forced: list[int] = Field(default_factory=list,
                              description="candidate ids placed by hand; they are "
                                          "built first and k more are sited around them")
    forbidden: list[int] = Field(default_factory=list,
                                 description="candidate ids the optimiser may not use")
    exact_solve: bool = Field(True, description="also run the exact MIP for a proven bound")


@app.post("/api/optimise", tags=["siting"])
def optimise(req: OptimiseRequest, b: Dep) -> dict:
    """Solve the siting problem the caller just described.

    Manual placements are not a second algorithm: a forced site is folded into
    the precovered mask, so the optimiser sites `k` more around what the planner
    has already decided, and the reported gain is the gain over that decision.
    """
    svc, scen = req.service, req.scenario
    if req.profile not in PROFILES:
        raise HTTPException(422, f"unknown profile {req.profile!r}; have {list(PROFILES)}")
    # The body carries the profile so a POST cannot silently solve the wrong city.
    if req.profile != b.profile:
        b = bundle(req.profile)
    _scenario(b, svc, scen)
    M = b.coverage_matrix(svc, scen)
    demand = b.demand[svc]
    total = float(demand.sum())
    n_cand = M.shape[1]

    for name, ids in (("forced", req.forced), ("forbidden", req.forbidden)):
        bad = [i for i in ids if not 0 <= i < n_cand]
        if bad:
            raise HTTPException(422, f"{name} candidate ids out of range: {bad[:5]}")
    if set(req.forced) & set(req.forbidden):
        raise HTTPException(422, "a candidate cannot be both forced and forbidden")

    pre = b.precovered(svc, scen).copy()
    base_share = float(demand[pre].sum() / total)

    if req.forced:
        forced_cov = np.asarray(M[:, req.forced].sum(axis=1)).ravel() > 0
        pre = pre | forced_cov
    manual_share = float(demand[pre].sum() / total)

    forbidden = np.zeros(n_cand, dtype=bool)
    if req.forbidden:
        forbidden[req.forbidden] = True
    if req.forced:
        forbidden[req.forced] = True      # already built; not available again

    prob = SitingProblem(coverage=M, precovered=pre, demand=demand, k=req.k,
                         ward_of=b.ward_of, forbidden=forbidden)

    t0 = time.time()
    gs = greedy.solve(prob)
    out: dict = {
        "service": svc, "scenario": scen, "k": req.k,
        "baseline_share": round(base_share, 4),
        "with_manual_share": round(manual_share, 4),
        "forced": req.forced,
        "greedy": {
            "sites": [int(j) for j in gs.selected],
            "share": round((gs.baseline_covered + gs.objective) / total, 4),
            "guarantee": "at least (1 - 1/e) of the optimal gain",
            "seconds": round(gs.wall_s, 3),
        },
    }

    if req.exact_solve:
        ex = exact.solve(prob, time_limit_s=EXACT_TIME_LIMIT_S)
        out["exact"] = {
            "sites": [int(j) for j in ex.selected],
            "share": round((ex.baseline_covered + ex.objective) / total, 4),
            "proven_optimal": bool(ex.proven_optimal),
            "proven_gap": ex.gap,
            "status": ex.status,
            "optimality": ex.optimality_note,
            "seconds": round(ex.wall_s, 3),
        }
        out["greedy_gap_vs_exact"] = round(
            (ex.objective - gs.objective) / max(ex.objective, 1e-9), 5)

    sites = out.get("exact", out["greedy"])["sites"]
    cand = _service(b, svc)["candidates"]
    out["site_positions"] = [cand[j] for j in sites]

    # Which cells the chosen sites actually add. Without this the console can
    # report a share that went up and show a map that did not move, which is the
    # difference between "the gap shrank" and "a number changed".
    built = list(req.forced) + list(sites)
    if built:
        after = np.asarray(M[:, built].sum(axis=1)).ravel() > 0
        newly = np.flatnonzero(after & ~b.precovered(svc, scen))
        out["newly_covered_cells"] = [int(i) for i in newly]
    else:
        out["newly_covered_cells"] = []
    out["uncertainty"] = _service(b, svc)["uncertainty"]
    out["publication_basis"] = b.ui["meta"].get("publication_basis")
    out["profile"] = b.profile
    out["wall_s"] = round(time.time() - t0, 3)
    return out


@app.get("/api/siting/{svc}", tags=["siting"])
def shipped_siting(svc: Service, b: Dep) -> dict:
    """The siting curve the build published, k = 1..10, for comparison."""
    return {"service": svc, "exact_by_k": _service(b, svc)["exact"]}


@app.get("/api/robust/{svc}", tags=["siting"])
def robust(svc: Service, b: Dep) -> dict:
    """Step 15: siting against the scenario distribution rather than one network."""
    try:
        return b.report(f"robust_{svc}_k10")
    except FileNotFoundError:
        raise HTTPException(404, f"no robust result for {svc}; run: make all")


# ------------------------------------------------------------------- export

@app.get("/api/export.csv", tags=["export"])
def export_csv(
    b: Dep,
    svc: Service = "ems",
    scenario: str = "dry",
    threshold_s: Annotated[int | None, Query(ge=60, le=1800)] = None,
    sites: Annotated[str, Query(description="comma-separated candidate ids")] = "",
) -> StreamingResponse:
    """The export brief: what was asked, what it rests on, and what it claims."""
    cov = coverage(svc, b, scenario=scenario, threshold_s=threshold_s)
    cand = _service(b, svc)["candidates"]
    chosen = [int(s) for s in sites.split(",") if s.strip().isdigit()]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["chennai-ers export"])
    w.writerow(["run_id", b.baseline.get("run_id")])
    w.writerow(["stations_signature", b.baseline.get("stations_signature")])
    w.writerow(["publication_basis", b.ui["meta"].get("publication_basis")])
    w.writerow(["basis_note", b.ui["meta"].get("basis_note")])
    w.writerow([])
    w.writerow(["service", svc, "scenario", scenario, "threshold_s", cov["threshold_s"]])
    w.writerow(["covered_share", cov["covered_share"]])
    w.writerow(["covered_demand", cov["covered_demand"]])
    w.writerow(["total_demand", cov["total_demand"]])
    unc = cov["uncertainty"]
    w.writerow(["uncertainty_points_if_listings_correct",
                unc["assumed_correct"]["spread_points"]])
    w.writerow(["uncertainty_points_if_listings_wrong",
                unc["if_unconfirmed_wrong"]["spread_points"]])
    w.writerow([])
    w.writerow(["proposed_site_id", "lat", "lon"])
    for j in chosen:
        if 0 <= j < len(cand):
            w.writerow([j, cand[j]["lat"], cand[j]["lon"]])
    w.writerow([])
    w.writerow(["ward_id", "demand", "covered_share"])
    for ward_id, row in sorted(cov["by_ward"].items()):
        w.writerow([ward_id, row["demand"], row["covered_share"]])

    buf.seek(0)
    name = f"chennai-ers-{svc}-{scenario}-{int(cov['threshold_s'])}s.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------- console
#
# Mounted last so it cannot shadow /api. Absent before `make ui`, which is not an
# error: the API is usable on its own and the OpenAPI docs live at /docs.
def mount_console(app: FastAPI, root: str = ".") -> bool:
    from pathlib import Path
    dist = Path(root) / "ui" / "dist"
    if not (dist / "index.html").exists():
        return False
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="console")
    return True


mount_console(app)
