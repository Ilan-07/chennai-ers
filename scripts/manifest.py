"""Hash every artefact under data/, so a repair can prove what it moved.

The audit that produced this repair found two artefacts that had gone stale
without anyone noticing (`stations_qa.json`, `survey_priority.json`), and one
that no longer matched its own registry hash. All three were invisible because
nothing recorded what the tree looked like before a change.

    python scripts/manifest.py write data/interim_manifest_pre.json
    python scripts/manifest.py diff  data/interim_manifest_pre.json

`diff` is the acceptance check for every phase: it names what changed, and a
change that the phase did not intend is a defect, not a detail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from ers.hashing import sha256_file  # noqa: E402

ROOT = Path(".")
# Bulk upstream caches are reproducible and enormous; the registry already
# pins the ones that matter.
SKIP = ("data/raw/osm_cache", "data/raw/ghsl", "data/tiles")


def scan() -> dict[str, dict]:
    out = {}
    for p in sorted(ROOT.glob("data/**/*")):
        if not p.is_file() or any(str(p).startswith(s) for s in SKIP):
            continue
        out[str(p)] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
    return out


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "write"
    path = Path(sys.argv[2] if len(sys.argv) > 2 else "data/interim_manifest_pre.json")
    now = scan()

    if cmd == "write":
        path.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n")
        print(f"wrote {path} ({len(now)} artefacts)")
        return 0

    was = json.loads(path.read_text())
    added = sorted(set(now) - set(was))
    removed = sorted(set(was) - set(now))
    changed = sorted(k for k in set(now) & set(was)
                     if now[k]["sha256"] != was[k]["sha256"])
    for label, rows in (("added", added), ("removed", removed), ("changed", changed)):
        for r in rows:
            print(f"{label:8s} {r}")
    print(f"\n{len(added)} added, {len(removed)} removed, {len(changed)} changed, "
          f"{len(set(now) & set(was)) - len(changed)} identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
