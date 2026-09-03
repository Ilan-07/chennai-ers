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
