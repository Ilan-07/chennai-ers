import json
from pathlib import Path

from ers.hashing import config_hash, sha256_file, short


def test_config_hash_is_order_independent():
    a = {"k": 5, "b": [1, 2], "x": {"p": 1.0, "q": 2}}
    b = {"x": {"q": 2, "p": 1.0}, "b": [1, 2], "k": 5}
    assert config_hash(a) == config_hash(b)


def test_config_hash_is_value_sensitive():
    base = {"k": 5, "t": 420}
    assert config_hash(base) != config_hash({"k": 6, "t": 420})
    assert config_hash(base) != config_hash({"k": 5, "t": 421})


def test_config_hash_list_order_matters():
    # Candidate rankings are ordered; the hash must notice a reordering.
    assert config_hash({"sel": [1, 2, 3]}) != config_hash({"sel": [3, 2, 1]})


def test_float_repr_drift_does_not_change_hash():
    assert config_hash({"w": 0.1 + 0.2}) == config_hash({"w": 0.30000000000000004})


def test_sha256_file(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"chennai")
    d = sha256_file(p)
    assert len(d) == 64 and short(d) == d[:12]
    assert sha256_file(p) == d
