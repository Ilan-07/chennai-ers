"""Travel-time attribution tests. Build step 06."""
import numpy as np
import pandas as pd
import pytest
import yaml
from pathlib import Path

from ers.geo.attrs import (attribute_edges, junction_delay, parse_dimension,
                           parse_maxspeed, primary_highway)

SPEEDS = yaml.safe_load(Path("config/speeds/base.yml").read_text())

# Fixed table for arithmetic tests. These must NOT read the live config: a
# recalibration would otherwise silently change what "18.0 s" means and the test
# would be asserting the config against itself.
FIXED = {
    "free_flow_kmh": {"residential": 20, "primary": 45, "tertiary": 30,
                      "motorway": 80, "service": 12},
    "peak_factor": {"residential": 0.75, "primary": 0.50, "tertiary": 0.60,
                    "motorway": 0.65, "service": 0.85},
    "junction_delay_s": {"signalised": 12, "unsignalised_degree_ge_3": 5, "other": 0},
}
EMS = yaml.safe_load(Path("config/services/ems.yml").read_text())
FIRE = yaml.safe_load(Path("config/services/fire.yml").read_text())


@pytest.mark.parametrize("raw,expected", [
    ("40", 40.0), ("40 km/h", 40.0), ("30 mph", 48.28), (["30", "50"], 30.0),
    ("IN:urban", 50.0), ("IN:rural", 80.0),
])
def test_parse_maxspeed_accepts_real_osm_forms(raw, expected):
    assert parse_maxspeed(raw) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize("bad", ["", None, "walk", "none", "999", "2", float("nan")])
def test_parse_maxspeed_rejects_junk(bad):
    assert parse_maxspeed(bad) is None


def test_parse_maxspeed_list_takes_the_slowest():
    """A merged way is only as fast as its slowest tagged segment."""
    assert parse_maxspeed(["60", "30", "50"]) == 30.0


@pytest.mark.parametrize("raw,expected", [
    (["residential", "primary"], "primary"),
    (["tertiary_link", "motorway"], "motorway"),
    ("trunk_link", "trunk_link"),
    ("busway", "residential"),
])
def test_primary_highway_keeps_link_suffix_and_picks_fastest(raw, expected):
    assert primary_highway(raw) == expected
    assert primary_highway(raw) in SPEEDS["free_flow_kmh"]


def test_every_highway_class_resolves_to_a_speed():
    for h in SPEEDS["free_flow_kmh"]:
        assert primary_highway(h) in SPEEDS["free_flow_kmh"]


@pytest.mark.parametrize("raw,expected", [("3.5", 3.5), ("2.5 m", 2.5), ("999", None), (None, None)])
def test_parse_dimension(raw, expected):
    assert parse_dimension(raw) == expected


def _edges(n=4, highway="residential", length=100.0, **extra):
    d = {"highway": [highway] * n, "length": [length] * n}
    d.update({k: [v] * n for k, v in extra.items()})
    return pd.DataFrame(d)


def test_traversal_time_matches_hand_calculation():
    # 100 m at residential 20 km/h = 18.0 s, no junction delay, no multiplier.
    e = _edges(1, "residential", 100.0)
    svc = {"emergency_multiplier": {}, "junction_delay_factor": 0.0, "access_filter": {}}
    r = attribute_edges(e, np.zeros(1), speeds=FIXED, service=svc)
    assert r.tau_ds[0] == 180        # 18.0 s in deciseconds


def test_calibrated_config_is_internally_consistent():
    """Guards the live table rather than pinning its values: every class must
    have a speed and a peak factor, and speeds must be physically plausible."""
    ff, pf = SPEEDS["free_flow_kmh"], SPEEDS["peak_factor"]
    assert set(ff) == set(pf)
    for cls, v in ff.items():
        assert 5 <= v <= 120, f"{cls} at {v} km/h is not a plausible road speed"
    for cls, v in pf.items():
        assert 0 < v <= 1.0, f"{cls} peak factor {v} must be in (0, 1]"
    assert ff["motorway"] > ff["primary"] > ff["residential"]
    assert 0.0 <= SPEEDS.get("junction_delay_scale", 1.0) <= 1.0
    assert 0 <= SPEEDS.get("trip_overhead_s", 0) <= 120


