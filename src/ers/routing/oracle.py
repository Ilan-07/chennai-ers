"""External routing oracle for travel-time validation. Build step 07.

Our travel times come almost entirely from an assumed speed table: only 1.61% of
Chennai arcs carry a `maxspeed` tag. That makes an independent check on the
routing model load-bearing rather than decorative.

OSRM's car profile is the oracle. It is not ground truth -- it is a different
model over the same OSM geometry -- but a large systematic divergence from it
indicates our speed table is wrong, and the residual bounds how much of the
error is ours rather than OSM's.
"""
from __future__ import annotations

import time

import numpy as np
import requests

OSRM_PUBLIC = "https://router.project-osrm.org"


def route_duration(lon1: float, lat1: float, lon2: float, lat2: float,
                   *, base: str = OSRM_PUBLIC, timeout: int = 30) -> tuple[float, float] | None:
    """(duration_s, distance_m) for one OD pair, or None when no route exists."""
    url = f"{base}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
    r = requests.get(url, params={"overview": "false"}, timeout=timeout)
    r.raise_for_status()          # a transport failure must not look like "no route"
    d = r.json()
    if d.get("code") != "Ok" or not d.get("routes"):
        return None
    route = d["routes"][0]
    return float(route["duration"]), float(route["distance"])


def batch_durations(pairs, *, base: str = OSRM_PUBLIC, sleep_s: float = 0.25,
                    progress_every: int = 50):
    """Sequential OD queries against a shared public service. Be polite."""
    out = []
    for i, (lon1, lat1, lon2, lat2) in enumerate(pairs):
        try:
            out.append(route_duration(lon1, lat1, lon2, lat2, base=base))
        except Exception as exc:                     # noqa: BLE001 - recorded, not hidden
            out.append(None)
            print(f"    pair {i}: {type(exc).__name__}", flush=True)
        if progress_every and (i + 1) % progress_every == 0:
            print(f"    {i+1}/{len(pairs)}", flush=True)
        time.sleep(sleep_s)
    return out


def agreement_stats(model_s: np.ndarray, oracle_s: np.ndarray) -> dict:
    """Bland-Altman style agreement, not correlation.

    Correlation is the wrong statistic here: two models can correlate at r=0.99
    while one is uniformly 40% slower. What matters is bias and spread of the
    difference.
    """
    m = np.asarray(model_s, dtype="float64")
    o = np.asarray(oracle_s, dtype="float64")
    ok = np.isfinite(m) & np.isfinite(o) & (o > 0)
    m, o = m[ok], o[ok]
    if len(m) == 0:
        return {"n": 0}

    ape = np.abs(m - o) / o
    ratio = m / o
    diff = m - o
    mean = (m + o) / 2
    return {
        "n": int(len(m)),
        "median_abs_pct_error": round(float(np.median(ape)), 4),
        "mean_abs_pct_error": round(float(ape.mean()), 4),
        "p90_abs_pct_error": round(float(np.quantile(ape, 0.90)), 4),
        "median_ratio_model_over_oracle": round(float(np.median(ratio)), 4),
        "bias_s": round(float(diff.mean()), 1),
        "bias_pct": round(float((m.sum() - o.sum()) / o.sum()), 4),
        "loa_lower_s": round(float(diff.mean() - 1.96 * diff.std()), 1),
        "loa_upper_s": round(float(diff.mean() + 1.96 * diff.std()), 1),
        "model_mean_s": round(float(m.mean()), 1),
        "oracle_mean_s": round(float(o.mean()), 1),
        "_mean_of_means": round(float(mean.mean()), 1),
    }


def band_median_ratio(model_s, oracle_s, band_labels, *, boot: int = 4000,
                      seed: int = 20260904) -> dict:
    """Per-band median(model/oracle) - 1, with a bootstrap CI.

    This replaces `bias_pct` as the per-band statistic, for two reasons found in
    stage-4 calibration.

    `bias_pct` is a ratio of SUMS, so inside a band it is dominated by the
    longest trips there. At n~50 its bootstrap 95% CI runs 5.5 to 25.2 points
    wide, which makes a <=5% gate on it untestable -- it cannot distinguish a
    passing model from a failing one, and it flipped the same configuration
    between pass and fail across two runs.

    It also HID a real effect. Because long trips dominate the sums, it washed
    out a systematic short-trip bias that the median ratio shows plainly.

    The CI is returned alongside the point estimate so a caller can see whether
    a band is genuinely off target or merely under-sampled.
    """
    rng = np.random.default_rng(seed)
    m = np.asarray(model_s, dtype="float64")
    o = np.asarray(oracle_s, dtype="float64")
    labels = np.asarray(band_labels)
    out = {}
    for b in sorted(set(labels.tolist())):
        sel = np.flatnonzero((labels == b) & np.isfinite(m) & np.isfinite(o) & (o > 0))
        if len(sel) == 0:
            out[str(b)] = {"n": 0}
            continue
        r = m[sel] / o[sel]
        bs = np.array([np.median(r[rng.integers(0, len(r), len(r))]) for _ in range(boot)])
        out[str(b)] = {
            "n": int(len(r)),
            "median_ratio_minus_1": round(float(np.median(r) - 1.0), 4),
            "ci_lower": round(float(np.percentile(bs, 2.5) - 1.0), 4),
            "ci_upper": round(float(np.percentile(bs, 97.5) - 1.0), 4),
            "ci_width_points": round(float(np.percentile(bs, 97.5) - np.percentile(bs, 2.5)) * 100, 2),
        }
    return out


def stratified_stats(model_s, oracle_s, band_labels) -> dict:
    """Agreement per distance band -- a global median can hide a band-specific bias.

    NOTE: the `bias_pct` reported here is a ratio of sums and is too unstable at
    this sample size to gate on; use `band_median_ratio` for that. It is retained
    because it is the statistic the earlier calibration stages recorded.
    """
    out = {}
    band_labels = np.asarray(band_labels)
    for b in sorted(set(band_labels.tolist())):
        sel = band_labels == b
        out[str(b)] = agreement_stats(np.asarray(model_s)[sel], np.asarray(oracle_s)[sel])
    return out
