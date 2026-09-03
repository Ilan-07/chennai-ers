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
    extra: dict = field(default_factory=dict)

    @property
    def total_covered(self) -> float:
        return self.baseline_covered + self.objective
