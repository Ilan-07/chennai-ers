"""Siting problem and solution types. Build step 11."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import sparse


@dataclass(frozen=True)
class SitingProblem:
    """Everything the optimiser needs, as arrays. No geometry, no I/O.

    coverage: |I| x |J| boolean CSR — cell i is covered by candidate j
    precovered: |I| bool — cell i is already covered by an existing station
    demand: |I| float — demand weight a_i
    """
    coverage: sparse.csr_matrix
    precovered: np.ndarray
    demand: np.ndarray
    k: int
    ward_of: np.ndarray | None = None
    land_feasible: np.ndarray | None = None
    equity_floor: float | None = None
    forbidden: np.ndarray | None = None

    def __post_init__(self) -> None:
        n_i, n_j = self.coverage.shape
        if self.precovered.shape != (n_i,):
            raise ValueError(f"precovered must be ({n_i},), got {self.precovered.shape}")
        if self.demand.shape != (n_i,):
            raise ValueError(f"demand must be ({n_i},), got {self.demand.shape}")
        if self.k < 0:
            raise ValueError("k must be non-negative")

    @property
    def n_cells(self) -> int:
        return self.coverage.shape[0]

    @property
    def n_candidates(self) -> int:
        return self.coverage.shape[1]

    def allowed(self) -> np.ndarray:
        """Candidates the optimiser may select."""
        ok = np.ones(self.n_candidates, dtype=bool)
        if self.land_feasible is not None:
            ok &= self.land_feasible
        if self.forbidden is not None:
            ok &= ~self.forbidden
        return ok


@dataclass(frozen=True)
class ScenarioCoverage:
    """One scenario's routed reachability. Coverage is a property of the NETWORK.

    A flood does not merely make cells slower to reach; it removes links, so a
    candidate that covers a cell on a dry day may not cover it at all under a
    100-year flood, and a cell precovered by an existing station may become
    unreachable. Both matrices therefore change per scenario, which is exactly
    why a single dry-day matrix cannot answer a siting question about flooding.
    """
    scenario: str
    weight: float
    coverage: sparse.csr_matrix     # |I| x |J| bool
    precovered: np.ndarray          # |I| bool
    report_only: bool = False
    stats: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RobustSitingProblem:
    """Site once, against a distribution of networks rather than one network.

    `scenarios` carries every scenario to be REPORTED. Only those with
    `report_only=False` and a positive weight enter an objective -- an extreme
    historical event is a stress test, not a design basis (Finding F-09), and
    that exclusion is structural here rather than something a caller must
    remember to do.
    """
    scenarios: tuple[ScenarioCoverage, ...]
    demand: np.ndarray
    k: int
    ward_of: np.ndarray | None = None
    land_feasible: np.ndarray | None = None
    forbidden: np.ndarray | None = None

    def __post_init__(self) -> None:
        if not self.scenarios:
            raise ValueError("at least one scenario is required")
        n_i = len(self.demand)
        n_j = self.scenarios[0].coverage.shape[1]
        for sc in self.scenarios:
            if sc.coverage.shape != (n_i, n_j):
                raise ValueError(
                    f"scenario {sc.scenario!r} coverage is {sc.coverage.shape}, "
                    f"expected {(n_i, n_j)}: every scenario must describe the SAME "
                    f"cells and the SAME candidate sites")
            if sc.precovered.shape != (n_i,):
                raise ValueError(f"scenario {sc.scenario!r} precovered must be ({n_i},)")
        if self.k < 0:
            raise ValueError("k must be non-negative")
        if len({sc.scenario for sc in self.scenarios}) != len(self.scenarios):
            raise ValueError("duplicate scenario ids")

    @property
    def n_cells(self) -> int:
        return len(self.demand)

    @property
    def n_candidates(self) -> int:
        return self.scenarios[0].coverage.shape[1]

    @property
    def design_basis(self) -> tuple[ScenarioCoverage, ...]:
        """Scenarios an objective may be built on."""
        return tuple(sc for sc in self.scenarios
                     if not sc.report_only and sc.weight > 0)

    def normalised_weights(self) -> dict[str, float]:
        """Design-basis weights renormalised to sum to 1.

        Renormalising is deliberate: a caller that runs a subset of scenarios
        must still get a weighted mean, not a number silently scaled down by the
        weight of whatever it left out.
        """
        db = self.design_basis
        total = sum(sc.weight for sc in db)
        if total <= 0:
            raise ValueError("design-basis scenario weights sum to zero")
        return {sc.scenario: sc.weight / total for sc in db}

    def allowed(self) -> np.ndarray:
        ok = np.ones(self.n_candidates, dtype=bool)
        if self.land_feasible is not None:
            ok &= self.land_feasible
        if self.forbidden is not None:
            ok &= ~self.forbidden
        return ok

    def single(self, scenario: str, **kw) -> SitingProblem:
        """The ordinary one-scenario problem, for like-for-like comparison."""
        sc = next(s for s in self.scenarios if s.scenario == scenario)
        return SitingProblem(coverage=sc.coverage, precovered=sc.precovered,
                             demand=self.demand, k=self.k, ward_of=self.ward_of,
                             land_feasible=self.land_feasible,
                             forbidden=self.forbidden, **kw)

    def evaluate(self, selected) -> dict:
        """Coverage share of `selected` under EVERY scenario, reported alone.

        This is the comparison that matters: a site set chosen on one scenario
        must be scored on all of them, or its robustness is an assumption.
        """
        sel = list(selected)
        total = float(self.demand.sum())
        out = {}
        for sc in self.scenarios:
            covered = sc.precovered.copy()
            if sel:
                covered |= np.asarray(sc.coverage[:, sel].sum(axis=1)).ravel() > 0
            out[sc.scenario] = round(float(self.demand[covered].sum() / total), 4)
        return out


@dataclass(frozen=True)
class SitingSolution:
    selected: tuple[int, ...]
    objective: float
    bound: float | None
    gap: float | None
    marginal_gains: tuple[float, ...]
    solver: str
    wall_s: float
    status: str
    baseline_covered: float = 0.0
    solution_status: str = "Unknown"
    proven_optimal: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def optimality_note(self) -> str:
        """One-line honesty stamp for reports.

        `status` alone cannot be trusted: pulp reports a HiGHS time-limit stop
        as "Optimal". A number that hit the wall must not be published as proven.
        """
        if self.proven_optimal:
            return "proven optimal"
        if self.solution_status == "Solution Found":
            return (f"NOT PROVEN - feasible incumbent only, stopped at "
                    f"{self.wall_s:.0f}s of a {self.extra.get('time_limit_s', '?')}s limit")
        return f"NOT PROVEN - {self.solution_status}"

    @property
    def total_covered(self) -> float:
        return self.baseline_covered + self.objective
