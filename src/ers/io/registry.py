"""Dataset version registry.

Every artefact this project ingests is recorded here with its checksum, licence
and fetch date, and every downstream result names its inputs by version id.

A refresh is a NEW VERSION, never an in-place overwrite, so that a run recorded
six months ago remains replayable against the data it actually used.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ers.hashing import sha256_file


@dataclass(frozen=True)
class DatasetVersion:
    id: int
    source: str          # 'osm_pbf' | 'worldpop' | 'tnfrs_stations' | ...
    version_label: str   # usually a fetch date, e.g. '2026-09-03'
    uri: str             # where it came from
    local_path: str
    sha256: str
    licence: str
    fetched_at: str
    bytes: int
    notes: dict = field(default_factory=dict)


class DatasetRegistry:
    def __init__(self, path: str | Path = "data/registry.json") -> None:
        self.path = Path(path)
        self._items: list[DatasetVersion] = []
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self._items = [DatasetVersion(**r) for r in raw]

    def register(
        self,
        *,
        source: str,
        uri: str,
        local_path: str | Path,
        licence: str,
        version_label: str | None = None,
        notes: dict | None = None,
    ) -> DatasetVersion:
        """Register a fetched file. Idempotent on (source, sha256)."""
        p = Path(local_path)
        if not p.exists():
            raise FileNotFoundError(p)
        digest = sha256_file(p)

        for it in self._items:
            if it.source == source and it.sha256 == digest:
                return it  # already registered, byte-identical

        label = version_label or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # If the same (source, label) exists with a different digest the upstream
        # data changed under us. Disambiguate rather than silently shadowing it.
        if any(i.source == source and i.version_label == label for i in self._items):
            label = f"{label}+{digest[:8]}"

        dv = DatasetVersion(
            id=max((i.id for i in self._items), default=0) + 1,
            source=source,
            version_label=label,
            uri=uri,
            local_path=str(p),
            sha256=digest,
            licence=licence,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            bytes=p.stat().st_size,
            notes=notes or {},
        )
        self._items.append(dv)
        self._flush()
        return dv

    def get(self, source: str, version_label: str | None = None) -> DatasetVersion:
        cands = [i for i in self._items if i.source == source]
        if version_label:
            cands = [i for i in cands if i.version_label == version_label]
        if not cands:
            raise KeyError(f"no dataset version for source={source!r} label={version_label!r}")
        return sorted(cands, key=lambda i: i.fetched_at)[-1]

    def all(self) -> list[DatasetVersion]:
        return list(self._items)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([asdict(i) for i in self._items], indent=2, sort_keys=True))
        tmp.replace(self.path)
