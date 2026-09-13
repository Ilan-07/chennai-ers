"""Build artefacts, loaded once and served. Build step 19.

The service is a VIEW over what `make all` produced, exactly as the static
console was: `scripts/export_ui_data.py` is still the only place that turns
routed results into UI-shaped data, so the API cannot disagree with the reports
by construction. What the API adds over a file on disk is the thing a file
cannot do -- solving a siting problem the visitor just typed, against the real
coverage matrix, with the real optimiser.

Nothing here recomputes routing. A request that would need a new isochrone is
refused rather than answered from a cheaper approximation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import sparse

SERVICES = ("ems", "fire")

# A profile is a study area, not a variant of one. The GCC build answers "can the
# corporation reach its residents in time"; the metro build answers the same
# question for the built-up city, which is 932 km2 and 10.8 M people. They share
# code and share nothing else -- different boundary, different demand surface,
# different station inventory -- so the service keeps them side by side and
# never averages or substitutes one for the other.
PROFILES = {
    "gcc": {"label": "Greater Chennai Corporation",
            "subdir": "", "area_km2": 426, "units": "200 wards",
            "note": "The corporation's own limits. Coverage is census-reconciled "
                    "throughout and every gate applies."},
    "full": {"label": "Chennai metropolitan settlement",
             "subdir": "full", "area_km2": 1581, "units": "200 wards + 213 H3 cells",
             "note": "The widest extent this project models: the contiguous settlement "
                     "at 500 people/km2, reaching Thiruporur, Kelambakkam, Chengalpattu "
                     "and Maraimalai Nagar. Every cell is reachable and the demand "
                     "surface matches the routed graph exactly. 22% of cells still sit "
                     "more than 300 m from a mapped road (A-14), so outer response "
                     "times carry a walk-to-road component. Population outside the GCC "
                     "is unreconciled GHS-POP; no flood scenarios; gates not run."},
    "metro": {"label": "Built-up Chennai metro",
              "subdir": "metro", "area_km2": 932, "units": "200 wards + 87 H3 cells",
              "note": "The contiguous urban centre, measured from GHS-POP. Includes "
                      "Tambaram, Pallavaram, Navalur and Siruseri. Population outside "
                      "the GCC is unreconciled GHS-POP; flood scenarios are absent "
                      "because the inundation layers stop at the GCC; the publish "
                      "gates have not been run against this profile."},
}


def profile_dir(root: str | Path, profile: str) -> Path:
    if profile not in PROFILES:
        raise KeyError(profile)
    base = Path(root) / "data" / "interim"
    sub = PROFILES[profile]["subdir"]
    return base / sub if sub else base


@dataclass(frozen=True)
class Bundle:
    root: Path
    profile: str
    ui: dict
    basemap: dict
    baseline: dict
    demand: dict[str, np.ndarray]
    ward_of: np.ndarray

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, root: str | Path = ".", profile: str = "gcc") -> "Bundle":
        root = Path(root)
        interim = profile_dir(root, profile)
        missing = [p.name for p in (interim / "ui_data.json", interim / "ui_basemap.json",
                                    interim / "baseline_report.json")
                   if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"{', '.join(missing)} absent for profile {profile!r} -- the API serves "
                f"build artefacts and will not invent them. Run: make all")

        ui = json.loads((interim / "ui_data.json").read_text())
        basemap = json.loads((interim / "ui_basemap.json").read_text())
        baseline = json.loads((interim / "baseline_report.json").read_text())

        # Per-service demand weights: fire is land-use weighted (A-07), EMS is
        # headcount, and using the wrong one silently changes every objective.
        import geopandas as gpd

        from ers.pipeline import demand_column

        cells = gpd.read_parquet(interim / "demand_cells.parquet")
        demand = {s: np.asarray(demand_column(cells, s), dtype="float64") for s in SERVICES}
        ward_of = cells["ward_id"].to_numpy()

        return cls(root=root, profile=profile, ui=ui, basemap=basemap,
                   baseline=baseline, demand=demand, ward_of=ward_of)

    # ------------------------------------------------------------- accessors
    def service(self, svc: str) -> dict:
        if svc not in self.ui["services"]:
            raise KeyError(svc)
        return self.ui["services"][svc]

    def scenario(self, svc: str, scen: str) -> dict:
        scs = self.service(svc)["scenarios"]
        if scen not in scs:
            raise KeyError(scen)
        return scs[scen]

    def scenarios(self, svc: str) -> list[str]:
        return list(self.service(svc)["scenarios"])

    def response_s(self, svc: str, scen: str) -> np.ndarray:
        """Per-cell response seconds from the existing network; -1 unreachable."""
        return np.asarray(self.scenario(svc, scen)["resp"], dtype="float64")

    def coverage_matrix(self, svc: str, scen: str) -> sparse.csr_matrix:
        """|cells| x |candidates| reachability within the service budget."""
        sc = self.scenario(svc, scen)
        indptr = np.asarray(sc["cov_indptr"], dtype="int32")
        indices = np.asarray(sc["cov_indices"], dtype="int32")
        n_cells = len(indptr) - 1
        n_cand = len(self.service(svc)["candidates"])
        data = np.ones(len(indices), dtype=bool)
        return sparse.csr_matrix((data, indices, indptr), shape=(n_cells, n_cand))

    def precovered(self, svc: str, scen: str) -> np.ndarray:
        """Cells the EXISTING stations reach within budget under this scenario."""
        resp = self.response_s(svc, scen)
        budget = float(self.service(svc)["budget_s"])
        return (resp >= 0) & (resp <= budget)

    def report(self, name: str) -> dict:
        p = profile_dir(self.root, self.profile) / f"{name}.json"
        if not p.exists():
            raise FileNotFoundError(name)
        return json.loads(p.read_text())

    def flood_extent(self) -> dict:
        """Which flood scenarios this study area may honestly be asked, and why.

        The console used to explain the metro's missing floods with a typed
        sentence. A sentence cannot go stale visibly: a new layer covering
        Tambaram would have changed nothing. This reads the measurement instead,
        so the reason carries its own number and updates when the data does.
        """
        f = Path(self.root) / "data/interim/flood_extent.json"
        try:
            rep = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            rep = {}
        prof = rep.get("profiles", {}).get(self.profile)
        if not prof:
            return {"measured": False,
                    "note": "flood-layer extent has not been measured for this "
                            "study area (scripts/flood_extent_report.py)"}
        refused = {k: v for k, v in prof["scenarios"].items()
                   if v.get("network_state") == "flood" and not v["applicable"]}
        # Grouped by the test that refused them, because three return-period
        # layers refused for the same reason are one fact, not three. The
        # per-scenario detail stays available for anyone who wants it.
        groups: dict[str, dict] = {}
        for k, v in sorted(refused.items()):
            g = groups.setdefault(v.get("test", "other"), {
                "test": v.get("test", "other"), "scenarios": [],
                "domain_share_min": 1.0, "domain_share_max": 0.0,
                "outside_km2_max": 0.0, "reason": v["reason"]})
            g["scenarios"].append(k)
            share = v.get("domain_covers_study_area")
            if share is not None:
                g["domain_share_min"] = min(g["domain_share_min"], share)
                g["domain_share_max"] = max(g["domain_share_max"], share)
            g["outside_km2_max"] = max(g["outside_km2_max"],
                                       v.get("study_area_outside_domain_km2") or 0.0)
        return {
            "measured": True,
            "study_area_km2": prof["study_area_km2"],
            "applicable": prof["applicable"],
            "refused": sorted(refused),
            "why": {k: v["reason"] for k, v in refused.items()},
            "groups": list(groups.values()),
        }

    def publication(self) -> dict:
        """What a reader is allowed to do with this build's numbers.

        Every profile answers this, not only the one with a waiver. The metro and
        full builds carry `publication_basis: blocked` and PROVISIONAL true, and
        a console that rendered their coverage without saying so would reproduce
        at the UI layer exactly the failure the gates exist to prevent.
        """
        meta = self.ui.get("meta", {})
        basis = meta.get("publication_basis", "provisional")
        gated = self.profile == "gcc"
        if basis == "waived":
            state, headline = "waived", "Published under a recorded waiver"
        elif basis == "surveyed":
            state, headline = "cleared", "Published on surveyed positions"
        else:
            state, headline = "blocked", "Provisional — not cleared for publication"
        return {
            "state": state,
            "headline": headline,
            "provisional": bool(meta.get("PROVISIONAL", state != "waived")),
            "note": meta.get("basis_note") or (
                "No waiver covers this study area and the publish gates have not been "
                "run against it. Figures here are indicative and must not be quoted as "
                "settled." if state == "blocked" else None),
            "gates_run": gated,
        }

    @property
    def total_demand(self) -> dict[str, float]:
        return {s: float(self.demand[s].sum()) for s in SERVICES}


@lru_cache(maxsize=8)
def _load_cached(root: str, profile: str, stamp: float) -> Bundle:
    return Bundle.load(root, profile)


def get_bundle(root: str = ".", profile: str = "gcc") -> Bundle:
    """The current build, loaded once and re-loaded when the build changes.

    Keying the cache on the export's mtime matters more here than the microsecond
    it costs: a rebuild while the server is up would otherwise serve figures from
    the previous run under the new run's banner, which is the exact class of
    silent staleness `test_artefact_freshness` exists to catch elsewhere.
    """
    export = profile_dir(root, profile) / "ui_data.json"
    stamp = export.stat().st_mtime if export.exists() else 0.0
    return _load_cached(root, profile, stamp)


def cache_clear() -> None:
    _load_cached.cache_clear()


get_bundle.cache_clear = cache_clear      # type: ignore[attr-defined]
