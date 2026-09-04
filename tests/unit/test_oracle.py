"""Routing-validation statistics. Build step 07. No network access."""
import numpy as np
import pytest

from ers.routing.oracle import agreement_stats, stratified_stats


def test_perfect_agreement():
    x = np.array([100.0, 200.0, 300.0])
    s = agreement_stats(x, x)
    assert s["median_abs_pct_error"] == 0.0
    assert s["median_ratio_model_over_oracle"] == 1.0
    assert s["bias_pct"] == 0.0


def test_uniform_slowness_is_caught_as_bias_not_hidden_by_correlation():
    """Two models can correlate at r=1.0 while one is uniformly 40% slower.
    Correlation would call this perfect; bias must not."""
    oracle = np.array([100.0, 200.0, 300.0, 400.0])
    model = oracle * 1.4
    s = agreement_stats(model, oracle)
    assert np.corrcoef(model, oracle)[0, 1] == pytest.approx(1.0)
    assert s["median_abs_pct_error"] == pytest.approx(0.4)
    assert s["bias_pct"] == pytest.approx(0.4)
    assert s["median_ratio_model_over_oracle"] == pytest.approx(1.4)


def test_non_finite_and_zero_oracle_values_are_dropped():
    model = np.array([100.0, np.nan, 300.0, 400.0])
    oracle = np.array([100.0, 200.0, 0.0, np.inf])
    s = agreement_stats(model, oracle)
    assert s["n"] == 1


def test_empty_input_does_not_raise():
    assert agreement_stats(np.array([]), np.array([]))["n"] == 0
    assert agreement_stats(np.array([np.nan]), np.array([np.nan]))["n"] == 0


def test_bias_direction_is_signed():
    oracle = np.array([100.0, 100.0])
    assert agreement_stats(oracle * 0.8, oracle)["bias_pct"] == pytest.approx(-0.2)
    assert agreement_stats(oracle * 1.2, oracle)["bias_pct"] == pytest.approx(0.2)


def test_limits_of_agreement_widen_with_spread():
    oracle = np.full(50, 300.0)
    tight = agreement_stats(oracle + np.linspace(-5, 5, 50), oracle)
    loose = agreement_stats(oracle + np.linspace(-100, 100, 50), oracle)
    assert (loose["loa_upper_s"] - loose["loa_lower_s"]) > \
           (tight["loa_upper_s"] - tight["loa_lower_s"])


def test_stratification_exposes_a_band_specific_bias_a_global_median_hides():
    """Short trips 60% slow, long trips accurate. The pooled median can look
    acceptable while one band is badly wrong."""
    oracle = np.array([60.0] * 10 + [1200.0] * 10)
    model = np.concatenate([np.full(10, 96.0), np.full(10, 1200.0)])
    bands = np.array(["0-2km"] * 10 + ["10-20km"] * 10)
    by = stratified_stats(model, oracle, bands)
    assert by["0-2km"]["bias_pct"] == pytest.approx(0.6)
    assert by["10-20km"]["bias_pct"] == pytest.approx(0.0)
    # Pooled bias is dominated by the long trips and understates the problem.
    assert agreement_stats(model, oracle)["bias_pct"] < 0.05


def test_stratified_stats_handles_missing_band():
    by = stratified_stats(np.array([100.0]), np.array([np.nan]), np.array(["a"]))
    assert by["a"]["n"] == 0


# ---------------------------------------------------------------------------
# Band statistic (stage 4). `bias_pct` is a ratio of sums and cannot be gated on
# at this sample size; the median ratio replaces it.
# ---------------------------------------------------------------------------

def test_band_median_ratio_is_not_dominated_by_the_longest_trip_in_the_band():
    """The failure mode that hid a real short-trip bias for two calibration
    stages: one long pair can swamp a ratio of sums, while the median cannot."""
    from ers.routing.oracle import agreement_stats, band_median_ratio
    # Nine short pairs each 20% slow, one long pair exactly right.
    model = np.array([120.0] * 9 + [4000.0])
    oracle = np.array([100.0] * 9 + [4000.0])
    band = np.array(["b"] * 10)
    sums = agreement_stats(model, oracle)["bias_pct"]
    med = band_median_ratio(model, oracle, band, boot=200)["b"]["median_ratio_minus_1"]
    assert sums < 0.05, "the long pair drags the sum-ratio toward zero"
    assert med == pytest.approx(0.20, abs=1e-6), "the median still sees the 20% bias"


def test_band_median_ratio_reports_a_confidence_interval():
    from ers.routing.oracle import band_median_ratio
    rng = np.random.default_rng(0)
    o = rng.uniform(100, 900, 60)
    m = o * rng.normal(1.1, 0.15, 60)          # a real spread of ratios
    out = band_median_ratio(m, o, np.array(["x"] * 60), boot=800)["x"]
    assert out["ci_lower"] <= out["median_ratio_minus_1"] <= out["ci_upper"]
    assert out["ci_width_points"] > 0


def test_an_exact_constant_ratio_gives_a_zero_width_interval():
    """Not a degenerate bug: if every pair is off by exactly the same factor,
    there is nothing for a resample to vary, and the honest CI is a point."""
    from ers.routing.oracle import band_median_ratio
    o = np.array([100.0, 250.0, 900.0])
    out = band_median_ratio(o * 1.1, o, np.array(["x"] * 3), boot=200)["x"]
    assert out["median_ratio_minus_1"] == pytest.approx(0.10, abs=1e-9)
    assert out["ci_width_points"] == 0.0


def test_a_wide_interval_signals_an_untestable_band():
    """A band whose CI is wider than the gate cannot be judged against it. The
    CI is returned precisely so a caller can tell that apart from a real fail."""
    from ers.routing.oracle import band_median_ratio
    rng = np.random.default_rng(1)
    o = rng.uniform(100, 300, 8)
    noisy = o * rng.uniform(0.5, 2.0, 8)
    out = band_median_ratio(noisy, o, np.array(["x"] * 8), boot=800)["x"]
    assert out["ci_width_points"] > 5.0


def test_bands_are_reported_independently():
    from ers.routing.oracle import band_median_ratio
    o = np.array([100.0] * 20)
    m = np.array([100.0] * 10 + [130.0] * 10)
    band = np.array(["near"] * 10 + ["far"] * 10)
    out = band_median_ratio(m, o, band, boot=200)
    assert out["near"]["median_ratio_minus_1"] == pytest.approx(0.0, abs=1e-9)
    assert out["far"]["median_ratio_minus_1"] == pytest.approx(0.30, abs=1e-9)
