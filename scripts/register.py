"""Registry integrity check.

The audit that prompted the 2026-09 repair found `stations_resolved.csv` no
longer matching its registered checksum -- 6866 bytes registered, 6423 on disk --
because it had been edited by hand after registration. Nothing checked, so
nothing noticed.

    python scripts/register.py --verify

The registry is APPEND-ONLY and versioned: "a refresh is a NEW VERSION, never an
in-place overwrite, so that a run recorded six months ago remains replayable
against the data it actually used." So an older entry pointing at a path that
has since been rewritten is HISTORICAL, not broken -- only the newest entry for
each source must match what is on disk. Treating superseded versions as failures
would make the check cry wolf on every legitimate refresh.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

from ers.hashing import sha256_file  # noqa: E402
from ers.io.registry import DatasetRegistry  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--verify", action="store_true", help="check hashes; non-zero on failure")
args = ap.parse_args()

reg = DatasetRegistry()
items = reg.all()

latest: dict[str, int] = {}
for it in items:
    if it.source not in latest or it.fetched_at > items[latest[it.source] - 1].fetched_at:
        latest[it.source] = it.id
current_ids = {i for i in latest.values()}

failures, superseded = [], []
print(f"{'id':>3}  {'state':11s} {'source':32s} path")
for it in sorted(items, key=lambda i: i.id):
    p = Path(it.local_path)
    is_current = it.id in current_ids
    if not p.exists():
        state = "MISSING" if is_current else "gone"
        (failures if is_current else superseded).append(it)
    elif sha256_file(p) == it.sha256:
        state = "ok" if is_current else "ok/hist"
    else:
        state = "MISMATCH" if is_current else "superseded"
        (failures if is_current else superseded).append(it)
    print(f"{it.id:>3}  {state:11s} {it.source:32s} {it.local_path}")

print(f"\n{len(current_ids)} current source(s), {len(superseded)} superseded/historical, "
      f"{len(failures)} failure(s)")
for f in failures:
    print(f"  FAIL id={f.id} {f.source}: {f.local_path} does not match its registered hash")

if args.verify:
    raise SystemExit(1 if failures else 0)
