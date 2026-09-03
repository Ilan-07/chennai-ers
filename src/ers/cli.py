"""Command line for every pipeline stage. Each stage is runnable standalone."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

import typer
import yaml

app = typer.Typer(add_completion=False, help="Chennai Emergency Response Siting pipeline")

CITY = Path("config/city/chennai.yml")
AUTH = Path("data/reference/tnfrs_stations_gcc.csv")
OSM = Path("data/raw/osm_stations_overpass.json")
RESOLVED = Path("data/interim/stations_resolved.csv")
WORKLIST = Path("data/interim/station_survey_worklist.csv")
QA = Path("data/interim/stations_qa.json")


def _bbox() -> tuple[float, float, float, float]:
    return tuple(yaml.safe_load(CITY.read_text())["bbox"])  # type: ignore[return-value]


def _load_resolved():
    from ers.io.stations import ResolvedStation
    out = []
    for r in csv.DictReader(RESOLVED.open()):
        out.append(ResolvedStation(
            r["station_name"], r["division"], r["service"],
            float(r["lat"]) if r["lat"] else None,
            float(r["lon"]) if r["lon"] else None,
            r["geocode_confidence"], r["match_source"], r["match_detail"],
            float(r["uncertainty_m"]) if r["uncertainty_m"] else None,
            r["survey_required"] == "True",
            r.get("osm_class", ""), r.get("osm_type", ""), r.get("plausibility", ""),
        ))
    return out


def _write_resolved(rows) -> None:
    with RESOLVED.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(asdict(rows[0])))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


@app.command("ingest-survey")
def ingest_survey(
    worklist: Path = typer.Option(WORKLIST, help="Completed survey worklist CSV"),
) -> None:
    """Merge manually verified station positions and reprint the publish gate."""
    from ers.io.stations import ingest_survey as _ingest

    rows = _load_resolved()
    work = list(csv.DictReader(worklist.open()))
    merged, report = _ingest(rows, work, _bbox())

    gate = report["gate"]
    typer.echo(f"accepted   : {report['accepted']}")
    typer.echo(f"still open : {len(report['still_open'])}")
    if report["rejected"]:
        typer.secho(f"REJECTED   : {len(report['rejected'])}", fg="red")
        for r in report["rejected"]:
            typer.secho(f"  {r['station']:16s} {r['reason']} {r.get('value','')}", fg="red")
    if report["large_moves_for_review"]:
        typer.secho("\nlarge moves - confirm these are deliberate:", fg="yellow")
        for f in report["large_moves_for_review"]:
            typer.echo(f"  {f['station']:16s} {f['moved_m']:>6} m   {f['was']} -> {f['now']}")

    _write_resolved(merged)
    QA.write_text(json.dumps(gate, indent=2, sort_keys=True))
    typer.echo(f"\nconfidence : {gate['by_confidence']}")
    if gate["passes_publish_gate"]:
        typer.secho("\nPUBLISH GATE: PASS - baseline coverage may now be published.", fg="green")
    else:
        n = len(gate["survey_required"])
        typer.secho(f"\nPUBLISH GATE: BLOCKED - {n} station(s) still provisional.", fg="yellow")


@app.command("station-status")
def station_status() -> None:
    """Show the current inventory and gate state."""
    from ers.io.stations import qa_report
    rows = _load_resolved()
    rep = qa_report(rows)
    typer.echo(json.dumps({k: v for k, v in rep.items() if k != "survey_required"}, indent=2))
    for r in rows:
        mark = "  SURVEY" if r.survey_required else ""
        typer.echo(f"  {r.geocode_confidence:9s} {r.lat:.5f},{r.lon:.5f} "
                   f"{r.station_name:16s} {r.plausibility:20s}{mark}")


if __name__ == "__main__":
    app()
