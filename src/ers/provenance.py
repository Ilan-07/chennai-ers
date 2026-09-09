"""The provenance block every report carries.

ASSUMPTIONS.md states the rule: "No number appears in any output unless it was
produced by a run ID that can be replayed." (Finding F-02.) Until the 2026-09
repair the rule was asserted but not built. Eight of roughly twenty-four reports
carried a `stations_signature`; the rest recorded nothing about the inputs they
were computed from, and two of them went stale without anyone noticing:

  * `stations_qa.json` published `locality: 29` against an inventory that had
    said `google_maps_poi: 29` for a day, and its `plausibility` labels
    described positions that had been discarded;
  * `survey_priority.json` -- the ranking that decides which stations to visit
    first -- was computed before the positions it ranks were replaced.

Both are invisible to a test that only checks numbers agree, because each file
was internally consistent. They are visible the moment every artefact records
WHICH inputs produced it and a test compares that against the inputs on disk.

Use `stamp()` in any script that writes a report:

    report = {**stamp(config=cfg, inputs=[ds.sha256], stations=st), "results": ...}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ers.hashing import config_hash, git_commit, run_id

# Reports whose numbers depend on where the stations are. Anything on this list
# must carry a `stations_signature`, and `tests/integration/test_artefact_freshness`
# fails the build if it does not match the current inventory.
STATION_DEPENDENT = (
    "baseline_report.json",
    "degradation_report.json",
    "optimise_ems.json",
    "optimise_fire.json",
    "frontier_ems.json",
    "frontier_fire.json",
    "equity_curve_ems.json",
    "equity_curve_fire.json",
    "robust_ems_k10.json",
    "robust_fire_k10.json",
    "sensitivity_stations_ems.json",
    "sensitivity_stations_fire.json",
    "sensitivity_mixed_ems.json",
    "sensitivity_mixed_fire.json",
    "survey_priority.json",
    "routing_validation.json",
    "calibration_stage4.json",
    "stations_qa.json",
)


def service_bases(service: str, stations: "pd.DataFrame") -> dict:
    """Which vehicle bases a service's coverage was actually routed from.

    THE EMS RESULTS ARE NOT COMPUTED FROM AMBULANCE BASES. Every row of the
    authoritative inventory is `service: fire`, and `load_service` reads it
    without filtering, so EMS coverage is the FIRE-STATION network scored
    against an ambulance standard: a 7-minute SFAC target, a 60 s turnout and
    the EMS speed multipliers, dispatched from fire stations.

    That is a defensible modelling choice -- the 108/EMRI standby points are
    unpublished and absent from OSM (an Overpass query over the GCC bbox
    returns zero `emergency=ambulance_station` features) -- but it is a
    substitution, not a detail, and it was previously recorded only as a
    sentence in ASSUMPTIONS.md while the headline "61.75% EMS coverage" was
    published bare.

    Returning it as a required block, asserted by `gates.evaluate` and by
    `tests/integration/test_service_provenance`, is what makes it impossible to
    publish the number without the qualification attached to it.
    """
    n = len(stations)
    by_service = stations["service"].value_counts().to_dict() if "service" in stations else {}
    own = int(by_service.get(service, 0))

    if own == n:
        return {"source": "authoritative", "bases": n, "proxy": None,
                "by_service": by_service}
    return {
        "source": "none",
        "bases": n,
        "proxy": "fire_stations",
        "by_service": by_service,
        "note": (f"No {service.upper()} base inventory exists. Coverage is modelled "
                 f"from the {n} authoritative fire stations, using {service.upper()} "
                 f"turnout offsets, speed multipliers and response standard. The 108 "
                 f"ambulance standby points are not published and are absent from OSM."),
        "resolves_when": "EMRI supplies the 108 standby-point list",
    }


def config_bundle(service: str | None = None, root: str = ".") -> dict:
    """The configuration a routed result actually depends on.

    Hashing only the one parameter a script happens to have in a local variable
    produces a run id that collides across genuinely different runs. The speed
    table, the emergency multipliers and the alarm/turnout offsets all change
    the answer, so all of them belong in the hash.
    """
    import yaml

    paths = ["config/city/chennai.yml", "config/speeds/base.yml"]
    if service:
        paths.append(f"config/services/{service}.yml")
    out = {}
    for rel in paths:
        p = Path(root) / rel
        if p.exists():
            out[rel] = yaml.safe_load(p.read_text())
    return out


def stamp(
    *,
    config: Any,
    inputs: list[str] | None = None,
    seed: int | None = None,
    stations: "pd.DataFrame | None" = None,
    service: str | None = None,
    extra: Any = None,
) -> dict:
    """Everything needed to replay a result, as a dict to merge into a report."""
    from ers.pipeline import station_signature

    sig = station_signature(stations) if stations is not None else None
    ins = sorted(inputs or [])
    return {
        "run_id": run_id(inputs=ins + ([sig] if sig else []), config=config,
                         seed=seed, extra=extra),
        "code_commit": git_commit(),
        "config_hash": config_hash(config),
        "input_digests": ins,
        "seed": seed,
        **({"stations_signature": sig} if sig else {}),
        **({"bases": service_bases(service, stations)}
           if service and stations is not None else {}),
    }
