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


def stratified_stats(model_s, oracle_s, band_labels) -> dict:
    """Agreement per distance band -- a global median can hide a band-specific bias."""
    out = {}
    band_labels = np.asarray(band_labels)
    for b in sorted(set(band_labels.tolist())):
        sel = band_labels == b
        out[str(b)] = agreement_stats(np.asarray(model_s)[sel], np.asarray(oracle_s)[sel])
    return out
