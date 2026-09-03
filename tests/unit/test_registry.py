from pathlib import Path

import pytest

from ers.io.registry import DatasetRegistry


def _make(tmp_path, name, content=b"data"):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_register_and_get(tmp_path: Path):
    reg = DatasetRegistry(tmp_path / "reg.json")
    f = _make(tmp_path, "a.csv")
    dv = reg.register(source="osm_pbf", uri="http://x", local_path=f, licence="ODbL")
    assert dv.id == 1 and len(dv.sha256) == 64
    assert reg.get("osm_pbf").sha256 == dv.sha256


def test_register_is_idempotent_on_identical_bytes(tmp_path: Path):
    reg = DatasetRegistry(tmp_path / "reg.json")
    f = _make(tmp_path, "a.csv")
    d1 = reg.register(source="s", uri="u", local_path=f, licence="L")
    d2 = reg.register(source="s", uri="u", local_path=f, licence="L")
    assert d1.id == d2.id and len(reg.all()) == 1


def test_changed_upstream_data_gets_a_new_version_not_a_shadow(tmp_path: Path):
    """A refresh must never overwrite a version in place -- historical runs
    must stay replayable against the bytes they actually used."""
    reg = DatasetRegistry(tmp_path / "reg.json")
    f = _make(tmp_path, "a.csv", b"v1")
    d1 = reg.register(source="s", uri="u", local_path=f, licence="L", version_label="2026-09-03")
    f.write_bytes(b"v2")
    d2 = reg.register(source="s", uri="u", local_path=f, licence="L", version_label="2026-09-03")
    assert d1.id != d2.id
    assert d1.version_label != d2.version_label
    assert len(reg.all()) == 2


def test_registry_persists_across_instances(tmp_path: Path):
    path = tmp_path / "reg.json"
    reg = DatasetRegistry(path)
    reg.register(source="s", uri="u", local_path=_make(tmp_path, "a"), licence="L")
    assert len(DatasetRegistry(path).all()) == 1


def test_missing_source_raises(tmp_path: Path):
    with pytest.raises(KeyError):
        DatasetRegistry(tmp_path / "reg.json").get("nope")
