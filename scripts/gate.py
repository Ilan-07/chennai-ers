"""Evaluate every publish gate and exit non-zero on a build failure.

    python scripts/gate.py          # table + exit status
    python scripts/gate.py --json   # machine-readable, for CI

Exit status is driven by BUILD gates only. A PUBLICATION gate failing means the
station survey is still outstanding -- true today, true until the fieldwork is
done, and not a reason for a red build. What it does mean is enforced by the
`provisional_stamped` BUILD gate: while the survey is open, every affected
artefact must say PROVISIONAL.
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import asdict

sys.path.insert(0, "src")

from ers.gates import BUILD, PUBLICATION, evaluate, summarise  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--json", action="store_true")
args = ap.parse_args()

results = evaluate(".")
summary = summarise(results)

if args.json:
    print(json.dumps({"summary": summary, "gates": [asdict(r) for r in results]},
                     indent=2, sort_keys=True))
    raise SystemExit(1 if summary["blocking_failures"] else 0)

order = {BUILD: 0, PUBLICATION: 1}
mark = {True: "PASS", False: "FAIL"}
width = max((len(r.id) for r in results), default=10)

last = None
for r in sorted(results, key=lambda r: (order.get(r.severity, 2), r.id)):
    if r.severity != last:
        print(f"\n--- {r.severity.upper()} ---")
        last = r.severity
    print(f"  {mark[r.passed]:4s}  {r.id:{width}s}  {str(r.value):>28s}  vs {r.threshold}")
    if not r.passed and r.note:
        for line in textwrap.wrap(r.note, 92):
            print(f"        {line}")

print(f"\n{summary['passed']}/{summary['gates']} gates pass")
if summary["publication_blocks"]:
    print(f"PUBLICATION BLOCKED by: {', '.join(summary['publication_blocks'])}")
if summary["reported_failures"]:
    print(f"reported (not enforced): {', '.join(summary['reported_failures'])}")
if summary["blocking_failures"]:
    print(f"BUILD FAILED: {', '.join(summary['blocking_failures'])}")

raise SystemExit(1 if summary["blocking_failures"] else 0)