def test_tau_is_integer_deciseconds_for_determinism():
    e = _edges(3, "primary", 137.4)
    r = attribute_edges(e, np.zeros(3), speeds=SPEEDS,
                        service={"emergency_multiplier": {}, "junction_delay_factor": 0.0})
    assert r.tau_ds.dtype == np.int32
    assert np.array_equal(r.tau_ds, r.tau_ds.astype(np.int64))


def test_maxspeed_tag_overrides_class_default():
    e = _edges(1, "residential", 100.0, maxspeed="60")
    svc = {"emergency_multiplier": {}, "junction_delay_factor": 0.0}
    r = attribute_edges(e, np.zeros(1), speeds=FIXED, service=svc)
    assert r.speed_source[0] == "maxspeed"
    assert r.speed_kmh[0] == pytest.approx(60.0)
    assert r.tau_ds[0] == 60         # 100 m at 60 km/h = 6.0 s


def test_peak_scenario_is_never_faster_than_free_flow():
    e = _edges(1, "primary", 1000.0)
    svc = {"emergency_multiplier": {}, "junction_delay_factor": 0.0}
    dry = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=svc)
    peak = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=svc, peak=True)
    assert peak.tau_ds[0] > dry.tau_ds[0]


def test_emergency_multiplier_stays_inside_the_literature_envelope():
    """RSCH: lights-and-siren saves ~159 s over a whole response. A 1.5-2x
    speed multiplier is not supported and must not creep into the config."""
    for svc in (EMS, FIRE):
        for v in svc["emergency_multiplier"].values():
            assert 0.7 <= v <= 1.25, f"{svc['service']} multiplier {v} outside envelope"


def test_fire_is_slower_than_ems_on_local_streets():
    e = _edges(1, "residential", 500.0)
    ems = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=EMS)
    fire = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=FIRE)
    assert fire.tau_ds[0] > ems.tau_ds[0]


def test_access_filter_excludes_low_bridges_for_fire_only():
    e = _edges(1, "residential", 100.0, maxheight="3.0")
    fire = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=FIRE)
    ems = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=EMS)
    assert fire.excluded[0] and fire.tau_ds[0] == np.iinfo(np.int32).max
    assert not ems.excluded[0]
    assert fire.stats["arcs_excluded_by_access_filter"] == 1


def test_junction_delay_ranks_signalised_above_plain_junction():
    deg = np.array([2, 3, 3])
    sig = np.array([False, False, True])
    d = junction_delay(deg, sig, FIXED)
    assert list(d) == [0.0, 5.0, 12.0]


def test_junction_delay_factor_halves_delay_for_emergency():
    e = _edges(1, "residential", 100.0)
    d = np.array([12.0])
    plain = attribute_edges(e, d, speeds=FIXED,
                            service={"emergency_multiplier": {}, "junction_delay_factor": 1.0})
    emerg = attribute_edges(e, d, speeds=FIXED,
                            service={"emergency_multiplier": {}, "junction_delay_factor": 0.5})
    assert plain.tau_ds[0] - emerg.tau_ds[0] == 60   # 6.0 s saved


def test_flood_factor_slows_and_zero_makes_unreachable():
    e = _edges(1, "residential", 100.0)
    svc = {"emergency_multiplier": {}, "junction_delay_factor": 0.0}
    base = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=svc)
    wade = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=svc,
                           flood_factor=np.array([0.35]))
    assert wade.tau_ds[0] > base.tau_ds[0]
    closed = attribute_edges(e, np.zeros(1), speeds=SPEEDS, service=svc,
                             flood_factor=np.array([0.0]))
    assert closed.tau_ds[0] == np.iinfo(np.int32).max
