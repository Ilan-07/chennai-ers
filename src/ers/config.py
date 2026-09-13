"""Which city profile a run is for. Build step 00.

Every script used to open `config/city/chennai.yml` by name, in 21 places. That
was correct while the project modelled exactly one study area, and it became the
obstacle the moment a second one existed: the GCC profile and the metro profile
differ in boundary, bbox and station inventory, and nothing else.

`ERS_CITY` selects the profile. The default is `chennai`, so every existing
command, Makefile rule and test behaves exactly as before.

    ERS_CITY=chennai_metro python scripts/build_demand.py

Interim artefacts are written per profile (`data/interim/` for the default,
`data/interim/metro/` otherwise) so the two builds cannot overwrite each other's
numbers. A GCC coverage figure and a metro coverage figure are answers to
different questions, and a directory that held both at once under one name would
be the same defect as the stale artefacts F-25 removed.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT = "chennai"


def city_name() -> str:
    return os.environ.get("ERS_CITY", DEFAULT).strip() or DEFAULT


def city_path(root: str | Path = ".") -> Path:
    p = Path(root) / "config" / "city" / f"{city_name()}.yml"
    if not p.exists():
        available = sorted(q.stem for q in (Path(root) / "config" / "city").glob("*.yml"))
        raise SystemExit(f"unknown ERS_CITY={city_name()!r}: {p} does not exist. "
                         f"Available profiles: {', '.join(available)}")
    return p


def city_config(root: str | Path = ".") -> dict:
    return yaml.safe_load(city_path(root).read_text())


def interim(root: str | Path = ".") -> Path:
    """Where this profile's derived artefacts live."""
    base = Path(root) / "data" / "interim"
    sub = city_config(root).get("interim_subdir")
    out = base / sub if sub else base
    out.mkdir(parents=True, exist_ok=True)
    return out


def is_default() -> bool:
    return city_name() == DEFAULT
