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
