"""Content hashing — the mechanism that makes every result traceable.

Determinism rule (Finding F-12): a config hash must depend only on the *values*
in a config, never on dict insertion order, float formatting, or Python version.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


def sha256_file(path: str | Path) -> str:
    """Streaming SHA-256 of a file. Used on every ingested artefact."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj: Any) -> Any:
    """Recursively normalise a config object into a canonical, order-free form."""
    if isinstance(obj, dict):
        return {str(k): _canonical(obj[k]) for k in sorted(obj, key=str)}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, float):
        # Avoid platform float repr drift; 12 significant digits is far more
        # precision than any parameter in this project carries.
        return float(f"{obj:.12g}")
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return str(obj)


def config_hash(cfg: Any) -> str:
    """Stable hash of a configuration.

    Two runs with the same config hash MUST produce identical results. The
    golden test asserts this; a mismatch is a build failure, not a warning.
    """
    payload = json.dumps(_canonical(cfg), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def short(h: str, n: int = 12) -> str:
    return h[:n]


def git_commit() -> str:
    """Current commit, or 'unknown' outside a work tree.

    A run identifier that does not name the code that produced it is not a run
    identifier. Absence is recorded explicitly rather than silently omitted.
    """
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                               text=True, timeout=5, check=True).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def run_id(*, inputs: list[str], config: Any, seed: int | None = None,
           extra: Any = None) -> str:
    """Identify a run by everything that can change its output.

    ASSUMPTIONS.md states the rule this implements: "No number appears in any
    output unless it was produced by a run ID that can be replayed." Until the
    2026-09 repair the rule was asserted but never built -- reports carried at
    most a `stations_signature`, and two thirds carried nothing at all, which
    is how `stations_qa.json` and `survey_priority.json` were able to go stale
    against inputs that had changed under them.

    Two runs agreeing on this id MUST agree on their numbers. The id covers the
    code (git commit), the parameters (config hash), the data (input digests,
    normally registry sha256s) and the randomness (seed).
    """
    payload = {
        "code": git_commit(),
        "config": config_hash(config),
        "inputs": sorted(inputs),
        "seed": seed,
        "extra": _canonical(extra) if extra is not None else None,
    }
    return short(config_hash(payload), 16)
